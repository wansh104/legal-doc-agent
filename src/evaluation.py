"""
Stage 6 — Ground Truth Comparison, Scoring, and Report.

Combines:
  - pre_generation_checks + post_generation_checks (validation.py)
  - entity-accuracy comparison (extracted structure vs. CaseInput ground truth)
  - template-fidelity phrase check (does each paragraph's move show at least
    one of the reference's fixed phrases)
  - a deterministic hallucination proxy (years / respondent numbers / exhibit
    labels appearing in generated text must trace back to the case input)

into six weighted dimensions, each scored as checks_passed / checks_total.
"""

from __future__ import annotations
import re
from src.schema import (
    CaseInput, ExtractedStructure, GeneratedParagraph, Issue, Severity,
    EvaluationReport, DimensionScore,
)
from src import template_spec as spec
from src.generation import FIXED_PHRASE_KEY_BY_MOVE
from src.validation import pre_generation_checks, post_generation_checks

DIMENSION_WEIGHTS = {
    "Entity Accuracy": 0.20,
    "Completeness": 0.20,
    "Structure": 0.20,
    "Consistency": 0.15,
    "Template Fidelity": 0.15,
    "Hallucination Check": 0.10,
}

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
RESP_NO_RE = re.compile(r"Respondent No\.?\s*(\d+)", re.IGNORECASE)
EXHIBIT_RE = re.compile(r"EXHIBIT[-\s]*[\u2018\u2019']?([A-Z])", re.IGNORECASE)


def _entity_accuracy_issues(case_input: CaseInput, extracted: ExtractedStructure) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    checks = []  # (label, passed: bool)

    checks.append(("forum_city", case_input.forum_city.lower() in (extracted.forum_line or "").lower()))
    checks.append(("jurisdiction_type", case_input.jurisdiction_type.lower() in (extracted.jurisdiction_line or "").lower()))
    checks.append(("case_number", case_input.case_number in (extracted.case_number_line or "")))
    checks.append(("petitioner_name", case_input.petitioner.name.lower() in (extracted.petitioner_name or "").lower()))

    expected_resp_names = {r.name.lower() for r in case_input.respondents}
    found_resp_names = " | ".join(extracted.respondent_names).lower()
    for r in case_input.respondents:
        checks.append((f"respondent_{r.number}_name", r.name.lower() in found_resp_names))

    checks.append(("deponent_name", case_input.deponent.name.lower() in (extracted.deponent_clause_text or "").lower()))
    checks.append(("place_of_attestation", case_input.place_of_attestation.lower() in (extracted.jurat_place or "").lower()))
    if case_input.advocate:
        checks.append(("advocate_firm", case_input.advocate.firm_name.lower() in (extracted.advocate_line or "").lower()))

    for label, passed in checks:
        if not passed:
            issues.append(Issue(
                dimension="Entity Accuracy", severity=Severity.ERROR,
                message=f"Expected entity '{label}' not found (or mismatched) in generated document.",
                source=f"evaluation.entity_accuracy:{label} (ground truth: case_input)",
            ))
    return issues, sum(1 for _, p in checks if p), len(checks)


def _completeness_issues(case_input: CaseInput, plan_len: int, extracted: ExtractedStructure) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    checks_total = 2
    checks_passed = 0

    if len(extracted.body_paragraphs) == plan_len:
        checks_passed += 1
    else:
        issues.append(Issue(
            dimension="Completeness", severity=Severity.ERROR,
            message=f"Expected {plan_len} body paragraphs, found {len(extracted.body_paragraphs)}.",
            source="evaluation.completeness:paragraph_count",
        ))

    if extracted.prayer_items:
        checks_passed += 1
    else:
        issues.append(Issue(
            dimension="Completeness", severity=Severity.ERROR,
            message="No prayer items found in generated document.",
            source="evaluation.completeness:prayer_items",
        ))

    return issues, checks_passed, checks_total


def _template_fidelity_phrase_issues(paragraphs: list[GeneratedParagraph]) -> tuple[list[Issue], int, int]:
    issues: list[Issue] = []
    checked = 0
    passed = 0
    for para in paragraphs:
        key = FIXED_PHRASE_KEY_BY_MOVE.get(para.move)
        if not key:
            continue  # CLOSING is deterministic template text, not worth re-checking
        checked += 1
        fixed_phrases = spec.FIXED_PHRASES.get(key, [])
        if any(phrase.lower() in para.text.lower() for phrase in fixed_phrases):
            passed += 1
        else:
            issues.append(Issue(
                dimension="Template Fidelity", severity=Severity.WARNING,
                message=f"Paragraph {para.number} ({para.move.value}) does not reuse any fixed phrase from the reference format.",
                source=f"evaluation.template_fidelity:paragraph_{para.number}",
            ))
    return issues, passed, checked


def _hallucination_proxy_issues(case_input: CaseInput, paragraphs: list[GeneratedParagraph]) -> tuple[list[Issue], int, int]:
    """Deterministic proxy, not a semantic hallucination check: flags any
    year, Respondent No., or Exhibit label mentioned in generated prose that
    doesn't trace back to the case input. A true semantic check (e.g. an LLM
    judge comparing each sentence to the source bullets) is noted as a
    limitation in the README."""
    issues: list[Issue] = []
    known_years = {case_input.case_year}
    for point in case_input.reply_points:
        for bullet in point.bullets:
            known_years.update(m for m in YEAR_RE.findall(bullet))
    known_years = {y if len(y) == 4 else y for y in known_years}
    known_resp_numbers = {str(r.number) for r in case_input.respondents}
    known_exhibit_labels = {e.label for e in case_input.exhibits}

    checked = 0
    passed = 0
    for para in paragraphs:
        checked += 1
        ok = True
        for y in YEAR_RE.findall(para.text):
            full_year = re.search(r"\b\d{4}\b", para.text)
        years_in_text = re.findall(r"\b\d{4}\b", para.text)
        for y in years_in_text:
            if y not in known_years and y != case_input.case_year:
                ok = False
                issues.append(Issue(
                    dimension="Hallucination Check", severity=Severity.ERROR,
                    message=f"Paragraph {para.number} mentions year {y}, which does not appear in the source case information.",
                    source=f"evaluation.hallucination_proxy:paragraph_{para.number}",
                ))
        for n in RESP_NO_RE.findall(para.text):
            if n not in known_resp_numbers:
                ok = False
                issues.append(Issue(
                    dimension="Hallucination Check", severity=Severity.ERROR,
                    message=f"Paragraph {para.number} references Respondent No.{n}, not present in case input's respondent list.",
                    source=f"evaluation.hallucination_proxy:paragraph_{para.number}",
                ))
        for label in EXHIBIT_RE.findall(para.text):
            if label.upper() not in known_exhibit_labels:
                ok = False
                issues.append(Issue(
                    dimension="Hallucination Check", severity=Severity.ERROR,
                    message=f"Paragraph {para.number} references Exhibit-'{label}', not defined in case input's exhibit list.",
                    source=f"evaluation.hallucination_proxy:paragraph_{para.number}",
                ))
        if ok:
            passed += 1
    return issues, passed, checked


def evaluate(
    case_input: CaseInput,
    paragraphs: list[GeneratedParagraph],
    extracted: ExtractedStructure,
    pre_issues: list[Issue] | None = None,
) -> EvaluationReport:
    all_issues: list[Issue] = list(pre_issues or [])

    post_issues = post_generation_checks(case_input, extracted)
    all_issues += post_issues

    entity_issues, ea_passed, ea_total = _entity_accuracy_issues(case_input, extracted)
    all_issues += entity_issues

    completeness_issues, comp_passed, comp_total = _completeness_issues(case_input, len(paragraphs), extracted)
    all_issues += completeness_issues

    fidelity_issues, fid_passed, fid_total = _template_fidelity_phrase_issues(paragraphs)
    all_issues += fidelity_issues

    hallucination_issues, hal_passed, hal_total = _hallucination_proxy_issues(case_input, paragraphs)
    all_issues += hallucination_issues

    # Structure & Consistency checks come from post_generation_checks (validation.py),
    # bucketed by the `dimension` field already set on each Issue.
    def _bucket(dim: str, base_total_hint: int) -> tuple[int, int]:
        dim_issues = [i for i in all_issues if i.dimension == dim and i.severity == Severity.ERROR]
        # total = hint (number of checks we know we ran) if hint > 0 else len(dim_issues) or 1
        total = base_total_hint if base_total_hint > 0 else max(len(dim_issues), 1)
        passed = max(total - len(dim_issues), 0)
        return passed, total

    structure_total = len(spec.REQUIRED_SECTIONS)
    structure_passed, structure_total = _bucket("Structure", structure_total)

    # Consistency checks run every time, regardless of outcome: respondent number
    # in the affidavit title, in the deponent clause, in each body paragraph that
    # mentions one, verification paragraph range, and jurat/verification verb agreement.
    consistency_total = 4 + len(extracted.body_paragraphs)
    consistency_passed, consistency_total = _bucket("Consistency", consistency_total)

    template_fidelity_total = fid_total + sum(
        1 for i in (post_issues) if i.dimension == "Template Fidelity"
    ) + len(case_input.exhibits)
    template_fidelity_passed = template_fidelity_total - sum(
        1 for i in all_issues if i.dimension == "Template Fidelity" and i.severity == Severity.ERROR
    )
    template_fidelity_passed = max(template_fidelity_passed, 0)

    dims = [
        DimensionScore(
            name="Entity Accuracy", weight=DIMENSION_WEIGHTS["Entity Accuracy"],
            checks_passed=ea_passed, checks_total=ea_total,
            score=round(100 * ea_passed / ea_total, 1) if ea_total else 100.0,
            detail="Extracted document fields compared against CaseInput ground truth.",
        ),
        DimensionScore(
            name="Completeness", weight=DIMENSION_WEIGHTS["Completeness"],
            checks_passed=comp_passed, checks_total=comp_total,
            score=round(100 * comp_passed / comp_total, 1) if comp_total else 100.0,
            detail="Body paragraph count and prayer presence checked against the plan.",
        ),
        DimensionScore(
            name="Structure", weight=DIMENSION_WEIGHTS["Structure"],
            checks_passed=structure_passed, checks_total=structure_total,
            score=round(100 * structure_passed / structure_total, 1) if structure_total else 100.0,
            detail="All 10 required sections from the format spec checked for presence.",
        ),
        DimensionScore(
            name="Consistency", weight=DIMENSION_WEIGHTS["Consistency"],
            checks_passed=consistency_passed, checks_total=consistency_total,
            score=round(100 * consistency_passed / consistency_total, 1) if consistency_total else 100.0,
            detail="Respondent number, verification range, and verb-agreement checks.",
        ),
        DimensionScore(
            name="Template Fidelity", weight=DIMENSION_WEIGHTS["Template Fidelity"],
            checks_passed=template_fidelity_passed, checks_total=template_fidelity_total,
            score=round(100 * template_fidelity_passed / template_fidelity_total, 1) if template_fidelity_total else 100.0,
            detail="Fixed-phrase reuse, exhibit mapping, and deponent-clause form.",
        ),
        DimensionScore(
            name="Hallucination Check", weight=DIMENSION_WEIGHTS["Hallucination Check"],
            checks_passed=hal_passed, checks_total=hal_total,
            score=round(100 * hal_passed / hal_total, 1) if hal_total else 100.0,
            detail="Deterministic proxy: years/respondent numbers/exhibit labels in generated prose must trace to case input.",
        ),
    ]

    overall = sum(d.score * d.weight for d in dims)

    explanation = (
        "Overall score is a weighted average of six dimensions "
        "(Entity Accuracy 20%, Completeness 20%, Structure 20%, Consistency 15%, "
        "Template Fidelity 15%, Hallucination Check 10%). Each dimension's score is "
        "checks_passed / checks_total * 100, where checks come from deterministic "
        "comparisons against the case input ground truth and the fixed format spec "
        "(see 01_Affidavit_Format_Explained.pdf) — no LLM is involved in scoring."
    )

    return EvaluationReport(
        overall_score=round(overall, 1),
        dimensions=dims,
        issues=all_issues,
        scoring_explanation=explanation,
    )
