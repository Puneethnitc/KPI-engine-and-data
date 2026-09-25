"""Run the current, evidence-limited diagnosis on supplied sample data."""

import argparse
import json
import os
from pathlib import Path

import yaml

from kpi_engine.pipeline import KPIEnginePipeline
from kpi_engine.verification import VerificationDesign


ROOT = Path(__file__).resolve().parents[1]


def run(
    kpi_id: str = "net_sales_revenue",
    target_date: str = "2023-07-24",
    region: str = "North",
    category: str = "Electronics",
    persona: str = "CFO",
    source_schema_path: str | None = None,
    sales_csv: str | None = None,
    marketing_csv: str | None = None,
    finance_csv: str | None = None,
    verification_design_path: str | None = None,
) -> dict:
    pipeline = KPIEnginePipeline(
        registry_dir=str(ROOT / "kpi_engine" / "registry"),
        evidence_csv=str(ROOT / "data" / "unstructured_evidence.csv"),
        access_csv=str(ROOT / "data" / "access_control.csv"),
        feedback_log_path=str(ROOT / "data" / "feedback_log.jsonl"),
        source_schema_path=source_schema_path,
        groq_api_key=os.environ.get("GROQ_API_KEY"),
    )
    design = None
    if verification_design_path:
        with Path(verification_design_path).open("r", encoding="utf-8") as design_file:
            spec = yaml.safe_load(design_file)
        if not isinstance(spec, dict):
            raise ValueError("Verification design must be a YAML or JSON mapping")
        if "quiet_windows" in spec:
            spec["quiet_windows"] = tuple(tuple(window) for window in spec["quiet_windows"])
        design = VerificationDesign(**spec)
    return pipeline.run_diagnosis(
        kpi_id=kpi_id,
        target_date=target_date,
        sales_csv=sales_csv or str(ROOT / "data" / "sales_daily.csv"),
        marketing_csv=marketing_csv or str(ROOT / "data" / "marketing_weekly.csv"),
        finance_csv=finance_csv or str(ROOT / "data" / "finance_monthly.csv"),
        persona=persona,
        dimension_slice={"region": region, "category": category},
        verification_design=design,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kpi", default="net_sales_revenue")
    parser.add_argument("--date", default="2023-07-24")
    parser.add_argument("--region", default="North")
    parser.add_argument("--category", default="Electronics")
    parser.add_argument("--persona", default="CFO")
    parser.add_argument("--source-schema", help="YAML mapping renamed source columns to canonical names")
    parser.add_argument("--sales-csv")
    parser.add_argument("--marketing-csv")
    parser.add_argument("--finance-csv")
    parser.add_argument("--verification-design", help="YAML/JSON file with an explicit observational event design")
    args = parser.parse_args()
    result = run(args.kpi, args.date, args.region, args.category, args.persona,
                 args.source_schema, args.sales_csv, args.marketing_csv, args.finance_csv,
                 args.verification_design)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
