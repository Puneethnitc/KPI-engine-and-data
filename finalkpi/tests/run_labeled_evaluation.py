"""Score reviewed per-KPI alert labels; never use generator notes as truth."""

import argparse
import csv
import json
from pathlib import Path

from kpi_engine.evaluation import ReviewedCase, evaluate_alerts
from kpi_engine.pipeline import KPIEnginePipeline


ROOT = Path(__file__).resolve().parent


def run(labels_csv: str) -> dict:
    cases = []
    with open(labels_csv, newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {"case_id", "kpi_id", "date", "region", "category", "event_present", "split", "reviewer"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Reviewed labels require columns: {', '.join(sorted(required))}")
        for row in reader:
            label = row["event_present"].strip().lower()
            if label not in {"true", "false"}:
                raise ValueError("event_present must be true or false")
            cases.append(ReviewedCase(
                case_id=row["case_id"], kpi_id=row["kpi_id"], date=row["date"],
                dimension_slice={key: row[key] for key in ("region", "category") if row[key]},
                event_present=label == "true", split=row["split"], reviewer=row["reviewer"],
            ))
    pipeline = KPIEnginePipeline(
        registry_dir=str(ROOT / "kpi_engine" / "registry"),
        evidence_csv=str(ROOT / "data" / "unstructured_evidence.csv"),
        access_csv=str(ROOT / "data" / "access_control.csv"),
        feedback_log_path=str(ROOT / "data" / "feedback_log.jsonl"),
    )
    registered = set(pipeline.registry.list_ids())
    if {case.kpi_id for case in cases} - registered:
        raise ValueError("Reviewed labels include an unknown KPI")

    def diagnose(case: ReviewedCase) -> dict:
        return pipeline.run_diagnosis(
            kpi_id=case.kpi_id, target_date=case.date,
            dimension_slice=case.dimension_slice, persona="CFO",
            sales_csv=str(ROOT / "data" / "sales_daily.csv"),
            marketing_csv=str(ROOT / "data" / "marketing_weekly.csv"),
            finance_csv=str(ROOT / "data" / "finance_monthly.csv"),
        )

    return {"label_source": str(labels_csv), "metrics": evaluate_alerts(cases, diagnose)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels_csv", help="Independently reviewed per-KPI case labels")
    print(json.dumps(run(parser.parse_args().labels_csv), indent=2, allow_nan=False))
