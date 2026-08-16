# PortalSync Extraction Backend

Pure Python processing modules for PortalSync. No HTTP server is included.

## Files

- `processor.py` — Core extraction processor. Reads file bytes, extracts text/data from PDFs, Excel files, CSVs, and plain text. Parses CSV/TSV content into records and can optionally call DeepSeek for unstructured extraction.
- `run_demo.py` — Demo script with hardcoded CSV data. Exits 0.
- `run_tests.py` — Test script for processor behavior.
- `requirements.txt` — Python dependencies.

## Usage

```bash
python3 run_demo.py
python3 run_tests.py
```

Set `DEEPSEEK_API_KEY` in the environment to enable DeepSeek extraction for unstructured documents.
