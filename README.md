# PDF → DocBook XML Converter

A local web application that converts **text-based PDFs** into **DocBook 5.0 XML**. It uses PyMuPDF for extraction, analyzes layout and typography to infer structure, and serves a browser UI for upload, preview, copy, and download.

## Features

- **DocBook 5.0 output** — `book` root with `info`, `chapter`, `section`, `para`, lists, and emphasis
- **Layout analysis** — lines and paragraphs grouped by vertical position and spacing
- **Structure detection** — headings mapped to chapters and sections from font size and weight
- **Lists** — bullet and numbered lists (`itemizedlist` / `orderedlist`)
- **Typography** — bold and italic preserved as `emphasis` with `role="bold"` / `role="italic"`
- **Links** — `http://` and `https://` URLs become `link` elements with XLink `href`
- **Metadata** — PDF title and author used in `info` when available
- **Text coverage** — reports how much PDF text was captured in the XML
- **XML safety** — invalid control characters stripped before serialization

## Requirements

- **Python 3.9+** (3.10+ recommended)
- PDFs with **selectable text** (not scanned images). Scanned PDFs need OCR first.

## Installation

1. Clone or copy this project folder.

2. Create and activate a virtual environment (recommended):

   ```bash
   python -m venv venv
   ```

   **Windows (PowerShell):**

   ```powershell
   .\venv\Scripts\Activate.ps1
   ```

   **macOS / Linux:**

   ```bash
   source venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install flask pymupdf lxml
   ```

## Running the app

From the project root (the folder containing `app.py`):

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

The server runs with `debug=True` on **port 5000** by default. Uploaded PDFs are stored briefly in `uploads/` and removed after each conversion.

## Usage

1. Open the web UI at `http://127.0.0.1:5000`.
2. Drag and drop a PDF onto the upload area, or click to browse.
3. Click **Convert to DocBook XML**.
4. Review the conversion summary (pages, chapters, sections, coverage, etc.).
5. **Copy XML** or **Download .xml** from the output panel.

Only `.pdf` files are accepted. The UI suggests a **50 MB** practical limit; very large files may be slow depending on your machine.

## Project structure

```
xml converter/
├── app.py              # Flask server, PDF extraction, DocBook builder
├── static/
│   └── index.html      # Web UI (upload, progress, stats, XML preview)
├── uploads/            # Temporary uploads (created automatically)
└── README.md
```

## API

### `GET /`

Serves the web interface (`static/index.html`).

### `POST /convert`

Converts an uploaded PDF to DocBook XML.

**Request:** `multipart/form-data` with field `file` (PDF).

**Success (200):** JSON body:

| Field | Description |
|-------|-------------|
| `xml` | Full DocBook XML string (UTF-8, with XML declaration) |
| `stats` | `pages`, `chapters`, `sections`, `paragraphs`, `list_items`, `blocks_detected`, `base_font_pt`, `chars_extracted`, `chars_in_pdf`, `coverage_percent` |
| `metadata` | `title`, `author` from PDF metadata (may be empty) |

**Errors:**

| Status | Meaning |
|--------|---------|
| `400` | No file or non-PDF file |
| `422` | No extractable text (e.g. scanned PDF) or invalid XML characters |
| `500` | Unexpected server error |

**Example (curl):**

```bash
curl -X POST -F "file=@document.pdf" http://127.0.0.1:5000/convert
```

## How conversion works

1. **Extract text** — PyMuPDF reads spans, blocks, words, and plain text; the pipeline picks the method with the best **coverage** (target ≥ 92% of PDF text per page).
2. **Group content** — Spans are merged into lines and paragraphs; hyphenation across line breaks is merged when possible.
3. **Classify blocks** — Font size, bold, length, and list markers classify paragraphs as title, section, subsection, list item, or body.
4. **Build DocBook** — Elements are nested under `book` → `chapter` → `section` → `para` / lists; unique `xml:id` values are assigned.
5. **Sanitize & serialize** — Text and attributes are cleaned for XML 1.0; output is pretty-printed UTF-8.

## DocBook output

- Namespace: `http://docbook.org/ns/docbook`
- Root: `<book version="5.0">`
- XLink namespace used for `link@xlink:href`
- Publication date in `info/pubdate` is set to the conversion date (UTC)

Heading detection is heuristic. Complex layouts (multi-column, footnotes, tables) may not map perfectly to semantic structure; body text is still retained in paragraphs where possible.

## Limitations

- **Scanned PDFs** — No OCR; conversion fails if no text layer exists.
- **Tables & figures** — Not modeled as DocBook `table` or `mediaobject`; content may appear as plain paragraphs.
- **Exact structure** — Chapter/section boundaries are inferred from typography, not from PDF bookmarks or tags.
- **Production use** — Default Flask `debug` mode is for local development only. For deployment, use a production WSGI server (e.g. Gunicorn, Waitress) and turn off debug.

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| “No extractable text found” | Use a PDF with selectable text, or run OCR first |
| Low coverage % | PDF may use unusual fonts or encoding; check output for missing blocks |
| “XML generation failed: invalid characters” | Rare control characters in the PDF; report if it persists |
| Port already in use | Change `port=5000` in `app.py` or stop the other process |

## Tech stack

| Component | Library |
|-----------|---------|
| Web server | [Flask](https://flask.palletsprojects.com/) |
| PDF parsing | [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`) |
| XML generation | [lxml](https://lxml.de/) |

## License

No license file is included in this repository. Add one if you plan to distribute or open-source the project.



run code 
 try { (Invoke-WebRequest -Uri http://127.0.0.1:5000/ -UseBasicParsing -TimeoutSec 3).StatusCode } catch { "down" }

 link 
 http://127.0.0.1:5000