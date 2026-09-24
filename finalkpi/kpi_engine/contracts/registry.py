from pathlib import Path

import yaml
from typing import Dict
from kpi_engine.contracts.models import KPIContract, MaterialityThresholds


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

        contract = KPIContract(
            kpi_id=data["kpi_id"],
            formula=data["formula"],
            unit=data["unit"],
            grain=data["grain"],
            source=data["source"],
            dimensions=data.get("dimensions", []),
            materiality=materiality,
            seasonal_period=int(data.get("seasonal_period", 0)),
            min_history_periods=int(data.get("min_history_periods", 0)),
            owner=data.get("owner", "unassigned"),
            access_tags=data.get("access_tags", []),
            version=int(data["version"]),
            definition=data["definition"],
            value_column=data["value_column"],
            aggregation=data["aggregation"],
            decomposition=data.get("decomposition") or {},
            reconciliation=data.get("reconciliation"),
            candidate_drivers=data.get("candidate_drivers", []),
            numerator_column=data.get("numerator_column"),
            denominator_column=data.get("denominator_column"),
            weight_column=data.get("weight_column"),
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
