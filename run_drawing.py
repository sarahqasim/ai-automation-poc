"""
What this script does:
- Sends one drawing PDF directly to the model as a  PDF document.
- Runs extraction in two passes:
  1) main extraction for all schedule rows
  2) follow-up check for missed rows
- Merges results and writes them to a CSV file.
"""
from dotenv import load_dotenv
load_dotenv(".env")

import base64
import csv
import json
import os
import re

import anthropic

PDF   = "example_drawing/D021779-M002_00_Q169.pdf"
OUT   = "output/drawing_output.csv"
MODEL = os.getenv("ANTHROPIC_DRAWING_MODEL", "claude-sonnet-4-20250514")

FIELDS = ["equipment_name", "item_detail", "qty", "location_service",
          "electrical", "basis_of_design", "section_ref"]

EXTRACTION_PROMPT = """You are an expert at reading HVAC/MEP engineering drawing schedules.

Your task has TWO steps:

STEP 1 — Catalog every schedule table on this drawing.
  Look at every part of the drawing and list the title of every schedule table you can see
  (e.g. "AHU Schedule", "Exhaust Fan Schedule", "Condensate Drain Pump Schedule", etc.).
  Do NOT skip any schedule, even small ones in corners.

STEP 2 — Extract every row from every schedule you listed.
  For each schedule table found in Step 1, extract every equipment row that has a unit tag.

  SKIP ONLY: diffuser/grille schedules with no unit tags (Linear Diffuser, Sidewall Supply,
  Ceiling Diffuser, Return Grille/Diffuser).

  For each unit row return:
    equipment_name   - unit tag exactly as written (e.g. "AHU-1", "FCU-C.1", "AC-1.1 / ACCU-1.1")
    item_detail      - full schedule title / equipment type description
    qty              - quantity (default "1")
    location_service - Location + Service columns joined with " / "; trim trailing "/"
    electrical       - V/PH/HZ exactly as written (e.g. "208/3/60", "115/1/60", "120/1/60")
                       Read this from the V/PH/HZ column. Blank ONLY if the column does not exist.
    basis_of_design  - manufacturer from the "BASIS OF DESIGN: ..." line nearest to THIS specific
                       schedule. Read it exactly (e.g. Annexair, Trane, Greenheck, Mitsubishi,
                       Beckett, IAC, Pennbarry, Magic Air, Anemostat). Do NOT copy the manufacturer
                       from another schedule. Blank only if no basis-of-design is stated.
    section_ref      - spec section number from notes near this schedule (number only, e.g. "15934")

  Rules:
  - Read every value directly from the document. Never guess.
  - Split-type AC: combine indoor + outdoor tags -> "AC-1.1 / ACCU-1.1"
  - Sound attenuators listed together ("ST-1S, ST-1R"): one row per tag.
  - Replace any double-quote characters inside string values with single-quotes.

Return ONLY a valid JSON object with two keys:
{
  "schedules_found": ["AHU Schedule", "Exhaust Fan Schedule", ...],
  "rows": [
    {"equipment_name":"...", "item_detail":"...", "qty":"1", "location_service":"...",
     "electrical":"...", "basis_of_design":"...", "section_ref":"..."},
    ...
  ]
}
"""

FOLLOWUP_PROMPT = """The previous extraction found these equipment rows: {found}

Look again at the drawing. Are there ANY unit-tagged equipment rows that were NOT in that list?
Common ones that are sometimes missed: Exhaust Fans (EF-x), Gravity Ventilators (GV-x),
Split-Type AC units (AC-x.x / ACCU-x.x), Condensate Drain Pumps (CP-x-x), VAV Boxes (VAV-x.x),
Sound Attenuators (ST-x), Fan Coil Units (FCU-x).

For any rows NOT already listed, return them in the same JSON array format.
If nothing is missing, return [].
"""


def read_pdf_b64(path: str) -> str:
    """Read a PDF file and return base64 text for API upload."""
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def repair_json(raw: str) -> str:
    """Try to fix broken quotes in model output before JSON parsing."""
    raw = raw.replace('\u201c', "'").replace('\u201d', "'")
    def fix(m):
        inner = re.sub(r'(?<!\\)"', "'", m.group(1))
        return '"' + inner + '"'
    return re.sub(r'"((?:[^"\\]|\\.)*)"', fix, raw)


def parse_json(raw: str):
    """Parse JSON safely, even if response is wrapped in code fences."""
    raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw)
    for attempt in (raw, repair_json(raw)):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            pass
    return None


def expand_combined_tags(rows: list) -> list:
    """Split combined tags like 'ST-1S, ST-1R' into separate rows."""
    out = []
    for row in rows:
        name = str(row.get("equipment_name", "")).strip()
        parts = [p.strip() for p in re.split(r",\s*", name)]
        if len(parts) > 1 and all(re.match(r"^[A-Z]{1,6}[-\.]\S", p) for p in parts):
            for part in parts:
                r = dict(row)
                r["equipment_name"] = part
                out.append(r)
        else:
            out.append(row)
    return out


_TAG_RE = re.compile(r"^[A-Z]{1,6}[-\./][A-Za-z0-9]")

def valid_tag(name: str) -> bool:
    """Basic check: keep only strings that look like equipment tags."""
    name = name.strip()
    return bool(name) and len(name) <= 30 and bool(_TAG_RE.match(name))


def clean_row(row: dict) -> dict:
    """Normalize extracted row fields and trim trailing separators."""
    cleaned = {f: str(row.get(f, "")).strip() for f in FIELDS}
    cleaned["location_service"] = re.sub(r"\s*/\s*$", "", cleaned["location_service"]).strip()
    return cleaned


def merge_rows(existing: list, new_rows: list) -> list:
    """
    Merge two extracted row lists by equipment tag.
    - Add rows not already present
    - Fill empty fields in existing rows when new data is available
    """
    by_key = {str(r["equipment_name"]).upper(): r for r in existing}
    order = [str(r["equipment_name"]).upper() for r in existing]

    for row in new_rows:
        key = str(row.get("equipment_name", "")).strip().upper()
        if not key:
            continue
        if key not in by_key:
            by_key[key] = row
            order.append(key)
        else:
            # Keep what we already have, but fill blanks from the new pass.
            for field in FIELDS:
                if not by_key[key].get(field) and row.get(field):
                    by_key[key][field] = row[field]

    return [by_key[k] for k in order]


# Main run starts here.

print(f"Reading: {PDF}")
pdf_b64 = read_pdf_b64(PDF)
print(f"Size: {len(pdf_b64) * 3 / 4 / 1_048_576:.2f} MB  model: {MODEL}\n")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

doc_content = {
    "type": "document",
    "source": {
        "type": "base64",
        "media_type": "application/pdf",
        "data": pdf_b64,
    },
}

# Pass 1: main extraction from the full drawing.
print("Pass 1: full extraction...")
resp1 = client.beta.messages.create(
    model=MODEL,
    max_tokens=4096,
    betas=["pdfs-2024-09-25"],
    messages=[{
        "role": "user",
        "content": [
            doc_content,
            {"type": "text", "text": EXTRACTION_PROMPT},
        ],
    }],
)

data1 = parse_json(resp1.content[0].text)
if isinstance(data1, dict):
    rows1 = data1.get("rows", [])
    schedules = data1.get("schedules_found", [])
elif isinstance(data1, list):
    rows1 = data1
    schedules = []
else:
    rows1 = []
    schedules = []

rows1 = expand_combined_tags(rows1)
rows1 = [r for r in rows1 if valid_tag(str(r.get("equipment_name", "")))]
rows1 = [clean_row(r) for r in rows1]

print(f"  Schedules found: {schedules}")
print(f"  Rows extracted: {len(rows1)}")

# Pass 2: ask again only for anything missed in pass 1.
found_tags = ", ".join(r["equipment_name"] for r in rows1)
followup_text = FOLLOWUP_PROMPT.format(found=found_tags)

print("\nPass 2: checking for missed rows...")
resp2 = client.beta.messages.create(
    model=MODEL,
    max_tokens=4096,
    betas=["pdfs-2024-09-25"],
    messages=[
        {
            "role": "user",
            "content": [
                doc_content,
                {"type": "text", "text": EXTRACTION_PROMPT},
            ],
        },
        {"role": "assistant", "content": resp1.content[0].text},
        {"role": "user",  "content": followup_text},
    ],
)

data2 = parse_json(resp2.content[0].text)
rows2 = data2 if isinstance(data2, list) else (data2.get("rows", []) if isinstance(data2, dict) else [])
rows2 = expand_combined_tags(rows2)
rows2 = [r for r in rows2 if valid_tag(str(r.get("equipment_name", "")))]
rows2 = [clean_row(r) for r in rows2]

print(f"  Additional rows found: {len(rows2)}")
if rows2:
    for r in rows2:
        print(f"    + {r['equipment_name']}")

# Merge both passes and write final CSV.
final = merge_rows(rows1, rows2)

os.makedirs("output", exist_ok=True)
with open(OUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(final)

print(f"\nDone -- {len(final)} rows written to {OUT}\n")
for r in final:
    print(r)
