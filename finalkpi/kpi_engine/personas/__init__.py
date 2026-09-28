# IMPLEMENTATION HANDOFF — persona configuration (Stage 8-lite)
# Current: one YAML per persona owns claim_order, driver_priority (lever
# families first), allowed_action_levers, approval_threshold and the fallback
# owner. kpi_engine/narrative.py:_claims and kpi_engine/action.py:recommend read
# it to select, order and gate; neither may add a fact, a number or a causal
# claim because of it. NarrativeEngine.validate still rebuilds the approved
# claims from the evidence payload, so a persona can only ever change what is
# read first, never what passes grounding.
# Next: the persona config is static per role. A learned ordering (which claim
# type this reviewer actually acts on) belongs in offline_learning, scored on the
# dev split, not hand-edited here.
# Check: an unknown persona gets the engine's default order and the full lever
# set, so a new role degrades to today's behaviour rather than to a silently
# narrower view; a persona that drops a claim type drops it for every run.

"""Persona configuration: what each role reads first, and may act on.

A persona config is a *view* over a diagnosis, never a source of facts. It
decides three things and nothing else:

* which approved claim types this role reads, and in what order;
* how the driver claims inside a run are ranked (lever families first);
* which decision cards the engine may raise for this role, and the minimum
  Attribution Confidence at which the role may approve one.

Every claim it orders is still rebuilt from the evidence payload by
``narrative.NarrativeEngine._claims`` and re-checked by
``narrative.NarrativeEngine.validate``. Every card it gates is still built from
the regression contribution by ``action.ActionRecommendationEngine``. Adding a
persona cannot make an unsupported number, entity or causal verb appear.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

PERSONA_DIR = Path(__file__).resolve().parent

# The engine's own claim order, used when no persona config is supplied or the
# payload carries no persona. It is the pre-Stage-8 behaviour verbatim, so a
# payload that arrives without a persona (a stored run, a projected payload, a
# unit fixture) renders exactly as it did before persona configs existed.
DEFAULT_CLAIM_ORDER: Tuple[str, ...] = (
    "SOURCE_STATUS",
    "OBSERVED_MOVEMENT",
    "MATERIALITY",
    "REVIEW",
    "ABSTENTION",
    "ACCOUNTING_NOT_CAUSAL",
    "FUNNEL_BRIDGE",
    "ATTRIBUTED_DRIVER",
    "CORROBORATION",
    "CORRELATIONAL",
    "OBSERVATIONAL",
    "CLARIFICATION_REQUEST",
    "EVENT_WINDOW",
    "ACCESS_BOUNDARY",
)

# Every lever family the action catalog can produce, in the engine's own order.
ALL_LEVER_FAMILIES: Tuple[str, ...] = (
    "source_integrity",
    "availability",
    "pricing",
    "promotions",
    "performance",
    "marketing",
    "contextual",
    "evidence_collection",
)

REQUIRED_FIELDS = {
    "persona_id", "display_name", "claim_order", "driver_priority",
    "allowed_action_levers", "approval_threshold", "max_driver_claims",
    "default_owner", "lever_owners", "decision_right",
}


class PersonaConfigError(ValueError):
    """A persona file is missing, malformed or claims an unknown lever."""


@dataclass(frozen=True)
class PersonaConfig:
    persona_id: str
    display_name: str
    claim_order: Tuple[str, ...]
    driver_priority: Tuple[str, ...]
    allowed_action_levers: Tuple[str, ...]
    approval_threshold: float
    max_driver_claims: int
    default_owner: str
    lever_owners: Dict[str, str]
    decision_right: str
    brief_prefix: str = ""
    brief_focus: str = ""
    workspace_headline: str = ""
    workspace_briefing: str = ""
    workspace_footer: str = ""

    def claim_rank(self, claim_type: str) -> int:
        """Position of a claim type in this persona's order, or -1 if dropped."""
        try:
            return self.claim_order.index(claim_type)
        except ValueError:
            return -1

    def reads(self, claim_type: str) -> bool:
        return claim_type in self.claim_order

    def lever_priority(self, family: str | None) -> int:
        if family is None:
            return len(self.driver_priority)
        try:
            return self.driver_priority.index(family)
        except ValueError:
            return len(self.driver_priority)

    def owner_for(self, family: str | None) -> str | None:
        if family is not None and family in self.lever_owners:
            return self.lever_owners[family]
        return self.default_owner


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently keeping the last value."""


def _unique_mapping(loader: Any, node: Any) -> Dict[str, Any]:
    mapping: Dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in mapping:
            raise PersonaConfigError(f"Duplicate persona YAML key: {key}")
        mapping[key] = loader.construct_object(value_node)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping,
)


def _as_str_tuple(value: Any, field: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise PersonaConfigError(f"persona field '{field}' must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise PersonaConfigError(f"persona field '{field}' must contain non-empty strings")
    if len(set(value)) != len(value):
        raise PersonaConfigError(f"persona field '{field}' contains duplicates")
    return tuple(value)


def _load_file(path: Path) -> PersonaConfig:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except FileNotFoundError as exc:
        raise PersonaConfigError(f"Persona config not found: {path.name}") from exc
    if not isinstance(raw, dict):
        raise PersonaConfigError(f"{path.name} is not a persona mapping")
    missing = sorted(REQUIRED_FIELDS - set(raw))
    if missing:
        raise PersonaConfigError(f"{path.name} is missing: {', '.join(missing)}")
    unknown = sorted(set(raw) - REQUIRED_FIELDS - {
        "aliases", "brief_prefix", "brief_focus",
        "workspace_headline", "workspace_briefing", "workspace_footer",
    })
    if unknown:
        raise PersonaConfigError(f"{path.name} has unknown fields: {', '.join(unknown)}")

    allowed = _as_str_tuple(raw["allowed_action_levers"], "allowed_action_levers")
    declared_levers = set(allowed) | set(raw["driver_priority"]) | set(raw["lever_owners"])
    unknown_levers = sorted(declared_levers - set(ALL_LEVER_FAMILIES))
    if unknown_levers:
        raise PersonaConfigError(
            f"{path.name} names levers outside the action catalog: {', '.join(unknown_levers)}"
        )
    threshold = raw["approval_threshold"]
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0.0 <= threshold <= 1.0:
        raise PersonaConfigError(f"{path.name} approval_threshold must be within [0, 1]")
    max_claims = raw["max_driver_claims"]
    if not isinstance(max_claims, int) or isinstance(max_claims, bool) or max_claims < 1:
        raise PersonaConfigError(f"{path.name} max_driver_claims must be a positive integer")
    lever_owners = raw["lever_owners"]
    if not isinstance(lever_owners, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value.strip()
        for key, value in lever_owners.items()
    ):
        raise PersonaConfigError(f"{path.name} lever_owners must map a lever family to a role")
    return PersonaConfig(
        persona_id=str(raw["persona_id"]),
        display_name=str(raw["display_name"]),
        claim_order=_as_str_tuple(raw["claim_order"], "claim_order"),
        driver_priority=_as_str_tuple(raw["driver_priority"], "driver_priority"),
        allowed_action_levers=allowed,
        approval_threshold=float(threshold),
        max_driver_claims=max_claims,
        default_owner=str(raw["default_owner"]),
        lever_owners=dict(lever_owners),
        decision_right=str(raw["decision_right"]),
        brief_prefix=str(raw.get("brief_prefix", "")),
        brief_focus=str(raw.get("brief_focus", "")),
        workspace_headline=str(raw.get("workspace_headline", "")),
        workspace_briefing=str(raw.get("workspace_briefing", "")),
        workspace_footer=str(raw.get("workspace_footer", "")),
    )


def _config_paths() -> Dict[str, Path]:
    paths: Dict[str, Path] = {}
    for path in sorted(PERSONA_DIR.glob("*.yaml")):
        config = _load_file(path)
        paths[config.persona_id.lower()] = path
    if not paths:
        raise PersonaConfigError("No persona configs are installed")
    return paths


def _aliases() -> Dict[str, str]:
    """Every spelling a caller may use, mapped to a persona_id."""
    resolved: Dict[str, str] = {}
    for path in _config_paths().values():
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
        resolved[raw["persona_id"].strip().lower()] = raw["persona_id"].strip().lower()
        for alias in raw.get("aliases") or ():
            if not isinstance(alias, str) or not alias.strip():
                raise PersonaConfigError(f"{path.name} has a non-string alias")
            key = alias.strip().lower()
            if key in resolved and resolved[key] != raw["persona_id"]:
                raise PersonaConfigError(f"Persona alias '{alias}' is claimed twice")
            resolved[key] = raw["persona_id"].strip().lower()
    return resolved


@lru_cache(maxsize=1)
def persona_aliases() -> Dict[str, str]:
    return dict(_aliases())


@lru_cache(maxsize=16)
def _load_cached(persona_id: str) -> PersonaConfig:
    return _load_file(_config_paths()[persona_id])


@lru_cache(maxsize=1)
def default_config() -> PersonaConfig:
    """The no-persona view: the engine's own order and the full lever set.

    A payload with no persona, or a persona with no config file, renders exactly
    as it did before Stage 8. It is deliberately *not* a restricted view: an
    unrecognised role must not silently lose levers, and the safety rules that
    matter (the causal-wording gate, the impact gate) apply to every persona
    including this one.
    """
    return PersonaConfig(
        persona_id="default",
        display_name="Default reviewer",
        claim_order=DEFAULT_CLAIM_ORDER,
        driver_priority=ALL_LEVER_FAMILIES,
        allowed_action_levers=ALL_LEVER_FAMILIES,
        approval_threshold=0.6,
        max_driver_claims=len(ALL_LEVER_FAMILIES) * 2,
        default_owner="analyst",
        lever_owners={},
        decision_right="Evidence review",
    )


def load_persona(persona: Any) -> PersonaConfig:
    """Resolve a persona id or alias to its config; unknown -> the default view.

    An empty persona is the engine's own default. A persona that is registered
    but has no config file, and a persona that is not registered at all, both
    resolve to :func:`default_config` rather than raising: a narrative must
    still render for a role the configuration does not know yet.
    """
    if not isinstance(persona, str) or not persona.strip():
        return default_config()
    resolved = persona_aliases().get(persona.strip().lower())
    if resolved is None:
        return default_config()
    return _load_cached(resolved)


def registered_personas() -> Tuple[str, ...]:
    """persona_ids that have a config file, in file-name order."""
    return tuple(_config_paths())
