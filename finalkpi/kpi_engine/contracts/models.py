# IMPLEMENTATION HANDOFF — semantic schema
# Current: dataclasses validate supported aggregation and component combinations.
# formula is required descriptive text, not the calculation execution path.
# Next: version a structured calculation spec plus comparison, coverage, source,
# reconciliation and analysis policies. Preserve old contracts through an adapter.
# Validate positive history, finite thresholds, field types, nested unknown keys,
# source/column existence and runnable capabilities before invoking the pipeline.
# Do not accept arbitrary Python or SQL in formula. See ../duckdb/README.md.
# Check: malformed policies fail with field-specific errors; adding a supported
# metric needs configuration only, and unsupported methods fail explicitly.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Business thresholds are already contractual; statistical constants such as
# MAD normalization belong to the method implementation, not every YAML file.
@dataclass
class MaterialityThresholds:
    z_threshold: float
    abs_threshold: float  # measured in the KPI contract's unit


@dataclass
class CalculationDefinition:
    """Structured, executable calculation metadata. The human formula remains descriptive."""

    operator: str
    value_column: Optional[str] = None
    numerator_column: Optional[str] = None
    denominator_column: Optional[str] = None
    weight_column: Optional[str] = None
    formula: str = ""
    description: str = ""

    @classmethod
    def from_mapping(cls, data: Optional[Dict[str, Any]]) -> Optional["CalculationDefinition"]:
        if not data:
            return None
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValueError("Calculation definition must be a mapping.")
        return cls(
            operator=str(data.get("operator") or data.get("aggregation") or "sum"),
            value_column=data.get("value_column"),
            numerator_column=data.get("numerator_column"),
            denominator_column=data.get("denominator_column"),
            weight_column=data.get("weight_column"),
            formula=data.get("formula") or "",
            description=data.get("description") or "",
        )

    def validate(self, kpi_id: str) -> None:
        if self.operator not in {"sum", "mean", "weighted_mean", "ratio_of_sums"}:
            raise ValueError(f"KPI {kpi_id}: unsupported aggregation {self.operator}.")
        if self.operator == "ratio_of_sums":
            if not self.numerator_column or not self.denominator_column:
                raise ValueError(f"KPI {kpi_id}: ratio requires numerator and denominator columns.")
            if self.numerator_column == self.denominator_column:
                raise ValueError(f"KPI {kpi_id}: ratio numerator and denominator must differ.")
        if self.operator == "weighted_mean" and not self.weight_column:
            raise ValueError(f"KPI {kpi_id}: weighted_mean requires weight_column.")


@dataclass
class MissingDataPolicy:
    null_policy: str = "reject"
    partial_group_policy: str = "reject"
    zero_is_valid: bool = True
    allow_empty: bool = False

    @classmethod
    def from_mapping(cls, data: Optional[Dict[str, Any]]) -> Optional["MissingDataPolicy"]:
        if not data:
            return None
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValueError("Missing data policy must be a mapping.")
        return cls(
            null_policy=str(data.get("null_policy", "reject")),
            partial_group_policy=str(data.get("partial_group_policy", "reject")),
            zero_is_valid=bool(data.get("zero_is_valid", True)),
            allow_empty=bool(data.get("allow_empty", False)),
        )


@dataclass
class AvailabilityPolicy:
    field: str = "available_at"
    cutoff_policy: str = "as_of"
    timezone: str = "UTC"
    revision_field: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: Optional[Dict[str, Any]]) -> Optional["AvailabilityPolicy"]:
        if not data:
            return None
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValueError("Availability policy must be a mapping.")
        return cls(
            field=str(data.get("field", "available_at")),
            cutoff_policy=str(data.get("cutoff_policy", "as_of")),
            timezone=str(data.get("timezone", "UTC")),
            revision_field=data.get("revision_field"),
        )


@dataclass
class ComparisonPolicy:
    period: str = "same_slice_closed_month_only"
    baseline_periods: List[str] = field(default_factory=list)
    weighting: str = "none"
    completeness: str = "required"
    config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Optional[Dict[str, Any]]) -> Optional["ComparisonPolicy"]:
        if not data:
            return None
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValueError("Comparison policy must be a mapping.")
        comparison = data.get("comparison", data.get("comparison_period", data.get("period", "same_slice_closed_month_only")))
        return cls(
            period=str(comparison or "same_slice_closed_month_only"),
            baseline_periods=list(data.get("baseline_periods") or data.get("baseline") or []),
            weighting=str(data.get("weighting", "none")),
            completeness=str(data.get("completeness", "required")),
            config=dict(data.get("config") or {}),
        )


@dataclass
class SourceFieldSpec:
    name: str
    field_type: str = "float"
    required: bool = True
    nullable: bool = False
    unit: Optional[str] = None
    description: str = ""

    @classmethod
    def from_mapping(cls, name: str, data: Any) -> "SourceFieldSpec":
        if isinstance(data, cls):
            return data
        if isinstance(data, str):
            return cls(name=name, field_type=data)
        if not isinstance(data, dict):
            raise ValueError(f"Source field '{name}' must be a mapping or string.")
        return cls(
            name=name,
            field_type=str(data.get("type") or data.get("field_type") or "float"),
            required=bool(data.get("required", True)),
            nullable=bool(data.get("nullable", False)),
            unit=data.get("unit"),
            description=str(data.get("description") or ""),
        )


@dataclass
class SourceCatalog:
    source_id: str
    format: str = "csv"
    grain: str = "daily"
    dimensions: List[str] = field(default_factory=list)
    natural_key: List[str] = field(default_factory=list)
    fields: Dict[str, SourceFieldSpec] = field(default_factory=dict)
    unit: Optional[str] = None
    availability: Optional[AvailabilityPolicy] = None
    missing_data: Optional[MissingDataPolicy] = None
    comparison_policy: Optional[ComparisonPolicy] = None
    timezone: str = "UTC"
    revision_field: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: Optional[Dict[str, Any]], default_source_id: Optional[str] = None) -> Optional["SourceCatalog"]:
        if not data:
            return None
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValueError("Source catalog must be a mapping.")
        source_id = str(data.get("source_id") or data.get("name") or default_source_id or "unknown_source")
        fields = {}
        for name, spec in (data.get("fields") or {}).items():
            fields[str(name)] = SourceFieldSpec.from_mapping(str(name), spec)
        availability = AvailabilityPolicy.from_mapping(data.get("availability"))
        missing_data = MissingDataPolicy.from_mapping(data.get("missing_data"))
        comparison_policy = ComparisonPolicy.from_mapping(data.get("comparison_policy") or data.get("comparison"))
        return cls(
            source_id=source_id,
            format=str(data.get("format", "csv")),
            grain=str(data.get("grain", "daily")),
            dimensions=list(data.get("dimensions") or []),
            natural_key=list(data.get("natural_key") or data.get("keys") or []),
            fields=fields,
            unit=data.get("unit"),
            availability=availability,
            missing_data=missing_data,
            comparison_policy=comparison_policy,
            timezone=str(data.get("timezone", "UTC")),
            revision_field=data.get("revision_field"),
        )


# The present schema is a bounded v1 capability, not a general expression model.
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
    schema_version: int = 1
    source_catalog: Optional[SourceCatalog] = None
    calculation: Optional[CalculationDefinition] = None
    comparison_policy: Optional[ComparisonPolicy] = None
    missing_data_policy: Optional[MissingDataPolicy] = None

    def resolved_calculation(self) -> CalculationDefinition:
        if self.calculation is not None:
            return self.calculation
        return CalculationDefinition(
            operator=self.aggregation,
            value_column=self.value_column,
            numerator_column=self.numerator_column,
            denominator_column=self.denominator_column,
            weight_column=self.weight_column,
            formula=self.formula,
            description=self.definition,
        )

    def validate_grain(self) -> None:
        """Enforces that grain-specific thresholds are non-zero and declared."""
        if self.schema_version < 1:
            raise ValueError(f"KPI {self.kpi_id}: schema_version must be >= 1.")
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
        calculation = self.resolved_calculation()
        calculation.validate(self.kpi_id)
        if self.aggregation not in {"sum", "mean", "weighted_mean", "ratio_of_sums"}:
            raise ValueError(f"KPI {self.kpi_id}: unsupported aggregation {self.aggregation}.")
        if self.aggregation == "ratio_of_sums":
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
