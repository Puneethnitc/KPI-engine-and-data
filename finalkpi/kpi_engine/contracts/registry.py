# IMPLEMENTATION HANDOFF — contract loading
# Current: YAML loader rejects duplicate keys, unknown top-level fields and IDs;
# converts values to dataclasses and invokes their validation.
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
    "decomposition", "reconciliation", "candidate_drivers",
    "numerator_column", "denominator_column", "weight_column",
    "schema_version", "source_catalog", "calculation", "comparison_policy",
    "missing_data_policy", "missing_data", "comparison",
}

class KPIRegistry:
    """Stage 0: Versioned KPI Registry.
    Loads and validates KPI semantic contracts from YAML definitions[cite: 1, 3].
    """
    def __init__(self, registry_dir: str):
        self.registry_dir = registry_dir
        self._contracts: Dict[str, KPIContract] = {}
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
            numerator_column=data.get("numerator_column") or calculation_data.get("numerator_column"),
            denominator_column=data.get("denominator_column") or calculation_data.get("denominator_column"),
            weight_column=data.get("weight_column") or calculation_data.get("weight_column"),
            schema_version=int(data.get("schema_version", 1)),
            source_catalog=source_catalog,
            calculation=calculation,
            comparison_policy=comparison_policy,
            missing_data_policy=missing_data_policy,
        )

        # Baked-in Check: Verify grain-appropriate threshold declaration
        contract.validate_grain()
        if contract.kpi_id in self._contracts:
            raise ValueError(f"Duplicate KPI id: {contract.kpi_id}")
        self._contracts[contract.kpi_id] = contract

    def get(self, kpi_id: str) -> KPIContract:
        if kpi_id not in self._contracts:
            raise KeyError(f"KPI '{kpi_id}' not found in registry.")
        return self._contracts[kpi_id]

    def list_ids(self) -> tuple[str, ...]:
        """Return all registered KPI IDs in a stable order."""
        return tuple(sorted(self._contracts))

    def __len__(self) -> int:
        return len(self._contracts)
