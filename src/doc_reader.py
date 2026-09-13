"""
Stages 1 & 5 — Structure Extraction from a rendered .docx.

Pure regex/pattern matching over paragraph text — deliberately NOT an LLM
call. We wrote the document ourselves with known formatting conventions
(Stage 4), so a reliable parser is straightforward and, unlike an LLM read,
gives byte-exact, reproducible answers for the deterministic checks in
Stage 6. LLM-based checks (used only for the Hallucination Check dimension)
are handled separately in evaluation.py.
"""

from __future__ import annotations
import re
from docx import Document
from src.schema import ExtractedStructure, ExtractedParagraph
from src.template_spec import REQUIRED_SECTIONS

RESPONDENT_NO_RE = re.compile(r"Respondent No\.?\s*(\d+)", re.IGNORECASE)
BODY_PARA_RE = re.compile(r"^(\d+)\.\s+(.*)$")
PRAYER_ITEM_RE = re.compile(r"^\(([a-h])\)\s+(.*)$")
VERIFICATION_RANGE_RE = re.compile(r"paragraphs?\s+(\d+\s+to\s+\d+)", re.IGNORECASE)
EXHIBIT_RE = re.compile(r"EXHIBIT[-\s]*[\u2018\u2019']?([A-Z])", re.IGNORECASE)
VERB_PATTERNS = [
    ("solemnly affirm", "solemnly affirm"),
    ("swear and affirm", "swear and affirm"),
]
JURAT_VERB_RE = re.compile(r"(Solemnly affirmed|Sworn)", re.IGNORECASE)


def extract_structure(docx_path: str) -> ExtractedStructure:
    """Extract structure from a .docx (used on our own generated output)."""
    doc = Document(docx_path)
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return _extract_structure_from_lines(lines)


def read_pdf_lines(pdf_path: str) -> list[str]:
    """Read a PDF's text content into a flat list of non-empty lines.
    Used to actually read the reference document and case info PDFs shipped
    with this assignment (Stage 1 / Stage 2 inputs), rather than assuming
    their content is already available as a string."""
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(line.strip() for line in text.splitlines() if line.strip())
    return lines


def extract_structure_from_pdf(pdf_path: str) -> ExtractedStructure:
    """Stage 1: parse the reference affidavit (given as a PDF) into
    ExtractedStructure. Used as a runtime sanity check that template_spec.py's
    hardcoded rules actually match what's in the shipped reference sample —
    see README design notes for why the rules themselves are hardcoded
    rather than re-derived from this parse on every run."""
    lines = read_pdf_lines(pdf_path)
    return _extract_structure_from_lines(lines)


def _extract_structure_from_lines(lines: list[str]) -> ExtractedStructure:
    result = ExtractedStructure()
    sections_found: set[str] = set()

    for i, line in enumerate(lines):
        upper = line.upper()

        if line.upper().startswith("IN THE HIGH COURT"):
            result.forum_line = line
            sections_found.add("forum_heading")
        elif upper.endswith("JURISDICTION") and "IN THE HIGH COURT" not in upper:
            result.jurisdiction_line = line
            sections_found.add("jurisdiction")
        elif re.search(r"NO\.\s*\S+\s*OF\s*\d{4}", upper):
            result.case_number_line = line
            sections_found.add("case_number")
        elif "...PETITIONER" in upper.replace(" ", ""):
            result.petitioner_name = line.split("\t")[0].strip()
            sections_found.add("cause_title")
        elif "...RESPONDENT" in upper.replace(" ", ""):
            name = line.split("\t")[0].strip()
            result.respondent_names.append(name)
            sections_found.add("cause_title")
        elif upper.startswith("VERSUS"):
            pass
        elif upper.startswith("AFFIDAVIT IN REPLY ON BEHALF OF RESPONDENT NO"):
            result.affidavit_title = line
            m = RESPONDENT_NO_RE.search(line)
            if m:
                result.respondent_number_in_title = int(m.group(1))
            sections_found.add("affidavit_title")
        elif "do hereby solemnly affirm and state as under" in line.lower() or \
             "do hereby swear" in line.lower():
            result.deponent_clause_text = line
            result.deponent_clause_respondent_numbers = [
                int(n) for n in RESPONDENT_NO_RE.findall(line)
            ]
            for phrase, verb in VERB_PATTERNS:
                if phrase in line.lower():
                    result.verification_verb = verb
            sections_found.add("deponent_clause")
        elif BODY_PARA_RE.match(line) and upper != "VERIFICATION" and not line.startswith("("):
            m = BODY_PARA_RE.match(line)
            result.body_paragraphs.append(
                ExtractedParagraph(number=int(m.group(1)), text=m.group(2))
            )
            sections_found.add("numbered_paragraphs")
        elif upper == "PRAYER":
            sections_found.add("prayer")
        elif PRAYER_ITEM_RE.match(line):
            m = PRAYER_ITEM_RE.match(line)
            result.prayer_items.append(m.group(2))
        elif upper.startswith("SOLEMNLY AFFIRMED AT") or upper.startswith("SWORN AT"):
            result.jurat_place = line.split(" at ", 1)[-1].strip() if " at " in line.lower() else line
            m = JURAT_VERB_RE.search(line)
            if m:
                result.jurat_verb = m.group(1)
            sections_found.add("jurat")
        elif upper.startswith("ON THIS"):
            result.jurat_date = line.replace("On this", "").strip()
        elif upper == "VERIFICATION":
            sections_found.add("verification")
        elif "do hereby verify" in line.lower():
            m = VERIFICATION_RANGE_RE.search(line)
            if m:
                result.verification_para_range = m.group(1)
            result.verification_respondent_numbers = [
                int(n) for n in RESPONDENT_NO_RE.findall(line)
            ]
        elif upper.startswith("VERIFIED AT"):
            pass
        elif upper.startswith("ADVOCATES FOR"):
            firm_line = lines[i - 1] if i > 0 else ""
            result.advocate_line = f"{firm_line} {line}".strip()

        exhibit_matches = EXHIBIT_RE.findall(line)
        if exhibit_matches:
            result.exhibit_labels_referenced.extend(exhibit_matches)

    result.sections_present = [s for s in REQUIRED_SECTIONS if s in sections_found]
    result.exhibit_labels_referenced = sorted(set(result.exhibit_labels_referenced))
    return result
