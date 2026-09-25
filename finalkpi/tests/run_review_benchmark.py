"""Reproducible case review; provisional windows are not accuracy labels."""

import argparse
import json
from pathlib import Path

import yaml

from kpi_engine.pipeline import KPIEnginePipeline


ROOT = Path(__file__).resolve().parents[1]


def run(manifest_path: str | None = None, kpi_ids: list[str] | None = None) -> dict:
    path = Path(manifest_path) if manifest_path else ROOT / "examples" / "review_windows.yaml"
    with path.open("r", encoding="utf-8") as source:
        manifest = yaml.safe_load(source)
    if not isinstance(manifest, dict) or manifest.get("label_status") != "PROVISIONAL_GENERATOR_NOTES":
        raise ValueError("Review manifest must explicitly declare provisional label status")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Review manifest needs cases")
    pipeline = KPIEnginePipeline(
        registry_dir=str(ROOT / "kpi_engine" / "registry"),
        evidence_csv=str(ROOT / "data" / "unstructured_evidence.csv"),
        access_csv=str(ROOT / "data" / "access_control.csv"),
        feedback_log_path=str(ROOT / "data" / "feedback_log.jsonl"),
    )
    selected = kpi_ids or list(pipeline.registry.list_ids())
    if set(selected) - set(pipeline.registry.list_ids()):
        raise ValueError("Unknown KPI in requested review")
    rows = []
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "context", "date", "slice"}:
            raise ValueError("Each review case needs id, context, date, and slice")
        if case["context"] not in {"documented_event", "reference_window"}:
            raise ValueError("Unknown review context")
        if not isinstance(case["slice"], dict):
            raise ValueError("Review slice must be a mapping")
        for kpi_id in selected:
            result = pipeline.run_diagnosis(
                kpi_id=kpi_id, target_date=case["date"],
                sales_csv=str(ROOT / "data" / "sales_daily.csv"),
                marketing_csv=str(ROOT / "data" / "marketing_weekly.csv"),
                finance_csv=str(ROOT / "data" / "finance_monthly.csv"),
                persona="CFO", dimension_slice=case["slice"],
            )
            movement = result["movement_assessment"] or {}
            rows.append({
                "case_id": case["id"], "context": case["context"],
                "date": case["date"], "slice": case["slice"], "kpi_id": kpi_id,
                "verdict": result["verdict"],
                "detector_agreement": movement.get("detector_agreement"),
                "is_material": movement.get("is_material"),
                "grounding_passed": result["grounding_passed"],
            })
    return {
        "label_status": "PROVISIONAL_GENERATOR_NOTES",
        "accuracy_metrics": None,
        "accuracy_note": "No independent ground-truth labels; counts are descriptive, not precision or recall.",
        "kpis": selected, "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--kpi", action="append", dest="kpis")
    args = parser.parse_args()
    print(json.dumps(run(args.manifest, args.kpis), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
