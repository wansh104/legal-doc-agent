# Evaluation Report — Affidavit in Reply

**Overall Score: 100.0/100**

## Dimension Scores

| Dimension | Score | Weight | Checks Passed | Detail |
|---|---|---|---|---|
| Entity Accuracy | 100.0/100 | 20% | 9/9 | Extracted document fields compared against CaseInput ground truth. |
| Completeness | 100.0/100 | 20% | 2/2 | Body paragraph count and prayer presence checked against the plan. |
| Structure | 100.0/100 | 20% | 10/10 | All 10 required sections from the format spec checked for presence. |
| Consistency | 100.0/100 | 15% | 11/11 | Respondent number, verification range, and verb-agreement checks. |
| Template Fidelity | 100.0/100 | 15% | 7/7 | Fixed-phrase reuse, exhibit mapping, and deponent-clause form. |
| Hallucination Check | 100.0/100 | 10% | 7/7 | Deterministic proxy: years/respondent numbers/exhibit labels in generated prose must trace to case input. |

## Issues Detected

None detected.

## Scoring Method

Overall score is a weighted average of six dimensions (Entity Accuracy 20%, Completeness 20%, Structure 20%, Consistency 15%, Template Fidelity 15%, Hallucination Check 10%). Each dimension's score is checks_passed / checks_total * 100, where checks come from deterministic comparisons against the case input ground truth and the fixed format spec (see 01_Affidavit_Format_Explained.pdf) — no LLM is involved in scoring.