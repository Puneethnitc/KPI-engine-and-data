from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class MaterialityThresholds:
    z_threshold: float
    abs_threshold: float  # measured in the KPI contract's unit

@dataclass
class KPIContract:
    kpi_id: str
    formula: str
    unit: str
    grain: str
    source: str
    dimensions: List[str]
    materiality: MaterialityThresholds
    seasonal_period: int
    min_history_periods: int
    owner: str
    access_tags: List[str]
    version: int
    definition: str
    value_column: str
    aggregation: str
    decomposition: Dict[str, str]
    reconciliation: Optional[Dict[str, str]]
    candidate_drivers: List[Dict[str, str]]
    numerator_column: Optional[str] = None
    denominator_column: Optional[str] = None
    weight_column: Optional[str] = None

    def validate_grain(self) -> None:
        """Enforces that grain-specific thresholds are non-zero and declared."""
        if self.seasonal_period <= 0:
            raise ValueError(f"KPI {self.kpi_id}: seasonal_period must be > 0.")
        if self.materiality.abs_threshold <= 0:
            raise ValueError(f"KPI {self.kpi_id}: abs_threshold must be > 0.")
        if self.materiality.z_threshold <= 0:
            raise ValueError(f"KPI {self.kpi_id}: z_threshold must be > 0.")
        if self.version < 1 or not self.definition.strip():
            raise ValueError(f"KPI {self.kpi_id}: version and definition are required.")
        if not self.value_column or not self.source or not self.unit or not self.formula:
            raise ValueError(f"KPI {self.kpi_id}: source, value_column, unit and formula are required.")
        if self.grain not in {"daily", "weekly", "monthly"}:
            raise ValueError(f"KPI {self.kpi_id}: unsupported grain {self.grain}.")
        if self.aggregation not in {"sum", "mean", "weighted_mean", "ratio_of_sums"}:
            raise ValueError(f"KPI {self.kpi_id}: unsupported aggregation {self.aggregation}.")
        if self.aggregation == "ratio_of_sums":
            if not self.numerator_column or not self.denominator_column:
                raise ValueError(f"KPI {self.kpi_id}: ratio requires numerator and denominator columns.")
            if self.numerator_column == self.denominator_column:
                raise ValueError(f"KPI {self.kpi_id}: ratio numerator and denominator must differ.")
            if self.decomposition:
                raise ValueError(f"KPI {self.kpi_id}: ratio decomposition is not supported.")
        elif self.numerator_column or self.denominator_column:
            raise ValueError(f"KPI {self.kpi_id}: numerator/denominator only apply to ratio_of_sums.")
        if self.aggregation == "weighted_mean" and not self.weight_column:
            raise ValueError(f"KPI {self.kpi_id}: weighted_mean requires weight_column.")
        if self.aggregation != "weighted_mean" and self.weight_column:
            raise ValueError(f"KPI {self.kpi_id}: weight_column only applies to weighted_mean.")
        if self.decomposition and set(self.decomposition) != {"quantity_column", "reference_rate_column"}:
            raise ValueError(f"KPI {self.kpi_id}: decomposition needs quantity_column and reference_rate_column.")
        if self.decomposition and self.aggregation != "sum":
            raise ValueError(f"KPI {self.kpi_id}: decomposition requires sum aggregation.")
        if any(not value for value in self.decomposition.values()):
            raise ValueError(f"KPI {self.kpi_id}: decomposition columns cannot be empty.")
        if self.reconciliation is not None:
            if self.aggregation != "sum":
                raise ValueError(f"KPI {self.kpi_id}: reconciliation requires sum aggregation.")
            if not isinstance(self.reconciliation, dict) or not self.reconciliation.get("finance_column"):
                raise ValueError(f"KPI {self.kpi_id}: reconciliation requires finance_column.")
            if self.reconciliation.get("comparison", "same_slice_closed_month_only") != "same_slice_closed_month_only":
                raise ValueError(f"KPI {self.kpi_id}: unsupported reconciliation comparison.")
            tolerance = self.reconciliation.get("tolerance_pct", 3.5)
            multiple = self.reconciliation.get("contradiction_multiple", 2.5)
            if not isinstance(tolerance, (int, float)) or not 0 < tolerance < 100:
                raise ValueError(f"KPI {self.kpi_id}: reconciliation tolerance_pct must be between 0 and 100.")
            if not isinstance(multiple, (int, float)) or multiple <= 1:
                raise ValueError(f"KPI {self.kpi_id}: contradiction_multiple must exceed 1.")
        if not self.dimensions or len(self.dimensions) != len(set(self.dimensions)):
            raise ValueError(f"KPI {self.kpi_id}: dimensions must be nonempty and unique.")
        driver_ids = [driver.get("id") for driver in self.candidate_drivers]
        if len(driver_ids) != len(set(driver_ids)):
            raise ValueError(f"KPI {self.kpi_id}: duplicate candidate driver id.")
        for driver in self.candidate_drivers:
            if not all(driver.get(field) for field in ("id", "column", "source", "grain")):
                raise ValueError(f"KPI {self.kpi_id}: each candidate driver needs id, column, source, grain.")
            if driver.get("aggregation", "mean") not in {"mean", "sum"}:
                raise ValueError(f"KPI {self.kpi_id}: candidate driver aggregation must be mean or sum.")
            if driver["grain"] not in {"daily", "weekly"}:
                raise ValueError(f"KPI {self.kpi_id}: unsupported candidate driver grain.")
