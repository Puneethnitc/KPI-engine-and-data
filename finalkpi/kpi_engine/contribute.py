# IMPLEMENTATION HANDOFF — modeled driver contributions
# Current: caller supplies all 2^n coalition outcomes for 2-4 drivers. Each effect
# is the weighted marginal outcome change across subsets; effects sum to the
# full-minus-empty model outcome. Observed minus modeled remains a residual.
# Next: define model ID/version, training/as-of scope, scenario baseline and input
# provenance before connecting a coalition provider. There is no fitted provider
# here today. Missing model outcomes should remain NOT_CALCULABLE in a future API.
# Share-of-observed can be negative or exceed 100%; never normalize it to hide
# offsetting effects or residuals. Preserve the MODEL_BASED_SCENARIO claim label.
# Check: complete coalition coverage, symmetry, null driver, efficiency, zero
# observed movement and mismatched scope/unit/model lineage.

"""Exact scenario Shapley; never infer causal values from correlations."""

from dataclasses import dataclass
from itertools import combinations
from math import factorial, isfinite
from typing import Mapping


@dataclass(frozen=True)
class ContributionScenario:
    """Predeclared coalition outcomes in the KPI's unit.

    Each tuple key is a subset of ``drivers``; () is the baseline outcome.
    Values must come from an explicit external counterfactual model, not from
    correlations or individual DiD estimates.
    """

    kpi_id: str
    unit: str
    drivers: tuple[str, ...]
    coalition_values: Mapping[tuple[str, ...], float]
    observed_movement: float


@dataclass(frozen=True)
class DriverContribution:
    driver_id: str
    modeled_effect: float
    share_of_observed_pct: float | None


@dataclass(frozen=True)
class ContributionResult:
    kpi_id: str
    unit: str
    claim_type: str
    status: str
    modeled_movement: float
    observed_movement: float
    unexplained_residual: float
    contributions: tuple[DriverContribution, ...]
    method: str = "exact_coalition_shapley"


class ShapleyContributor:
    """Allocate a supplied counterfactual model, not observed causal effects."""

    @staticmethod
    def quantify(scenario: ContributionScenario) -> ContributionResult:
        if not isinstance(scenario, ContributionScenario):
            raise TypeError("A ContributionScenario is required")
        drivers = scenario.drivers
        if not 2 <= len(drivers) <= 4 or len(set(drivers)) != len(drivers) or any(
            not isinstance(driver, str) or not driver for driver in drivers
        ):
            raise ValueError("Require 2–4 distinct, nonempty driver IDs")
        if not scenario.kpi_id or not scenario.unit or not isfinite(scenario.observed_movement):
            raise ValueError("Require a KPI, unit, and finite observed movement")

        values: dict[frozenset[str], float] = {}
        for key, value in scenario.coalition_values.items():
            if (not isinstance(key, tuple) or len(key) != len(set(key))
                    or any(driver not in drivers for driver in key)):
                raise ValueError("Coalition keys must be unique subsets of the declared drivers")
            coalition = frozenset(key)
            if coalition in values or not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError("Coalition outcomes must be unique finite numbers")
            values[coalition] = float(value)
        expected = {frozenset(part) for size in range(len(drivers) + 1)
                    for part in combinations(drivers, size)}
        if set(values) != expected:
            raise ValueError("Supply one outcome for every coalition, including empty and full")

        n = len(drivers)
        effects = {}
        for driver in drivers:
            others = [item for item in drivers if item != driver]
            effect = 0.0
            for size in range(n):
                weight = factorial(size) * factorial(n - size - 1) / factorial(n)
                for part in combinations(others, size):
                    subset = frozenset(part)
                    effect += weight * (values[subset | {driver}] - values[subset])
            effects[driver] = effect
        modeled = values[frozenset(drivers)] - values[frozenset()]
        if not isfinite(modeled) or any(not isfinite(effect) for effect in effects.values()):
            raise ValueError("Coalition effects overflowed")
        if abs(sum(effects.values()) - modeled) > 1e-8 * max(1.0, abs(modeled)):
            raise ArithmeticError("Shapley effects do not reconcile to the modeled movement")
        observed = float(scenario.observed_movement)
        return ContributionResult(
            kpi_id=scenario.kpi_id, unit=scenario.unit,
            claim_type="MODEL_BASED_SCENARIO", status="ALLOCATED",
            modeled_movement=modeled, observed_movement=observed,
            unexplained_residual=observed - modeled,
            contributions=tuple(DriverContribution(
                driver, effects[driver],
                None if abs(observed) < 1e-12 else 100 * effects[driver] / observed,
            ) for driver in drivers),
        )
