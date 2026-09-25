# IMPLEMENTATION HANDOFF — configured dataset locations
# Current: bundled sales/marketing/finance/access files and demo scope defaults;
# SQLite path is separately configurable and its directory is created on import.
# Next: reference a validated source catalog and choose valid scope/date defaults
# from metadata. Keep app storage separate from the analytic query connection.
# Check: an alternate dataset works through configuration without path edits;
# no stale North/Electronics/date default is silently applied to that dataset.

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUNTIME_DIR = Path(os.getenv("KPI_RUNTIME_DIR", ROOT / "backend" / "runtime"))
CHROMA_DIR = Path(os.getenv("KPI_CHROMA_DIR", RUNTIME_DIR / "chroma"))

ENGINE_REGISTRY_DIR = str(ROOT / "kpi_engine" / "registry")
EVIDENCE_CSV = str(ROOT / "data" / "unstructured_evidence.csv")
ACCESS_CSV = str(ROOT / "data" / "access_control.csv")
SALES_CSV = str(ROOT / "data" / "sales_daily.csv")
MARKETING_CSV = str(ROOT / "data" / "marketing_weekly.csv")
FINANCE_CSV = str(ROOT / "data" / "finance_monthly.csv")
FEEDBACK_LOG_PATH = str(ROOT / "data" / "feedback_log.jsonl")
DB_PATH = Path(os.getenv("KPI_BACKEND_DB", RUNTIME_DIR / "kpi_backend.sqlite3"))

DEFAULT_PERSONA = os.getenv("KPI_DEMO_PERSONA", "CFO")
DEFAULT_REGION = os.getenv("KPI_DEMO_REGION", "North")
DEFAULT_CATEGORY = os.getenv("KPI_DEMO_CATEGORY", "Electronics")
DEFAULT_DATE = os.getenv("KPI_DEMO_DATE", "2023-07-24")

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "KPI_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
