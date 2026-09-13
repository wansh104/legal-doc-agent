import tempfile
import os
import json
import streamlit as st
from dotenv import load_dotenv
load_dotenv()

import sys
sys.path.insert(0, os.path.dirname(__file__))

from src.pipeline import run_pipeline, render_report_markdown, StageError
from src import doc_reader

st.set_page_config(page_title="Legal Document Generation Agent", layout="wide")

st.title("Legal Document Generation & Evaluation Agent")
st.caption("Generates an Affidavit in Reply from case information, following a reference format, then evaluates its own output.")

with st.sidebar:
    st.header("Configuration")
    api_key_input = st.text_input("Gemini API key (optional)", type="password",
                                   help="Leave blank to use GEMINI_API_KEY from your .env file, if set. "
                                        "If neither is set, falls back to demo mode using cached output for the sample case below.")
    if api_key_input:
        os.environ["GEMINI_API_KEY"] = api_key_input

    if os.environ.get("GEMINI_API_KEY"):
        st.success("Using live Gemini calls.")
    else:
        st.info("Demo mode: no API key set. Using cached extraction/generation for the sample case so the app still runs end to end.")

    st.divider()
    st.markdown("**Reference document**")
    st.caption("01_Affidavit_Format_Explained.pdf / 02_Affidavit_in_Reply_Sample — bundled with this app.")

DEFAULT_CASE_INFO_PATH = os.path.join(os.path.dirname(__file__), "data", "case_information.txt")
DEFAULT_REFERENCE_PDF = os.path.join(os.path.dirname(__file__), "data", "reference_sample_affidavit.pdf")

st.subheader("1. Case information")
use_sample = st.checkbox("Use the bundled sample case (Sunrise Housing v. State of Maharashtra & MMRDA)", value=True)

if use_sample:
    case_info_text = open(DEFAULT_CASE_INFO_PATH, encoding="utf-8").read()
    st.text_area("Case information (read-only preview)", case_info_text, height=200, disabled=True)
else:
    uploaded = st.file_uploader("Upload case information (.txt or .pdf)", type=["txt", "pdf"])
    case_info_text = None
    if uploaded is not None:
        if uploaded.name.endswith(".pdf"):
            tmp_path = os.path.join(tempfile.gettempdir(), "_uploaded_case_info.pdf")
            with open(tmp_path, "wb") as f:
                f.write(uploaded.read())
            case_info_text = "\n".join(doc_reader.read_pdf_lines(tmp_path))
        else:
            case_info_text = uploaded.read().decode("utf-8")
        st.text_area("Case information (parsed)", case_info_text, height=200, disabled=True)
        if not api_key_input:
            st.warning(
                "You uploaded a custom case, but no API key is set — demo mode only has cached "
                "output for the bundled sample case, so extraction/generation will fail for a "
                "different case. Add a Gemini API key in the sidebar to run this one live."
            )

st.subheader("2. Generate & evaluate")
run_clicked = st.button("Generate Affidavit in Reply", type="primary", disabled=case_info_text is None)

if run_clicked:
    output_path = os.path.join(tempfile.gettempdir(), "generated_affidavit.docx")
    with st.spinner("Running pipeline (extraction \u2192 mapping \u2192 generation \u2192 evaluation)..."):
        try:
            result = run_pipeline(
                case_info_text=case_info_text,
                reference_pdf_path=DEFAULT_REFERENCE_PDF,
                output_docx_path=output_path,
            )
        except StageError as e:
            st.error(f"**{e.stage}** failed.\n\n{e.original}")
            st.stop()
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            st.stop()

    st.success("Done.")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Generated document")
        with open(output_path, "rb") as f:
            st.download_button(
                "Download generated_affidavit.docx", f,
                file_name="generated_affidavit.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with st.expander("Structured case input (Stage 2 output)"):
            st.json(json.loads(result.case_input.model_dump_json()))
        with st.expander("Evidence mapping (provenance)"):
            st.json(result.case_input.provenance)
        if result.reference_structure_summary:
            with st.expander("Reference document structure check (Stage 1)"):
                st.json(result.reference_structure_summary)
        if result.warnings:
            for w in result.warnings:
                st.warning(w)

    with col2:
        st.subheader("Evaluation report")
        r = result.evaluation_report
        st.metric("Overall Score", f"{r.overall_score}/100")
        for d in r.dimensions:
            st.progress(d.score / 100, text=f"{d.name}: {d.score}/100 ({d.checks_passed}/{d.checks_total} checks)")

        st.markdown("**Issues detected**")
        if not r.issues:
            st.success("No issues detected.")
        else:
            for issue in r.issues:
                icon = "\U0001F534" if issue.severity.value == "error" else "\U0001F7E1"
                st.markdown(f"{icon} **[{issue.dimension}]** {issue.message}  \n*Source: {issue.source}*")

        report_md = render_report_markdown(result)
        st.download_button("Download evaluation_report.md", report_md, file_name="evaluation_report.md")
        st.download_button(
            "Download evaluation_report.json",
            r.model_dump_json(indent=2),
            file_name="evaluation_report.json",
        )

        with st.expander("Scoring method"):
            st.write(r.scoring_explanation)
