# PDF Field Extractor

Streamlit app that extracts structured fields from **specification PDFs** and
**drawing PDFs**, then merges them into a single CSV matched by equipment name.

---

## Project structure

```
app/
├── app.py                    ← Streamlit application
├── requirements.txt          ← Python dependencies
├── .env.example              ← API key template
└── scripts/
    ├── extract_specs.py      ← Spec extractor  (text-based, pypdf)
    └── extract_drawings.py   ← Drawing extractor (native PDF document API)
```

---

## Setup

### 1. Install Python dependencies

```powershell
cd "c:\Users\SARAH QASIM\testing\app"
pip install -r requirements.txt
```

### 2. Set your Anthropic API key

Create a `.env` file in this folder:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Or enter it directly in the Streamlit sidebar when the app is running.

---

## Running the app

```powershell
cd "c:\Users\SARAH QASIM\testing\app"
streamlit run app.py
```

---

## How to use

1. **Upload Specification PDFs** — the spec extractor reads text and extracts:
   section number, manufacturers, warranty, training, spare parts.

2. **Upload Drawing PDFs** — the drawing extractor uses Claude Vision to read
   equipment schedules and extracts: equipment tag, item detail, qty, location,
   electrical supply, basis of design.

3. **Match settings** (sidebar):
   - *Spec match column* → `section` (the 5-digit spec section number, e.g. 15934)
   - *Drawing match column* → `equipment_name` (the unit tag, e.g. AHU-1)
   - Change these to whatever column makes sense for your project.

4. Click **Extract & Merge** and download the CSV.

---

## Custom scripts

You can replace either extractor by uploading your own `.py` script in the
**Step 2** panel. Your script must expose:

```python
def process_pdfs(pdf_paths: list[str]) -> list[dict]:
    ...
```

Each dict must include an `equipment_name` key (used as the default join key).

---

## Matching logic

Specs and drawings are linked by a common column.

| Side      | Typical match column | Example value                            |
|-----------|---------------------|------------------------------------------|
| Spec      | `section`           | `15934`                                  |
| Spec      | `equipment_name`    | `ROOFTOP AIR HANDLING UNITS FOR CORRIDOR`|
| Drawing   | `equipment_name`    | `AHU-1`                                  |

Because spec sections describe a *type* of equipment while drawings list
individual *unit tags*, exact auto-matching is rarely possible.
The app performs an outer join on the columns you choose — you can review the
merged table and adjust the match columns from the sidebar.
