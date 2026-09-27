# IMPLEMENTATION HANDOFF — ground-truth harness smoke test
# Current: exercises tests/run_ground_truth_eval.py end to end on a tiny,
# hand-picked subset (one positive date per real event, plus a few negatives)
# so a broken harness fails fast in CI without paying for the full ~230-case
# run. Assertions are loose bounds recording the Stage 0 baseline, not
# regression gates; every later stage tightens them as the plan requires.
# Next: Stage 2 tightens detection assertions, Stage 3 tightens driver
# assertions, once those stages implement the corrected behaviour.
# Check: the harness must run to completion and return well-formed metrics
# even before any of the later-stage fixes exist.

import csv
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from run_ground_truth_eval import DEFAULT_LABELS, build_pipeline, evaluate  # noqa: E402

# One representative case per event (first positive date) plus 2 negatives.
SMOKE_CASE_IDS = {
    "EVT01-2023-07-20-net_sales_revenue",
    "EVT02-2023-10-28-net_sales_revenue",
    "EVT03-2024-02-05-net_sales_revenue",
    "EVT04-2024-05-15-net_sales_revenue",
    "EVT05-2024-07-14-net_sales_revenue",
    "EVT06-2023-04-11-net_sales_revenue",
}


def _load_smoke_cases() -> list[dict]:
    with open(DEFAULT_LABELS, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [row for row in reader if row["case_id"] in SMOKE_CASE_IDS]
    negatives = []
    with open(DEFAULT_LABELS, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row["event_id"] and len(negatives) < 2:
                negatives.append(row)
    rows.extend(negatives)
    for row in rows:
        row["event_present"] = row["event_present"].strip().lower() == "true"
        row["is_decoy"] = str(row.get("is_decoy", "")).strip().lower() == "true"
    return rows


class GroundTruthSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = _load_smoke_cases()
        cls.pipeline = build_pipeline()

    def test_label_file_has_expected_events(self) -> None:
        self.assertTrue(Path(DEFAULT_LABELS).is_file())
        event_ids = {row["event_id"] for row in self.cases if row["event_id"]}
        self.assertEqual(event_ids, {"EVT01", "EVT02", "EVT03", "EVT04", "EVT05", "EVT06"})

    def test_harness_runs_end_to_end(self) -> None:
        self.assertEqual(len(self.cases), 8)
        metrics = evaluate(self.cases, self.pipeline)
        self.assertEqual(metrics["case_count"], 8)

        detection = metrics["detection"]
        self.assertIn("EVT01", detection["recall_per_event"])
        self.assertIsNotNone(detection["false_alarm_rate_negatives"])

        attribution = metrics["attribution"]
        # Stage 0 baseline: driver ranking finds the true cause on at most a
        # couple of the 5 real (non-decoy) events. This documents the known
        # flaw (F-R1/F-R2/F-R3); Stage 3 must raise this bound.
        self.assertLessEqual(attribution["events_with_any_top1_hit"], 2)
        self.assertEqual(attribution["events_scored"], 5)

        # Stage 0 baseline: the decoy (EVT05) still surfaces a confident-
        # looking top driver because nothing checks whether it truly moved.
        # Stage 3/7 must bring this down; Stage 0 only records it.
        self.assertEqual(attribution["decoy_cases"], 1)

        causal = metrics["causal"]
        self.assertIn("EVT01", causal["verdict_counts_per_event"])

        confidence = metrics["confidence"]
        self.assertIsNone(confidence["brier_score"])
        self.assertTrue(confidence["overall_status_counts"])


if __name__ == "__main__":
    unittest.main()
