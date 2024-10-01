# minhash-retrieval
Finds your documents in the HPLT datasets. 
Inputs: your documents should be stored in the jsonl format with fields ```article```, ```headline```.
Each document will be added to the index twice: with and without the headline. Then each HPLT document will be searched in the index.

# Dependencies
See [environment on NIRD](requirements_nird.lock)

# Preprocessing
Assume your documents are stored in fixed.jsonl. Preprocessing removes all non-letters to make retrieval independent from whitespaces, newlines and other special characters.
```python retriever.py preprocess_content fixed.jsonl```
fixed.jsonl.preproc.pkl is dumped to disk, your docuemnts will be read from this file during retrieval

# Retrieval
```./run_retrieval.sh fixed.jsonl.preproc.pkl deduplicated/ ./fixed-in-deduplicated-run2```
This creates a MinHash index and puts docuemnts form fixed.jsonl.preproc.pkl there. Then retreives near-duplicates for HPLT docuemnts stored in deduplicated/. The outputs are dumped to the folder /fixed-in-deduplicated-run2
