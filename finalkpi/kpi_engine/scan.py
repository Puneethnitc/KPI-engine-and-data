# IMPLEMENTATION HANDOFF — movement scanning and prioritisation
# Current: a fast, detection-only pass across every authorised (kpi, slice)
# for one date. No attribution, no reconciliation, no narrative -- purely
# "what moved and how much does it matter", for the Overview "Top movements
# today" feed and any future cross-slice alerting.
# Next: share a single prepared-request cache with KPIEnginePipeline instead
# of reloading sales_daily per call; add a real value_column-vs-kpi_id source
# renaming path if a scanned KPI ever needs one (the five bundled KPIs don't).
# Check: only authorised (region, category) slices are ever scanned or
# returned; a movement's priority is comparable across differently-united
# KPIs via kpi_weight, never a raw unit-mismatched delta.

"""MovementScanner: fast movement-only detection across every authorised slice."""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from kpi_engine.access import AccessController
from kpi_engine.contracts import KPIRegistry
from kpi_engine.contracts.metrics import prepare_metric_request
from kpi_engine.contracts.models import KPIContract
from kpi_engine.detection.models import MovementAssessment
from kpi_engine.detection.robust import RobustBaselineDetector
from kpi_engine.normalize import DataNormalizer


def movement_priority(assessment: MovementAssessment, contract: KPIContract) -> float:
    """priority = |delta| x min(|score| / z_threshold, 3) x kpi_weight (F-D4).

    Kept in sync with backend/service.py's movement_priority, which computes
    the same formula from a serialized movement/contract_snapshot pair for
    callers that only have the projected API payload, not live objects.
    """
    if assessment.delta is None or assessment.robust_score is None:
        return 0.0
    z_threshold = contract.materiality.z_threshold or 1.0
    return abs(assessment.delta) * min(abs(assessment.robust_score) / z_threshold, 3.0) * contract.kpi_weight


@dataclass(frozen=True)
class Movement:
    kpi_id: str
    region: Optional[str]
    category: Optional[str]
    is_material: bool
    priority: float
    delta: Optional[float]
    rel_delta: Optional[float]
    actual_value: Optional[float]
    expected_value: Optional[float]
    detector_agreement: str
    status: str


class MovementScanner:
    """Detection-only fast path: scan every authorised (kpi, slice) for a date.

    Never runs driver ranking, reconciliation or narrative -- callers that
    need those should follow up with KPIEnginePipeline.run_diagnosis on the
    specific (kpi, slice) a scanned movement points at.
    """

    def __init__(self, registry_dir: str, access_csv: str, source_schema_path: Optional[str] = None):
        self.registry = KPIRegistry(registry_dir)
        self.access_controller = AccessController(access_csv)
        source_schemas: Dict[str, Dict[str, str]] = {}
        if source_schema_path:
            import yaml
            with open(source_schema_path, "r", encoding="utf-8") as handle:
                spec = yaml.safe_load(handle)
            if isinstance(spec, dict):
                source_schemas = spec
        self.normalizer = DataNormalizer(source_schemas)
        # Fast path (F-D4): the robust detector alone, not the full
        # robust+MSTL ensemble. Fitting a seasonal forecast per (kpi, slice)
        # made a company-wide scan take several seconds; a scan's job is
        # triage/prioritisation, not the dual-detector confirmation a full
        # diagnose_scope call already does for whichever slice the analyst
        # follows up on.
        self.detector = RobustBaselineDetector()

    def _authorized_slices(self, persona: str, daily: pd.DataFrame) -> List[Optional[Dict[str, str]]]:
        """Every authorised (region, category) slice actually present in the
        data, plus the company-wide rollup (None -> no dimension_slice) when
        the persona is entitled to see it. AccessController is consulted per
        candidate slice, never inferred from the access_control.csv row
        shape alone, so a category-restricted role only gets its own rows.
        """
        if daily.empty:
            return []
        real_slices = (
            daily[["region", "category"]].drop_duplicates().to_dict("records")
            if {"region", "category"} <= set(daily.columns) else []
        )
        candidates: List[Optional[Dict[str, str]]] = [None, *real_slices]
        authorized = []
        for candidate in candidates:
            if self.access_controller.check(persona, candidate).allowed:
                authorized.append(candidate)
        return authorized

    def scan(
        self,
        date: str,
        persona: str,
        kpis: Sequence[str],
        sales_csv: str,
        as_of: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        target = pd.Timestamp(date).normalize()
        cutoff = pd.Timestamp(as_of) if as_of else target + pd.Timedelta(days=1, hours=12)
        daily, _ = self.normalizer.align_sources(sales_csv, None, None, as_of=cutoff)
        if daily.empty:
            return []
        slices = self._authorized_slices(persona, daily)
        movements: List[Movement] = []
        for kpi_id in kpis:
            try:
                contract = self.registry.get(kpi_id)
            except KeyError:
                continue
            if contract.source != "sales_daily" or contract.grain != "daily":
                continue
            frame = daily
            if contract.aggregation == "sum" and contract.value_column != kpi_id:
                if contract.value_column not in frame.columns:
                    continue
                frame = frame.copy()
                frame[kpi_id] = frame[contract.value_column]
            for dimension_slice in slices:
                scoped = frame
                for key, value in (dimension_slice or {}).items():
                    scoped = scoped[scoped[key] == value]
                if scoped.empty:
                    continue
                prepared = prepare_metric_request(
                    scoped, contract, target, dimension_slice=dimension_slice, as_of=cutoff,
                )
                assessment = self.detector.evaluate_movement(
                    scoped, contract, target.date().isoformat(), metric_col=kpi_id,
                    comparison_plan=prepared.comparison,
                )
                if assessment.status != "OK":
                    continue
                movements.append(Movement(
                    kpi_id=kpi_id,
                    region=(dimension_slice or {}).get("region"),
                    category=(dimension_slice or {}).get("category"),
                    is_material=assessment.is_material,
                    priority=movement_priority(assessment, contract),
                    delta=assessment.delta,
                    rel_delta=assessment.rel_delta,
                    actual_value=assessment.actual_value,
                    expected_value=assessment.expected_value,
                    detector_agreement=assessment.detector_agreement,
                    status=assessment.status,
                ))
        movements.sort(key=lambda item: item.priority, reverse=True)
        return [asdict(item) for item in movements]
