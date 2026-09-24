"""Held-out evaluation keeps abstentions visible and rejects weak labels."""

import unittest

from kpi_engine.evaluation import ReviewedCase, evaluate_alerts


class EvaluationCases(unittest.TestCase):
    def case(self, case_id, positive, split="holdout"):
        return ReviewedCase(case_id, "orders", f"2023-01-{int(case_id):02d}",
                            {"region": "North"}, positive, split, "independent_reviewer")

    def test_counts_and_abstentions_are_separate(self):
        cases = [self.case("1", True), self.case("2", False),
                 self.case("3", True), self.case("4", False)]
        outcomes = {"1": ("OK", True), "2": ("OK", True),
                    "3": ("INSUFFICIENT_HISTORY", None), "4": ("OK", False)}
        report = evaluate_alerts(cases, lambda case: {
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "movement_assessment": {"status": outcomes[case.case_id][0],
                                    "is_material": outcomes[case.case_id][1]},
        })["holdout"]["orders"]
        self.assertEqual((report["tp"], report["fp"], report["tn"], report["abstain_positive"]),
                         (1, 1, 1, 1))
        self.assertEqual(report["precision_on_scored"], 0.5)
        self.assertEqual(report["recall_on_scored"], 1.0)

    def test_requires_review_and_unique_case(self):
        case = self.case("1", True)
        with self.assertRaises(ValueError):
            evaluate_alerts([case, case], lambda _: {})
        with self.assertRaises(ValueError):
            evaluate_alerts([ReviewedCase("1", "orders", "2023-01-01", {}, True,
                                          "holdout", "")], lambda _: {})


if __name__ == "__main__":
    unittest.main()
