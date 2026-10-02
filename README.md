# Cover Letter Manager

A local, filesystem-backed Python desktop application for organizing cover letters, generating PDFs, filtering entries, and searching letter content semantically.

## What it includes

- Startup directory passed as a command-line argument.
- Files stored under `root/company/position/`.
- One original file, one generated PDF, and one `.prop` metadata file per entry.
- Supported input formats: PDF, DOC, DOCX, ODT, RTF, TXT, Markdown, and HTML.
- Company and position text filters.
- Optional date-from and date-to filters.
- Semantic search over chunked letter text and metadata.
- Open the PDF or original file in its default application.
- Reveal the selected entry in Windows Explorer, macOS Finder, or the Linux file manager.
- Optional key/value metadata stored in the entry's `.prop` file.
- A disposable semantic index stored under `.coverletter_manager/semantic/`.

## Recommended environment

Use Python 3.11 or 3.12. Create a virtual environment so PySide6, PyTorch, and the embedding model remain isolated from the rest of your system.

### Windows setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install LibreOffice if you want DOC, DOCX, ODT, and RTF conversion. The application looks for `soffice` or `libreoffice` on `PATH` and also checks the usual Windows and macOS installation paths.

Start the app by passing the cover-letter library directory:

```powershell
python main.py "D:\Documents\CoverLetters"
```

Or:

```powershell
run_windows.bat "D:\Documents\CoverLetters"
```

The directory is created if it does not already exist.

### Linux or macOS setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
./run.sh "$HOME/Documents/CoverLetters"
```

## Example filesystem

```text
CoverLetters/
|-- NVIDIA/
|   `-- Software Engineer/
|       |-- 2026-08-15_a1b2c3d4_original.docx
|       |-- 2026-08-15_a1b2c3d4_cover-letter.pdf
|       `-- 2026-08-15_a1b2c3d4.prop
|-- Acme Labs/
|   `-- Backend Engineer/
|       |-- 2026-07-20_e5f6a7b8_original.txt
|       |-- 2026-07-20_e5f6a7b8_cover-letter.pdf
|       `-- 2026-07-20_e5f6a7b8.prop
`-- .coverletter_manager/
    |-- semantic/
    |   |-- manifest.json
    |   `-- vectors.npy
    `-- tmp/
```

Multiple applications to the same company and position can coexist because each filename includes its date and a short unique ID.

## `.prop` format

The extension is custom, but the contents are TOML so the files are readable and easy to parse:

```toml
schema_version = 1
id = "9cd446ac6c4f4af2a24c7cc714b60d9a"
company = "NVIDIA"
position = "Software Engineer"
date = "2026-08-15"
created_at = "2026-08-15T20:15:00+00:00"
source_name = "nvidia-letter.docx"
original_file = "2026-08-15_9cd446ac_original.docx"
pdf_file = "2026-08-15_9cd446ac_cover-letter.pdf"

[extra]
status = "applied"
job_url = "https://example.com/jobs/123"
contact = "Hiring Manager"
```

The `.prop` files and letter files are authoritative. The vector index is derived data and can be deleted or rebuilt from the GUI.

## Semantic search behavior

The app uses `sentence-transformers/all-MiniLM-L6-v2` by default. It extracts the cover-letter text, divides it into manageable chunks, adds company/position/date/extra metadata to each chunk, and stores normalized embeddings in `vectors.npy`. Search scores are the best matching chunk score for each entry.

The first semantic search or manual index rebuild downloads the model if it is not already cached. Later searches use the local model cache and persisted vectors. To select a different model:

```bash
python main.py "/path/to/CoverLetters" --model "sentence-transformers/multi-qa-mpnet-base-cos-v1"
```

Changing the model causes the index to rebuild automatically.

## PDF conversion

- PDF inputs are copied as both the preserved original and generated-PDF artifact.
- TXT, Markdown, and HTML are converted locally with ReportLab.
- DOC, DOCX, ODT, and RTF are converted through LibreOffice in headless mode.
- The original file is always preserved in its original format.

The repository uses a staging directory and only moves completed files into the company/position directory after conversion and metadata generation succeed.

## Create sample entries

From the project root:

```bash
python tools/create_sample_data.py "/path/to/a/demo-library"
python main.py "/path/to/a/demo-library"
```

## Run core tests

```bash
pip install -r requirements-dev.txt
pytest
```

## limitations

- Existing entries are currently read-only in the GUI; create corrected entries or edit `.prop` files carefully outside the app.
- Scanned/image-only PDFs require OCR, which is not included.
- Generated PDFs for TXT, Markdown, and HTML use a clean plain-text layout rather than reproducing rich formatting.
- Semantic model loading can be heavy on the first run; it is executed in a worker thread so the interface remains responsive.
- There is no database. Scanning `.prop` files builds the in-memory list, while the hidden NumPy vector index accelerates semantic search.
