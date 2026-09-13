"""
Stage 2 — Entity Extraction.

Turns the free-text case information document into a validated CaseInput
(schema.py). Primary path is an LLM call (robust to phrasing variance in
future case-info documents); a hand-built mock is supplied as the offline
fallback for the one case info document shipped with this assignment, so
the app still runs end-to-end in a demo/no-API-key environment.
"""

from __future__ import annotations
from src.schema import CaseInput
from src.llm_client import generate_structured

EXTRACTION_PROMPT = """You are extracting structured data from a legal case-information \
brief so it can be used to auto-generate an Affidavit in Reply.

Read the case information document below and extract every field required by the JSON \
schema you will be given. Rules:
- Do not invent any fact that is not stated in the document. If a field is genuinely \
absent, use an empty string / empty list / null as the schema allows.
- "reply_points" must preserve the ORDER given in the document and must classify each \
point into exactly one of these moves: IDENTITY_AND_PERUSAL, BLANKET_DENIAL, \
PRELIMINARY_POSITION, SUBSTANTIVE_ANSWER. Do not add a CLOSING point yourself — that is \
added automatically later.
- Set deponent.is_org_officer = true if the deponent is signing on behalf of an \
organisation/authority respondent (i.e. the deponent's name differs from the replying \
respondent's name). Set it false if the deponent IS the replying respondent (a natural \
person replying for themself).
- "provenance" should map key field names (e.g. "deponent.name", "reply_points", \
"verification_verb") to a short human-readable pointer to where you found them in the \
document (section heading or label), for traceability.
- "prayer_extra_items" must be an EMPTY LIST unless the case information asks for a form of \
relief that is NOT already covered by: dismissing the petition with costs, refusing interim \
relief, or a general catch-all "such other reliefs" clause. A sentence that just restates \
"dismiss the petition with costs" (even in different words, even attributed to the \
respondent by name) is NOT an extra item — it is already covered by the fixed prayer \
skeleton, so leave it out entirely. Only include something here if it asks for a genuinely \
different, specific form of relief (e.g. "direct the Petitioner to pay damages of Rs. X").

CASE INFORMATION DOCUMENT:
---
{case_info_text}
---
"""

# Hand-built ground truth for the Sunrise Housing / MMRDA case shipped with this
# assignment (03_Case_Information.pdf). Used as the offline mock and doubles as
# the demo-mode cached output referenced in the README.
MOCK_CASE_INPUT: dict = {
    "forum_city": "BOMBAY",
    "jurisdiction_type": "ORDINARY ORIGINAL CIVIL",
    "proceeding_type": "WRIT PETITION",
    "case_number": "1847",
    "case_year": "2026",
    "petitioner": {
        "name": "Sunrise Housing Private Limited",
        "description": "",
        "is_organisation": True,
    },
    "respondents": [
        {"name": "State of Maharashtra", "description": "", "is_organisation": True, "number": 1},
        {
            "name": "Mumbai Metropolitan Region Development Authority",
            "description": "",
            "is_organisation": True,
            "number": 2,
        },
    ],
    "replying_respondent_number": 2,
    "deponent": {
        "name": "Arvind Rajan",
        "age": None,
        "designation": "Deputy Metropolitan Commissioner",
        "address": "Bandra East, Mumbai, Maharashtra",
        "is_org_officer": True,
    },
    "reply_points": [
        {
            "order": 1,
            "heading": "Point 1 — Filing of Affidavit in Reply",
            "move": "IDENTITY_AND_PERUSAL",
            "bullets": [
                "The deponent has perused a copy of the Writ Petition filed by Sunrise Housing Private Limited.",
                "The deponent is filing this Affidavit in Reply on behalf of Respondent No. 2, Mumbai Metropolitan Region Development Authority, to oppose the contentions raised in the Writ Petition and the reliefs sought by the Petitioner.",
            ],
            "exhibit_label": None,
        },
        {
            "order": 2,
            "heading": "Point 2 — General Denial",
            "move": "BLANKET_DENIAL",
            "bullets": [
                "Respondent No. 2 denies all statements, contentions and averments made in the Writ Petition except those specifically admitted in this Affidavit in Reply.",
                "Nothing contained in the Writ Petition that has not been specifically dealt with or admitted is to be treated as an admission by Respondent No. 2.",
            ],
            "exhibit_label": None,
        },
        {
            "order": 3,
            "heading": "Point 3 — Preliminary Position",
            "move": "PRELIMINARY_POSITION",
            "bullets": [
                "The Writ Petition is misconceived and devoid of merits.",
                "The actions challenged by the Petitioner were taken in accordance with the applicable redevelopment procedure and within the authority available to Respondent No. 2.",
            ],
            "exhibit_label": None,
        },
        {
            "order": 4,
            "heading": "Point 4 — Denial Regarding the Communication",
            "move": "SUBSTANTIVE_ANSWER",
            "bullets": [
                "Respondent No. 2 denies that the impugned communication dated 15 July 2026 was issued without authority.",
            ],
            "exhibit_label": None,
        },
        {
            "order": 5,
            "heading": "Point 5 — Authority for the Communication",
            "move": "SUBSTANTIVE_ANSWER",
            "bullets": [
                "The communication dated 15 July 2026 was issued pursuant to the applicable redevelopment procedure and after consideration of the relevant records.",
            ],
            "exhibit_label": None,
        },
        {
            "order": 6,
            "heading": "Point 6 — Document Relied Upon",
            "move": "SUBSTANTIVE_ANSWER",
            "bullets": [
                "Respondent No. 2 relies upon the communication dated 15 July 2026.",
                "A copy of that communication is to be annexed and marked as EXHIBIT-'A'.",
            ],
            "exhibit_label": "A",
        },
    ],
    "exhibits": [{"label": "A", "description": "Communication dated 15 July 2026"}],
    "prayer_extra_items": [],
    "place_of_attestation": "Mumbai",
    "attestation_date": "5 September 2026",
    "verification_verb": "solemnly affirm",
    "advocate": {"firm_name": "Rajan & Associates", "acting_for_respondent_number": 2},
    "provenance": {
        "forum_city/jurisdiction_type/proceeding_type/case_number/case_year": "Case Information §1 Court and Case Details",
        "petitioner": "Case Information §1 Court and Case Details — Petitioner",
        "respondents": "Case Information §1 Court and Case Details — Respondent No. 1 / No. 2",
        "deponent.name": "Case Information §2 Deponent Details — Name",
        "deponent.designation": "Case Information §2 Deponent Details — Designation",
        "deponent.address": "Case Information §2 Deponent Details — Address",
        "reply_points": "Case Information §3 Reply Points to be Incorporated",
        "exhibits": "Case Information §3 Point 6 — Document Relied Upon",
        "verification_verb": "Case Information §2 Deponent Details — Verification verb",
        "place_of_attestation": "Case Information §5 Attestation Details — Place",
        "attestation_date": "Case Information §5 Attestation Details — Date",
        "advocate": "Case Information §6 Advocate",
    },
}


def extract_case_input(case_info_text: str) -> CaseInput:
    prompt = EXTRACTION_PROMPT.format(case_info_text=case_info_text)
    return generate_structured(prompt, CaseInput, mock_response=MOCK_CASE_INPUT)
