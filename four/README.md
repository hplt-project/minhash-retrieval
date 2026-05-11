## Minhash Retrieval for HPLT v4

This retriever is meant to be used with HPLT version 4.

### Build

Build the binary using:
```
$ cargo build -r
```

### Usage

```
$ ./hplt_minhash_retrieval --help
Find documents inside HPLT v4

Usage: hplt_minhash_retrieval [OPTIONS] <QUERY> <SOURCE>

Arguments:
  <QUERY>   Path to the file containing the documents you are looking for
  <SOURCE>  Path to a directory containing text.zst and metadata.zst in which to search the queries

Options:
  -i, --id <ID>
          What field to use to identify the queries (line numbers are used if not given)
  -n, --ngram <NGRAM>
          Size of n-grams for Jaccard similarity [default: 10]
      --min-length <MIN_LENGTH>
          Minimum length of documents (both query and HPLT, number of bytes, inclusive) [default: 100]
      --max-length <MAX_LENGTH>
          Maximum length of documents (both query and HPLT, number of bytes, exclusive) [default: 100000]
      --num-bands <NUM_BANDS>
          Number of bands for minhash [default: 42]
      --band-width <BAND_WIDTH>
          Band width for minhash [default: 3]
      --jaccard-threshold <JACCARD_THRESHOLD>
          Jaccard threshold for minhash [default: 0.5]
  -h, --help
          Print help
  -V, --version
          Print version
```


### Input

The query file should be a jsonl file where each line contains two fields:
- `article`
- `headline`

The retriever then add two documents to the minhash index:
- `article` by itself
- `headline` and `article` concatenated (in that order)

The query file can contains more fields, they will be ignored, except if `--id` is given in which case the field in question will be used to identify the query.
To modify the fields being used for the search, refer to lines 218–225 of `src/main.rs`.


### Output

The retriever writes json lines on stdout, the line format is as follow:
```
{
	"q":42, # The query ID
	"h":"b1b2d90e559c02db7ca9ff86f1efcfe8", # The HPLT-sample ID (to be used as a checksum)
	"p":"CC-MAIN-2020-10/42", # Path to the matching HPLT data
	"t":{"b":723850983,"e":724036153,"l":111}, # Where to find the document in text.zst
	"m":{"b":84320248,"e":84435715,"l":621}, # Where to find the document's metadata in metadata.zst
	"s":0.789729, # The minhash similarity between the query and HPLT document
}
```

For the `t` and `m` fields, the location inside the `.zst` file is described by three fields:
- `b` is the frame offset in bytes: a retriever can start reading at that offset in the zstd file (inclusive)
- `e` is the end of the frames in bytes: a retriever can stop reading at that offset in the zstd file (exclusive)
- `l` is the line offset in the frame: after skpping to the correct frame, a retriever should ignore that many newlines `\n` before finding the sample (this is 0 if the start of the sample is aligned with the start of a frame)

For example, the text sample associated with the above output can be retrieved using:
```
$ curl -r 723850983-724036152 https://data.hplt-project.org/four/pool/CC-MAIN-2020-10/42/text.zst | zstdcat | sed -n '112p'
```

Note that the `e` field is the end (exclusive) while the HTTP `Range` header is inclusive, thus explaining the `724036152` vs `724036153`; furthermore, `sed` starts numbering lines at 1, thus `112p` instead of `111` in the `l` field.


#### Data Lookup

To automatize the above lookup procedure and recover the text and metadata associated with those locations, we provide a `lookup.py` script:
```
$ ./lookup.py --help
usage: lookup.py [-h] [-c CACHE] output matches

Lookup documents and metadata from minhash results.

positional arguments:
  output             Path where the jsonl containing documents and metadata will be written.
  matches            Path to the jsonl containing the minhash output to lookup in HPLT.

options:
  -h, --help         show this help message and exit
  -c, --cache CACHE  Path to a cache directory to store downloaded data incrementally and continue from it.
```

Since HPLT archive zstd frames contain multiple samples, it is necessary to download more data than what is actually needed to recover the HPLT text, this overhead should be in the order of 6400% (yes, that's big, but usually a lot less than the 200+TB of the full HPLTv4).

To avoid redownloading the data in case of failure, it is strongly recommended to run the lookup script with a `--cache` argument.


### HPC

The slurm script we used to distribute the minhash search can be found in `meta_run.py`.
This script automatically distribute the HPLT files over `-n` slurm jobs using a multiway number partitioning algorithm and then run those jobs unless `-d` is given.
The slurm jobs use the `#STAGE IN` directives, avoiding consuming CPU-hours for data import/copy.
```
$ ./meta_run.py --help
usage: meta_run.py [-h] [-n NPARALLEL] [-d]

Run slurm scripts for HPLTv4 matching.

options:
  -h, --help            show this help message and exit
  -n, --nparallel NPARALLEL
                        Number of parallel jobs to run.
  -d, --dry-run         Write the job files to disk in ./run directory but do not run them.
```

This is only provided as an example and the script should be adapted to your slurm project, file hierarchy, etc.
