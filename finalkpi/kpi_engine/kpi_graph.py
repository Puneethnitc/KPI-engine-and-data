"""Deterministic, accounting-only connected KPI story for one scope and date."""

from __future__ import annotations

from itertools import permutations
from math import factorial, isfinite
from pathlib import Path
from typing import Any, Mapping

import yaml

from kpi_engine.action import ActionRecommendationEngine
from kpi_engine.decompose import DeterministicDecomposer


GRAPH_PATH = Path(__file__).with_name("config") / "kpi_graph.yaml"


def load_kpi_graph(path: str | Path = GRAPH_PATH) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        graph = yaml.safe_load(stream)
    if not isinstance(graph, dict) or graph.get("version") != 1:
        raise ValueError("Unsupported KPI graph config")
    relationships = graph.get("relationships")
    stages = graph.get("stages")
    if not isinstance(relationships, dict) or not isinstance(stages, list) or len(stages) != 4:
        raise ValueError("KPI graph needs relationships and four ordered stages")
    if len({stage["id"] for stage in stages}) != len(stages):
        raise ValueError("KPI graph stage IDs must be unique")
    for target, sources in relationships.items():
        if not isinstance(target, str) or not isinstance(sources, list) or len(sources) != 2:
            raise ValueError("Each KPI relationship needs two factors")
    if graph.get("revenue_kpi") not in relationships:
        raise ValueError("Revenue relationship is missing")
    return graph


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return None
    return float(value)


def _bridge(factors: list[tuple[str, float, float]], total_delta: float) -> dict[str, float]:
    """Symmetric multiplicative Shapley bridge, balanced at display precision."""
    names = [item[0] for item in factors]
    baseline = {name: old for name, old, _ in factors}
    actual = {name: new for name, _, new in factors}

    def product(active: frozenset[str]) -> float:
        value = 1.0
        for name in names:
            value *= actual[name] if name in active else baseline[name]
        return value

    if len(factors) == 3:
        bridge = DeterministicDecomposer.decompose_funnel(
            factors[0][1], factors[0][2], factors[1][1], factors[1][2], factors[2][1], factors[2][2])
        effects = {name: part["effect"] for name, part in zip(names, bridge["components"])}
    else:
        effects = {name: 0.0 for name in names}
        for order in permutations(names):
            active: frozenset[str] = frozenset()
            for name in order:
                next_active = active | {name}
                effects[name] += (product(next_active) - product(active)) / factorial(len(names))
                active = next_active
        if abs(sum(effects.values()) - total_delta) > 1e-5 * max(1, abs(total_delta)):
            raise ValueError("KPI graph does not reconcile to revenue")
    cents_left = round(total_delta * 100)
    rounded: dict[str, float] = {}
    for name in names[:-1]:
        cents = round(effects[name] * 100)
        rounded[name] = cents / 100
        cents_left -= cents
    rounded[names[-1]] = cents_left / 100
    return rounded


def _driver_owner(driver_id: str, results: Mapping[str, dict[str, Any]]) -> str:
    for result in results.values():
        for candidate in (result.get("contract_snapshot") or {}).get("candidate_drivers", []):
            if candidate.get("id") == driver_id and candidate.get("owner"):
                return candidate["owner"]
    entry = ActionRecommendationEngine.LEVERS.get(driver_id)
    return entry[1] if entry else "analyst"


def build_kpi_story(results_by_kpi: Mapping[str, dict[str, Any]], graph: dict[str, Any] | None = None) -> dict[str, Any]:
    graph = graph or load_kpi_graph()
    expected_ids = set(graph["relationships"]) | {stage["kpi_id"] for stage in graph["stages"]}
    nodes: list[dict[str, Any]] = []
    values: dict[str, tuple[float, float]] = {}
    for kpi_id in sorted(expected_ids):
        movement = (results_by_kpi.get(kpi_id) or {}).get("movement_assessment") or {}
        old, new = _number(movement.get("expected_value")), _number(movement.get("actual_value"))
        if old is not None and new is not None:
            values[kpi_id] = (old, new)
        pct = None if old in (None, 0) or new is None else round((new / old - 1) * 100, 2)
        nodes.append({"kpi_id": kpi_id, "actual": new, "expected": old, "percent_change": pct,
                      "material": bool(movement.get("is_material")),
                      "status": "normal" if not movement.get("is_material") or pct is None else "down" if pct < 0 else "up",
                      "missing": kpi_id not in values, "consequence_of": None})
    node_by_id = {node["kpi_id"]: node for node in nodes}
    missing_stages = [stage["id"] for stage in graph["stages"] if stage["kpi_id"] not in values]
    revenue_id = graph["revenue_kpi"]
    edges: list[dict[str, Any]] = []
    root_stage: str | None = None
    delta: float | None = None
    if revenue_id in values:
        # Use observed totals for each ratio. Their independently rounded KPI
        # baselines need not multiply exactly; the derived ratios always do.
        # Walk the declared identities, keeping orders as the denominator for
        # units. Conversion's displayed KPI is independently rounded, while
        # orders / traffic is the ratio that exactly reconciles the totals.
        relationships = graph["relationships"]
        stages = graph["stages"]
        traffic_id = stages[0]["kpi_id"]
        order_id = next(target for target, pair in relationships.items() if traffic_id in pair)
        units_id = next(target for target, pair in relationships.items() if order_id in pair and target != revenue_id)
        levels = [(stages[0]["id"], traffic_id), (stages[1]["id"], order_id),
                  (stages[2]["id"], units_id), (stages[3]["id"], revenue_id)]
        levels = [(stage_id, kpi_id) for stage_id, kpi_id in levels if kpi_id in values]
        factors: list[tuple[str, float, float]] = []
        previous: tuple[float, float] | None = None
        valid_identity = True
        for stage_id, kpi_id in levels:
            old, new = values[kpi_id]
            if previous is None:
                factors.append((stage_id, old, new))
            elif (previous[0] == 0 and old != 0) or (previous[1] == 0 and new != 0):
                valid_identity = False
                break
            else:
                old_ratio = old / previous[0] if previous[0] else new / previous[1] if previous[1] else 1.0
                new_ratio = new / previous[1] if previous[1] else old_ratio
                factors.append((stage_id, old_ratio, new_ratio))
            previous = (old, new)
        raw_delta = values[revenue_id][1] - values[revenue_id][0]
        delta = round(raw_delta, 2)
        if valid_identity and factors and factors[0][0] != graph["stages"][-1]["id"]:
            effects = _bridge(factors, raw_delta)
            stage_by_id = {stage["id"]: stage for stage in graph["stages"]}
            factor_changes = {name: None if old == 0 else round((new / old - 1) * 100, 2)
                              for name, old, new in factors}
            edges = []
            percent_left = 10000
            for index, (name, amount) in enumerate(effects.items()):
                percent_cents = None if not delta else percent_left if index == len(effects) - 1 else round(amount / delta * 10000)
                if percent_cents is not None:
                    percent_left -= percent_cents
                edges.append({"stage": name, "from": stage_by_id[name]["kpi_id"], "to": revenue_id,
                              "contribution_inr": amount,
                              "factor_percent_change": factor_changes[name],
                              "contribution_pct": None if percent_cents is None else percent_cents / 100})
            if any(edge["contribution_inr"] != 0 for edge in edges):
                root_stage = max(edges, key=lambda edge: (abs(edge["contribution_inr"]), -list(effects).index(edge["stage"])))["stage"]
    root_kpi = next((stage["kpi_id"] for stage in graph["stages"] if stage["id"] == root_stage), None)
    # A consequence is a material KPI strictly downstream of the root stage in the
    # declared identities. The root, upstream stages, parallel inputs (traffic vs
    # conversion) and non-material KPIs are never marked.
    downstream: set[str] = set()
    if root_kpi:
        grew = True
        while grew:
            grew = False
            for target, inputs in graph["relationships"].items():
                if target not in downstream and (root_kpi in inputs or downstream & set(inputs)):
                    downstream.add(target)
                    grew = True
    for node in nodes:
        if node["kpi_id"] in downstream and node["material"] and node["percent_change"] not in (None, 0):
            node["consequence_of"] = root_stage

    # A driver on orders/revenue may corroborate an upstream weak stage. Put
    # it on that stage only when no direct stage attribution exists.
    stage_sources = {stage["id"]: stage["kpi_id"] for stage in graph["stages"]}
    stage_effects = {edge["stage"]: edge["contribution_inr"] for edge in edges}
    chains_by_driver: dict[str, dict[str, Any]] = {}
    for stage_id, kpi_id in stage_sources.items():
        effect = stage_effects.get(stage_id, 0)
        if not effect or not node_by_id[kpi_id]["material"]:
            continue
        ranked = [] if stage_id == graph["stages"][-1]["id"] and root_stage != stage_id else [
            (driver, kpi_id) for driver in (((results_by_kpi.get(kpi_id) or {}).get("driver_analysis") or {}).get("ranked_drivers") or [])]
        if stage_id == root_stage and not any((_number(d.get("attribution_confidence")) or 0) >= 0.35 for d, _ in ranked):
            ranked = [(driver, downstream) for downstream in (order_id, units_id, revenue_id)
                      for driver in (((results_by_kpi.get(downstream) or {}).get("driver_analysis") or {}).get("ranked_drivers") or [])]
        for driver, evidence_kpi in ranked:
            driver_id = driver.get("driver_id")
            ac = _number(driver.get("attribution_confidence"))
            share = _number(driver.get("explained_share"))
            if not driver_id or ac is None or ac < 0.35 or share is None or share <= 0:
                continue
            impact = round(effect * share, 2)
            if delta is not None and impact * delta <= 0:
                continue
            evidence = driver.get("corroboration") or {}
            documents = [doc.get("doc_id") for doc in evidence.get("documents", []) if doc.get("doc_id")]
            verification = (results_by_kpi.get(evidence_kpi) or {}).get("causal_verification") or {}
            verdict = verification.get("verdict") if verification.get("driver_id") == driver_id else "NOT_TESTED"
            chain = chains_by_driver.setdefault(driver_id, {"driver_id": driver_id, "stages": [],
                "via_kpi": kpi_id, "revenue_impact": 0.0, "attribution_confidence": ac,
                "band": driver.get("band"), "causal_verdict": verdict,
                "corroboration_doc_ids": [], "owner": _driver_owner(driver_id, results_by_kpi),
                "attribution_source_kpis": [],
                "stage_impacts": [],
                "shared_cause": False})
            if stage_id in chain["stages"]:
                continue
            chain["stages"].append(stage_id)
            chain["stage_impacts"].append({"stage": stage_id, "explained_share": share,
                                           "revenue_impact": impact, "attribution_source_kpi": evidence_kpi})
            chain["revenue_impact"] = round(chain["revenue_impact"] + impact, 2)
            chain["attribution_confidence"] = max(chain["attribution_confidence"], ac)
            chain["attribution_source_kpis"] = sorted(set(chain["attribution_source_kpis"] + [evidence_kpi]))
            chain["corroboration_doc_ids"] = sorted(set(chain["corroboration_doc_ids"] + documents))
            if verdict != "NOT_TESTED":
                chain["causal_verdict"] = verdict
    chains = list(chains_by_driver.values())
    for chain in chains:
        for source_kpi, result in results_by_kpi.items():
            for driver in ((result.get("driver_analysis") or {}).get("ranked_drivers") or []):
                if driver.get("driver_id") != chain["driver_id"]:
                    continue
                chain["attribution_source_kpis"] = sorted(set(chain["attribution_source_kpis"] + [source_kpi]))
                documents = [doc.get("doc_id") for doc in (driver.get("corroboration") or {}).get("documents", []) if doc.get("doc_id")]
                chain["corroboration_doc_ids"] = sorted(set(chain["corroboration_doc_ids"] + documents))
        chain["shared_cause"] = len(chain["stages"]) > 1 or len(chain["attribution_source_kpis"]) > 1
        chain["recoverable_impact_inr"] = max(0.0, -chain["revenue_impact"])
    chains.sort(key=lambda chain: (-chain["recoverable_impact_inr"], -chain["attribution_confidence"], chain["driver_id"]))
    headline_facts = [{"kind": "revenue", "delta": delta,
                       "percent_change": node_by_id.get(revenue_id, {}).get("percent_change")},
                      {"kind": "root_stage", "stage": root_stage}]
    headline_facts.extend({"kind": "normal_stage", "stage": stage["id"]}
                          for stage in graph["stages"] if node_by_id[stage["kpi_id"]]["status"] == "normal")
    headline_facts.extend({"kind": "missing_stage", "stage": stage_id} for stage_id in missing_stages)
    return {"nodes": nodes, "edges": edges, "root_stage": root_stage,
            "missing_stages": missing_stages, "revenue_delta": delta,
            "cause_chains": chains, "act_first": chains,
            "headline_facts": headline_facts,
            "method": "multiplicative_shapley_accounting_not_causal"}
