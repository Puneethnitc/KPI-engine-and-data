# HANDOFF: public contract exports. Keep existing imports working during schema
# migration; expose a new version deliberately after registry/consumer updates.
# No catalog loading or query execution should happen just by importing here.

"""Validated KPI contract models and registry."""

from kpi_engine.contracts.models import (
    AvailabilityPolicy,
    CalculationDefinition,
    ComparisonPolicy,
    KPIContract,
    MaterialityThresholds,
    MissingDataPolicy,
    SourceCatalog,
    SourceFieldSpec,
)
from kpi_engine.contracts.registry import KPIRegistry

__all__ = [
    "KPIContract",
    "MaterialityThresholds",
    "CalculationDefinition",
    "ComparisonPolicy",
    "AvailabilityPolicy",
    "MissingDataPolicy",
    "SourceCatalog",
    "SourceFieldSpec",
    "KPIRegistry",
]
