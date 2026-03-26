"""
Extract section, manufacturers, warranty, training, and spare parts from spec PDFs → CSV.
Requires: pypdf, anthropic (optional, for warranty). Set ANTHROPIC_API_KEY for warranty extraction.

Warranty uses Claude Sonnet by default; override with ANTHROPIC_WARRANTY_MODEL if needed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from pypdf import PdfReader

try:
    from anthropic import Anthropic

    _anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    _anthropic_client = Anthropic(api_key=_anthropic_key) if _anthropic_key else None
except ImportError:
    _anthropic_client = None


# -----------------------------------------------------------------------------
# PDF text → lines
# -----------------------------------------------------------------------------


def extract_lines(pdf_path: Path | str) -> list[str]:
    reader = PdfReader(pdf_path)
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if not text:
            continue
        for line in text.splitlines():
            clean = line.strip()
            if clean:
                lines.append(clean)
    return lines


def extract_section(lines: list[str]) -> str:
    for line in lines:
        match = re.search(r"SECTION\s+(\d+)", line.upper())
        if match:
            return match.group(1)
    return ""


# -----------------------------------------------------------------------------
# Manufacturers + warranty blocks (preserve newlines per PDF line)
# -----------------------------------------------------------------------------


def _manufacturer_capture_stop(upper_line: str) -> bool:
    """True when manufacturers subsection should end (major divisions, not sheet refs)."""
    u = upper_line.strip()
    if re.match(r"^PART\s+\d+", u):
        return True
    if re.match(r"^END\s+OF\s+SECTION", u):
        return True
    if "PART" in u and re.search(r"\bEXECUTION\b", u):
        return True
    return False


# Only treat a line as leaving the WARRANTY block when it looks like the next
# spec subsection heading (e.g. "1.08 TRAINING"). A bare "\d+\.\d+\s" match is
# unsafe: it fires on "2.0 tons", "1.5 years" style lines and drops bullet warranties.
_WARRANTY_EXIT = re.compile(
    r"^\s*\d{1,2}\.\d{1,3}\s+"
    r"(?:TRAINING|SUBMITTAL|SUBMITTALS|DELIVERY|STORAGE|HANDLING|"
    r"QUALITY\s+CONTROL|FIELD\s+QUALITY|FIELD\s+TESTING|MAINTENANCE\s+MATERIAL|MAINTENANCE\s+SERVICE|"
    r"PART\s+2\b|PART\s+3\b|EXECUTION|PRODUCT|SEQUENCE|SCOPE|"
    r"CONTRACT\s+CLOSEOUT|CLOSEOUT|PAYMENT)\b",
    re.I,
)


def _warranty_block_should_end(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if _WARRANTY_EXIT.match(s):
        return True
    # Generic "1.08 TITLE" style break (two-part section ID + uppercase title), but not
    # lines that still read like warranty content.
    if re.match(r"^\d{1,2}\.\d{1,3}\s+\d", s):
        return False
    m = re.match(r"^\d{1,2}\.\d{1,3}\s+(.+)$", s)
    if not m:
        return False
    tail = m.group(1).strip()
    if len(tail) < 4:
        return False
    # Still warranty-ish: keep capturing
    if re.search(
        r"\b(warrant|month|year|labor|vfd|wheel|casing|recovery|rust|substantial\s+completion)\b",
        tail,
        re.I,
    ):
        return False
    # All-caps or leading capital section title
    letters = re.sub(r"[^A-Za-z]+", "", tail)
    if len(letters) >= 6 and letters.isupper():
        return True
    return False


def extract_warranty_block_text(lines: list[str]) -> str:
    """
    Collect lines from the WARRANTY subsection only.
    Safer than relying on parse_document alone when PDF line breaks interact with state machine.
    """
    parts: list[str] = []
    capture = False
    for line in lines:
        upper = line.upper()
        if re.search(r"\d+\.\d+.*WARRANTY", upper):
            capture = True
            continue
        if capture and _warranty_block_should_end(line):
            break
        if capture:
            parts.append(line)
    return "\n".join(parts)


def parse_document(lines: list[str]) -> dict[str, str]:
    results = {"manufacturers": "", "warranty": ""}
    current: str | None = None

    for line in lines:
        upper = line.upper()

        if re.search(r"\d+\.\d+.*MANUFACTURER", upper):
            current = "manufacturers"
            continue

        if re.search(r"\d+\.\d+.*WARRANTY", upper):
            current = "warranty"
            continue

        if current == "warranty" and _warranty_block_should_end(line):
            current = None
            continue

        if current != "warranty" and re.search(r"\d+\.\d+\s", upper):
            current = None
            continue

        if current == "manufacturers" and _manufacturer_capture_stop(upper):
            current = None
            continue

        if current:
            sep = "\n" if results[current] else ""
            results[current] = results[current] + sep + line

    return results


# Prose / spec language — not brand names (used after splitting PDF-merge artifacts on "/")
_MANU_PROSE = re.compile(
    r"subject\s+to\s+compliance|"
    r"following\s+manufacturers|"
    r"\bor\s+equal\b|"
    r"\bequal\s+or\s+better\b|"
    r"packaged\s+air\s+handling|"
    r"provide\s+.*\bfrom\b|"
    r"approved\s+manufacturers\s+for|"
    r"\bmanufacturers\s+for\b|"
    r"\bcapacities\b|"
    r"\bdimensions\b|"
    r"\bweights\b|"
    r"\bmaterials\b|"
    r"\bperformance\b|"
    r"\bcriteria\b|"
    r"\bcontractor\b|"
    r"\bresponsibility\b|"
    r"\bbasis\s+of\b|"
    r"\bmechanical\b|"
    r"\belectrical\b|"
    r"\binstallation\b|"
    r"\bsubmit\b|"
    r"\bcompliance\b|"
    r"\boperating\s+costs?\b|"
    r"\bmaintenance\s+costs?\b|"
    r"\bincluding\s+operating\b|"
    r"\bincluding\s+the\b|"
    r"\bincluding\s+all\b|"
    r"\bcosts?\s+and\s+benefits\b",
    re.I,
)

# Category headings merged with lists, e.g. "Pumps Units:", "Heat Recovery Units:"
_MANU_CATEGORY_HEADING = re.compile(
    r"^pumps?\s+units\s*:?\s*$|"
    r"^heat\s+pumps?\s+units\s*:?\s*$|"
    r"^heat\s+recovery\s+units\s*:?\s*$|"
    r"^recovery\s+units\s*:?\s*$|"
    r"^air\s+handling\s+units\s*:?\s*$|"
    r"\b(?:two|three)[\s-]+pipe\b.*\bunits\b|"
    r"\b(?:occupied|unoccupied)\s+space\b.*\bunits\b",
    re.I,
)

# Sheet / header fragments like (CONSTANT VOLUME SYSTEM) 15934 - 52
_MANU_SHEET_OR_HEADER = re.compile(
    r"\(\s*[A-Z][A-Z\s\-]{3,}\s*\)|"  # (CONSTANT VOLUME SYSTEM)
    r"\b\d{4,}\s*-\s*\d{2,}\b",  # 15934 - 52
    re.I,
)

_MANU_SENTENCE_STOPWORDS = re.compile(
    r"\b(?:the|are|and|for|with|than|that|from|any|all|not|"
    r"shall|must|will|including|except|where|better|provide)\b",
    re.I,
)


def _looks_like_manufacturer_name(s: str) -> bool:
    """Filter spec prose / merged PDF junk; keep short brand-like tokens."""
    t = s.strip()
    if not t:
        return False
    # Subsection labels always end with ":" — never strip before this check
    if t.endswith(":"):
        return False
    line = t.rstrip(".,;:")
    if not line or not re.search(r"[A-Za-z]", line):
        return False
    # Sentence tail glued before the first real brand (e.g. "including operating costs.")
    if re.match(r"^including\s+", line, re.I) and re.search(
        r"\b(cost|costs|fee|fees|expense|operating|maintenance)\b", line, re.I
    ):
        return False
    if _MANU_CATEGORY_HEADING.search(line):
        return False
    if _MANU_PROSE.search(line):
        return False
    if _MANU_SHEET_OR_HEADER.search(line):
        return False
    if re.match(r"^PART\s+\d+", line, re.I):
        return False
    if len(line) > 85:
        return False
    words = line.split()
    if len(words) > 10:
        return False
    if len(words) >= 4 and ("," in line or ";" in line):
        return False
    if line.count(",") >= 2:
        return False
    sw = len(_MANU_SENTENCE_STOPWORDS.findall(line))
    if sw >= 2:
        return False
    # Mostly digits (page/sheet noise)
    if re.match(r"^[\d\s\-/]+$", line):
        return False
    return True


def _iter_manufacturer_input_fragments(text: str):
    """
    PDF extract often glues lines with '/'. Yield candidates from newlines and,
    when needed, split on slashes so plain name lists survive extraction.
    """
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        slashes = line.count("/")
        # Multiple segments merged, or one long line with path-like breaks
        if slashes >= 2 or (slashes >= 1 and len(line) > 90):
            for part in re.split(r"\s*/\s*", line):
                p = part.strip()
                if p:
                    yield p
            continue
        yield line


def extract_manufacturers(text: str) -> str:
    if not text or not text.strip():
        return ""

    boiler = re.compile(
        r"subject\s+to\s+compliance|"
        r"following\s+manufacturers|"
        r"\bor\s+equal\b|"
        r"packaged\s+air\s+handling|"
        r"provide\s+.*\bfrom\b|"
        r"approved\s+manufacturers\s+for|"
        r"manufacturers\s+for\s+",
        re.I,
    )

    def is_category_or_intro_letter_line(line: str) -> bool:
        if boiler.search(line):
            return True
        if line.rstrip().endswith(":"):
            return True
        if len(line) > 90:
            return True
        return False

    manufacturers: list[str] = []
    seen: set[str] = set()

    def add_name(name: str) -> None:
        name = name.strip()
        if not name or not _looks_like_manufacturer_name(name):
            return
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            manufacturers.append(name)

    for raw in _iter_manufacturer_input_fragments(text):
        line = raw.strip()
        if not line:
            continue

        m = re.match(r"^\d+\.\s+(.+)$", line)
        if m:
            add_name(m.group(1).strip())
            continue

        m = re.match(r"^(?:\(\s*\d+\s*\)|\d+\))\s+(.+)$", line)
        if m:
            add_name(m.group(1).strip())
            continue

        if re.match(r"^[•\u00b7\\-–—]\s", line):
            name = re.sub(r"^[•\u00b7\\-–—]\s", "", line).strip()
            add_name(name)
            continue

        m = re.match(r"^[A-Z]\.\s+(.+)$", line)
        if m:
            if is_category_or_intro_letter_line(line):
                continue
            add_name(m.group(1).strip())
            continue

        if boiler.search(line):
            continue
        add_name(line)

    return "/".join(manufacturers)


def _strip_json_fence(content: str) -> str:
    s = content.strip()
    if s.startswith("```"):
        s = s[3:].lstrip()
        s = re.sub(r"^(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _claude_response_text(message: object) -> str:
    """Concatenate text blocks from a Claude Messages API response."""
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


def _years_label(years_value: float) -> str:
    if abs(years_value - 1.0) < 1e-9:
        return "1 year"
    if abs(years_value - round(years_value)) < 1e-9:
        return f"{int(round(years_value))} years"
    return f"{round(years_value, 1)} years"


def _regex_fallback_warranties(text: str) -> str:
    """Simple regex fallback when the API is unavailable."""
    if not text.strip():
        return ""
    lines_out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        t = re.sub(r"\s+", " ", s.strip())
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            lines_out.append(t)

    for m in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(months?|years?)\b.{0,150}?(?=[.;\n]|$)",
        text,
        re.I | re.DOTALL,
    ):
        n, u = float(m.group(1)), m.group(2).lower()
        years = n / 12.0 if u.startswith("m") else n
        label = _years_label(years)
        rest = m.group(0)[m.end(2) - m.start() :].strip()
        sm = re.search(r"\b(?:on|for|covering)\s+(.+)", rest, re.I)
        comp = sm.group(1).strip()[:80] if sm else ""
        if comp:
            add(f"{label} on {comp}")
    return "\n".join(lines_out) if lines_out else ""


def ai_extract_warranty(text: str) -> str:
    if not text.strip():
        return ""

    if _anthropic_client is None:
        return _regex_fallback_warranties(text)

    model = os.getenv("ANTHROPIC_WARRANTY_MODEL", "claude-sonnet-4-20250514")

    prompt = f"""
Extract warranty information from the specification text below.

Instructions:
- Identify ALL components mentioned in the warranty section (do NOT assume fixed names — read what is actually written).
- Identify the base warranty duration that applies generally.
- If a specific component has an "additional" or "extended" warranty period, ADD it to the base to get the final total for that component.
- If the total warranty for a component is explicitly stated, use that directly.
- Return the FINAL warranty duration per component.
- Always express durations in YEARS. Convert months to years (e.g. 24 months = 2 years, 36 months = 3 years, 60 months = 5 years).

Output format — return ONLY a JSON array of objects, no markdown fences:
[
  {{"years": <number>, "component": "<component name from the text>"}},
  ...
]

One object per distinct warranty. Component names must come from the actual text (e.g. "parts and labor", "compressors", "VFDs", "unit casing", "refrigerant circuit") — never invent generic labels like "system" or "equipment".

Text:
{text}
"""

    try:
        response = _anthropic_client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _claude_response_text(response)
        if not raw:
            raise ValueError("empty response")
        raw = _strip_json_fence(raw)
        data = json.loads(raw)
        if isinstance(data, dict):
            for key in ("warranties", "lines", "items", "results", "output"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ValueError("not a list")
        lines: list[str] = []
        seen: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            comp = str(
                item.get("component") or item.get("scope") or item.get("item") or ""
            ).strip()
            y = item.get("years")
            if y is None and item.get("months") is not None:
                y = float(item["months"]) / 12.0
            if not comp or y is None:
                continue
            try:
                yf = float(y)
            except (TypeError, ValueError):
                continue
            line = f"{_years_label(yf)} on {comp}"
            k = line.casefold()
            if k not in seen:
                seen.add(k)
                lines.append(line)
        if not lines:
            raise ValueError("no lines")
        return "\n".join(lines)
    except Exception:
        return _regex_fallback_warranties(text)


# -----------------------------------------------------------------------------
# Training
# -----------------------------------------------------------------------------


def extract_training(lines: list[str]) -> str:
    capture = False
    training_text = ""

    for line in lines:
        upper = line.upper()

        if "TRAINING" in upper and line == line.upper():
            capture = True
            continue

        if capture and re.search(r"\d+\.\d+\s", upper):
            break

        if capture:
            training_text += " " + line

    matches = re.findall(r"(\d+)\s*(hours|hrs|hour|hr)", training_text, re.I)
    if matches:
        return f"{matches[0][0]} hrs required"
    return ""


# -----------------------------------------------------------------------------
# Spare parts
# -----------------------------------------------------------------------------


def extract_spare_parts(lines: list[str]) -> str:
    capture = False
    section_text: list[str] = []

    for line in lines:
        upper = line.upper()

        if re.search(r"\d+\.\d+\s+MAINTENANCE", upper) or re.search(
            r"\d+\.\d+\s+MAINTENANCE MATERIAL", upper
        ):
            capture = True
            continue

        if capture and re.match(r"\d+\.\d+\s+[A-Z]", upper):
            break

        if capture:
            section_text.append(line)

    text = " ".join(section_text)
    matches = re.findall(
        r"spare\s+(?:set\s+of\s+)?([a-zA-Z\-]+)", text, re.IGNORECASE
    )
    results: list[str] = []
    for item in matches:
        cleaned = item.strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"^(set of|sets of)\s+", "", cleaned, flags=re.I)
        results.append(cleaned.title())
    return "\n".join(dict.fromkeys(results))


# -----------------------------------------------------------------------------
# Headers / footers
# -----------------------------------------------------------------------------


def remove_headers_footers(lines: list[str]) -> list[str]:
    cleaned_lines: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        upper = text.upper()
        if (
            "NYCSCA" in upper
            or "DESIGN NO" in upper
            or "ROOFTOP AIR HANDLING" in upper
            or re.match(r"\d{2}/\d{2}/\d{2,4}", text)
        ):
            continue
        cleaned_lines.append(text)
    return cleaned_lines


# -----------------------------------------------------------------------------
# Folder → rows
# -----------------------------------------------------------------------------


def process_folder(folder: str | Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pdf_files = sorted(Path(folder).glob("*.pdf"))

    for i, pdf in enumerate(pdf_files, start=1):
        lines = extract_lines(pdf)
        lines = remove_headers_footers(lines)

        section = extract_section(lines)
        parsed = parse_document(lines)
        manufacturers = extract_manufacturers(parsed["manufacturers"])
        wt_parse = parsed["warranty"]
        wt_block = extract_warranty_block_text(lines)
        warranty_text = (
            wt_block
            if len(wt_block.strip()) >= len(wt_parse.strip())
            else wt_parse
        )
        if not warranty_text.strip():
            warranty_text = (wt_block + "\n" + wt_parse).strip()
        warranty = ai_extract_warranty(warranty_text)
        training = extract_training(lines)
        spare_parts = extract_spare_parts(lines)

        rows.append(
            {
                "sr#": str(i),
                "section": section,
                "manufacturers": manufacturers,
                "warranty": warranty,
                "training": training,
                "spare parts": spare_parts,
            }
        )

    return rows


def save_csv(rows: list[dict[str, str]], filename: str | Path) -> None:
    fields = ["sr#", "section", "manufacturers", "warranty", "training", "spare parts"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


# -----------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract spec fields from all PDFs in a folder and write a CSV.",
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=Path("input"),
        help="Folder containing .pdf files (default: ./input)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output") / "spec_summary.csv",
        help="Output CSV path (default: ./output/spec_summary.csv)",
    )
    args = parser.parse_args()
    folder = args.input.resolve()
    out_path = args.output.resolve()

    if not folder.is_dir():
        raise SystemExit(f"Input path is not a folder: {folder}")

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDF files found in: {folder}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = process_folder(folder)
    save_csv(rows, out_path)
    print(f"Wrote {len(rows)} row(s) to {out_path}")


if __name__ == "__main__":
    main()
