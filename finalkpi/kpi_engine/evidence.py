"""Source evidence contract builder.

Constructs a serializable evidence structure for every diagnosis run containing:
- source_readiness: overall readiness of data integration
- sources[]: per-source metadata from catalog + runtime observation
- alignment[]: how weekly/monthly data was aligned to daily KPI grain
- reconciliation: independent value comparison result (or NOT_APPLICABLE)
- lineage[]: claim → source path

Critical semantic rules (do not change):
- NOT_APPLICABLE means no independent comparison is configured.  It is NOT
  a failure; it is informational and non-blocking.
- Source readiness and reconciliation status are completely independent.
- Data-quality failure (DRIFT with quality_flag) is separate from value DRIFT.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd


# ---------------------------------------------------------------------------
# Source readiness statuses
# ---------------------------------------------------------------------------
# READY       – all required sources loaded, aligned and available.
# PARTIAL     – some sources loaded but marketing or finance unavailable.
# STALE       – a source's latest available timestamp is behind the cutoff.
# MISSING     – a required source could not be loaded at all.
# QUALITY_FAILED – a quality validation prevented use of the source.

CADENCE_MAP = {
    "daily": "T+1 business day",
    "weekly": "T+3 business days after week end",
    "monthly": "T+5 business days after month close",
}

ROLE_MAP = {
    "sales_daily": "primary_metric",
    "marketing_weekly": "driver",
    "finance_monthly": "independent_comparison",
}


@dataclass
class SourceEntry:
    source_id: str
    display_name: str
    source_role: str
    file_identifier: Optional[str]
    native_grain: str
    refresh_cadence: Optional[str]
    event_time_field: str
    availability_time_field: str
    requested_as_of: Optional[str]
    latest_event_time: Optional[str]
    latest_available_time: Optional[str]
    coverage_start: Optional[str]
    coverage_end: Optional[str]
    records_read: Optional[int]
    records_after_scope: Optional[int]
    coverage_status: str  # FULL | PARTIAL | EMPTY | NOT_LOADED
    quality_status: str   # OK | QUALITY_FAILED | NOT_LOADED
    access_classification: str
    authorized: bool
    transformations: List[str] = field(default_factory=list)


@dataclass
class AlignmentEntry:
    source_id: str
    target_grain: str
    calendar: str
    aggregation: str
    join_keys: List[str]
    availability_rule: str
    period_completeness_rule: str
    alignment_status: str   # ALIGNED | NOT_LOADED | NOT_REQUIRED
    limitations: List[str] = field(default_factory=list)


@dataclass
class LineageEntry:
    claim: str
    source_id: str
    contract_version: Optional[str]
    query_identifier: Optional[str]
    row_or_period_reference: Optional[str]
    analytical_method: Optional[str]
    claim_type: str
    access_classification: str


@dataclass
class ReconciliationEvidence:
    status: str   # NOT_APPLICABLE | NOT_AVAILABLE_FOR_PERIOD | AGREED | DRIFT | CONTRADICTED
    applicable: bool
    primary_source: Optional[str]
    comparison_source: Optional[str]
    metric: Optional[str]
    unit: Optional[str]
    scope: Optional[Dict[str, str]]
    primary_period: Optional[str]
    comparison_period: Optional[str]
    primary_value: Optional[float]
    comparison_value: Optional[float]
    absolute_gap: Optional[float]
    gap_percent: Optional[float]
    tolerance: Optional[float]
    comparison_basis: Optional[str]
    blocking: bool
    reason: Optional[str]
    quality_status: Optional[str]


@dataclass
class SourceReadiness:
    status: str  # READY | PARTIAL | STALE | MISSING | QUALITY_FAILED
    required_sources: List[str]
    available_sources: List[str]
    limitations: List[str] = field(default_factory=list)


class SourceEvidenceBuilder:
    """Build a structured evidence payload from catalog metadata, runtime frames,
    and the reconciliation result already computed by the pipeline."""

    _DISPLAY_NAMES = {
        "sales_daily": "Daily Sales (sales_daily)",
        "marketing_weekly": "Weekly Marketing (marketing_weekly)",
        "finance_monthly": "Monthly Finance (finance_monthly)",
    }
    _ACCESS = {
        "sales_daily": "internal",
        "marketing_weekly": "internal",
        "finance_monthly": "restricted",
    }

    def build(
        self,
        *,
        result: Dict[str, Any],
        scope: Dict[str, Any],
        sales_frame: Optional[pd.DataFrame] = None,
        marketing_frame: Optional[pd.DataFrame] = None,
        finance_frame: Optional[pd.DataFrame] = None,
        sales_path: Optional[str] = None,
        marketing_path: Optional[str] = None,
        finance_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a fully-populated source evidence payload."""
        kpi_id = result.get("kpi_id", "")
        as_of = result.get("as_of")
        verdict = result.get("verdict", "")
        authorized = verdict != "ACCESS_DENIED"
        dimension_slice = {k: v for k, v in scope.items()
                           if k in ("region", "category")}
        target_date = result.get("target_date") or scope.get("target_date")

        # --- Determine which sources are required for this KPI ----------
        # Required sources are derived from contract semantics, not from path
        # existence.  marketing_weekly is required iff a driver references it;
        # finance_monthly is required iff reconciliation is configured (not
        # merely NOT_APPLICABLE).  Paths are used only for file_identifier.
        contract_recon = result.get("reconciliation_verdict") or {}
        recon_status = contract_recon.get("status", "NOT_APPLICABLE")
        has_reconciliation = recon_status not in ("NOT_APPLICABLE", None)

        # marketing is required only when it was actually loaded for the run
        # (caller passes marketing_frame only when a driver used it)
        uses_marketing = marketing_frame is not None
        # finance is required only when reconciliation is configured (not NA)
        uses_finance = has_reconciliation or finance_frame is not None

        required = ["sales_daily"]
        if uses_marketing:
            required.append("marketing_weekly")
        if uses_finance:
            required.append("finance_monthly")

        sources: List[SourceEntry] = []
        alignment: List[AlignmentEntry] = []
        available_sources: List[str] = []
        limitations: List[str] = []

        # ----- sales_daily ------------------------------------------------
        sales_entry = self._build_sales_entry(
            frame=sales_frame if authorized else None,
            file_path=sales_path,
            as_of=as_of,
            target_date=target_date,
            dimension_slice=dimension_slice if authorized else {},
            authorized=authorized,
        )
        sources.append(sales_entry)
        if sales_entry.coverage_status not in ("EMPTY", "NOT_LOADED"):
            available_sources.append("sales_daily")
        if sales_entry.coverage_status == "PARTIAL":
            limitations.append("Sales daily coverage is partial for the requested scope.")
        if not authorized:
            limitations.append("Source inventory is not available for an unauthorized scope.")

        # ----- marketing_weekly -------------------------------------------
        if "marketing_weekly" in required:
            mkt_entry = self._build_marketing_entry(
                frame=marketing_frame if authorized else None,
                file_path=marketing_path,
                as_of=as_of,
                target_date=target_date,
                dimension_slice=dimension_slice if authorized else {},
                authorized=authorized,
            )
            sources.append(mkt_entry)
            if mkt_entry.coverage_status not in ("EMPTY", "NOT_LOADED"):
                available_sources.append("marketing_weekly")
            alignment.append(self._marketing_alignment(mkt_entry))
            if mkt_entry.coverage_status == "NOT_LOADED":
                limitations.append("Weekly marketing data was not available for this run.")
        elif marketing_path:
            # path was supplied but marketing was not required by contract –
            # record it as informational NOT_REQUIRED alignment
            alignment.append(AlignmentEntry(
                source_id="marketing_weekly",
                target_grain="daily",
                calendar="ISO week (Monday–Sunday)",
                aggregation="N/A",
                join_keys=[],
                availability_rule="N/A",
                period_completeness_rule="N/A",
                alignment_status="NOT_REQUIRED",
                limitations=["No driver in the KPI contract references marketing_weekly."],
            ))

        # ----- finance_monthly --------------------------------------------
        if "finance_monthly" in required:
            fin_entry = self._build_finance_entry(
                frame=finance_frame if authorized else None,
                file_path=finance_path,
                as_of=as_of,
                target_date=target_date,
                dimension_slice=dimension_slice if authorized else {},
                authorized=authorized,
            )
            sources.append(fin_entry)
            if fin_entry.coverage_status not in ("EMPTY", "NOT_LOADED"):
                available_sources.append("finance_monthly")
            alignment.append(self._finance_alignment(fin_entry))
            if fin_entry.coverage_status == "NOT_LOADED":
                limitations.append("Monthly finance data was not loaded; independent comparison unavailable.")
            elif fin_entry.coverage_status == "EMPTY":
                limitations.append("Monthly finance has no rows for the requested as-of cutoff.")

        # ----- source readiness (staleness check) ------------------------
        # STALE: primary source's latest_available_time is more than SLA days
        # behind the saved as-of cutoff.
        _stale = False
        if authorized and as_of:
            SLA_DAYS = {"sales_daily": 2, "marketing_weekly": 5, "finance_monthly": 10}
            cutoff_ts = pd.Timestamp(as_of)
            for src in sources:
                if src.latest_available_time:
                    try:
                        lat_ts = pd.Timestamp(src.latest_available_time)
                        sla = SLA_DAYS.get(src.source_id, 2)
                        if (cutoff_ts - lat_ts).days > sla:
                            _stale = True
                            limitations.append(
                                f"{src.source_id} is STALE: latest availability "
                                f"{src.latest_available_time} is more than {sla} days "
                                f"behind the as-of cutoff {as_of}."
                            )
                    except Exception:
                        pass

        # Reconciliation quality flag also drives QUALITY_FAILED readiness
        recon_quality_flag = (contract_recon.get("details") or {}).get("quality_flag")
        _quality_failed = bool(recon_quality_flag == "QUALITY_FAILED")

        readiness_status = self._compute_readiness_status(
            sources, authorized, limitations, stale=_stale, quality_failed=_quality_failed
        )
        source_readiness = SourceReadiness(
            status=readiness_status,
            required_sources=required,
            available_sources=available_sources,
            limitations=limitations,
        )

        # ----- reconciliation --------------------------------------------
        recon_evidence = self._build_reconciliation_evidence(
            recon_result=contract_recon,
            result=result,
            scope=dimension_slice,
            authorized=authorized,
        )

        # ----- lineage ---------------------------------------------------
        lineage = self._build_lineage(result, authorized)

        return {
            "run_id": result.get("run_id"),
            "kpi_id": kpi_id,
            "target_date": target_date,
            "as_of": as_of,
            "scope": dimension_slice,
            "source_readiness": asdict(source_readiness),
            "sources": [asdict(s) for s in sources],
            "alignment": [asdict(a) for a in alignment],
            "reconciliation": asdict(recon_evidence),
            "lineage": [asdict(le) for le in lineage],
            "narrative_claim_evidence": result.get("narrative_claims") if authorized else [],
            "limitations": limitations,
        }

    def _safe_file_identifier(self, file_path: Optional[str]) -> Optional[str]:
        if not file_path:
            return None
        p = Path(file_path)
        parts = p.parts
        if "demo_fixtures" in parts:
            idx = parts.index("demo_fixtures")
            return "/".join(parts[idx:])
        return p.name

    def _build_sales_entry(
        self,
        frame: Optional[pd.DataFrame],
        file_path: Optional[str],
        as_of: Optional[str],
        target_date: Optional[str],
        dimension_slice: Dict[str, str],
        authorized: bool,
    ) -> SourceEntry:
        if not authorized or frame is None:
            return SourceEntry(
                source_id="sales_daily",
                display_name=self._DISPLAY_NAMES["sales_daily"],
                source_role=ROLE_MAP["sales_daily"],
                file_identifier=self._safe_file_identifier(file_path),
                native_grain="daily",
                refresh_cadence=CADENCE_MAP["daily"],
                event_time_field="date",
                availability_time_field="available_at",
                requested_as_of=as_of,
                latest_event_time=None,
                latest_available_time=None,
                coverage_start=None,
                coverage_end=None,
                records_read=None,
                records_after_scope=None,
                coverage_status="NOT_LOADED",
                quality_status="NOT_LOADED",
                access_classification=self._ACCESS["sales_daily"] if authorized else "restricted",
                authorized=authorized,
                transformations=["as_of cutoff filter", "dimension slice"] if authorized else [],
            )

        scoped = self._scope_frame(frame, dimension_slice)
        records_read = len(frame)
        records_after_scope = len(scoped)
        latest_event = scoped["date"].max() if not scoped.empty else None
        latest_available = (
            scoped["available_at"].max() if "available_at" in scoped.columns and not scoped.empty
            else None
        )
        coverage_start = scoped["date"].min().date().isoformat() if not scoped.empty else None
        coverage_end = scoped["date"].max().date().isoformat() if not scoped.empty else None
        coverage_status = self._daily_coverage_status(scoped, "date", target_date)

        return SourceEntry(
            source_id="sales_daily",
            display_name=self._DISPLAY_NAMES["sales_daily"],
            source_role=ROLE_MAP["sales_daily"],
            file_identifier=self._safe_file_identifier(file_path),
            native_grain="daily",
            refresh_cadence=CADENCE_MAP["daily"],
            event_time_field="date",
            availability_time_field="available_at",
            requested_as_of=as_of,
            latest_event_time=str(latest_event.date()) if latest_event is not None and not pd.isna(latest_event) else None,
            latest_available_time=str(latest_available) if latest_available is not None and not pd.isna(latest_available) else None,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            records_read=records_read,
            records_after_scope=records_after_scope,
            coverage_status=coverage_status,
            quality_status="OK",
            access_classification=self._ACCESS["sales_daily"],
            authorized=True,
            transformations=["as_of cutoff filter", "dimension slice", "available_at filter applied"],
        )

    def _build_marketing_entry(
        self,
        frame: Optional[pd.DataFrame],
        file_path: Optional[str],
        as_of: Optional[str],
        target_date: Optional[str],
        dimension_slice: Dict[str, str],
        authorized: bool,
    ) -> SourceEntry:
        if not authorized or frame is None:
            return SourceEntry(
                source_id="marketing_weekly",
                display_name=self._DISPLAY_NAMES["marketing_weekly"],
                source_role=ROLE_MAP["marketing_weekly"],
                file_identifier=self._safe_file_identifier(file_path),
                native_grain="weekly",
                refresh_cadence=CADENCE_MAP["weekly"],
                event_time_field="week_start",
                availability_time_field="available_at",
                requested_as_of=as_of,
                latest_event_time=None,
                latest_available_time=None,
                coverage_start=None,
                coverage_end=None,
                records_read=None,
                records_after_scope=None,
                coverage_status="NOT_LOADED",
                quality_status="NOT_LOADED",
                access_classification=self._ACCESS["marketing_weekly"] if authorized else "restricted",
                authorized=authorized,
                transformations=[],
            )

        # Frame may be the expanded daily version; estimate weekly rows
        # by looking at unique week_start values if available
        scoped_raw = self._scope_frame(frame, dimension_slice)
        records_read = len(frame)
        records_after_scope = len(scoped_raw)

        # Date range using native date column (expanded to daily by normalizer)
        date_col = "date" if "date" in scoped_raw.columns else "week_start"
        latest_event = scoped_raw[date_col].max() if not scoped_raw.empty else None
        latest_available = (
            scoped_raw["available_at"].max()
            if "available_at" in scoped_raw.columns and not scoped_raw.empty
            else None
        )
        coverage_start = scoped_raw[date_col].min().date().isoformat() if not scoped_raw.empty else None
        coverage_end = scoped_raw[date_col].max().date().isoformat() if not scoped_raw.empty else None
        coverage_status = self._weekly_coverage_status(scoped_raw, date_col, target_date)

        return SourceEntry(
            source_id="marketing_weekly",
            display_name=self._DISPLAY_NAMES["marketing_weekly"],
            source_role=ROLE_MAP["marketing_weekly"],
            file_identifier=self._safe_file_identifier(file_path),
            native_grain="weekly",
            refresh_cadence=CADENCE_MAP["weekly"],
            event_time_field="week_start",
            availability_time_field="available_at",
            requested_as_of=as_of,
            latest_event_time=str(latest_event.date()) if latest_event is not None and not pd.isna(latest_event) else None,
            latest_available_time=str(latest_available) if latest_available is not None and not pd.isna(latest_available) else None,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            records_read=records_read,
            records_after_scope=records_after_scope,
            coverage_status=coverage_status,
            quality_status="OK",
            access_classification=self._ACCESS["marketing_weekly"],
            authorized=True,
            transformations=[
                "available_at cutoff filter",
                "weekly rows expanded to daily calendar for join alignment",
                "native values preserved at weekly grain (not divided by 7)",
            ],
        )

    def _build_finance_entry(
        self,
        frame: Optional[pd.DataFrame],
        file_path: Optional[str],
        as_of: Optional[str],
        target_date: Optional[str],
        dimension_slice: Dict[str, str],
        authorized: bool,
    ) -> SourceEntry:
        if not authorized or frame is None:
            return SourceEntry(
                source_id="finance_monthly",
                display_name=self._DISPLAY_NAMES["finance_monthly"],
                source_role=ROLE_MAP["finance_monthly"],
                file_identifier=self._safe_file_identifier(file_path),
                native_grain="monthly",
                refresh_cadence=CADENCE_MAP["monthly"],
                event_time_field="month_start",
                availability_time_field="available_at",
                requested_as_of=as_of,
                latest_event_time=None,
                latest_available_time=None,
                coverage_start=None,
                coverage_end=None,
                records_read=None,
                records_after_scope=None,
                coverage_status="NOT_LOADED",
                quality_status="NOT_LOADED",
                access_classification=self._ACCESS["finance_monthly"] if authorized else "restricted",
                authorized=authorized,
                transformations=[],
            )

        scoped = self._scope_frame(frame, dimension_slice)
        records_read = len(frame)
        records_after_scope = len(scoped)

        date_col = "date" if "date" in scoped.columns else "month_start"
        latest_event = scoped["month_end"].max() if "month_end" in scoped.columns and not scoped.empty else None
        latest_available = (
            scoped["available_at"].max()
            if "available_at" in scoped.columns and not scoped.empty
            else None
        )
        coverage_start = (
            scoped[date_col].min().date().isoformat()
            if date_col in scoped.columns and not scoped.empty else None
        )
        coverage_end = (
            scoped["month_end"].max().date().isoformat()
            if "month_end" in scoped.columns and not scoped.empty else None
        )
        coverage_status = self._monthly_coverage_status(scoped, target_date)

        return SourceEntry(
            source_id="finance_monthly",
            display_name=self._DISPLAY_NAMES["finance_monthly"],
            source_role=ROLE_MAP["finance_monthly"],
            file_identifier=self._safe_file_identifier(file_path),
            native_grain="monthly",
            refresh_cadence=CADENCE_MAP["monthly"],
            event_time_field="month_start",
            availability_time_field="available_at",
            requested_as_of=as_of,
            latest_event_time=str(latest_event.date()) if latest_event is not None and not pd.isna(latest_event) else None,
            latest_available_time=str(latest_available) if latest_available is not None and not pd.isna(latest_available) else None,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            records_read=records_read,
            records_after_scope=records_after_scope,
            coverage_status=coverage_status,
            quality_status="OK",
            access_classification=self._ACCESS["finance_monthly"],
            authorized=True,
            transformations=[
                "closes_at used as available_at (provisional rows excluded)",
                "available_at cutoff filter applied",
                "latest revision selected per period/slice",
            ],
        )

    @staticmethod
    def _scope_frame(frame: pd.DataFrame, dimension_slice: Dict[str, str]) -> pd.DataFrame:
        result = frame
        for key, value in (dimension_slice or {}).items():
            if key in result.columns:
                result = result[result[key] == value]
        return result

    @staticmethod
    def _daily_coverage_status(frame: pd.DataFrame, date_col: str, target_date: Optional[str]) -> str:
        if frame.empty:
            return "EMPTY"
        if not target_date or date_col not in frame.columns:
            return "FULL"
        dates = pd.to_datetime(frame[date_col], errors="coerce").dt.normalize()
        return "FULL" if pd.Timestamp(target_date).normalize() in set(dates.dropna()) else "PARTIAL"

    @staticmethod
    def _weekly_coverage_status(frame: pd.DataFrame, date_col: str, target_date: Optional[str]) -> str:
        if frame.empty:
            return "EMPTY"
        if not target_date or date_col not in frame.columns:
            return "FULL"
        target = pd.Timestamp(target_date).normalize()
        starts = pd.to_datetime(frame[date_col], errors="coerce").dt.normalize().dropna()
        return "FULL" if any(start <= target <= start + pd.Timedelta(days=6) for start in starts) else "PARTIAL"

    @staticmethod
    def _monthly_coverage_status(frame: pd.DataFrame, target_date: Optional[str]) -> str:
        if frame.empty:
            return "EMPTY"
        if not target_date:
            return "FULL"
        target = pd.Timestamp(target_date).normalize()
        if "month_end" in frame.columns:
            ends = pd.to_datetime(frame["month_end"], errors="coerce").dt.normalize()
            return "FULL" if target in set(ends.dropna()) else "PARTIAL"
        if "month_start" in frame.columns:
            starts = pd.to_datetime(frame["month_start"], errors="coerce").dt.to_period("M")
            return "FULL" if target.to_period("M") in set(starts.dropna()) else "PARTIAL"
        return "PARTIAL"

    @staticmethod
    def _marketing_alignment(mkt: SourceEntry) -> AlignmentEntry:
        # alignment_status must be ALIGNED | NOT_LOADED | NOT_REQUIRED
        if mkt.coverage_status == "NOT_LOADED":
            alignment_status = "NOT_LOADED"
        elif mkt.coverage_status == "EMPTY":
            alignment_status = "NOT_LOADED"  # loaded file but zero rows after cutoff
        else:
            alignment_status = "ALIGNED"
        return AlignmentEntry(
            source_id="marketing_weekly",
            target_grain="daily",
            calendar="ISO week (Monday–Sunday)",
            aggregation="weekly report repeated across 7 calendar days; values are not divided",
            join_keys=["date", "region", "category"],
            availability_rule="available_at <= as_of cutoff",
            period_completeness_rule="partial weeks allowed; week_end must be 6 days after week_start",
            alignment_status=alignment_status,
            limitations=[] if alignment_status == "ALIGNED" else [
                "Marketing data not loaded; driver columns will be absent"
                if mkt.coverage_status == "NOT_LOADED" else
                "No marketing rows available for the requested scope and cutoff"
            ],
        )

    @staticmethod
    def _finance_alignment(fin: SourceEntry) -> AlignmentEntry:
        # alignment_status must be ALIGNED | NOT_LOADED | NOT_REQUIRED
        if fin.coverage_status in ("NOT_LOADED", "EMPTY"):
            alignment_status = "NOT_LOADED"
        else:
            alignment_status = "ALIGNED"
        limitations = []
        if fin.coverage_status == "EMPTY":
            limitations.append(
                "Finance has no closed-period rows available at the requested as-of cutoff; "
                "independent comparison will return NOT_AVAILABLE_FOR_PERIOD."
            )
        elif fin.coverage_status == "NOT_LOADED":
            limitations.append(
                "Finance source was not loaded; independent comparison is not possible."
            )
        return AlignmentEntry(
            source_id="finance_monthly",
            target_grain="monthly",
            calendar="calendar month (day 1 to last day of month)",
            aggregation="monthly total compared against daily sum for matching period",
            join_keys=["region", "category", "month_end"],
            availability_rule="available_at (= closes_at) <= as_of cutoff; provisional rows excluded",
            period_completeness_rule="closed_period mode: finance period must end on requested target_date",
            alignment_status=alignment_status,
            limitations=limitations,
        )

    @staticmethod
    def _compute_readiness_status(
        sources: List[SourceEntry],
        authorized: bool,
        limitations: List[str],
        stale: bool = False,
        quality_failed: bool = False,
    ) -> str:
        if not authorized:
            return "MISSING"
        # Source-level quality failure
        if any(s.quality_status == "QUALITY_FAILED" for s in sources) or quality_failed:
            return "QUALITY_FAILED"
        # Find required (required == mandatory for diagnostic completeness)
        # Primary source (sales_daily) not loaded = MISSING
        primary = next((s for s in sources if s.source_id == "sales_daily"), None)
        if primary is None or primary.coverage_status in ("NOT_LOADED", "EMPTY"):
            return "MISSING"
        # Any other required source not loaded/empty = PARTIAL
        non_primary = [s for s in sources if s.source_id != "sales_daily"]
        statuses = {s.coverage_status for s in non_primary}
        if "NOT_LOADED" in statuses or "EMPTY" in statuses:
            return "PARTIAL"
        # Primary is partial = PARTIAL
        if primary.coverage_status == "PARTIAL":
            return "PARTIAL"
        if stale:
            return "STALE"
        return "READY"

    @staticmethod
    def _build_reconciliation_evidence(
        recon_result: Dict[str, Any],
        result: Dict[str, Any],
        scope: Dict[str, str],
        authorized: bool,
    ) -> ReconciliationEvidence:
        """Convert the pipeline's ReconciliationVerdict asdict into the structured evidence type.

        NOT_APPLICABLE is explicitly non-blocking and informational.
        """
        if not authorized:
            return ReconciliationEvidence(
                status="NOT_APPLICABLE",
                applicable=False,
                primary_source=None,
                comparison_source=None,
                metric=None,
                unit=None,
                scope=None,
                primary_period=None,
                comparison_period=None,
                primary_value=None,
                comparison_value=None,
                absolute_gap=None,
                gap_percent=None,
                tolerance=None,
                comparison_basis=None,
                blocking=False,
                reason="Scope is unauthorized; no evidence is shown.",
                quality_status=None,
            )

        status = recon_result.get("status", "NOT_APPLICABLE")
        details = recon_result.get("details") or {}
        gap_pct = recon_result.get("gap_pct")
        tolerance = recon_result.get("tolerance_used")
        applicable = status not in ("NOT_APPLICABLE",)
        blocking = status == "CONTRADICTED"

        sales_total = details.get("sales_mtd_total")
        finance_total = details.get("finance_total")
        absolute_gap = (
            round(abs(sales_total - finance_total), 2)
            if sales_total is not None and finance_total is not None
            else None
        )
        kpi_id = result.get("kpi_id")
        reason = details.get("reason")
        quality_flag = details.get("quality_flag")

        # NOT_APPLICABLE: provide a clear, human-readable explanation
        if status == "NOT_APPLICABLE":
            reason = reason or f"No independent finance comparison is configured for {kpi_id}. This is informational and non-blocking."
            applicable = False

        return ReconciliationEvidence(
            status=status,
            applicable=applicable,
            primary_source="sales_daily" if applicable else None,
            comparison_source="finance_monthly" if applicable else None,
            metric=kpi_id if applicable else None,
            unit=result.get("segment", {}).get("unit") or "INR" if applicable else None,
            scope=scope or None,
            primary_period=details.get("year_month"),
            comparison_period=details.get("year_month"),
            primary_value=sales_total,
            comparison_value=finance_total,
            absolute_gap=absolute_gap,
            gap_percent=gap_pct,
            tolerance=tolerance,
            comparison_basis=details.get("mode"),
            blocking=blocking,
            reason=reason,
            quality_status=quality_flag,
        )

    @staticmethod
    def _build_lineage(result: Dict[str, Any], authorized: bool) -> List[LineageEntry]:
        if not authorized:
            return []
        entries: List[LineageEntry] = []
        for claim in result.get("narrative_claims") or []:
            for path in claim.get("evidence_paths") or []:
                entries.append(LineageEntry(
                    claim=claim.get("text") or "",
                    source_id=claim.get("source_id") or "sales_daily",
                    contract_version=str(result.get("contract_version")) if result.get("contract_version") else None,
                    query_identifier=path,
                    row_or_period_reference=claim.get("row_reference"),
                    analytical_method=result.get("narrative_method"),
                    claim_type=claim.get("claim_type") or "observation",
                    access_classification="internal",
                ))
        if not entries and result.get("kpi_id"):
            segment = result.get("segment") or result.get("treated_slice") or {}
            reference = ", ".join(
                str(value) for value in (
                    result.get("target_date") or result.get("post_end"),
                    segment.get("region"),
                    segment.get("category"),
                ) if value
            ) or None
            entries.append(LineageEntry(
                claim=f"Observed movement for {result['kpi_id']}",
                source_id="sales_daily",
                contract_version=str(result.get("contract_version")) if result.get("contract_version") else None,
                query_identifier=None,
                row_or_period_reference=reference,
                analytical_method="governed KPI aggregation and prior-history comparison",
                claim_type="observation",
                access_classification="internal",
            ))
            reconciliation = result.get("reconciliation_verdict") or {}
            if reconciliation.get("status") not in (None, "NOT_APPLICABLE"):
                details = reconciliation.get("details") or {}
                entries.append(LineageEntry(
                    claim=f"Independent reconciliation: {reconciliation.get('status')}",
                    source_id="finance_monthly",
                    contract_version=str(result.get("contract_version")) if result.get("contract_version") else None,
                    query_identifier=None,
                    row_or_period_reference=details.get("year_month"),
                    analytical_method=details.get("mode") or "independent source comparison",
                    claim_type="reconciliation",
                    access_classification="restricted",
                ))
        return entries
