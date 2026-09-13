"""
Structured intermediate schema for the Legal Document Generation Agent.

Design note: this schema is deliberately generic enough to hold ANY party
(person or organisation) and ANY number of respondents, even though the
current scope only needs one Affidavit in Reply. This is what lets us claim
the "reusable template/schema" bonus without actually building a second
document type.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ReplyMove(str, Enum):
    """The five rhetorical moves a paragraph in an Affidavit in Reply can make.
    Order in the document always follows this sequence (Section 3 of the
    format explainer), though SUBSTANTIVE_ANSWER can repeat."""
    IDENTITY_AND_PERUSAL = "IDENTITY_AND_PERUSAL"
    BLANKET_DENIAL = "BLANKET_DENIAL"
    PRELIMINARY_POSITION = "PRELIMINARY_POSITION"
    SUBSTANTIVE_ANSWER = "SUBSTANTIVE_ANSWER"
    CLOSING = "CLOSING"


class VerificationVerb(str, Enum):
    SOLEMNLY_AFFIRM = "solemnly affirm"
    SWEAR_AND_AFFIRM = "swear and affirm"

    @property
    def jurat_form(self) -> str:
        """The Part-9 jurat verb that must agree with this Part-6 verb."""
        return {
            VerificationVerb.SOLEMNLY_AFFIRM: "Solemnly affirmed",
            VerificationVerb.SWEAR_AND_AFFIRM: "Sworn",
        }[self]


# ---------------------------------------------------------------------------
# Parties
# ---------------------------------------------------------------------------
class ClauseBatch(BaseModel):
    """One Gemini call drafts every paragraph's case-specific clause at once,
    keyed by ReplyPoint.heading — instead of one call per paragraph."""
    clauses: dict[str, str]

class Party(BaseModel):
    """A named party in the cause title (petitioner or a respondent)."""
    name: str
    description: str = Field(
        default="", description="e.g. 'Through the Principal Secretary, Mumbai.' or age/occupation/address"
    )
    is_organisation: bool = False


class Respondent(Party):
    number: int = Field(..., description="Respondent No. N")


class Deponent(BaseModel):
    """The person actually swearing the affidavit. May or may not be the
    replying respondent themself — see is_org_officer."""
    name: str
    age: Optional[int] = None
    designation: Optional[str] = Field(
        None, description="Required when is_org_officer=True, e.g. 'Deputy Metropolitan Commissioner'"
    )
    address: str
    is_org_officer: bool = Field(
        False, description="True when the replying respondent is an organisation and this person deposes on its behalf"
    )

    @field_validator("designation")
    @classmethod
    def _designation_required_for_officers(cls, v, info):
        # Soft check only — hard enforcement happens in validation.py so the
        # error is caught with full context (which check, which source).
        return v


class Advocate(BaseModel):
    firm_name: str
    acting_for_respondent_number: int


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

class ReplyPoint(BaseModel):
    """One bullet-cluster from the case info's 'Reply Points' section, before
    it has been turned into affidavit prose."""
    order: int
    heading: str = Field(..., description="e.g. 'Point 2 — General Denial' (for traceability only)")
    move: ReplyMove
    bullets: list[str]
    exhibit_label: Optional[str] = Field(None, description="e.g. 'A' if this point references an exhibit")


class Exhibit(BaseModel):
    label: str  # "A", "B", ...
    description: str


class GeneratedParagraph(BaseModel):
    """One numbered body paragraph in the final document."""
    number: int
    move: ReplyMove
    text: str
    source_point_order: Optional[int] = Field(
        None, description="Evidence mapping: which ReplyPoint.order this paragraph was generated from"
    )
    exhibit_label: Optional[str] = None


# ---------------------------------------------------------------------------
# Top-level case input (Stage 2 output — the "structured intermediate JSON")
# ---------------------------------------------------------------------------

class CaseInput(BaseModel):
    # Court / case identity
    forum_city: str
    jurisdiction_type: str = Field(..., description="e.g. 'ORDINARY ORIGINAL CIVIL' (without the word JURISDICTION)")
    proceeding_type: str = Field(..., description="e.g. 'WRIT PETITION'")
    case_number: str
    case_year: str

    # Cause title
    petitioner: Party
    respondents: list[Respondent]
    replying_respondent_number: int

    # Deponent
    deponent: Deponent

    # Content
    reply_points: list[ReplyPoint]
    exhibits: list[Exhibit] = Field(default_factory=list)
    prayer_extra_items: list[str] = Field(
        default_factory=list, description="Any case-specific prayer clauses beyond the fixed (a)/(b)/(c) skeleton"
    )

    # Attestation
    place_of_attestation: str
    attestation_date: str  # kept as given string (e.g. "5 September 2026"); formatted at render time
    verification_verb: VerificationVerb

    # Drafting block
    advocate: Optional[Advocate] = None

    # Evidence mapping: field_name -> where it was found in the source doc
    provenance: dict[str, str] = Field(default_factory=dict)

    def replying_respondent(self) -> Respondent:
        for r in self.respondents:
            if r.number == self.replying_respondent_number:
                return r
        raise ValueError(f"No respondent numbered {self.replying_respondent_number} in respondents list")


# ---------------------------------------------------------------------------
# Extracted structure of a rendered document (Stage 1 & 5 output)
# ---------------------------------------------------------------------------

class ExtractedParagraph(BaseModel):
    number: Optional[int]
    text: str


class ExtractedStructure(BaseModel):
    """What we get back out of a .docx (reference OR generated) by parsing it.
    Used both to build the template spec (from the reference) and to check
    the generated document against ground truth (Stage 5/6)."""
    sections_present: list[str] = Field(default_factory=list)

    forum_line: Optional[str] = None
    jurisdiction_line: Optional[str] = None
    case_number_line: Optional[str] = None

    petitioner_name: Optional[str] = None
    respondent_names: list[str] = Field(default_factory=list)
    affidavit_title: Optional[str] = None
    respondent_number_in_title: Optional[int] = None

    deponent_clause_text: Optional[str] = None
    deponent_clause_respondent_numbers: list[int] = Field(default_factory=list)

    body_paragraphs: list[ExtractedParagraph] = Field(default_factory=list)

    prayer_items: list[str] = Field(default_factory=list)

    jurat_place: Optional[str] = None
    jurat_date: Optional[str] = None
    jurat_verb: Optional[str] = None

    verification_para_range: Optional[str] = None  # e.g. "1 to 5"
    verification_verb: Optional[str] = None
    verification_respondent_numbers: list[int] = Field(default_factory=list)

    exhibit_labels_referenced: list[str] = Field(default_factory=list)

    advocate_line: Optional[str] = None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class Issue(BaseModel):
    dimension: str
    severity: Severity
    message: str
    source: str = Field(..., description="Where this was detected, e.g. 'validation.check_respondent_number_consistency' or 'ground_truth: case_info.deponent.name'")


class DimensionScore(BaseModel):
    name: str
    score: float  # 0-100
    weight: float  # fraction of overall, sums to 1.0 across dimensions
    checks_passed: int
    checks_total: int
    detail: str = ""


class EvaluationReport(BaseModel):
    overall_score: float
    dimensions: list[DimensionScore]
    issues: list[Issue]
    scoring_explanation: str
