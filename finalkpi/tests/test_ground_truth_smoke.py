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

ROOT_EVENTS = TESTS_DIR.parent / "data" / "ground_truth_events.csv"

from run_ground_truth_eval import (  # noqa: E402
    DEFAULT_LABELS,
    build_pipeline,
    evaluate,
    load_cases,
    true_driver_ids,
)

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
        # Stage 1 baseline: remapping stockout -> stock_availability, adding
        # price_discount/promo_flag/weather_temp, and removing the mechanical
        # traffic_drop driver (F-R1/F-R2/F-R4) raised this from Stage 0's <=2
        # to 3 of 5 on this 8-case subset. Full explained-movement ranking
        # (Stage 3) is still required to close the remaining gap (EVT01's
        # hits are still wrong-signed; EVT06/weather is still unranked here).
        self.assertGreaterEqual(attribution["events_with_any_top1_hit"], 3)
        # Direction-aware hits (correct id AND correct sign) can only be a
        # subset of naive hits (F-R2/F-R3: some "hits" are wrong-signed).
        self.assertLessEqual(
            attribution["events_with_any_top1_direction_hit"], attribution["events_with_any_top1_hit"]
        )
        self.assertEqual(attribution["events_scored"], 5)

        # Stage 0 baseline: EVT05 (event_present=False) never counts toward
        # recall or driver accuracy; it is reported separately below.
        self.assertNotIn("EVT05", detection["recall_per_event"])
        self.assertNotIn("EVT05", attribution["per_event"])

        decoy = metrics["decoy"]
        # Stage 0 baseline: the decoy (EVT05) still surfaces a confident-
        # looking top driver because nothing checks whether it truly moved.
        # Stage 3/7 must bring this down; Stage 0 only records it.
        self.assertEqual(decoy["cases"], 1)
        self.assertIsNotNone(decoy["confident_driver_rate"])

        causal = metrics["causal"]
        self.assertIn("EVT01", causal["verdict_counts_per_event"])

        confidence = metrics["confidence"]
        # Stage 7: Brier/AC-gap are no longer placeholders (they were always
        # None before Attribution Confidence existed); on this tiny 6-case
        # smoke subset they may still legitimately be None if nothing
        # scored, so this only checks the fields exist and are well-formed.
        ac_metrics = confidence["attribution_confidence"]
        self.assertIn("brier_score", ac_metrics)
        self.assertIn("ac_gap", ac_metrics)
        self.assertIn("decoy_max_ac", ac_metrics)
        self.assertTrue(confidence["overall_status_counts"])


class MultiTrueDriverLabellingTests(unittest.TestCase):
    """One event can genuinely have more than one true cause.

    EVT02 is a flash sale, which is a price discount AND a promotion, so both
    price_discount and promo_flag are true causes. Scoring it against a single
    id would report promo_flag as a miss on a case it does explain.
    """

    def test_evt02_lists_both_of_its_true_drivers(self) -> None:
        with open(ROOT_EVENTS, newline="", encoding="utf-8") as handle:
            events = {row["event_id"]: row for row in csv.DictReader(handle)}
        self.assertEqual(
            set(events["EVT02"]["true_driver_ids"].split("|")),
            {"price_discount", "promo_flag"},
        )

    def test_every_evt02_case_carries_both_true_drivers(self) -> None:
        cases = [row for row in load_cases(DEFAULT_LABELS, "all") if row["event_id"] == "EVT02"]
        self.assertTrue(cases)
        for row in cases:
            self.assertEqual(true_driver_ids(row), {"price_discount", "promo_flag"})

    def test_single_driver_events_are_unaffected(self) -> None:
        cases = {row["event_id"]: row for row in load_cases(DEFAULT_LABELS, "all") if row["event_id"]}
        self.assertEqual(true_driver_ids(cases["EVT01"]), {"marketing_spend"})
        self.assertEqual(true_driver_ids(cases["EVT03"]), {"stock_availability"})
        self.assertEqual(true_driver_ids(cases["EVT06"]), {"weather_temp"})
        # The decoy has no true driver at all.
        self.assertEqual(true_driver_ids(cases["EVT05"]), set())

    def test_a_hit_on_either_listed_true_driver_counts(self) -> None:
        """End to end on the harness scoring path: ranking promo_flag first on
        an EVT02 case is a correct answer, not a miss."""
        case = next(row for row in load_cases(DEFAULT_LABELS, "all")
                    if row["case_id"] == "EVT02-2023-11-05-net_sales_revenue")

        def result_with_top(driver_id: str) -> dict:
            return {
                "movement_assessment": {"status": "OK", "is_material": True,
                                        "is_statistically_significant": True, "is_business_material": True},
                "driver_analysis": {"status": "ASSESSED", "ranked_drivers": [
                    {"driver_id": driver_id, "explained_share": 0.4, "attribution_confidence": 0.6,
                     "band": "MODERATE", "moved": True, "offsetting": False, "sample_size": 40},
                ]},
            }

        pipeline = build_pipeline()
        for driver_id in ("price_discount", "promo_flag"):
            with self.subTest(driver_id=driver_id):
                metrics = evaluate([case], pipeline, runner=lambda row: result_with_top(driver_id))
                self.assertEqual(metrics["attribution"]["top1_accuracy"], 1.0)
                self.assertEqual(metrics["attribution"]["events_with_any_top1_hit"], 1)

        # A driver that is not a true cause is still a miss.
        metrics = evaluate([case], pipeline, runner=lambda row: result_with_top("weather_temp"))
        self.assertEqual(metrics["attribution"]["top1_accuracy"], 0.0)
        self.assertEqual(metrics["attribution"]["events_with_any_top1_hit"], 0)


if __name__ == "__main__":
    unittest.main()
