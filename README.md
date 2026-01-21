# minhash-retrieval
Finds your documents in the HPLT datasets. This tool was developed specifically for creation of the [UCDP Ab-
stractive Event analysis Corpus](https://aclanthology.org/2025.konvens-2.8/), therefore has some limitations:
-  hyperparameters are hard-coded and selected based on general considerations to optimize recall,
-  not tested for languages other than English, especially preprocessing may require modifications when applied to non-latin scripts.

**Inputs**: your documents should be stored in the jsonl format with fields ```article```, ```headline```.
Each document will be added to the index twice: with and without the headline. Then each HPLT document will be searched in the index.

**Outputs**: jsonl with the following informations for each near-match:
* qid: file path and line number (starting from 1) identifying an HPLT document
* tid: line number (starting from 1) identifying your document in the input json, or negated line number
* sim: Jaccard simliarity
* text: text of the retrieved HPLT document

# Dependencies
See [environment on NIRD](requirements_nird.lock)

# Preprocessing
Assume your documents are stored in fixed.jsonl. Preprocessing removes all non-letters to make retrieval independent from whitespaces, newlines and other special characters.
```python retriever.py preprocess_content fixed.jsonl```
fixed.jsonl.preproc.pkl is dumped to disk, your documents will be read from this file during retrieval

# Retrieval
For search in the deduplicate/cleaned versions of data release 2:

```./run_retrieval1.sh fixed.jsonl.preproc.pkl deduplicated/ ./fixed-in-deduplicated-run2 text '*.zst'```

This creates a MinHash index and puts docuemnts form fixed.jsonl.preproc.pkl there. Then retreives near-duplicates for HPLT docuemnts stored in deduplicated/. The outputs are dumped to the folder ./fixed-in-deduplicated-run2

For search in the outputs of stage2 of data release 2:

```./run_retrieval1.sh fixed.jsonl.preproc.pkl _stage2out/ ./fixed-in-stage2out t text.zst```



# Acknowledgements

This project has received funding from the European Union’s Horizon Europe research and innovation programme under grant agreement No 101070350 and from UK Research and Innovation (UKRI) under the UK government’s Horizon Europe funding guarantee [grant number 10052546]
