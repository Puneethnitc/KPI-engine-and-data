"""Generate a local, read-only HTML evidence review for all registered KPIs."""

import argparse
from html import escape
from pathlib import Path

from kpi_engine.pipeline import KPIEnginePipeline


ROOT = Path(__file__).resolve().parent


def _safe(value) -> str:
    return escape(str(value), quote=True)


def build_report(date: str = "2023-07-24", region: str = "North",
                 category: str = "Electronics", persona: str = "CFO") -> str:
    pipeline = KPIEnginePipeline(
        registry_dir=str(ROOT / "kpi_engine" / "registry"),
        evidence_csv=str(ROOT / "data" / "unstructured_evidence.csv"),
        access_csv=str(ROOT / "data" / "access_control.csv"),
        feedback_log_path=str(ROOT / "data" / "feedback_log.jsonl"),
    )
    requested_slice = {"region": region, "category": category}
    sections = []
    for kpi_id in pipeline.registry.list_ids():
        result = pipeline.run_diagnosis(
            kpi_id, date,
            str(ROOT / "data" / "sales_daily.csv"),
            str(ROOT / "data" / "marketing_weekly.csv"),
            str(ROOT / "data" / "finance_monthly.csv"),
            persona=persona, dimension_slice=requested_slice,
        )
        movement = result.get("movement_assessment") or {}
        reconciliation = result.get("reconciliation_verdict") or {}
        facts = "".join(
            f"<li><span>{_safe(label)}</span><strong>{_safe(value)}</strong></li>"
            for label, value in (
                ("Verdict", result.get("verdict")),
                ("Observed change", movement.get("delta", "Unavailable")),
                ("Source status", reconciliation.get("status", "Unavailable")),
                ("Detector agreement", movement.get("detector_agreement", "Unavailable")),
                ("Accounting bridge", result.get("decomposition_status")),
                ("Causal check", result.get("causal_verdict") or "Not run"),
            )
        )
        claims = "".join(
            f"<li>{_safe(claim['text'])}<small>Evidence: "
            f"{_safe(', '.join(claim['evidence_paths']))}</small></li>"
            for claim in result.get("narrative_claims", [])
        )
        cards = "".join(
            f"<li><strong>{_safe(card['kind'])}</strong>: {_safe(card['recommendation'])} "
            f"<small>{_safe(card['status'])} · {_safe(card['owner'])}</small></li>"
            for card in result.get("decision_cards", [])
        ) or "<li>No recommendation from this evidence.</li>"
        sections.append(
            f"<section><h2>{_safe(kpi_id)}</h2><p class='summary'>{_safe(result['narrative'])}</p>"
            f"<ul class='facts'>{facts}</ul><details><summary>Evidence-bound claims</summary>"
            f"<ol>{claims}</ol></details><h3>Human review</h3><ul>{cards}</ul>"
            f"<p class='foot'>Grounding: {_safe(result['grounding_passed'])}; "
            f"LLM: {_safe(result.get('llm_status'))}. No action is executed.</p></section>"
        )
    title = f"KPI review · {date} · {region}/{category}"
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_safe(title)}</title><style>"
            "body{font:16px/1.55 system-ui,sans-serif;margin:0;background:#f4f7fb;color:#17243b}"
            "main{max-width:1080px;margin:auto;padding:32px}h1{margin-bottom:4px}"
            ".intro{color:#45546b;margin-bottom:28px}section{background:white;border:1px solid #d9e2ee;"
            "border-radius:14px;padding:24px;margin:18px 0;box-shadow:0 3px 12px #1f35500a}"
            ".summary{font-size:1.08rem}ul{padding-left:22px}.facts{list-style:none;padding:0;"
            "display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}"
            ".facts li{background:#eef3fa;border-radius:8px;padding:10px;display:grid}"
            ".facts span,small,.foot{color:#52627b}small{display:block;margin-top:4px}"
            "details{border-top:1px solid #e2e8f0;padding-top:12px}summary{cursor:pointer;font-weight:600}"
            "</style></head><body><main>"
            f"<h1>{_safe(title)}</h1><p class='intro'>Read-only evidence review for {_safe(persona)}. "
            "Accounting, correlation, and observational checks are distinct. "
            "No causal probability or automatic action is implied.</p>"
            + "".join(sections) + "</main></body></html>")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2023-07-24")
    parser.add_argument("--region", default="North")
    parser.add_argument("--category", default="Electronics")
    parser.add_argument("--persona", default="CFO")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.date, args.region, args.category, args.persona)
    args.output.write_text(report, encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
