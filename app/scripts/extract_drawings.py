"""
Drawing PDF Extractor — Native PDF Document Approach
=====================================================
Standard interface for the Streamlit app:

    process_pdfs(pdf_paths: list[str]) -> list[dict]

How it works:
  Sends each PDF directly to Claude as a native document (same as Claude.ai web UI).
  Claude processes the full page in one shot with complete context —
  no image conversion, no splitting, no resolution loss.

  Two-pass strategy:
    Pass 1 — full extraction with catalog step (find all schedule tables, then extract all rows)
    Pass 2 — follow-up to catch any rows missed in Pass 1

Each dict contains:
    equipment_name   – unit tag (e.g. "AHU-1")  ← used for matching
    item_detail      – schedule title / equipment type
    qty              – quantity
    location_service – location and/or service
    electrical       – V/PH/HZ
    basis_of_design  – manufacturer
    section_ref      – spec section number referenced near the schedule
    source_file      – original PDF filename

Requires:
    pip install anthropic python-dotenv
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

MODEL = os.getenv("ANTHROPIC_DRAWING_MODEL", "claude-sonnet-4-20250514")

OUTPUT_FIELDS = [
    "equipment_name",
    "item_detail",
    "qty",
    "location_service",
    "electrical",
    "basis_of_design",
    "section_ref",
    "source_file",
]

_EXTRACTION_PROMPT = """You are an expert at reading HVAC/MEP engineering drawing schedules.

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

_FOLLOWUP_PROMPT = """The previous extraction found these schedules and equipment rows:
{found}

Look at the drawing again very carefully.

FIRST — Are there any entire schedule TABLES that were completely missed?
Common overlooked schedule types:
  Exhaust Fan Schedule, Gravity Ventilator Schedule, Split-Type / VRF AC Schedule,
  Condensate Drain Pump Schedule, VAV Box Schedule, Sound Attenuator Schedule,
  Fan Coil Unit Schedule, Energy Recovery Unit Schedule, Heat Pump Schedule,
  Rooftop Unit Schedule, Cabinet Unit Heater Schedule, Unit Ventilator Schedule,
  Pumps Schedule, Radiation / Convector Schedule.
Look in every corner and margin of the drawing for small tables that may have been missed.

SECOND — Within already-found schedules, are there any individual unit-tagged rows missing?

Return ALL missed rows (from both missed tables and missed rows in found tables)
in the same JSON array format. If nothing is missing, return [].
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

_EXTRACTION_CACHE: dict[str, list] = {}

def _pdf_hash(path: str) -> str:
    """MD5 of the PDF file contents — used as cache key."""
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def _read_pdf_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _repair_json(raw: str) -> str:
    raw = raw.replace('\u201c', "'").replace('\u201d', "'")

    def fix(m):
        inner = re.sub(r'(?<!\\)"', "'", m.group(1))
        return '"' + inner + '"'

    return re.sub(r'"((?:[^"\\]|\\.)*)"', fix, raw)


def _parse_json(raw: str):
    raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw)
    for attempt in (raw, _repair_json(raw)):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            pass
    return None


def _expand_combined_tags(rows: list) -> list:
    """Split 'ST-1S, ST-1R' type entries into individual rows."""
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

def _valid_tag(name: str) -> bool:
    name = name.strip()
    return bool(name) and len(name) <= 30 and bool(_TAG_RE.match(name))


def _clean_row(row: dict, source: str) -> dict:
    cleaned = {f: str(row.get(f, "")).strip() for f in OUTPUT_FIELDS if f != "source_file"}
    cleaned["location_service"] = re.sub(
        r"\s*/\s*$", "", cleaned["location_service"]
    ).strip()
    cleaned["source_file"] = source
    if not cleaned.get("equipment_name"):
        cleaned["equipment_name"] = cleaned.get("item_detail", source)
    return cleaned


def _merge_rows(existing: list, new_rows: list) -> list:
    """Add new_rows not already present; enrich existing rows with missing field values."""
    by_key: dict = {}
    order: list = []
    for row in existing:
        key = str(row.get("equipment_name", "")).strip().upper()
        if key and key not in by_key:
            by_key[key] = row
            order.append(key)

    for row in new_rows:
        key = str(row.get("equipment_name", "")).strip().upper()
        if not key:
            continue
        if key not in by_key:
            by_key[key] = row
            order.append(key)
        else:
            for field in OUTPUT_FIELDS:
                if not by_key[key].get(field) and row.get(field):
                    by_key[key][field] = row[field]

    return [by_key[k] for k in order]


# ── Core extraction ───────────────────────────────────────────────────────────

def _process_single_pdf(pdf_path: str, client: anthropic.Anthropic) -> list:
    """Extract all equipment schedule rows from one PDF using the native document API."""
    source = Path(pdf_path).name

    # Return cached result if this exact PDF was already processed
    cache_key = _pdf_hash(pdf_path)
    if cache_key in _EXTRACTION_CACHE:
        return _EXTRACTION_CACHE[cache_key]

    pdf_b64 = _read_pdf_b64(pdf_path)

    doc_block = {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": pdf_b64,
        },
    }

    # Pass 1: full extraction
    resp1 = client.beta.messages.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0,
        betas=["pdfs-2024-09-25"],
        messages=[{
            "role": "user",
            "content": [
                doc_block,
                {"type": "text", "text": _EXTRACTION_PROMPT},
            ],
        }],
    )

    data1 = _parse_json(resp1.content[0].text)
    if isinstance(data1, dict):
        rows1 = data1.get("rows", [])
    elif isinstance(data1, list):
        rows1 = data1
    else:
        rows1 = []

    rows1 = _expand_combined_tags(rows1)
    rows1 = [r for r in rows1 if _valid_tag(str(r.get("equipment_name", "")))]
    rows1 = [_clean_row(r, source) for r in rows1]

    # Pass 2: gap-fill follow-up
    found_tags = ", ".join(r["equipment_name"] for r in rows1)
    followup_text = _FOLLOWUP_PROMPT.format(found=found_tags)

    resp2 = client.beta.messages.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0,
        betas=["pdfs-2024-09-25"],
        messages=[
            {
                "role": "user",
                "content": [
                    doc_block,
                    {"type": "text", "text": _EXTRACTION_PROMPT},
                ],
            },
            {"role": "assistant", "content": resp1.content[0].text},
            {"role": "user", "content": followup_text},
        ],
    )

    data2 = _parse_json(resp2.content[0].text)
    if isinstance(data2, list):
        rows2 = data2
    elif isinstance(data2, dict):
        rows2 = data2.get("rows", [])
    else:
        rows2 = []

    rows2 = _expand_combined_tags(rows2)
    rows2 = [r for r in rows2 if _valid_tag(str(r.get("equipment_name", "")))]
    rows2 = [_clean_row(r, source) for r in rows2]

    result = _merge_rows(rows1, rows2)
    _EXTRACTION_CACHE[cache_key] = result
    return result


# ── Public interface ──────────────────────────────────────────────────────────

def process_pdfs(pdf_paths):
    """
    Extract drawing schedule fields from a list of PDF file paths.
    Returns a list of dicts (one per equipment row).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. "
            "Enter it in the Streamlit sidebar or create a .env file."
        )

    client = anthropic.Anthropic(api_key=api_key)
    all_rows = []

    for pdf_path in pdf_paths:
        try:
            rows = _process_single_pdf(pdf_path, client)
            all_rows.extend(rows)
        except Exception as exc:
            all_rows.append(
                {
                    "equipment_name": Path(pdf_path).stem,
                    "item_detail": f"ERROR: {exc}",
                    "qty": "",
                    "location_service": "",
                    "electrical": "",
                    "basis_of_design": "",
                    "section_ref": "",
                    "source_file": Path(pdf_path).name,
                }
            )

    return all_rows


# ── CLI / debug helper ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import csv
    import sys

    if len(sys.argv) < 2:
        print("Usage: python extract_drawings.py input.pdf [output.csv]")
        sys.exit(1)

    pdf  = sys.argv[1]
    out  = sys.argv[2] if len(sys.argv) > 2 else "equipment_schedule.csv"
    rows = process_pdfs([pdf])

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done -- {len(rows)} row(s) written to {out}")
