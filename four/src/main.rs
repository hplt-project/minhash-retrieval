use clap::Parser;
use gaoya::minhash::{MinHashIndex, MinHasher32, MinHasher};
use regex::Regex;
use serde_json;
use std::error::Error;
use std::fs::File;
use std::io::{BufReader, BufRead, Write, Lines};
use std::path;
use std::sync::LazyLock;
use fnv;
use zstd_framed;


/// Command-line arguments
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct ProgramOptions {
    /// Path to the file containing the documents you are looking for
    query: path::PathBuf,

    /// Path to a directory containing text.zst and metadata.zst in which to search the queries
    source: path::PathBuf,

    /// What field to use to identify the queries (line numbers are used if not given)
    #[arg(short, long)]
    id: Option<String>,

    /// Size of n-grams for Jaccard similarity
    #[arg(short, long, default_value_t=10)]
    ngram: usize,

    /// Minimum length of documents (both query and HPLT, number of bytes, inclusive)
    #[arg(long, default_value_t=100)]
    min_length: usize,

    /// Maximum length of documents (both query and HPLT, number of bytes, exclusive)
    #[arg(long, default_value_t=100000)]
    max_length: usize,

    /// Number of bands for minhash
    #[arg(long, default_value_t=42)]
    num_bands: usize,

    /// Band width for minhash
    #[arg(long, default_value_t=3)]
    band_width: usize,

    /// Jaccard threshold for minhash
    #[arg(long, default_value_t=0.5)]
    jaccard_threshold: f64,
}

struct IndexedZstdLines<'a> {
    seek_table: Vec<zstd_framed::table::ZstdFrame>,
    lines: Lines<zstd_framed::reader::ZstdReader<'a, BufReader<File>>>,
    character_id: u64,
    line_id: u64,
    frame_id: usize,
}

struct IndexedZstdLine {
    line: String,
    frame_begin: u64,
    frame_end: u64,
    line_offset: u64,
}

impl<'a> IndexedZstdLines<'a> {
    pub fn new(path: path::PathBuf) -> Result<Self, Box<dyn Error>> {
        let mut archive = File::open(path)?;
        let seek_table = zstd_framed::table::read_seek_table(&mut archive)?.unwrap();
        let vectorized = seek_table.frames().collect();
        let reader = zstd_framed::ZstdReader::builder(archive).with_seek_table(seek_table).build()?;
        Ok(IndexedZstdLines {
            seek_table: vectorized,
            lines: reader.lines(),
            character_id: 0,
            line_id: 0,
            frame_id: 0,
        })
    }
}

impl<'a> Iterator for IndexedZstdLines<'a> {
    type Item = IndexedZstdLine;

    fn next(&mut self) -> Option<Self::Item> {
        if let Some(line_result) = self.lines.next() {
            let line = line_result.expect("Error reading zstd line.");
            let offset = 1 + line.len() as u64;
            let begin_frame_id = self.frame_id;
            let begin_line_id = self.line_id;

            self.character_id += offset;

            if self.character_id >= self.seek_table[self.frame_id].decompressed_range().end {
                loop {
                    self.frame_id += 1;
                    if self.frame_id >= self.seek_table.len() || self.character_id < self.seek_table[self.frame_id].decompressed_range().end {
                        break;
                    }
                }

                if self.frame_id >= self.seek_table.len() || self.character_id == self.seek_table[self.frame_id].decompressed_range().start {
                    // The newline character was the last in the frame
                    self.line_id = 0;
                } else {
                    // The current sample is in-between frames, the next sample will have to ignore
                    // the leftovers
                    self.line_id = 1;
                }
            } else {
                self.line_id += 1;
            }

            let end_frame_id = if self.frame_id >= self.seek_table.len() {
                self.seek_table.len() - 1
            } else if self.character_id == self.seek_table[self.frame_id].decompressed_range().start {
                self.frame_id - 1
            } else {
                self.frame_id
            };
            Some(IndexedZstdLine {
                line: line,
                frame_begin: self.seek_table[begin_frame_id].compressed_range().start,
                frame_end: self.seek_table[end_frame_id].compressed_range().end,
                line_offset: begin_line_id,
            })
        } else {
            None
        }
    }
}

struct NgramIterator<'a> {
    data: &'a str,
    begin: usize,
    end: usize,
}

fn successor(data: &str, index: &mut usize) -> bool {
    loop {
        *index += 1;
        if *index >= data.len() {
            return false;
        }
        if data.is_char_boundary(*index) {
            break;
        }
    }
    true
}

impl<'a> NgramIterator<'a> {
    pub fn new(data: &'a str, ngram: usize) -> Self {
        let mut end: usize = 0;
        for _ in 0 .. ngram {
            successor(data, &mut end);
        }
        NgramIterator {
            data: data,
            begin: 0,
            end: end,
        }
    }
}

impl<'a> Iterator for NgramIterator<'a> {
    type Item = &'a str;

    fn next(&mut self) -> Option<Self::Item> {
        if !successor(self.data, &mut self.end) {
            None
        } else {
            successor(self.data, &mut self.begin);
            Some(&self.data[self.begin .. self.end])
        }
    }
}

struct HPLTSearch {
    options: ProgramOptions,
    minhasher: MinHasher32<fnv::FnvBuildHasher>,
    index: MinHashIndex<u32, u64>,
}

impl HPLTSearch {
    pub fn new() -> Self {
        let options = ProgramOptions::parse();
        HPLTSearch {
            minhasher: MinHasher32::new(options.num_bands * options.band_width),
            index: MinHashIndex::new(options.num_bands, options.band_width, options.jaccard_threshold),
            options: options,
        }
    }

    fn signature(&self, text: &str) -> Option<Vec<u32>> {
        static REMOVE_ME: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"_|\W").expect("Invalid regex")
        });

        let cleaned: String = REMOVE_ME.replace_all(text, "").to_string();
        if cleaned.len() >= self.options.min_length && cleaned.len() < self.options.max_length {
            Some(self.minhasher.create_signature(NgramIterator::new(&cleaned, self.options.ngram)))
        } else {
            None
        }
    }

    fn read_queries(&mut self) -> Result<(), Box<dyn Error>> {
        let query_file = File::open(&self.options.query)?;
        for (line_id, line) in BufReader::new(query_file).lines().enumerate() {
            let object: serde_json::Value = serde_json::from_str(&line?)?;
            let id = match &self.options.id {
                Some(field) => object[field].as_u64().expect("Id field not found in query"),
                _ => line_id as u64,
            };
            let text = object["article"].as_str().expect("Bad article field in query");
            let headline = object["headline"].as_str().expect("Bad headline field in query");
            if let Some(value) = self.signature(text) {
                self.index.insert(id, value);
            }
            if let Some(value) = self.signature(&(headline.to_owned() + text)) {
                self.index.insert(id, value);
            }
        }

        Ok(())
    }

    fn process_haystack(&mut self) -> Result<(), Box<dyn Error>> {
        let text_input = IndexedZstdLines::new(self.options.source.join("text.zst"))?;
        let meta_input = IndexedZstdLines::new(self.options.source.join("metadata.zst"))?;

        for (text_sample, meta_sample) in std::iter::zip(text_input, meta_input) {
            let text_object: serde_json::Value = serde_json::from_str(&text_sample.line)?;
            let Some(text) = text_object["text"].as_str() else { continue };
            let Some(value) = self.signature(text) else { continue };
            if let Some((query_id, similarity)) = self.index.query_one(&value) {
                let meta_object: serde_json::Value = serde_json::from_str(&meta_sample.line)?;
                let found = serde_json::json!({
                    "q": query_id,
                    "p": self.options.source,
                    "h": meta_object["id"].as_str().expect("id-less sample in HPLT"),
                    "t": {
                        "b": text_sample.frame_begin,
                        "e": text_sample.frame_end,
                        "l": text_sample.line_offset,
                    },
                    "m": {
                        "b": meta_sample.frame_begin,
                        "e": meta_sample.frame_end,
                        "l": meta_sample.line_offset,
                    },
                    "s": similarity,
                });
                serde_json::to_writer(std::io::stdout(), &found)?;
                write!(std::io::stdout(), "\n")?;
            }
        }

        Ok(())
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut search = HPLTSearch::new();
    search.read_queries()?;
    search.process_haystack()?;
    Ok(())
}
