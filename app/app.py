"""
PDF Field Extractor — Streamlit App (Tameer branded)
"""

from __future__ import annotations

import difflib
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

import pandas as pd
import streamlit as st

# Load API key from .env (searches current dir and parent dirs automatically)
try:
    from dotenv import load_dotenv
    # Try the project root .env first, then fall back to any .env in parent dirs
    _env_file = Path(__file__).parent.parent / ".env"
    load_dotenv(_env_file if _env_file.exists() else None)
except ImportError:
    pass

st.set_page_config(
    page_title="AI Automation POC — Tameer",
    page_icon="📄",
    layout="wide",
)

SCRIPTS_DIR = Path(__file__).parent / "scripts"
LOGO_PATH   = Path(__file__).parent / "tameer_logo.png"

# ── Brand CSS ─────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Page background ── */
.stApp { background-color: #f5f6fa; }

/* ── Adjust top padding so main logo aligns with sidebar logo ── */
.stMainBlockContainer, div[data-testid="stMainBlockContainer"] {
    padding-top: 3.5rem !important;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background-color: #ffffff;
    border-right: 1px solid #e3e6f0;
}
section[data-testid="stSidebar"] * { color: #4a4a4a !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: #2c3e50 !important; }

/* ── Top-level headings ── */
h1 { color: #2c3e50 !important; font-weight: 700 !important; }
h2, h3, h4 { color: #2c3e50 !important; font-weight: 600 !important; }

/* ── Primary button (Extract) ── */
div[data-testid="stButton"] > button[kind="primary"] {
    background-color: #ffffff !important;
    border: 1px solid #d1d5db !important;
    color: #1a1a1a !important;
    font-weight: 600 !important;
    border-radius: 6px !important;
    padding: 0.55rem 1.5rem !important;
    transition: background-color 0.2s, border-color 0.2s;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background-color: #f3f4f6 !important;
    border-color: #9ca3af !important;
}

/* ── Download buttons ── */
div[data-testid="stDownloadButton"] > button {
    background-color: #ffffff !important;
    border: 1px solid #d1d5db !important;
    color: #1a1a1a !important;
    font-weight: 600 !important;
    border-radius: 6px !important;
}
div[data-testid="stDownloadButton"] > button:hover {
    background-color: #f3f4f6 !important;
    border-color: #9ca3af !important;
}

/* ── File uploader outer card ── */
div[data-testid="stFileUploader"] {
    background-color: #ffffff !important;
    border: 1px solid #e3e6f0 !important;
    border-left: 4px solid #f7941d !important;
    border-radius: 10px !important;
    padding: 1.2rem 1.2rem 1.2rem 1.4rem !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
}
div[data-testid="stFileUploader"]:hover {
    box-shadow: 0 4px 16px rgba(247,148,29,0.15) !important;
    border-left-color: #e07e0a !important;
}

/* ── Dropzone — force light background ── */
[data-testid="stFileUploaderDropzone"],
[data-testid="stFileUploaderDropzone"] > div {
    background-color: #f9fafb !important;
    background:       #f9fafb !important;
    border: none !important;
    border-radius: 8px !important;
    color-scheme: light !important;
}
[data-testid="stFileUploaderDropzone"]:hover,
[data-testid="stFileUploaderDropzone"]:hover > div {
    background-color: #f3f4f6 !important;
    background:       #f3f4f6 !important;
}

/* ── All text inside dropzone and file list ── */
[data-testid="stFileUploaderDropzone"] span,
[data-testid="stFileUploaderDropzone"] small,
[data-testid="stFileUploaderDropzone"] p,
[data-testid="stFileUploaderDropzone"] div,
div[data-testid="stFileUploader"] span,
div[data-testid="stFileUploader"] small,
div[data-testid="stFileUploader"] p,
div[data-testid="stFileUploader"] li {
    color: #1a1a1a !important;
}

/* ── Success alert text ── */
div[data-testid="stAlert"] p,
div[data-testid="stAlert"] span {
    color: #1a1a1a !important;
}

/* ── Browse files button ── */
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploaderDropzone"] button * {
    background-color: #ffffff !important;
    background:       #ffffff !important;
    color: #1a1a1a !important;
    border: 1px solid #d1d5db !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}
[data-testid="stFileUploaderDropzone"] button:hover,
[data-testid="stFileUploaderDropzone"] button:hover * {
    background-color: #f3f4f6 !important;
    background:       #f3f4f6 !important;
    border-color: #9ca3af !important;
}

/* ── Success / info alerts ── */
div[data-testid="stAlert"][kind="success"],
div.stSuccess {
    background-color: #eaf7ee !important;
    border-left: 4px solid #27ae60 !important;
    color: #1e7e45 !important;
}
div[data-testid="stAlert"][kind="info"],
div.stInfo {
    background-color: #eaf2fb !important;
    border-left: 4px solid #2980b9 !important;
}

/* ── Table (st.table) ── */
div[data-testid="stTable"] {
    background-color: #ffffff !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    border: 1px solid #d1d5db !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05) !important;
}
div[data-testid="stTable"] table {
    width: 100% !important;
    border-collapse: collapse !important;
    background-color: #ffffff !important;
    color: #1a1a1a !important;
}
div[data-testid="stTable"] thead tr th {
    background-color: #f3f4f6 !important;
    color: #1a1a1a !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    padding: 10px 14px !important;
    border-bottom: 2px solid #1a1a1a !important;
    border-right: 1px solid #d1d5db !important;
    text-align: left !important;
}
div[data-testid="stTable"] tbody tr td {
    background-color: #ffffff !important;
    color: #1a1a1a !important;
    padding: 9px 14px !important;
    border-bottom: 1px solid #d1d5db !important;
    border-right: 1px solid #d1d5db !important;
    font-size: 0.85rem !important;
}
div[data-testid="stTable"] tbody tr:last-child td {
    border-bottom: none !important;
}
div[data-testid="stTable"] tbody tr:hover td {
    background-color: #fef6ec !important;
}

/* ── Divider ── */
hr { border-color: #e3e6f0 !important; }

/* ── Caption / small text ── */
small, .stCaption { color: #7f8c8d !important; }

/* ── Spinner text ── */
div[data-testid="stSpinner"] p,
div[data-testid="stSpinner"] span,
div[data-testid="stSpinner"] * { color: #1a1a1a !important; }

/* ── Section cards ── */
.tameer-card {
    background: #ffffff;
    border-radius: 10px;
    border: 1px solid #e3e6f0;
    padding: 1.5rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}

.tameer-badge {
    display: inline-block;
    background-color: #fff3e0;
    color: #f7941d;
    font-size: 0.75rem;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 20px;
    margin-bottom: 0.5rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def save_uploads(files, dest_dir: Path) -> list:
    saved = []
    for f in files:
        p = dest_dir / f.name
        p.write_bytes(f.read())
        saved.append(p)
    return saved


_DROP_COLS = {"section_ref", "source_file", "section"}

_COLUMN_LABELS = {
    "equipment_name":  "Equipment Name",
    "item_detail":     "Item Detail",
    "qty":             "Qty",
    "location_service":"Location / Service",
    "electrical":      "Electrical",
    "basis_of_design": "Basis of Design",
    "manufacturers":   "Manufacturers",
    "warranty":        "Warranty",
    "training":        "Training",
    "spare_parts":     "Spare Parts",
}

def run_extractor(module, pdf_paths: list) -> pd.DataFrame:
    if not hasattr(module, "process_pdfs"):
        raise AttributeError(
            "Script must define `process_pdfs(pdf_paths: list[str]) -> list[dict]`."
        )
    rows = module.process_pdfs([str(p) for p in pdf_paths])
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    cols_to_drop = [c for c in df.columns if c in _DROP_COLS]
    if cols_to_drop:
        df = df.drop(columns=cols_to_drop)
    df = df.rename(columns=_COLUMN_LABELS)
    return df


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse spaces."""
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()

# Common filler words that shouldn't influence equipment matching
_STOP_WORDS = {"the", "a", "an", "of", "and", "or", "for", "to", "in", "at",
               "by", "with", "type", "unit", "schedule", "system"}

def _keywords(text: str) -> set[str]:
    """Return meaningful words from text, excluding stop words and short tokens."""
    return {w for w in _normalise(text).split() if w not in _STOP_WORDS and len(w) > 1}

def _jaccard(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)

def _match_score(draw_row: dict, spec_name: str) -> float:
    """
    Score a drawing row against a spec equipment name using word-set Jaccard similarity.
    item_detail (full schedule title) is the primary signal; equipment_name tag is secondary.
    Jaccard correctly penalises descriptions that only partially overlap keyword-wise.
    """
    spec_kw = _keywords(spec_name)

    # Primary: item_detail has the full human-readable schedule description
    detail_kw = _keywords(str(draw_row.get("item_detail", "")))
    score_detail = _jaccard(detail_kw, spec_kw)

    # Secondary: tag (e.g. "DOAS-1") — low weight, only helps if detail is empty
    tag_kw = _keywords(str(draw_row.get("equipment_name", "")))
    score_tag = _jaccard(tag_kw, spec_kw) * 0.4

    return max(score_detail, score_tag)

def merge_spec_draw(spec_df: pd.DataFrame, draw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Left-join drawing rows with spec data.
    Matches 'Item Detail' against spec 'Equipment Name' using Jaccard word-set similarity.
    Drawing rows are the base; spec columns are appended where a match is found.
    """
    if spec_df.empty and draw_df.empty:
        return pd.DataFrame()
    if spec_df.empty:
        return draw_df.copy()
    if draw_df.empty:
        return spec_df.copy()

    eq_col     = "Equipment Name"
    detail_col = "Item Detail"

    spec_cols  = [c for c in spec_df.columns if c != eq_col]
    spec_names = spec_df[eq_col].tolist() if eq_col in spec_df.columns else []

    merged_rows = []
    for _, row in draw_df.iterrows():
        draw_dict = row.to_dict()
        # Build a proxy dict with original key names for _match_score
        proxy = {
            "equipment_name": str(draw_dict.get(eq_col, "")),
            "item_detail":    str(draw_dict.get(detail_col, "")),
        }
        best_name, best_score = None, 0.0
        for sname in spec_names:
            score = _match_score(proxy, sname)
            if score > best_score:
                best_score, best_name = score, sname

        spec_row = (
            spec_df[spec_df[eq_col] == best_name].iloc[0]
            if best_name and best_score >= 0.45
            else None
        )
        merged = draw_dict.copy()
        for col in spec_cols:
            merged[col] = spec_row[col] if spec_row is not None else ""
        merged_rows.append(merged)

    draw_cols = list(draw_df.columns)
    all_cols  = draw_cols + [c for c in spec_cols if c not in draw_cols]
    return pd.DataFrame(merged_rows, columns=all_cols)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)
    else:
        st.markdown("## Tameer")

    st.divider()
    if os.environ.get("ANTHROPIC_API_KEY"):
        st.success("API key loaded")
    else:
        st.error("API key not found. Add `ANTHROPIC_API_KEY` to your `.env` file.")


# ── Header ────────────────────────────────────────────────────────────────────

import base64 as _b64

def _logo_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return _b64.b64encode(f.read()).decode()

if LOGO_PATH.exists():
    _logo_b64 = _logo_base64(LOGO_PATH)
    st.markdown(f"""
<div style="
    display: inline-block;
    padding: 0 0 0.75rem 0;
    border-bottom: 2px solid #f7941d;
    margin-bottom: 1.5rem;
    width: 100%;
">
    <img src="data:image/png;base64,{_logo_b64}"
         style="height: 56px; width: auto; object-fit: contain; display: block;" />
    <span style="
        display: block;
        font-size: 1.4rem;
        font-weight: 700;
        color: #2c3e50;
        margin-top: 0.5rem;
        letter-spacing: -0.01em;
    ">Equipment Log</span>
</div>
""", unsafe_allow_html=True)
else:
    st.markdown("## Equipment Log")
    st.divider()

# ── Upload section ────────────────────────────────────────────────────────────

col1, col2 = st.columns(2, gap="large")

with col1:
    st.markdown(
        "<div class='tameer-badge'>Specifications</div>",
        unsafe_allow_html=True,
    )
    st.markdown("#### Specification PDFs")
    spec_files = st.file_uploader(
        "spec_upload",
        type="pdf",
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="spec_pdfs",
        help="Upload one or more specification PDF files.",
    )
    if spec_files:
        st.success(f"{len(spec_files)} file(s) ready")
    else:
        st.caption("No files uploaded yet.")

with col2:
    st.markdown(
        "<div class='tameer-badge'>Drawings</div>",
        unsafe_allow_html=True,
    )
    st.markdown("#### Drawing PDFs")
    draw_files = st.file_uploader(
        "draw_upload",
        type="pdf",
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="draw_pdfs",
        help="Upload one or more drawing PDF files.",
    )
    if draw_files:
        st.success(f"{len(draw_files)} file(s) ready")
    else:
        st.caption("No files uploaded yet.")

st.divider()

# ── Run button ────────────────────────────────────────────────────────────────

nothing_uploaded = not spec_files and not draw_files

run = st.button(
    "Extract",
    type="primary",
    use_container_width=True,
    disabled=nothing_uploaded,
)

if nothing_uploaded:
    st.caption("Upload at least one PDF to enable extraction.")

# ── Extraction ────────────────────────────────────────────────────────────────

if run:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("API key not found. Add `ANTHROPIC_API_KEY` to your `.env` file and restart the app.")
        st.stop()

    st.session_state.pop("spec_df", None)
    st.session_state.pop("draw_df", None)

    temp_spec_dir = Path(tempfile.mkdtemp())
    temp_draw_dir = Path(tempfile.mkdtemp())

    try:
        if spec_files:
            with st.spinner(f"Extracting from {len(spec_files)} specification PDF(s)..."):
                try:
                    spec_paths = save_uploads(spec_files, temp_spec_dir)
                    spec_mod = load_module("spec_extractor", SCRIPTS_DIR / "extract_specs.py")
                    st.session_state["spec_df"] = run_extractor(spec_mod, spec_paths)
                except Exception:
                    st.error("Spec extraction failed:")
                    st.code(traceback.format_exc())

        if draw_files:
            with st.spinner(f"Extracting from {len(draw_files)} drawing PDF(s)..."):
                try:
                    draw_paths = save_uploads(draw_files, temp_draw_dir)
                    draw_mod = load_module("draw_extractor", SCRIPTS_DIR / "extract_drawings.py")
                    st.session_state["draw_df"] = run_extractor(draw_mod, draw_paths)
                except Exception:
                    st.error("Drawing extraction failed:")
                    st.code(traceback.format_exc())

    finally:
        shutil.rmtree(temp_spec_dir, ignore_errors=True)
        shutil.rmtree(temp_draw_dir, ignore_errors=True)

# ── Results ───────────────────────────────────────────────────────────────────

spec_df: pd.DataFrame = st.session_state.get("spec_df", pd.DataFrame())
draw_df: pd.DataFrame = st.session_state.get("draw_df", pd.DataFrame())

if not spec_df.empty or not draw_df.empty:
    st.divider()
    st.markdown("## Results")

    res1, res2 = st.columns(2, gap="large")

    with res1:
        st.markdown(
            "<div class='tameer-badge'>Specifications</div>",
            unsafe_allow_html=True,
        )
        st.markdown("#### Specification Output")
        if spec_df.empty:
            st.info("No spec data extracted.")
        else:
            st.success(f"{len(spec_df)} equipment(s) extracted")
            st.table(spec_df)
            st.download_button(
                label="Download Spec CSV",
                data=df_to_csv_bytes(spec_df),
                file_name="spec_output.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True,
                key="dl_spec",
            )

    with res2:
        st.markdown(
            "<div class='tameer-badge'>Drawings</div>",
            unsafe_allow_html=True,
        )
        st.markdown("#### Drawing Output")
        if draw_df.empty:
            st.info("No drawing data extracted.")
        else:
            st.success(f"{len(draw_df)} equipment(s) extracted")
            st.table(draw_df)
            st.download_button(
                label="Download Drawing CSV",
                data=df_to_csv_bytes(draw_df),
                file_name="drawing_output.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True,
                key="dl_draw",
            )

    # ── Combined output ────────────────────────────────────────────────────────
    if not spec_df.empty and not draw_df.empty:
        st.divider()
        st.markdown(
            "<div class='tameer-badge'>Combined</div>",
            unsafe_allow_html=True,
        )
        st.markdown("#### Combined Output")

        combined_df = merge_spec_draw(spec_df, draw_df)
        st.session_state["combined_df"] = combined_df

        matched = int(combined_df["Manufacturers"].ne("").sum()) if "Manufacturers" in combined_df.columns else 0
        st.success(f"{len(combined_df)} row(s) — {matched} matched to a spec")
        st.table(combined_df)
        st.download_button(
            label="Download Combined CSV",
            data=df_to_csv_bytes(combined_df),
            file_name="combined_output.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True,
            key="dl_combined",
        )
