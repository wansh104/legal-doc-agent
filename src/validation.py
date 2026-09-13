"""
Deterministic checks — none of these call an LLM.

Two passes:
  - pre_generation_checks(): run on CaseInput BEFORE we build the docx.
    Catches malformed input early ("nice to have: validation layer that
    catches errors before the final document is produced").
  - post_generation_checks(): run on the ExtractedStructure parsed back out
    of the generated docx, compared against CaseInput. This is the
    "at least three deterministic checks" required by the minimum bar —
    there are six here.
"""

from __future__ import annotations
import re
from src.schema import CaseInput, ExtractedStructure, Issue, Severity, VerificationVerb
from src.template_spec import REQUIRED_SECTIONS

RESPONDENT_NO_RE = re.compile(r"Respondent No\.?\s*(\d+)", re.IGNORECASE)


def pre_generation_checks(case_input: CaseInput) -> list[Issue]:
    issues: list[Issue] = []

    try:
        respondent = case_input.replying_respondent()
    except ValueError as e:
        issues.append(Issue(
            dimension="Consistency", severity=Severity.ERROR, message=str(e),
            source="validation.pre_generation_checks:replying_respondent_lookup",
        ))
        return issues  # nothing else can be safely checked without this

    if respondent.is_organisation and not case_input.deponent.is_org_officer:
        issues.append(Issue(
            dimension="Consistency", severity=Severity.ERROR,
            message=(
                f"Respondent No.{respondent.number} ({respondent.name}) is an organisation, "
                f"but deponent.is_org_officer is False. Deponent rule requires an officer to "
                f"depose on the organisation's behalf (Part 6)."
            ),
            source="validation.pre_generation_checks:deponent_org_rule",
        ))
    if respondent.is_organisation and case_input.deponent.is_org_officer and not case_input.deponent.designation:
        issues.append(Issue(
            dimension="Consistency", severity=Severity.ERROR,
            message="Deponent is marked as an org officer but has no designation set (Part 6 requires one).",
            source="validation.pre_generation_checks:missing_designation",
        ))
    if not respondent.is_organisation and case_input.deponent.is_org_officer:
        issues.append(Issue(
            dimension="Consistency", severity=Severity.WARNING,
            message=f"Respondent No.{respondent.number} is a natural person but deponent.is_org_officer is True.",
            source="validation.pre_generation_checks:person_flagged_as_officer",
        ))

    if not case_input.reply_points:
        issues.append(Issue(
            dimension="Completeness", severity=Severity.ERROR,
            message="No reply points supplied — cannot draft body paragraphs.",
            source="validation.pre_generation_checks:empty_reply_points",
        ))

    referenced_labels = {p.exhibit_label for p in case_input.reply_points if p.exhibit_label}
    known_labels = {e.label for e in case_input.exhibits}
    for label in referenced_labels - known_labels:
        issues.append(Issue(
            dimension="Template Fidelity", severity=Severity.ERROR,
            message=f"Reply point references Exhibit-'{label}' which is not listed in case_input.exhibits.",
            source="validation.pre_generation_checks:unknown_exhibit_label",
        ))

    if not case_input.place_of_attestation or not case_input.attestation_date:
        issues.append(Issue(
            dimension="Completeness", severity=Severity.ERROR,
            message="Missing place or date of attestation — jurat cannot be completed.",
            source="validation.pre_generation_checks:missing_attestation",
        ))

    return issues


def post_generation_checks(case_input: CaseInput, extracted: ExtractedStructure) -> list[Issue]:
    issues: list[Issue] = []
    n = case_input.replying_respondent_number

    # Check 1 — respondent number consistency across every part that names it
    # Note: the verification paragraph never names a respondent number in this
    # format (see reference sample) — only the affidavit title and deponent
    # clause do — so only those two are checked here.
    all_number_sources = {
        "affidavit_title": extracted.respondent_number_in_title,
        "deponent_clause": (extracted.deponent_clause_respondent_numbers or [None])[0]
        if extracted.deponent_clause_respondent_numbers else None,
    }
    for source_name, value in all_number_sources.items():
        if value is not None and value != n:
            issues.append(Issue(
                dimension="Consistency", severity=Severity.ERROR,
                message=f"Respondent number in {source_name} is {value}, expected {n}.",
                source=f"validation.post_generation_checks:respondent_number_consistency:{source_name}",
            ))
        elif value is None:
            issues.append(Issue(
                dimension="Consistency", severity=Severity.WARNING,
                message=f"Could not find a respondent number in {source_name} to verify.",
                source=f"validation.post_generation_checks:respondent_number_consistency:{source_name}",
            ))

    # Check 1b — every body paragraph that names a respondent number names the
    # correct one (this is what catches the assignment's own example issue:
    # "Respondent number is inconsistent in paragraph 5")
    for para in extracted.body_paragraphs:
        mentioned = [int(m) for m in RESPONDENT_NO_RE.findall(para.text)]
        for m in mentioned:
            if m != n:
                issues.append(Issue(
                    dimension="Consistency", severity=Severity.ERROR,
                    message=f"Paragraph {para.number} refers to Respondent No.{m}, expected Respondent No.{n}.",
                    source=f"validation.post_generation_checks:respondent_number_consistency:paragraph_{para.number}",
                ))

    # Check 2 — verification paragraph range matches actual body paragraph count
    actual_count = len(extracted.body_paragraphs)
    expected_range = f"1 to {actual_count}"
    if extracted.verification_para_range != expected_range:
        issues.append(Issue(
            dimension="Consistency", severity=Severity.ERROR,
            message=(
                f"Verification paragraph range is '{extracted.verification_para_range}', "
                f"but the document has {actual_count} body paragraphs (expected '{expected_range}')."
            ),
            source="validation.post_generation_checks:verification_range_match",
        ))

    # Check 3 — verification verb (Part 6) agrees with jurat verb (Part 9)
    expected_jurat_verb = case_input.verification_verb.jurat_form
    if extracted.jurat_verb and extracted.jurat_verb.lower() != expected_jurat_verb.lower():
        issues.append(Issue(
            dimension="Consistency", severity=Severity.ERROR,
            message=(
                f"Jurat verb is '{extracted.jurat_verb}' but deponent clause verb "
                f"'{case_input.verification_verb.value}' requires jurat verb '{expected_jurat_verb}'."
            ),
            source="validation.post_generation_checks:verb_agreement",
        ))
    elif not extracted.jurat_verb:
        issues.append(Issue(
            dimension="Consistency", severity=Severity.WARNING,
            message="Could not detect a jurat verb in the generated document.",
            source="validation.post_generation_checks:verb_agreement",
        ))

    # Check 4 — all required sections present
    missing = [s for s in REQUIRED_SECTIONS if s not in extracted.sections_present]
    for section in missing:
        issues.append(Issue(
            dimension="Structure", severity=Severity.ERROR,
            message=f"Required section '{section}' was not found in the generated document.",
            source="validation.post_generation_checks:required_sections",
        ))

    # Check 5 — exhibit reference mapped correctly
    for exhibit in case_input.exhibits:
        if exhibit.label not in extracted.exhibit_labels_referenced:
            issues.append(Issue(
                dimension="Template Fidelity", severity=Severity.ERROR,
                message=f"Exhibit-'{exhibit.label}' is defined in case input but not referenced anywhere in the generated document.",
                source="validation.post_generation_checks:exhibit_mapping",
            ))

    # Check 6 — deponent clause uses the correct person/organisation form
    try:
        respondent = case_input.replying_respondent()
    except ValueError:
        respondent = None
    if respondent and respondent.is_organisation and extracted.deponent_clause_text:
        text_lower = extracted.deponent_clause_text.lower()
        bad_pattern = f"i am the respondent no.{respondent.number}" in text_lower.replace(" ", "")
        has_role_phrase = "of the respondent no" in text_lower
        if bad_pattern or not has_role_phrase:
            issues.append(Issue(
                dimension="Template Fidelity", severity=Severity.ERROR,
                message=(
                    "Deponent clause does not use the organisation-officer form "
                    "('the [designation] of the Respondent No.N above named') even though "
                    f"Respondent No.{respondent.number} is an organisation."
                ),
                source="validation.post_generation_checks:deponent_clause_form",
            ))

    return issues
