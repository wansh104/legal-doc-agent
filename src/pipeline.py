"""
End-to-end pipeline orchestration.

Each stage is wrapped so a failure is reported as
"Stage X (<name>) failed: <reason>" instead of a bare traceback — this is
the "mechanism that explains why the system failed, not only that it
failed" bonus item. Streamlit (app.py) and any CLI entry point both call
run_pipeline() so there's exactly one place this logic lives.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from src.schema import CaseInput, EvaluationReport
from src import extraction, mapping, generation, doc_reader, validation, evaluation
from src import template_spec


class StageError(Exception):
    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.original = original
        super().__init__(f"Stage failed: {stage} — {type(original).__name__}: {original}")


@dataclass
class PipelineResult:
    case_input: CaseInput
    docx_path: str
    evaluation_report: EvaluationReport
    paragraphs: list = field(default_factory=list)
    reference_structure_summary: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def run_pipeline(
    case_info_text: str,
    reference_pdf_path: str | None,
    output_docx_path: str,
) -> PipelineResult:
    warnings: list[str] = []

    # Stage 1 — Template / Structure Analysis (sanity check against the hardcoded spec)
    reference_summary = {}
    if reference_pdf_path:
        try:
            ref_structure = doc_reader.extract_structure_from_pdf(reference_pdf_path)
            reference_summary = {
                "sections_found_in_reference": ref_structure.sections_present,
                "missing_vs_spec": [
                    s for s in template_spec.REQUIRED_SECTIONS
                    if s not in ref_structure.sections_present
                ],
            }
        except Exception as e:
            warnings.append(f"Stage 1 (reference structure read) failed non-fatally: {e}")

    # Stage 2 — Entity Extraction
    try:
        case_input = extraction.extract_case_input(case_info_text)
    except Exception as e:
        raise StageError("Stage 2: Entity Extraction", e) from e

    # Pre-generation validation
    try:
        pre_issues = validation.pre_generation_checks(case_input)
    except Exception as e:
        raise StageError("Pre-generation validation", e) from e
    blocking = [i for i in pre_issues if i.severity.value == "error"]
    if blocking:
        raise StageError(
            "Pre-generation validation",
            ValueError(f"{len(blocking)} blocking issue(s): " + "; ".join(i.message for i in blocking)),
        )

    # Stage 3 — Content Mapping
    try:
        plan = mapping.build_paragraph_plan(case_input)
    except Exception as e:
        raise StageError("Stage 3: Content Mapping", e) from e

    # Stage 4 — Document Generation
    try:
        paragraphs = generation.draft_all_paragraphs(plan, case_input)
        generation.build_docx(case_input, paragraphs, output_docx_path)
    except Exception as e:
        raise StageError("Stage 4: Document Generation", e) from e

    # Stage 5 — Extraction from generated document
    try:
        extracted = doc_reader.extract_structure(output_docx_path)
    except Exception as e:
        raise StageError("Stage 5: Generated-Document Structure Extraction", e) from e

    # Stage 6 — Ground Truth Comparison + Scoring
    try:
        report = evaluation.evaluate(case_input, paragraphs, extracted, pre_issues=pre_issues)
    except Exception as e:
        raise StageError("Stage 6: Evaluation", e) from e

    return PipelineResult(
        case_input=case_input,
        docx_path=output_docx_path,
        evaluation_report=report,
        paragraphs=paragraphs,
        reference_structure_summary=reference_summary,
        warnings=warnings,
    )


def inject_test_error(result: PipelineResult, corrupted_path: str) -> EvaluationReport:
    """Makes a copy of the generated docx with a deliberately wrong
    respondent number in the affidavit title, re-parses it, and re-runs
    Stage 6 evaluation against the SAME case_input/paragraphs (no new LLM
    calls) — this is what proves the deterministic checks actually catch
    something, not just that they pass on clean input."""
    from docx import Document
    doc = Document(result.docx_path)
    wrong_number = result.case_input.replying_respondent_number + 1
    for p in doc.paragraphs:
        if p.text.strip().upper().startswith("AFFIDAVIT IN REPLY ON BEHALF OF RESPONDENT NO"):
            for run in p.runs:
                run.text = run.text.replace(
                    str(result.case_input.replying_respondent_number), str(wrong_number)
                )
    doc.save(corrupted_path)

    corrupted_structure = doc_reader.extract_structure(corrupted_path)
    return evaluation.evaluate(result.case_input, result.paragraphs, corrupted_structure, pre_issues=[])


def render_report_markdown(result: PipelineResult) -> str:
    r = result.evaluation_report
    lines = [
        "# Evaluation Report — Affidavit in Reply",
        "",
        f"**Overall Score: {r.overall_score}/100**",
        "",
        "## Dimension Scores",
        "",
        "| Dimension | Score | Weight | Checks Passed | Detail |",
        "|---|---|---|---|---|",
    ]
    for d in r.dimensions:
        lines.append(f"| {d.name} | {d.score}/100 | {int(d.weight*100)}% | {d.checks_passed}/{d.checks_total} | {d.detail} |")

    lines += ["", "## Issues Detected", ""]
    if not r.issues:
        lines.append("None detected.")
    else:
        for idx, issue in enumerate(r.issues, 1):
            lines.append(f"{idx}. **[{issue.severity.value.upper()}] {issue.dimension}** — {issue.message}")
            lines.append(f"   - *Source: {issue.source}*")

    lines += ["", "## Scoring Method", "", r.scoring_explanation]

    if result.warnings:
        lines += ["", "## Non-fatal Warnings", ""]
        for w in result.warnings:
            lines.append(f"- {w}")

    return "\n".join(lines)