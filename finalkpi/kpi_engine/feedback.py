# IMPLEMENTATION HANDOFF — proposed corrections
# Current: append JSONL feedback with pending-review status and an actual UTC
# creation time; historical diagnoses and contract definitions remain untouched.
# Next: align record IDs and review lifecycle with backend/storage.py's separate
# feedback path. Reference run/contract/source versions and validate run linkage.
# SQLite may keep this transactional work when DuckDB handles analytics.
# Check: feedback persists as a proposal; no automatic causal label or contract
# rewrite, and original/corrected text must remain a paired audit record.

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass, asdict


# Stored feedback shape; corrections are proposed evidence for later review.
@dataclass
class FeedbackRecord:
    run_id: str
    user_id: str
    kpi_id: str
    target_date: str
    feedback_type: str  # "CORRECT_CAUSE", "MISSED_DRIVER", "INCORRECT_NARRATIVE"
    comments: str
    timestamp: str
    original_text: str | None = None
    corrected_text: str | None = None
    review_status: str = "PENDING_REVIEW"


# Persistence boundary; callers choose the destination through configuration.
class FeedbackLogger:
    """Append proposed corrections without mutating historical output."""

    def __init__(self, log_filepath: str = "data/feedback_log.jsonl"):
        self.log_filepath = log_filepath

    def log_feedback(
        self,
        run_id: str,
        user_id: str,
        kpi_id: str,
        target_date: str,
        feedback_type: str,
        comments: str = "",
        original_text: str | None = None,
        corrected_text: str | None = None,
    ) -> FeedbackRecord:
        """Append a structured, pending-review feedback entry."""
        if bool(original_text) != bool(corrected_text):
            raise ValueError("A correction needs both original and corrected text")
        if not run_id or not user_id or not kpi_id or not target_date or not feedback_type:
            raise ValueError("Feedback requires run, user, KPI, date, and type")
        directory = os.path.dirname(self.log_filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
        
        record = FeedbackRecord(
            run_id=run_id,
            user_id=user_id,
            kpi_id=kpi_id,
            target_date=target_date,
            feedback_type=feedback_type,
            comments=comments,
            timestamp=datetime.now(timezone.utc).isoformat(),
            original_text=original_text,
            corrected_text=corrected_text,
        )

        with open(self.log_filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record)) + "\n")
        return record
