# IMPLEMENTATION HANDOFF — contract loading
# Current: YAML loader rejects duplicate keys, unknown top-level fields and IDs;
# converts values to dataclasses and invokes their validation. mechanical_components
# (Stage 1, F-R2) and expected_direction_by_scope (F-R4) are accepted driver/contract
# fields; LEGACY_DRIVER_IDS/resolve_driver_id resolve pre-rename driver ids (F-R5).
# Next: add schema-version dispatch, nested validation, source-catalog resolution
# and a stable contract digest for each run. KPI version and schema version are
# separate concepts. Validate actual engine support, not only accepted syntax.
# Check: preserve duplicate-key rejection; an invalid registry fails before any
# query. A contract edit must change its digest and appear in run lineage.

from pathlib import Path

import yaml
from typing import Dict
from kpi_engine.contracts.models import (
    CalculationDefinition,
    ComparisonPolicy,
    KPIContract,
    MaterialityThresholds,
    MissingDataPolicy,
    SourceCatalog,
)
from kpi_engine.query.catalog import SourceCatalog as RuntimeSourceCatalog
from kpi_engine.contracts.semantic import semantic_contract_projection


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently keeping the last value."""


def _unique_mapping(loader, node):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in mapping:
            raise ValueError(f"Duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)

CONTRACT_FIELDS = {
    "kpi_id", "version", "definition", "value_column", "aggregation",
    "formula", "unit", "grain", "source", "dimensions", "materiality",
    "seasonal_period", "min_history_periods", "owner", "access_tags",
    "decomposition", "reconciliation", "candidate_drivers", "mechanical_components",
    "numerator_column", "denominator_column", "weight_column",
    "schema_version", "source_catalog", "calculation", "comparison_policy",
    "missing_data_policy", "missing_data", "comparison",
    "display_name", "status", "business_purpose", "steward", "tags",
    "precision", "aggregation_notes", "supported_rollups", "calendar", "timezone",
    "null_policy", "zero_policy", "statistical_method", "detector_agreement_rule",
    "threshold_status", "calibration_reference", "driver_method", "driver_limitations",
    "decomposition_limitations", "effective_from", "effective_to", "approved_by",
    "change_reason", "source_catalog_version", "policy_reference",
}

NESTED_FIELDS = {
    "materiality": {"z_threshold", "abs_threshold"},
    "calculation": {"operator", "aggregation", "value_column", "numerator_column", "denominator_column", "weight_column", "formula", "description"},
    "comparison_policy": {"period", "comparison", "baseline_periods", "weighting", "completeness", "config"},
    "reconciliation": {"finance_source", "finance_column", "mode", "keys", "unit", "tolerance_pct", "contradiction_multiple", "require_matching_coverage", "comparison", "coverage_rule", "availability_rule"},
    "decomposition": {"quantity_column", "reference_rate_column"},
}
DRIVER_FIELDS = {
    "id", "display_name", "unit", "controllability", "expected_direction", "expected_direction_by_scope",
    "column", "source", "grain", "aggregation",
    "allowed_lags", "min_pairs", "minimum_coverage", "max_lag", "window_days", "threshold", "ranking_window_days",
    "monthly_min_pairs", "owner", "ranking", "policy", "lag_policy", "availability", "lag_availability",
}

# Stage 1 (plan §1.3) renames these driver ids for clarity (a driver id should
# describe the variable, not the event/direction baked into the old name).
# Historical runs and feedback records may still reference the old spelling;
# resolve_driver_id() is the single place that alias gets resolved.
LEGACY_DRIVER_IDS = {
    "ad_spend_drop": "marketing_spend",
    "checkout_latency_spike": "checkout_latency",
    "competitor_price_cut": "competitor_price_index",
    "stockout": "stock_availability",
}


def resolve_driver_id(driver_id: str) -> str:
    """Map a legacy driver id (pre plan §1.3 rename) to its current id."""
    return LEGACY_DRIVER_IDS.get(driver_id, driver_id)

class KPIRegistry:
    """Stage 0: Versioned KPI Registry.
    Loads and validates KPI semantic contracts from YAML definitions[cite: 1, 3].
    """
    def __init__(self, registry_dir: str, source_catalog: RuntimeSourceCatalog | None = None):
        self.registry_dir = registry_dir
        self._contracts: Dict[str, KPIContract] = {}
        self.source_catalog = source_catalog or RuntimeSourceCatalog()
        self.load_all()

    def load_all(self) -> None:
        directory = Path(self.registry_dir)
        if not directory.is_dir():
            raise FileNotFoundError(f"Registry directory not found: {self.registry_dir}")

        paths = sorted((*directory.glob("*.yaml"), *directory.glob("*.yml")))
        if not paths:
            raise ValueError(f"No KPI contracts found in {directory}")
        for filepath in paths:
            self._load_file(filepath)

    def _load_file(self, filepath: Path) -> None:
        with filepath.open("r", encoding="utf-8") as f:
            data = yaml.load(f, Loader=UniqueKeyLoader)
        if not isinstance(data, dict):
            raise ValueError(f"{filepath.name}: expected a YAML mapping")
        unknown = set(data) - CONTRACT_FIELDS
        if unknown:
            raise ValueError(f"{filepath.name}: unknown contract fields: {sorted(unknown)}")
        for parent, accepted in NESTED_FIELDS.items():
            nested = data.get(parent)
            if isinstance(nested, dict):
                nested_unknown = set(nested) - accepted
                if nested_unknown:
                    raise ValueError(f"{filepath.name}.{parent}: unknown fields: {sorted(nested_unknown)}")
        for index, driver in enumerate(data.get("candidate_drivers") or []):
            if not isinstance(driver, dict):
                raise ValueError(f"{filepath.name}.candidate_drivers[{index}]: expected a mapping.")
            driver_unknown = set(driver) - DRIVER_FIELDS
            if driver_unknown:
                raise ValueError(f"{filepath.name}.candidate_drivers[{index}]: unknown fields: {sorted(driver_unknown)}")
        if filepath.stem != data.get("kpi_id"):
            raise ValueError(f"{filepath.name}: filename must match kpi_id")

        mat_data = data.get("materiality", {})
        materiality = MaterialityThresholds(
            z_threshold=float(mat_data.get("z_threshold", 0.0)),
            abs_threshold=float(mat_data.get("abs_threshold", 0.0))
        )

        calculation_data = dict(data.get("calculation") or {})
        if data.get("aggregation") is not None:
            calculation_data["operator"] = data["aggregation"]
        if data.get("value_column") is not None:
            calculation_data["value_column"] = data["value_column"]
        if data.get("numerator_column") is not None:
            calculation_data["numerator_column"] = data["numerator_column"]
        if data.get("denominator_column") is not None:
            calculation_data["denominator_column"] = data["denominator_column"]
        if data.get("weight_column") is not None:
            calculation_data["weight_column"] = data["weight_column"]
        if data.get("formula") is not None:
            calculation_data["formula"] = data["formula"]
        if data.get("definition") is not None:
            calculation_data["description"] = data["definition"]
        if not calculation_data:
            calculation_data = {
                "operator": data.get("aggregation"),
                "value_column": data.get("value_column"),
                "numerator_column": data.get("numerator_column"),
                "denominator_column": data.get("denominator_column"),
                "weight_column": data.get("weight_column"),
                "formula": data.get("formula", ""),
                "description": data.get("definition", ""),
            }
        calculation = CalculationDefinition.from_mapping(calculation_data)
        source_catalog = SourceCatalog.from_mapping(
            data.get("source_catalog") or {
                "source_id": data.get("source"),
                "grain": data.get("grain"),
                "dimensions": data.get("dimensions", []),
                "unit": data.get("unit"),
                "fields": {
                    data.get("value_column"): {"type": "float", "required": True},
                    **({}
                        if data.get("numerator_column") is None
                        else {data.get("numerator_column"): {"type": "float", "required": True}}),
                    **({}
                        if data.get("denominator_column") is None
                        else {data.get("denominator_column"): {"type": "float", "required": True}}),
                },
            },
            default_source_id=data.get("source"),
        )
        comparison_policy = ComparisonPolicy.from_mapping(
            data.get("comparison_policy") or data.get("comparison") or data.get("reconciliation")
        )
        missing_data_policy = MissingDataPolicy.from_mapping(
            data.get("missing_data_policy") or data.get("missing_data")
        )

        contract = KPIContract(
            kpi_id=data["kpi_id"],
            formula=data.get("formula") or calculation_data.get("formula", ""),
            unit=data.get("unit") or source_catalog.unit if source_catalog else "",
            grain=data.get("grain") or (source_catalog.grain if source_catalog else "daily"),
            source=data.get("source") or (source_catalog.source_id if source_catalog else ""),
            dimensions=data.get("dimensions", []) or (source_catalog.dimensions if source_catalog else []),
            materiality=materiality,
            seasonal_period=int(data.get("seasonal_period", 0)),
            min_history_periods=int(data.get("min_history_periods", 0)),
            owner=data.get("owner", "unassigned"),
            access_tags=data.get("access_tags", []),
            version=int(data["version"]),
            definition=data.get("definition") or calculation_data.get("description", ""),
            value_column=data.get("value_column") or calculation_data.get("value_column") or "",
            aggregation=data.get("aggregation") or calculation_data.get("operator") or "sum",
            decomposition=data.get("decomposition") or {},
            reconciliation=data.get("reconciliation"),
            candidate_drivers=data.get("candidate_drivers", []),
            mechanical_components=list(data.get("mechanical_components") or []),
            numerator_column=data.get("numerator_column") or calculation_data.get("numerator_column"),
            denominator_column=data.get("denominator_column") or calculation_data.get("denominator_column"),
            weight_column=data.get("weight_column") or calculation_data.get("weight_column"),
            schema_version=int(data.get("schema_version", 1)),
            source_catalog=source_catalog,
            calculation=calculation,
            comparison_policy=comparison_policy,
            missing_data_policy=missing_data_policy,
            display_name=data.get("display_name"),
            status=str(data.get("status", "ACTIVE")),
            business_purpose=data.get("business_purpose"),
            steward=data.get("steward"),
            tags=list(data.get("tags") or []),
            precision=int(data.get("precision", 2)),
            aggregation_notes=list(data.get("aggregation_notes") or []),
            supported_rollups=list(data.get("supported_rollups") or []),
            calendar=str(data.get("calendar", "Gregorian")),
            timezone=str(data.get("timezone") or (source_catalog.timezone if source_catalog else "UTC")),
            null_policy=data.get("null_policy"),
            zero_policy=data.get("zero_policy"),
            statistical_method=str(data.get("statistical_method", "robust rolling baseline with seasonal forecast review")),
            detector_agreement_rule=str(data.get("detector_agreement_rule", "material alert uses robust detector; seasonal-only signal requires review")),
            threshold_status=str(data.get("threshold_status", "PROVISIONAL")),
            calibration_reference=data.get("calibration_reference"),
            driver_method=str(data.get("driver_method", "native-grain first-difference lagged Pearson association")),
            driver_limitations=list(data.get("driver_limitations") or []),
            decomposition_limitations=list(data.get("decomposition_limitations") or []),
            effective_from=data.get("effective_from"),
            effective_to=data.get("effective_to"),
            approved_by=data.get("approved_by"),
            change_reason=data.get("change_reason"),
            source_catalog_version=str(data.get("source_catalog_version", "1")),
            policy_reference=str(data.get("policy_reference", "access_control.csv")),
        )

        # Baked-in Check: Verify grain-appropriate threshold declaration
        contract.validate_grain()
        self._validate_source_links(contract, source_catalog)
        if contract.kpi_id in self._contracts:
            raise ValueError(f"Duplicate KPI id: {contract.kpi_id}")
        self._contracts[contract.kpi_id] = contract

    def _validate_source_links(self, contract: KPIContract, inline_source: SourceCatalog | None) -> None:
        try:
            primary = self.source_catalog.get_source(contract.source)
        except KeyError as error:
            raise ValueError(f"KPI {contract.kpi_id}.source: {error}") from error
        if primary.grain != contract.grain:
            raise ValueError(
                f"KPI {contract.kpi_id}.grain: {contract.grain} does not match source "
                f"{primary.source_id} grain {primary.grain}."
            )
        if inline_source is not None and inline_source.source_id in self.source_catalog.sources:
            shared = self.source_catalog.get_source(inline_source.source_id)
            if inline_source.grain != shared.grain:
                raise ValueError(
                    f"KPI {contract.kpi_id}.source_catalog.grain: inline value {inline_source.grain} "
                    f"conflicts with shared source {shared.source_id} grain {shared.grain}."
                )
            inline_fields = inline_source.fields or {}
            for field_name in (
                contract.resolved_calculation().value_column,
                contract.resolved_calculation().numerator_column,
                contract.resolved_calculation().denominator_column,
            ):
                if not field_name or field_name not in inline_fields or field_name not in shared.fields:
                    continue
                inline_unit = inline_fields[field_name].unit
                shared_unit = shared.fields[field_name].unit
                if inline_unit and shared_unit and inline_unit != shared_unit:
                    raise ValueError(
                        f"KPI {contract.kpi_id}.source_catalog.fields.{field_name}.unit: inline value "
                        f"{inline_unit} conflicts with shared source {shared.source_id} unit {shared_unit}."
                    )
        if set(contract.dimensions) - set(primary.dimensions):
            raise ValueError(f"KPI {contract.kpi_id}.dimensions: unknown source dimensions {sorted(set(contract.dimensions) - set(primary.dimensions))}.")
        calculation = contract.resolved_calculation()
        calculation_fields = (
            [calculation.numerator_column, calculation.denominator_column]
            if calculation.operator == "ratio_of_sums" else
            [calculation.value_column, calculation.weight_column]
        )
        for field_name in filter(None, calculation_fields):
            if field_name not in primary.fields:
                raise ValueError(f"KPI {contract.kpi_id}.calculation: source {primary.source_id} has no field '{field_name}'.")
        if contract.decomposition:
            quantity_field = contract.decomposition.get("quantity_column")
            if quantity_field not in primary.fields:
                raise ValueError(f"KPI {contract.kpi_id}.decomposition.quantity_column: source {primary.source_id} has no field '{quantity_field}'.")
            reference_label = contract.decomposition.get("reference_rate_column")
            if not reference_label or not isinstance(reference_label, str):
                raise ValueError(f"KPI {contract.kpi_id}.decomposition.reference_rate_column: a presentation label is required.")
        for index, driver in enumerate(contract.candidate_drivers):
            try:
                source = self.source_catalog.get_source(driver["source"])
            except KeyError as error:
                raise ValueError(f"KPI {contract.kpi_id}.candidate_drivers[{index}].source: {error}") from error
            if source.grain != driver["grain"]:
                raise ValueError(
                    f"KPI {contract.kpi_id}.candidate_drivers[{index}].grain: declared {driver['grain']} "
                    f"does not match {source.source_id} grain {source.grain}."
                )
            if driver["column"] not in source.fields:
                raise ValueError(f"KPI {contract.kpi_id}.candidate_drivers[{index}].column: source {source.source_id} has no field '{driver['column']}'.")
            declared_unit = source.fields[driver["column"]].unit
            if driver.get("unit") and declared_unit and driver["unit"] != declared_unit:
                raise ValueError(f"KPI {contract.kpi_id}.candidate_drivers[{index}].unit: {driver['unit']} conflicts with source field unit {declared_unit}.")
        if contract.reconciliation:
            source_id = contract.reconciliation.get("finance_source", "finance_monthly")
            try:
                comparison_source = self.source_catalog.get_source(source_id)
            except KeyError as error:
                raise ValueError(f"KPI {contract.kpi_id}.reconciliation.finance_source: {error}") from error
            metric = contract.reconciliation.get("finance_column")
            if metric not in comparison_source.fields:
                raise ValueError(f"KPI {contract.kpi_id}.reconciliation.finance_column: source {source_id} has no field '{metric}'.")
            metric_unit = comparison_source.fields[metric].unit
            if metric_unit and contract.reconciliation.get("unit") != metric_unit:
                raise ValueError(f"KPI {contract.kpi_id}.reconciliation.unit: {contract.reconciliation.get('unit')} conflicts with source field unit {metric_unit}.")
            if comparison_source.access_classification != "restricted" and source_id == "finance_monthly":
                raise ValueError(f"KPI {contract.kpi_id}.reconciliation.finance_source: finance source must be classified restricted.")
            keys = contract.reconciliation.get("keys") or []
            if set(keys) != set(contract.dimensions):
                raise ValueError(f"KPI {contract.kpi_id}.reconciliation.keys: keys must match KPI dimensions {contract.dimensions}.")
            if any(key not in comparison_source.fields for key in keys):
                raise ValueError(f"KPI {contract.kpi_id}.reconciliation.keys: one or more keys are absent from source {source_id}.")
            if contract.reconciliation.get("unit") != contract.unit:
                raise ValueError(f"KPI {contract.kpi_id}.reconciliation.unit: comparison unit must match KPI unit {contract.unit}.")
            if comparison_source.grain != "monthly":
                raise ValueError(f"KPI {contract.kpi_id}.reconciliation.finance_source: comparison source must be monthly grain.")

    def semantic_snapshot(self, kpi_id: str, *, allowed_roles: list[str]) -> dict:
        contract = self.get(kpi_id)
        source = self.source_catalog.get_source(contract.source)
        comparison_source = None
        if contract.reconciliation:
            comparison_source = self.source_catalog.get_source(
                contract.reconciliation.get("finance_source", "finance_monthly")
            )
        return semantic_contract_projection(
            contract, source, allowed_roles=allowed_roles,
            comparison_source=comparison_source,
        )

    def get(self, kpi_id: str) -> KPIContract:
        if kpi_id not in self._contracts:
            raise KeyError(f"KPI '{kpi_id}' not found in registry.")
        return self._contracts[kpi_id]

    def list_ids(self) -> tuple[str, ...]:
        """Return all registered KPI IDs in a stable order."""
        return tuple(sorted(self._contracts))

    def __len__(self) -> int:
        return len(self._contracts)
