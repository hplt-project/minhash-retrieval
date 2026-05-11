# minhash-retrieval
Document retrieval system based on [MinHash](https://en.wikipedia.org/wiki/MinHash) and [LSH](https://en.wikipedia.org/wiki/Locality-sensitive_hashing) for finding documents in the HPLT datasets that are similar to the given documents.

This tool was developed specifically for creation of the [UCDP Abstractive Event analysis Corpus](https://aclanthology.org/2025.konvens-2.8/) and has the following limitations:
- hyperparameters are hard-coded and selected based on general considerations to optimize recall;
- not tested for languages other than English, preprocessing may require modifications for non-Latin scripts.

The code in this directory was written for HPLTv2. To work with HPLTv4, refer to the [four](four/) directory.

## Input/Output Format

### Input Requirements
Your documents should be stored in JSONL format with fields `article` and `headline`. Each document will be added to the index twice: with and without the headline.

### Output Format
The tool outputs JSONL with the following information for each near-match:

- `qid`: File path and line number (starting from 1) identifying an HPLT document
- `tid`: Line number (starting from 1) identifying your document in the input JSON, or negated line number
- `sim`: Jaccard similarity score
- `text`: Text of the retrieved HPLT document

# Dependencies
See [environment on NIRD](requirements_nird.lock) for the complete dependency list.

# Usage

## Preprocessing
Assume your documents are stored in fixed.jsonl. Preprocessing removes all non-letters to make retrieval independent from whitespaces, newlines and other special characters.
```bash
python retriever.py preprocess_content fixed.jsonl
```

This creates `fixed.jsonl.preproc.pkl` which contains your preprocessed documents for retrieval.

## Retrieval
`run_retrieval1.sh` creates a MinHash index from your preprocessed documents and retrieves near-duplicates from HPLT datasets.

#### Arguments
1. **PKL** - Path to your preprocessed documents pickle file (e.g., `fixed.jsonl.preproc.pkl`)
2. **HPLT_DIR** - Directory containing HPLT documents to search through
3. **OUTD** - Output directory for retrieval results
4. **TEXTFIELD** - Text field name in HPLT documents ('text' for the deduplicated/cleaned version of datasets or 't' for stage2 outputs)
5. **FILEPATTERN** - File pattern to match in HPLT directory ('*.zst' for the deduplicated/cleaned version of datasets or 'text.zst' for stage2 outputs)

#### Usage Examples

For search in the deduplicate/cleaned versions of data release 2:

```./run_retrieval1.sh fixed.jsonl.preproc.pkl deduplicated/ ./fixed-in-deduplicated-run2 text '*.zst'```

This creates a MinHash index from your documents and retrieves near-duplicates for HPLT documents stored in deduplicated/. The outputs are dumped to the folder ./fixed-in-deduplicated-run2

For search in the outputs of stage2 of data release 2:

```./run_retrieval1.sh fixed.jsonl.preproc.pkl _stage2out/ ./fixed-in-stage2out t text.zst```



# Acknowledgements

This project has received funding from the European Union’s Horizon Europe research and innovation programme under grant agreement No 101070350 and from UK Research and Innovation (UKRI) under the UK government’s Horizon Europe funding guarantee [grant number 10052546]
