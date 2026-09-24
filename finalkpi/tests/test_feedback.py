"""Feedback preserves a proposed correction without silently changing evidence."""

import json
import tempfile
import unittest
from pathlib import Path

from kpi_engine.feedback import FeedbackLogger


class FeedbackCases(unittest.TestCase):
    def test_before_after_is_pending_review_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feedback.jsonl"
            record = FeedbackLogger(str(path)).log_feedback(
                "run-1", "reviewer-1", "orders", "2023-07-24",
                "INCORRECT_NARRATIVE", "Driver was not established",
                "Traffic caused the decline", "Traffic is a correlational candidate",
            )
            self.assertEqual(record.review_status, "PENDING_REVIEW")
            saved = json.loads(path.read_text().strip())
            self.assertEqual(saved["original_text"], "Traffic caused the decline")
            self.assertEqual(saved["corrected_text"], "Traffic is a correlational candidate")

    def test_partial_correction_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                FeedbackLogger(str(Path(directory) / "feedback.jsonl")).log_feedback(
                    "run-1", "reviewer-1", "orders", "2023-07-24",
                    "INCORRECT_NARRATIVE", original_text="Before",
                )


if __name__ == "__main__":
    unittest.main()
