"""
PDF Field Extractor — Streamlit App (Tameer branded)
"""

from __future__ import annotations

import importlib.util
import os
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
    background-color: #f7941d !important;
    border: none !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    border-radius: 6px !important;
    padding: 0.55rem 1.5rem !important;
    transition: background-color 0.2s;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background-color: #e07e0a !important;
}

/* ── Download buttons ── */
div[data-testid="stDownloadButton"] > button {
    background-color: #f7941d !important;
    border: none !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    border-radius: 6px !important;
}
div[data-testid="stDownloadButton"] > button:hover {
    background-color: #e07e0a !important;
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
    background-color: #f7941d !important;
    background:       #f7941d !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}
[data-testid="stFileUploaderDropzone"] button:hover,
[data-testid="stFileUploaderDropzone"] button:hover * {
    background-color: #e07e0a !important;
    background:       #e07e0a !important;
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

/* ── Dataframe ── */
div[data-testid="stDataFrame"] {
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #e3e6f0;
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


def run_extractor(module, pdf_paths: list) -> pd.DataFrame:
    if not hasattr(module, "process_pdfs"):
        raise AttributeError(
            "Script must define `process_pdfs(pdf_paths: list[str]) -> list[dict]`."
        )
    rows = module.process_pdfs([str(p) for p in pdf_paths])
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


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

st.markdown("## AI Automation POC")

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
            st.success(f"{len(spec_df)} row(s) extracted")
            st.dataframe(spec_df, use_container_width=True, height=380)
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
            st.success(f"{len(draw_df)} row(s) extracted")
            st.dataframe(draw_df, use_container_width=True, height=380)
            st.download_button(
                label="Download Drawing CSV",
                data=df_to_csv_bytes(draw_df),
                file_name="drawing_output.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True,
                key="dl_draw",
            )
