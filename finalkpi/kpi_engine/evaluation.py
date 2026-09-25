# IMPLEMENTATION HANDOFF — evaluation boundary
# Current: report per-KPI train/holdout confusion counts with abstentions separate.
# Next: add contract/policy/source versions and case coverage to evaluation runs;
# use independent labels for calibration, plus hand-calculated metric fixtures
# for DuckDB parity. Data-generator event names are not automatic ground truth.
# Check: duplicate cases fail, abstentions stay visible, held-out cases are not
# used to choose thresholds, and metric correctness is evaluated separately.

"""Evaluate alerts only against independently reviewed, per-KPI labels."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewedCase:
    case_id: str
    kpi_id: str
    date: str
    dimension_slice: dict[str, str]
    event_present: bool
    split: str
    reviewer: str


def evaluate_alerts(cases: list[ReviewedCase], run_case: Callable[[ReviewedCase], dict]) -> dict:
    """Score the primary alert, counting abstentions separately from negatives.

    The caller must supply independently reviewed cases; this function never
    derives labels from the dataset generator or from the engine's verdict.
    """
    if not cases:
        raise ValueError("At least one independently reviewed case is required")
    seen = set()
    counts: dict[tuple[str, str], Counter] = {}
    for case in cases:
        if (not isinstance(case, ReviewedCase) or not case.case_id or not case.kpi_id
                or case.split not in {"train", "holdout"} or not case.reviewer
                or not isinstance(case.event_present, bool)):
            raise ValueError("Cases require a KPI, reviewer, boolean label, and train/holdout split")
        key = (case.kpi_id, case.date, tuple(sorted(case.dimension_slice.items())))
        if key in seen:
            raise ValueError("Duplicate KPI/date/slice label")
        seen.add(key)
        result = run_case(case)
        movement = result.get("movement_assessment") or {}
        verdict = result.get("verdict")
        decision = movement.get("is_material")
        bucket = counts.setdefault((case.split, case.kpi_id), Counter())
        if verdict in {"ACCESS_DENIED", "CONTRADICTED"} or movement.get("status") != "OK" or not isinstance(decision, bool):
            bucket["abstain_positive" if case.event_present else "abstain_negative"] += 1
        elif decision and case.event_present:
            bucket["tp"] += 1
        elif decision:
            bucket["fp"] += 1
        elif case.event_present:
            bucket["fn"] += 1
        else:
            bucket["tn"] += 1
    output = {}
    for (split, kpi_id), bucket in sorted(counts.items()):
        tp, fp, fn = bucket["tp"], bucket["fp"], bucket["fn"]
        output.setdefault(split, {})[kpi_id] = {
            **{name: bucket[name] for name in (
                "tp", "fp", "fn", "tn", "abstain_positive", "abstain_negative"
            )},
            "precision_on_scored": tp / (tp + fp) if tp + fp else None,
            "recall_on_scored": tp / (tp + fn) if tp + fn else None,
            "note": "Abstentions excluded from scored precision/recall and reported separately.",
        }
    return output
