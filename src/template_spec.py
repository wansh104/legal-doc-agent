"""
Template specification for an Affidavit in Reply — Bombay High Court, writ
matter, short reply, transcribed from 01_Affidavit_Format_Explained.pdf.

This module is the single source of truth for:
  - the 10 required parts (used as a completeness checklist)
  - fixed/boilerplate phrases (used as few-shot anchors for generation AND
    as substring checks during evaluation)
  - the deponent-clause rule (person vs organisation)
  - date formatting

Keeping this as plain Python constants (not an LLM-derived spec) is a
deliberate choice: the rules are unambiguous and already given to us in
writing, so re-deriving them via LLM would only add noise and cost.
"""

from __future__ import annotations

REQUIRED_SECTIONS: list[str] = [
    "forum_heading",
    "jurisdiction",
    "case_number",
    "cause_title",
    "affidavit_title",
    "deponent_clause",
    "numbered_paragraphs",
    "prayer",
    "jurat",
    "verification",
]

# Section 4 of the format explainer — fixed phrases, keyed by where they're used.
FIXED_PHRASES: dict[str, list[str]] = {
    "deponent_clause": [
        "above named",
        "do hereby solemnly affirm and state as under:",
    ],
    "para_1_identity": [
        "am well acquainted with the facts and circumstances of the case",
        "I have perused the Petition and the documents annexed thereto",
        "am competent to affirm this Affidavit in Reply",
    ],
    "para_2_blanket_denial": [
        "At the outset, I deny each and every allegation, contention and submission",
        "save and except those specifically admitted herein",
        "misconceived, devoid of merits and is liable to be dismissed in limine",
    ],
    "para_3_preliminary": [
        "has suppressed material facts",
        "strictly in accordance with law and after following due procedure",
        "No legal, constitutional or fundamental right",
        "has been infringed",
    ],
    "substantive_answer": [
        "With reference to the averments made in the Petition",
        "the same are false, incorrect and denied",
        "has failed to make out any case warranting interference",
        "the extraordinary writ jurisdiction of this Hon'ble Court",
    ],
    "closing": [
        "In the premises aforesaid",
        "deserves to be dismissed with costs",
    ],
    "prayer": [
        "I therefore respectfully pray that this Hon'ble Court may be pleased to:",
        "grant such other and further reliefs as this Hon'ble Court may deem fit and proper",
    ],
    "verification": [
        "true and correct to my knowledge and belief",
        "nothing material has been concealed therefrom",
    ],
}

ORDINAL_SUFFIXES = {1: "st", 2: "nd", 3: "rd"}


def prose_case_type(proceeding_type: str) -> str:
    """proceeding_type is stored/rendered ALL CAPS in headings (Part 3), but
    the same term appears in normal title case inside prose paragraphs and
    the prayer (see reference sample: 'the Writ Petition deserves to be
    dismissed', not 'the WRIT PETITION deserves...')."""
    return proceeding_type.title()


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = ORDINAL_SUFFIXES.get(n % 10, "th")
    return f"{n}{suffix}"


def format_attestation_date(date_str: str) -> str:
    """Convert e.g. '5 September 2026' -> '5th day of September 2026'.
    Accepts already-formatted strings idempotently."""
    if "day of" in date_str:
        return date_str
    parts = date_str.strip().split()
    if len(parts) != 3:
        return date_str  # fall back rather than guessing
    day_str, month, year = parts
    try:
        day = int(day_str)
    except ValueError:
        return date_str
    return f"{ordinal(day)} day of {month} {year}"


def respondent_role_phrase(deponent, replying_respondent_number: int) -> str:
    """Shared by the deponent clause and paragraph 1 — 'the Respondent No.N'
    or 'the [designation] of the Respondent No.N'."""
    if deponent.is_org_officer:
        if not deponent.designation:
            raise ValueError("Organisation deponent requires a designation (deponent rule, Part 6)")
        return f"the {deponent.designation} of the Respondent No.{replying_respondent_number}"
    return f"the Respondent No.{replying_respondent_number}"


def deponent_clause_intro(deponent, replying_respondent_number: int) -> str:
    """Section 2 (Deponent rule). deponent: schema.Deponent"""
    role_phrase = respondent_role_phrase(deponent, replying_respondent_number) + " above named"
    age_part = f"Age {deponent.age} years, " if deponent.age else ""
    return (
        f"I, {deponent.name}, {age_part}residing at {deponent.address}, "
        f"{role_phrase}, do hereby solemnly affirm and state as under:"
    )


# ---------------------------------------------------------------------------
# Paragraph templates (Section 3 of the format explainer). Paragraphs 1-3 and
# the substantive-answer opening are ALMOST ENTIRELY fixed boilerplate in the
# reference sample — only small case-specific clauses vary. Encoding that as
# a template (rather than asking an LLM to reproduce boilerplate on every
# call) is what keeps generated paragraphs the same length and register as
# the reference, instead of drifting longer/repetitive across live calls —
# the deponent's identity/authority is established ONCE here, not restated
# per paragraph, which is exactly what a live Gemini call kept getting wrong
# when asked to "not restate it" in free text rather than the structure
# simply not offering the option.
# ---------------------------------------------------------------------------

def identity_paragraph(deponent, replying_respondent_number: int, proceeding_type: str, extra_clause: str = "") -> str:
    role_phrase = respondent_role_phrase(deponent, replying_respondent_number)
    base = (
        f"I say that I am {role_phrase} in the above {prose_case_type(proceeding_type)} and am well "
        f"acquainted with the facts and circumstances of the case. I have perused the "
        f"Petition and the documents annexed thereto and am competent to affirm this "
        f"Affidavit in Reply."
    )
    return f"{base} {extra_clause}".strip() if extra_clause else base


def blanket_denial_paragraph(proceeding_type: str) -> str:
    prose_type = prose_case_type(proceeding_type)
    return (
        f"At the outset, I deny each and every allegation, contention and submission "
        f"made in the {prose_type}, save and except those specifically admitted herein. "
        f"I say that the {prose_type} is misconceived, devoid of merits and is liable to "
        f"be dismissed in limine."
    )


def preliminary_position_paragraph(extra_clause: str = "") -> str:
    lead_in = f"I say that {extra_clause} " if extra_clause else "I say that the Petition is misconceived and devoid of merits. "
    return (
        f"{lead_in}The action complained of has been taken strictly in accordance with "
        f"law and after following due procedure. No legal, constitutional or fundamental "
        f"right of the Petitioner has been infringed."
    )


SUBSTANTIVE_FIXED_OPENING = "With reference to the averments made in the Petition, I say that the same are false, incorrect and denied."


def substantive_answer_paragraph(case_specific_sentence: str) -> str:
    return f"{SUBSTANTIVE_FIXED_OPENING} {case_specific_sentence}".strip()


PRAYER_TEMPLATE = [
    "dismiss the present {proceeding_type} with costs;",
    "refuse any interim or ad-interim relief sought by the Petitioner; and",
    "grant such other and further reliefs as this Hon'ble Court may deem fit and proper in the facts and circumstances of the case.",
]

VERIFICATION_TEMPLATE = (
    "I, {deponent_name}, the Deponent above named, do hereby verify that the contents of "
    "paragraphs 1 to {n} and the Prayer above are true and correct to my knowledge and belief "
    "and that nothing material has been concealed therefrom."
)
