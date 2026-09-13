"""
Stage 4 — Document Generation.

Two responsibilities, deliberately separated:
  1. draft_paragraphs(): turn each ReplyPoint's bullets into a properly
     worded affidavit paragraph. LLM-driven in live mode (few-shot on the
     fixed phrases from template_spec so the register matches the sample);
     hand-authored per-point mock in offline/demo mode.
  2. build_docx(): deterministic docx assembly. This does NOT touch the LLM
     at all — headings, cause title, deponent clause, prayer skeleton,
     jurat and verification are pure string templating + python-docx
     formatting, because those must be exactly right and an LLM is the
     wrong tool for "always bold this, always center that".
"""

from __future__ import annotations
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT

from src.schema import CaseInput, ReplyPoint, ReplyMove, GeneratedParagraph, ClauseBatch
from src.llm_client import generate_structured
from src import template_spec as spec

# ---------------------------------------------------------------------------
# Hand-authored mock CLAUSES (not full paragraphs) for the shipped Sunrise
# Housing / MMRDA case. Keyed by ReplyPoint.heading. Each is just the short
# case-specific addition that gets appended to a deterministic template
# sentence from template_spec.py — not a full paragraph — since paragraphs
# 1-3 and every substantive answer's opening are fixed boilerplate.
# In live mode these are never used — draft_all_clauses() calls Gemini once
# instead, batching every paragraph's clause into a single call (see
# ClauseBatch in schema.py for why: free-tier Gemini rate limits).
# ---------------------------------------------------------------------------
MOCK_CLAUSES: dict[str, str] = {
    "Point 1 — Filing of Affidavit in Reply": (
        "I am filing the present Affidavit in Reply to oppose the contentions raised in "
        "the said Writ Petition and the reliefs sought by the Petitioner."
    ),
    "Point 2 — General Denial": (
        "Nothing contained in the Writ Petition that has not been specifically dealt with "
        "or admitted herein shall be treated as an admission by the Respondent No.2."
    ),
    "Point 3 — Preliminary Position": (
        "the actions challenged by the Petitioner were taken pursuant to the applicable "
        "redevelopment procedure and within the authority available to the Respondent No.2."
    ),
    "Point 4 — Denial Regarding the Communication": (
        "I deny that the communication dated 15th July 2026 was issued without authority."
    ),
    "Point 5 — Authority for the Communication": (
        "The communication dated 15th July 2026 was issued pursuant to the applicable "
        "redevelopment procedure and after due consideration of the relevant records."
    ),
    "Point 6 — Document Relied Upon": (
        "The Respondent No.2 relies upon the communication dated 15th July 2026. Hereto "
        "annexed and marked as EXHIBIT-'A' is a copy of the said communication."
    ),
}

FIXED_PHRASE_KEY_BY_MOVE = {
    ReplyMove.IDENTITY_AND_PERUSAL: "para_1_identity",
    ReplyMove.BLANKET_DENIAL: "para_2_blanket_denial",
    ReplyMove.PRELIMINARY_POSITION: "para_3_preliminary",
    ReplyMove.SUBSTANTIVE_ANSWER: "substantive_answer",
}


def _clause_instruction(point: ReplyPoint) -> str:
    if point.move == ReplyMove.IDENTITY_AND_PERUSAL:
        return (
            "Draft (or return empty string if nothing to add) ONE sentence stating why the "
            "deponent is filing this reply / what it opposes, beyond simply having perused "
            "the petition and being competent to affirm (that's already covered elsewhere)."
        )
    if point.move == ReplyMove.BLANKET_DENIAL:
        return (
            "Draft (or return empty string) ONE sentence for any case-specific denial "
            "detail beyond the standard blanket denial (already covered elsewhere: denying "
            "all allegations, petition being misconceived and liable to dismissal in limine)."
        )
    if point.move == ReplyMove.PRELIMINARY_POSITION:
        return (
            "Draft ONE clause of the form '<subject> is/was/were <lawful basis>' describing "
            "specifically why/how the challenged action was lawful, to fit into the sentence: "
            "'I say that [YOUR CLAUSE]. The action complained of has been taken strictly in "
            "accordance with law...' Do not include 'I say that' yourself."
        )
    if point.move == ReplyMove.SUBSTANTIVE_ANSWER:
        return (
            "Draft 1-2 sentences with the specific case fact being answered here (the fixed "
            "opening 'With reference to the averments made in the Petition, I say that the "
            "same are false, incorrect and denied.' is ALREADY WRITTEN before your text — do "
            "not repeat any part of it)."
        )
    raise ValueError(f"No clause instruction for move: {point.move}")


def _batch_clause_prompt(plan: list[ReplyPoint]) -> str:
    sections = []
    for point in plan:
        if point.move == ReplyMove.CLOSING:
            continue  # fully deterministic, never drafted
        sections.append(
            f"### Point: {point.heading}\n"
            f"Instruction: {_clause_instruction(point)}\n"
            f"Facts available (do not add facts beyond these):\n- " + "\n- ".join(point.bullets)
        )
    return (
        "You are drafting SHORT case-specific additions (at most 2 sentences each) to an "
        "Indian court Affidavit in Reply, one per point below. For every point, the "
        "surrounding boilerplate sentence is ALREADY WRITTEN elsewhere — do not repeat it, "
        "do not restate the deponent's name, designation, or 'on behalf of Respondent No.N' "
        "(that is established once, elsewhere in the document, not per paragraph).\n\n"
        "Formal legal register, first person. If a point's facts add nothing beyond what a "
        "generic boilerplate sentence would already say, its value should be an empty string.\n\n"
        + "\n\n".join(sections)
    )


def draft_all_clauses(plan: list[ReplyPoint]) -> dict[str, str]:
    """Single Gemini call for every paragraph's case-specific clause — see
    ClauseBatch docstring in schema.py for why this is batched rather than
    one call per paragraph (free-tier rate limits)."""
    prompt = _batch_clause_prompt(plan)
    batch = generate_structured(prompt, ClauseBatch, mock_response={"clauses": MOCK_CLAUSES})
    return batch.clauses


def draft_paragraph(point: ReplyPoint, case_input: CaseInput, clauses: dict[str, str]) -> str:
    clause = clauses.get(point.heading, "").strip()

    if point.move == ReplyMove.IDENTITY_AND_PERUSAL:
        return spec.identity_paragraph(
            case_input.deponent, case_input.replying_respondent_number,
            case_input.proceeding_type, extra_clause=clause,
        )
    if point.move == ReplyMove.BLANKET_DENIAL:
        base = spec.blanket_denial_paragraph(case_input.proceeding_type)
        return f"{base} {clause}".strip() if clause else base
    if point.move == ReplyMove.PRELIMINARY_POSITION:
        return spec.preliminary_position_paragraph(extra_clause=clause)
    if point.move == ReplyMove.SUBSTANTIVE_ANSWER:
        return spec.substantive_answer_paragraph(clause)
    if point.move == ReplyMove.CLOSING:
        # Fully deterministic — no LLM involved, no risk of drift on the one
        # sentence that every affidavit ends with identically.
        return (
            f"In the premises aforesaid, I say that the {spec.prose_case_type(case_input.proceeding_type)} "
            f"deserves to be dismissed with costs."
        )
    raise ValueError(f"Unhandled move: {point.move}")


def draft_all_paragraphs(plan: list[ReplyPoint], case_input: CaseInput) -> list[GeneratedParagraph]:
    clauses = draft_all_clauses(plan)
    paragraphs = []
    for point in plan:
        text = draft_paragraph(point, case_input, clauses)
        paragraphs.append(
            GeneratedParagraph(
                number=point.order,
                move=point.move,
                text=text,
                source_point_order=point.order if point.move != ReplyMove.CLOSING else None,
                exhibit_label=point.exhibit_label,
            )
        )
    return paragraphs


# ---------------------------------------------------------------------------
# Deterministic docx assembly
# ---------------------------------------------------------------------------

def _is_duplicate_of_fixed_prayer(item: str) -> bool:
    """Defensive filter: even with an explicit extraction-prompt instruction,
    an LLM extraction call can still surface a restatement of the standard
    dismiss-with-costs prayer as if it were a distinct item. Catch that here
    rather than trust the prompt alone."""
    lowered = item.lower()
    return "dismiss" in lowered and "cost" in lowered


def _prayer_items(case_input: CaseInput) -> list[str]:
    prose_type = spec.prose_case_type(case_input.proceeding_type)
    template_items = [item.format(proceeding_type=prose_type) for item in spec.PRAYER_TEMPLATE]
    extra_items = [
        item for item in case_input.prayer_extra_items
        if not _is_duplicate_of_fixed_prayer(item)
    ]
    return template_items[:-1] + extra_items + template_items[-1:]


def _heading(doc, text: str, size=12):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(size)
    return p


def _party_line(doc, name: str, description: str, tag: str):
    p = doc.add_paragraph()
    p.paragraph_format.tab_stops.add_tab_stop(Inches(6.0), WD_TAB_ALIGNMENT.RIGHT)
    text = name
    if description:
        text += f", {description}"
    run = p.add_run(f"{text}\t{tag}")
    run.font.size = Pt(11)
    return p


def build_docx(case_input: CaseInput, paragraphs: list[GeneratedParagraph], out_path: str) -> str:
    respondent = case_input.replying_respondent()
    doc = Document()
    style = doc.styles["Normal"]
    style.font.size = Pt(11)
    style.font.name = "Times New Roman"

    # Part 1-3: forum, jurisdiction, case number
    _heading(doc, f"IN THE HIGH COURT OF JUDICATURE AT {case_input.forum_city}")
    _heading(doc, f"{case_input.jurisdiction_type} JURISDICTION")
    _heading(doc, f"{case_input.proceeding_type} NO. {case_input.case_number} OF {case_input.case_year}")
    doc.add_paragraph()

    # Part 4: cause title
    _party_line(doc, case_input.petitioner.name, case_input.petitioner.description, "...Petitioner")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("VERSUS").bold = True
    for r in case_input.respondents:
        _party_line(doc, f"{r.number}. {r.name}", r.description, f"...Respondent No.{r.number}")
    doc.add_paragraph()

    # Part 5: affidavit title
    _heading(doc, f"AFFIDAVIT IN REPLY ON BEHALF OF RESPONDENT NO. {case_input.replying_respondent_number}")
    doc.add_paragraph()

    # Part 6: deponent clause
    clause = spec.deponent_clause_intro(case_input.deponent, case_input.replying_respondent_number)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.add_run(clause)
    doc.add_paragraph()

    # Part 7: numbered paragraphs
    for para in paragraphs:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        num_run = p.add_run(f"{para.number}. ")
        num_run.bold = True
        p.add_run(para.text)
    doc.add_paragraph()

    # Part 8: prayer
    _heading(doc, "PRAYER")
    p = doc.add_paragraph()
    p.add_run(f"I therefore respectfully pray that this Hon'ble Court may be pleased to:")
    letters = "abcdefgh"
    prayer_items = _prayer_items(case_input)
    for i, item in enumerate(prayer_items):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        letter_run = p.add_run(f"({letters[i]}) ")
        letter_run.bold = True
        p.add_run(item)
    doc.add_paragraph()

    # Part 9: jurat
    date_formatted = spec.format_attestation_date(case_input.attestation_date)
    p = doc.add_paragraph()
    p.add_run(f"Solemnly affirmed at {case_input.place_of_attestation}")
    p = doc.add_paragraph()
    p.add_run(f"On this {date_formatted}")
    p = doc.add_paragraph()
    p.paragraph_format.tab_stops.add_tab_stop(Inches(6.0), WD_TAB_ALIGNMENT.RIGHT)
    p.add_run("Before Me\t")
    dep_run = p.add_run("DEPONENT")
    dep_run.bold = True
    doc.add_paragraph()

    # Part 10: verification
    _heading(doc, "VERIFICATION")
    verification_text = spec.VERIFICATION_TEMPLATE.format(
        deponent_name=case_input.deponent.name, n=len(paragraphs)
    )
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.add_run(f"I, {case_input.deponent.name}, the Deponent above named, do hereby verify that the "
               f"contents of paragraphs 1 to {len(paragraphs)} and the Prayer above are true and "
               f"correct to my knowledge and belief and that nothing material has been concealed "
               f"therefrom.")
    p = doc.add_paragraph()
    p.add_run(f"Verified at {case_input.place_of_attestation} on this {date_formatted}.")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.add_run("DEPONENT").bold = True
    doc.add_paragraph()

    # Advocate / drafting block
    if case_input.advocate:
        p = doc.add_paragraph()
        p.add_run(case_input.advocate.firm_name.upper()).bold = True
        p = doc.add_paragraph()
        p.add_run(f"Advocates for the Respondent No.{case_input.advocate.acting_for_respondent_number}.")

    doc.save(out_path)
    return out_path