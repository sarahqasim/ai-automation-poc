"""
Specification PDF Extractor
============================
Standard interface for the Streamlit app:

    process_pdfs(pdf_paths: list[str]) -> list[dict]

Each dict contains:
    equipment_name  – used to match with drawing results
    section         – spec section number (e.g. "15934")
    manufacturers   – slash-separated list of manufacturer names
    warranty        – one warranty line per row ("N years on component")
    training        – training hours if mentioned
    spare_parts     – spare parts listed
    source_file     – original filename

Requires: pypdf, anthropic (optional — regex fallback if key absent)
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pypdf import PdfReader

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from anthropic import Anthropic
    _key = os.environ.get("ANTHROPIC_API_KEY")
    _client = Anthropic(api_key=_key) if _key else None
except ImportError:
    _client = None


# ── PDF → lines ───────────────────────────────────────────────────────────────

def _extract_lines(pdf_path: str) -> list[str]:
    reader = PdfReader(pdf_path)
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            clean = line.strip()
            if clean:
                lines.append(clean)
    return lines


def _remove_headers_footers(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        t = line.strip()
        if not t:
            continue
        u = t.upper()
        if (
            "NYCSCA" in u
            or "DESIGN NO" in u
            or re.match(r"\d{2}/\d{2}/\d{2,4}", t)
        ):
            continue
        out.append(t)
    return out


# ── Section ───────────────────────────────────────────────────────────────────

def _extract_section(lines: list[str]) -> str:
    for line in lines:
        m = re.search(r"SECTION\s+(\d+)", line.upper())
        if m:
            return m.group(1)
    return ""


# ── Equipment name from filename ──────────────────────────────────────────────

def _equipment_name_from_file(path: Path, section: str) -> str:
    """
    Derive a human-readable equipment name from the filename.
    Example: "D021779-15934-ROOFTOP AIR HANDLING UNITS FOR -CORRIDOR.pdf"
             → "ROOFTOP AIR HANDLING UNITS FOR CORRIDOR"
    Falls back to the section number if no description is found.
    """
    stem = path.stem
    # Strip leading project-number prefix like "D021779-15934-"
    stem = re.sub(r"^[A-Za-z]?\d{5,7}[-_]?\d{3,6}[-_]?", "", stem).strip("-_ ")
    # Clean up dashes/underscores
    stem = re.sub(r"[-_]+", " ", stem).strip()
    stem = re.sub(r"\s+", " ", stem)
    return stem if stem else section


# ── Manufacturers ─────────────────────────────────────────────────────────────

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

_MANU_SHEET_OR_HEADER = re.compile(
    r"\(\s*[A-Z][A-Z\s\-]{3,}\s*\)|"   # (CONSTANT VOLUME SYSTEM)
    r"\b\d{4,}\s*-\s*\d{2,}\b",         # 15934 - 52
    re.I,
)

_MANU_SENTENCE_STOPWORDS = re.compile(
    r"\b(?:the|are|and|for|with|than|that|from|any|all|not|"
    r"shall|must|will|including|except|where|better|provide)\b",
    re.I,
)


def _looks_like_manufacturer_name(s: str) -> bool:
    t = s.strip()
    if not t:
        return False
    if t.endswith(":"):
        return False
    line = t.rstrip(".,;:")
    if not line or not re.search(r"[A-Za-z]", line):
        return False
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
    if len(_MANU_SENTENCE_STOPWORDS.findall(line)) >= 2:
        return False
    if re.match(r"^[\d\s\-/]+$", line):
        return False
    return True


def _iter_manufacturer_input_fragments(text: str):
    """Yield candidate name strings; split slash-merged lines when needed."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        slashes = line.count("/")
        if slashes >= 2 or (slashes >= 1 and len(line) > 90):
            for part in re.split(r"\s*/\s*", line):
                p = part.strip()
                if p:
                    yield p
            continue
        yield line


def _parse_manufacturers_block(text: str) -> str:
    if not text or not text.strip():
        return ""

    boiler = re.compile(
        r"subject\s+to\s+compliance|following\s+manufacturers|"
        r"\bor\s+equal\b|packaged\s+air\s+handling|provide\s+.*\bfrom\b|"
        r"approved\s+manufacturers\s+for|manufacturers\s+for\s+",
        re.I,
    )

    def _is_category_or_intro(line: str) -> bool:
        return bool(boiler.search(line)) or line.rstrip().endswith(":") or len(line) > 90

    names: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        name = name.strip()
        if not name or not _looks_like_manufacturer_name(name):
            return
        k = name.casefold()
        if k not in seen:
            seen.add(k)
            names.append(name)

    for raw in _iter_manufacturer_input_fragments(text):
        line = raw.strip()
        if not line:
            continue

        # Numbered list:  "1. Name"
        m = re.match(r"^\d+\.\s+(.+)$", line)
        if m:
            _add(m.group(1).strip())
            continue

        # Parenthetical number:  "(1) Name" or "1) Name"
        m = re.match(r"^(?:\(\s*\d+\s*\)|\d+\))\s+(.+)$", line)
        if m:
            _add(m.group(1).strip())
            continue

        # Bullet / dash:  "• Name" or "- Name" or "* Name"
        if re.match(r"^[•\u00b7\*\-–—]\s*", line):
            name = re.sub(r"^[•\u00b7\*\-–—]\s*", "", line).strip()
            _add(name)
            continue

        # Letter-prefixed list:  "A. Name"
        m = re.match(r"^[A-Z]\.\s+(.+)$", line)
        if m:
            if _is_category_or_intro(line):
                continue
            _add(m.group(1).strip())
            continue

        if boiler.search(line):
            continue
        _add(line)

    return "/".join(names)


# ── Document parsing (manufacturers + warranty blocks) ───────────────────────

_WARRANTY_EXIT = re.compile(
    r"^\s*\d{1,2}\.\d{1,3}\s+"
    r"(?:TRAINING|SUBMITTAL|SUBMITTALS|DELIVERY|STORAGE|HANDLING|"
    r"QUALITY\s+CONTROL|FIELD\s+QUALITY|FIELD\s+TESTING|"
    r"MAINTENANCE\s+MATERIAL|MAINTENANCE\s+SERVICE|"
    r"PART\s+2\b|PART\s+3\b|EXECUTION|PRODUCT|PAYMENT)\b",
    re.I,
)


def _warranty_should_end(line: str) -> bool:
    s = line.strip()
    if _WARRANTY_EXIT.match(s):
        return True
    m = re.match(r"^\d{1,2}\.\d{1,3}\s+(.+)$", s)
    if not m:
        return False
    tail = m.group(1).strip()
    if re.search(
        r"\b(warrant|month|year|labor|vfd|wheel|casing|recovery|rust)\b", tail, re.I
    ):
        return False
    letters = re.sub(r"[^A-Za-z]+", "", tail)
    return len(letters) >= 6 and letters.isupper()


def _parse_document(lines: list[str]) -> dict[str, str]:
    result = {"manufacturers": "", "warranty": ""}
    current: str | None = None
    for line in lines:
        u = line.upper()
        if re.search(r"\d+\.\d+.*MANUFACTURER", u):
            current = "manufacturers"
            continue
        if re.search(r"\d+\.\d+.*WARRANTY", u):
            current = "warranty"
            continue
        if current == "warranty" and _warranty_should_end(line):
            current = None
            continue
        if current != "warranty" and re.search(r"\d+\.\d+\s", u):
            current = None
            continue
        if current == "manufacturers" and re.match(r"^(?:PART\s+\d+|END\s+OF\s+SECTION)", u.strip()):
            current = None
            continue
        if current:
            sep = "\n" if result[current] else ""
            result[current] = result[current] + sep + line
    return result


def _warranty_block(lines: list[str]) -> str:
    parts: list[str] = []
    capture = False
    for line in lines:
        if re.search(r"\d+\.\d+.*WARRANTY", line.upper()):
            capture = True
            continue
        if capture and _warranty_should_end(line):
            break
        if capture:
            parts.append(line)
    return "\n".join(parts)


# ── Warranty extraction ───────────────────────────────────────────────────────

def _years_label(y: float) -> str:
    if abs(y - 1.0) < 1e-9:
        return "1 year"
    if abs(y - round(y)) < 1e-9:
        return f"{int(round(y))} years"
    return f"{round(y, 1)} years"


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s[3:].lstrip()
        s = re.sub(r"^json\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _claude_text(msg) -> str:
    return "".join(
        getattr(b, "text", "") or ""
        for b in (getattr(msg, "content", None) or [])
        if getattr(b, "type", None) == "text"
    ).strip()


def _regex_warranty(text: str) -> str:
    """Simple regex fallback when the API is unavailable."""
    t = re.sub(r"(\d+)-(?=years?|months?)", r"\1 ", text, flags=re.I)
    t = re.sub(r"\s+", " ", t)

    word_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "twelve": 12, "fifteen": 15, "twenty": 20,
        "twenty-five": 25, "thirty": 30, "thirty-six": 36, "sixty": 60,
    }

    def to_years(amount: str, unit: str) -> float | None:
        a = amount.strip().lower()
        n = word_map.get(a)
        if n is None:
            try:
                n = float(a)
            except ValueError:
                return None
        return float(n) / 12.0 if unit.lower().startswith("m") else float(n)

    PAT = re.compile(
        r"(additional\s+)?"
        r"(one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|"
        r"twenty(?:-five)?|thirty(?:-six)?|sixty|\d+(?:\.\d+)?)"
        r"\s*[-]?\s*(year|yr|month)\w*\b",
        re.I,
    )

    base_years: float | None = None
    lines_out: list[str] = []
    seen: set[str] = set()

    for m in PAT.finditer(t):
        is_add = bool(m.group(1))
        y = to_years(m.group(2), m.group(3))
        if y is None:
            continue

        # Look backwards for the component/subject
        before = t[max(0, m.start() - 200) : m.start()]
        after = t[m.end() : min(len(t), m.end() + 150)]
        comp = ""

        # "X shall have" / "X shall be covered"
        sm = re.search(
            r"(?:^|[.;]\s*)([A-Za-z][^.;]{2,60}?)\s+shall\s+(?:have|be)\s*$",
            before,
            re.I,
        )
        if sm:
            comp = sm.group(1).strip()

        # "warranty for X" / "for the X"
        if not comp:
            sm = re.search(r"\b(?:warranty\s+for|for\s+the|for)\s+([^.,;]{3,60})$", before, re.I)
            if sm:
                comp = sm.group(1).strip()

        # "cover all parts and labor" / "for parts and labor"
        if not comp:
            sm = re.search(r"\b(?:for|cover(?:ing)?)\s+(?:all\s+)?([^.,;\n]{3,60})", after, re.I)
            if sm:
                comp = sm.group(1).strip()

        comp = re.sub(r"\s+", " ", comp).strip(" .,;")
        if not comp:
            comp = "parts and labor"

        final_y = (base_years or 0) + y if is_add and base_years is not None else y
        if not is_add and base_years is None:
            base_years = y

        label = f"{_years_label(final_y)} on {comp[:80]}"
        k = label.casefold()
        if k not in seen:
            seen.add(k)
            lines_out.append(label)

    return "\n".join(lines_out)


def _ai_warranty(text: str) -> str:
    if not text.strip():
        return ""
    if _client is None:
        return _regex_warranty(text)

    model = os.getenv("ANTHROPIC_WARRANTY_MODEL", "claude-sonnet-4-20250514")
    prompt = f"""
Extract warranty information from the specification text below.

Instructions:
- Identify ALL components mentioned (do NOT assume fixed names — read what is written).
- Identify the base warranty duration that applies generally.
- If a component has an "additional" or "extended" warranty, ADD it to the base to get the final total.
- If the total is explicitly stated, use that directly.
- Return the FINAL warranty duration per component.
- Express durations in YEARS only. Convert months: 24→2, 36→3, 60→5.

Return ONLY a JSON array, no markdown:
[{{"years": <number>, "component": "<name from text>"}}]

Text:
{text}
"""
    try:
        resp = _client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _strip_fence(_claude_text(resp))
        data = json.loads(raw)
        if isinstance(data, dict):
            for k in ("warranties", "items", "results"):
                if isinstance(data.get(k), list):
                    data = data[k]
                    break
        if not isinstance(data, list):
            raise ValueError("not a list")
        lines: list[str] = []
        seen: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            comp = str(item.get("component") or item.get("scope") or "").strip()
            y = item.get("years")
            if y is None and item.get("months"):
                y = float(item["months"]) / 12.0
            if not comp or y is None:
                continue
            line = f"{_years_label(float(y))} on {comp}"
            k = line.casefold()
            if k not in seen:
                seen.add(k)
                lines.append(line)
        return "\n".join(lines) if lines else _regex_warranty(text)
    except Exception:
        return _regex_warranty(text)


# ── Training ──────────────────────────────────────────────────────────────────

def _extract_training(lines: list[str]) -> str:
    capture, text = False, ""
    for line in lines:
        u = line.upper()
        if "TRAINING" in u and line == u:
            capture = True
            continue
        if capture and re.search(r"\d+\.\d+\s", u):
            break
        if capture:
            text += " " + line
    m = re.findall(r"(\d+)\s*(hours?|hrs?)", text, re.I)
    return f"{m[0][0]} hrs required" if m else ""


# ── Spare parts ───────────────────────────────────────────────────────────────

def _extract_spare_parts(lines: list[str]) -> str:
    capture, parts = False, []
    for line in lines:
        u = line.upper()
        if re.search(r"\d+\.\d+\s+MAINTENANCE", u):
            capture = True
            continue
        if capture and re.match(r"\d+\.\d+\s+[A-Z]", u):
            break
        if capture:
            parts.append(line)
    text = " ".join(parts)
    items = re.findall(r"spare\s+(?:set\s+of\s+)?([a-zA-Z\-]+)", text, re.I)
    cleaned = []
    seen: set[str] = set()
    for it in items:
        c = re.sub(r"\s+", " ", it).strip().title()
        c = re.sub(r"^(Set Of|Sets Of)\s+", "", c, flags=re.I)
        if c.casefold() not in seen:
            seen.add(c.casefold())
            cleaned.append(c)
    return "\n".join(cleaned)


# ── Public interface ──────────────────────────────────────────────────────────

def process_pdfs(pdf_paths: list[str]) -> list[dict]:
    """
    Extract spec fields from a list of PDF file paths.
    Returns a list of dicts (one per PDF).
    """
    rows: list[dict] = []
    for i, path_str in enumerate(pdf_paths, start=1):
        path = Path(path_str)
        lines = _remove_headers_footers(_extract_lines(path_str))

        section = _extract_section(lines)
        parsed = _parse_document(lines)

        wt_block = _warranty_block(lines)
        wt_text = (
            wt_block
            if len(wt_block.strip()) >= len(parsed["warranty"].strip())
            else parsed["warranty"]
        ) or (wt_block + "\n" + parsed["warranty"]).strip()

        rows.append(
            {
                "equipment_name": _equipment_name_from_file(path, section),
                "section": section,
                "manufacturers": _parse_manufacturers_block(parsed["manufacturers"]),
                "warranty": _ai_warranty(wt_text),
                "training": _extract_training(lines),
                "spare_parts": _extract_spare_parts(lines),
                "source_file": path.name,
            }
        )
    return rows
