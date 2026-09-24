from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ENGINE_REGISTRY_DIR = str(ROOT / "kpi_engine" / "registry")
EVIDENCE_CSV = str(ROOT / "data" / "unstructured_evidence.csv")
ACCESS_CSV = str(ROOT / "data" / "access_control.csv")
SALES_CSV = str(ROOT / "data" / "sales_daily.csv")
MARKETING_CSV = str(ROOT / "data" / "marketing_weekly.csv")
FINANCE_CSV = str(ROOT / "data" / "finance_monthly.csv")
FEEDBACK_LOG_PATH = str(ROOT / "data" / "feedback_log.jsonl")
DB_PATH = Path(os.getenv("KPI_BACKEND_DB", ROOT / "backend" / "data" / "kpi_backend.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_PERSONA = os.getenv("KPI_DEMO_PERSONA", "CFO")
DEFAULT_REGION = os.getenv("KPI_DEMO_REGION", "North")
DEFAULT_CATEGORY = os.getenv("KPI_DEMO_CATEGORY", "Electronics")
DEFAULT_DATE = os.getenv("KPI_DEMO_DATE", "2023-07-24")
