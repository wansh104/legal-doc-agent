"""
Stage 3 — Content Mapping.

Deterministic: the case info's reply_points already arrive in the order they
must appear (Section 3 of the format explainer requires
Identity -> Blanket Denial -> Preliminary Position -> Substantive Answer(s)),
so mapping is just: keep that order, then append a synthesized CLOSING point
that ISN'T in the case info (it's boilerplate, not case-specific fact), then
number sequentially 1..N.
"""

from __future__ import annotations
from src.schema import CaseInput, ReplyPoint, ReplyMove

CLOSING_HEADING = "Closing"


def build_paragraph_plan(case_input: CaseInput) -> list[ReplyPoint]:
    ordered = sorted(case_input.reply_points, key=lambda p: p.order)

    expected_move_prefix = [
        ReplyMove.IDENTITY_AND_PERUSAL,
        ReplyMove.BLANKET_DENIAL,
        ReplyMove.PRELIMINARY_POSITION,
    ]
    for expected, actual in zip(expected_move_prefix, ordered):
        if actual.move != expected:
            raise ValueError(
                f"Reply point order violates the fixed sequence: expected {expected} "
                f"at position {expected_move_prefix.index(expected) + 1}, got {actual.move} "
                f"(heading: {actual.heading}). Check extraction output."
            )

    closing = ReplyPoint(
        order=ordered[-1].order + 1,
        heading=CLOSING_HEADING,
        move=ReplyMove.CLOSING,
        bullets=[],
        exhibit_label=None,
    )
    plan = ordered + [closing]

    # renumber 1..N to guarantee no gaps regardless of source `order` values
    for i, point in enumerate(plan, start=1):
        point.order = i
    return plan
