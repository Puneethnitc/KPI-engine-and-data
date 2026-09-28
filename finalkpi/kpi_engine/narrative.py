# IMPLEMENTATION HANDOFF — evidence rendering
# Current: builds approved claims and validates their evidence paths. An optional
# remote model selects existing wording variants; it cannot calculate new facts.
# Persona configs (Stage 8) select, order and reword claims; they cannot add one.
# Next: render declared units, comparison periods, coverage and lineage from the
# shared result schema. Configure provider/model separately from KPI semantics.
# Preserve deterministic fallback and align backend chat with these claim types.
# Check: unsupported numbers, missing paths and contradictory verdicts fail
# grounding; access denials contain no diagnostic details. SQL computes facts.

"""Deterministic, evidence-bound diagnosis narrative.

This renderer accepts no arbitrary prose. Validation rebuilds the permitted
claims from the evidence payload, so changed numbers, entities, or causal
language cannot pass merely because some matching token exists elsewhere.

Stage 8-lite adds a *persona view* over those same claims. ``_claims`` takes a
``PersonaConfig`` and uses it for three things and nothing else: which approved
claim types this role reads, in what order, and how the driver claims are
ranked among themselves (lever families first, then the persona's cap). A
persona never contributes a number, an entity or a causal verb, because
``validate`` rebuilds the expected claims with the same config and still refuses
anything outside that set.
"""

from dataclasses import asdict, dataclass, replace
import json
import math
import os
import time
from typing import Any, Callable, Iterable, Sequence
from urllib.request import Request, urlopen

from kpi_engine.personas import PersonaConfig, load_persona

# Stage 8-lite: the Attribution Confidence at or above which a causal verb may be
# used, and the causal verdicts that permit one. Both conditions are required --
# a high AC with an untested driver still says "is associated with", and a
# supported causal test with a low AC is not promoted either.
CAUSAL_WORDING_MIN_AC = 0.6
CAUSAL_SUPPORTED_VERDICTS = frozenset({"SUPPORTED_CONDITIONAL"})
# The unambiguous phrase a low-confidence attribution may use. It reads as a
# causal statement, so validate() rejects it unless the rule above is satisfied.
CAUSAL_PHRASE = "likely caused"
ASSOCIATED_PHRASE = "is associated with"
# Unstructured evidence can only add support or a contradiction, never a cause.
CORROBORATION_STATUSES = frozenset({"CORROBORATED", "CONTRADICTED"})
CORROBORATION_DOC_LIMIT = 3
# How many ranked drivers are listed before `max_driver_claims` truncates.
CLAIM_DRIVER_FAMILIES = {"stock_availability", "checkout_latency", "competitor_price_index",
                         "marketing_spend", "price_discount", "promo_flag", "weather_temp"}
# DriverAnalysis statuses that withdraw every ranked driver from the narrative.
BLOCKED_DRIVER_STATUSES = frozenset({
    "BLOCKED", "INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE", "EXPLORATORY_NON_MATERIAL",
})


def lever_family(driver_id: str | None) -> str:
    """The lever family a driver belongs to; shared with the action catalog."""
    return {
        "checkout_latency": "performance",
        "competitor_price_index": "pricing",
        "marketing_spend": "marketing",
        "stock_availability": "availability",
        "price_discount": "promotions",
        "promo_flag": "promotions",
        "weather_temp": "contextual",
    }.get(driver_id or "", "contextual")


def _causal_wording_allowed(driver: dict[str, Any], payload: dict[str, Any]) -> bool:
    """`likely caused` needs AC >= 0.6 *and* a supported causal test on this driver."""
    confidence = driver.get("attribution_confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return False
    if float(confidence) < CAUSAL_WORDING_MIN_AC:
        return False
    verification = payload.get("causal_verification") or {}
    return (
        verification.get("verdict") in CAUSAL_SUPPORTED_VERDICTS
        and verification.get("driver_id") == driver.get("driver_id")
    )


def _claim_subject(text: str, *phrases: str) -> str:
    """The subject at the head of a claim, i.e. everything before its predicate."""
    for phrase in phrases:
        head, separator, _ = text.partition(phrase)
        if separator:
            return head.strip()
    return text.strip()


def _driver_subject(text: str) -> str:
    return _claim_subject(text, CAUSAL_PHRASE, ASSOCIATED_PHRASE)


def _corroboration_subject(text: str) -> str:
    return _claim_subject(text, " is corroborated by", " is contradicted by")


@dataclass(frozen=True)
class GroundedClaim:
    text: str
    evidence_paths: tuple[str, ...]
    claim_type: str


@dataclass(frozen=True)
class NarrativeResult:
    text: str
    claims: tuple[GroundedClaim, ...]
    grounding_passed: bool
    rejected_claims: tuple[str, ...]
    method: str = "deterministic_evidence_template"
    llm_status: str = "NOT_REQUESTED"


class NarrativeEngine:
    """Render only approved templates from the current diagnosis payload."""

    def __init__(self, api_key: str | None = None,
                 llm_client: Callable[[list[list[str]]], dict[str, Any]] | None = None):
        self.api_key = api_key
        self.llm_client = llm_client

    @staticmethod
    def _variants(claim: 'GroundedClaim', payload: dict) -> tuple[str, ...]:
        reconciliation = payload.get('reconciliation_verdict') or {}
        recon_status = reconciliation.get('status', '')
        alternatives = {
            "SOURCE_STATUS": lambda: (
                f"No independent comparison is configured for {payload.get('kpi_id', 'this KPI')}."
                if recon_status == "NOT_APPLICABLE" else
                "Independent finance comparison was not available for this period; "
                "the movement is based on the governed operational source."
                if recon_status == "NOT_AVAILABLE_FOR_PERIOD" else
                f"{(reconciliation.get('details') or {}).get('reason', 'Finance close is not yet due for this period')}; "
                "the movement is based on the governed operational source."
                if recon_status == "PENDING_CLOSE" else
                f"The comparable source agrees within tolerance (gap: {reconciliation.get('gap_pct', 'n/a')}%)."
                if recon_status == "AGREED" else
                f"The comparable source shows a gap of {reconciliation.get('gap_pct', 'n/a')}% — "
                "within DRIFT range; conclusions are qualified."
                if recon_status == "DRIFT" else
                f"The source comparison is {recon_status}."
            ),
            "OBSERVED_MOVEMENT": lambda: (
                f"On {payload['target_date']}, {payload['kpi_id']} moved by "
                f"{payload['movement_assessment']['delta']} in its declared unit."
            ),
            "MATERIALITY": lambda: "Statistical and business-materiality thresholds both passed.",
            "ACCOUNTING_NOT_CAUSAL": lambda: (
                f"The exact accounting bridge totals {payload['decomposition']['total_delta']} "
                "in the KPI unit; it does not establish a cause."
            ),
            "CORRELATIONAL": lambda: (
                f"Treat {claim.text.split(' is a correlational candidate')[0]} as a correlational hypothesis only."
            ),
            "ATTRIBUTED_DRIVER": lambda: (
                f"{_driver_subject(claim.text)}'s share of the movement is a statistical "
                "estimate from the regression fit, not a proven cause."
            ),
            "CORROBORATION": lambda: (
                f"{_corroboration_subject(claim.text)} also appears in the governed evidence "
                "corpus; a document's stance is context, not a cause."
            ),
            "FUNNEL_BRIDGE": lambda: (
                f"The funnel bridge totals {payload.get('funnel_bridge', {}).get('total_delta')} "
                "in the KPI unit; it explains where the movement happened, not why."
            ),
            "OBSERVATIONAL": lambda: (
                f"The observational check is {payload['causal_verification']['verdict']}; "
                "causation remains unproven."
            ),
        }
        alternative = alternatives.get(claim.claim_type)
        return (claim.text, alternative()) if alternative else (claim.text,)

    def _request_llm(self, options: list[list[str]]) -> dict[str, Any]:
        if self.llm_client is not None:
            return self.llm_client(options)
        if not self.api_key:
            raise RuntimeError("No LLM provider configured")
        endpoint = f"{os.getenv('GROQ_BASE_URL', 'https://api.groq.com/openai/v1').rstrip('/')}" \
            "/chat/completions"
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        body = json.dumps({
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": (
                    "Choose one approved wording for each sentence, in order. "
                    "Return JSON with only a variants array of zero-based option indexes. "
                    "Do not write prose, add claims, or change the number of sentences."
                )},
                {"role": "user", "content": json.dumps({"options": options})},
            ],
        }).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                   "User-Agent": "kpi-engine/1.0"}
        request = Request(
            endpoint, data=body,
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            answer = json.load(response)
        selected = json.loads(answer["choices"][0]["message"]["content"])
        usage = answer.get("usage") or {}
        if isinstance(selected, dict) and usage:
            selected["_usage"] = {
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            }
        return selected

    @staticmethod
    def _kpi_unit(payload: dict[str, Any]) -> str | None:
        """The KPI's declared business unit, read from the contract snapshot."""
        thresholds = ((payload.get("contract_snapshot") or {}).get("materiality") or {}).get("business_thresholds") or {}
        unit = thresholds.get("unit")
        return unit if isinstance(unit, str) and unit.strip() else None

    @staticmethod
    def _confidence_phrase(candidate: dict[str, Any]) -> str:
        """`confidence 78% (Likely a contributing cause)`, or an explicit refusal."""
        value = candidate.get("attribution_confidence")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            return "Attribution Confidence was not computed for this driver"
        label = candidate.get("label") or candidate.get("band") or "unbanded"
        percent = min(value * 100, 99.9)
        formatted = f"{percent:.1f}" if value >= 0.995 else f"{percent:.0f}"
        return f"confidence {formatted}% ({label})"

    @classmethod
    def _attributed_driver_claim(cls, payload: dict[str, Any], candidate: dict[str, Any]) -> str:
        """The per-driver attribution sentence, with the Stage 8 causal-wording gate.

        `likely caused` appears only when this driver carries AC >= 0.6 *and* the
        causal test on this driver returned SUPPORTED_CONDITIONAL. Every other
        case, including a high AC with an untested driver, reads as an
        association. The verb is derived here and nowhere else, so validate()
        can rebuild the same sentence and reject any other phrasing.
        """
        name = candidate.get("display_name", candidate["driver_id"])
        share = candidate.get("explained_share")
        share_text = "an unmeasured share" if share is None else f"~{share * 100:.0f}%"
        contribution = candidate.get("contribution")
        unit = cls._kpi_unit(payload)
        contribution_text = (
            f" ({contribution}{f' {unit}' if unit else ' in the KPI unit'})"
            if contribution is not None else ""
        )
        if _causal_wording_allowed(candidate, payload):
            return (
                f"{name} {CAUSAL_PHRASE} {share_text} of the movement{contribution_text}; "
                f"{cls._confidence_phrase(candidate)}."
            )
        return (
            f"{name} {ASSOCIATED_PHRASE} {share_text} of the movement{contribution_text}; "
            f"{cls._confidence_phrase(candidate)}."
        )

    @staticmethod
    def _corroboration_claim(payload: dict[str, Any], candidate: dict[str, Any]) -> str | None:
        """A citation claim for the driver's unstructured evidence, or None.

        Documents are named by id only, and only the ones corroborate.py already
        filtered by availability, scope and entitlement. A document's presence
        never upgrades an association into a cause, so neither wording asserts
        one.
        """
        corroboration = candidate.get("corroboration") or {}
        status = corroboration.get("status")
        if status not in CORROBORATION_STATUSES:
            return None
        documents = [
            document.get("doc_id")
            for document in (corroboration.get("documents") or [])[:CORROBORATION_DOC_LIMIT]
            if isinstance(document, dict) and document.get("doc_id")
        ]
        if not documents:
            return None
        name = candidate.get("display_name", candidate["driver_id"])
        verb = "corroborated by" if status == "CORROBORATED" else "contradicted by"
        return (
            f"{name} is {verb} {len(documents)} governed document"
            f"{'s' if len(documents) > 1 else ''} ({', '.join(documents)})."
        )

    @classmethod
    def _driver_claims(
        cls, payload: dict[str, Any], ranked_drivers: Sequence[dict[str, Any]],
        container: str,
    ) -> list[tuple[str | None, list['GroundedClaim']]]:
        """One group of claims per ranked driver, in payload order.

        A correlated driver yields one CORRELATIONAL claim. An attributed driver
        yields its ATTRIBUTED_DRIVER claim and, when the Stage 6 corroborator
        found stance-bearing documents, one CORROBORATION claim. The two travel
        together as a group so persona reordering and truncation can never keep
        a document citation whose driver claim was dropped. The group carries
        its driver id so persona lever-family ordering needs no path parsing.
        """
        groups: list[tuple[str | None, list[GroundedClaim]]] = []
        for index, candidate in enumerate(ranked_drivers):
            if container == "driver_analysis":
                evidence_paths = (
                    f"driver_analysis.ranked_drivers.{index}.driver_id",
                    f"driver_analysis.ranked_drivers.{index}.relationship_type",
                )
                corroboration_path = f"driver_analysis.ranked_drivers.{index}.corroboration.status"
            else:
                evidence_paths = (
                    f"correlational_candidates.{index}.driver_id",
                    f"correlational_candidates.{index}.claim_type",
                )
                corroboration_path = f"correlational_candidates.{index}.corroboration.status"
            if candidate.get("relationship_type") == "ATTRIBUTION":
                claim_text = cls._attributed_driver_claim(payload, candidate)
                claim_type = "ATTRIBUTED_DRIVER"
            elif container == "driver_analysis":
                claim_text = (
                    f"{candidate.get('display_name', candidate['driver_id'])} is a ranked association only, "
                    "not an accounting contribution or causal estimate."
                )
                claim_type = "CORRELATIONAL"
            else:
                claim_text = f"{candidate['driver_id']} is a correlational candidate, not an established cause."
                claim_type = "CORRELATIONAL"
            claims = [GroundedClaim(claim_text, evidence_paths, claim_type)]
            corroboration = cls._corroboration_claim(payload, candidate)
            if corroboration is not None:
                claims.append(GroundedClaim(corroboration, (corroboration_path,), "CORROBORATION"))
            groups.append((candidate.get("driver_id"), claims))
        return groups

    @staticmethod
    def _clarification_claim(payload: dict[str, Any]) -> GroundedClaim | None:
        """Ask the reader to disambiguate instead of naming a cause.

        Emitted only when Stage 7's ambiguity rule fired and there is at least
        one ranked driver to disambiguate between. This is the one claim type
        that exists to make the engine say less.
        """
        status = (payload.get("confidence_profile") or {}).get("attribution_status")
        if status not in {"AMBIGUOUS", "NO_CONFIDENT_DRIVER"}:
            return None
        if not ((payload.get("driver_analysis") or {}).get("ranked_drivers")):
            return None
        if status == "AMBIGUOUS":
            text = (
                "Two or more drivers have similar Attribution Confidence, so the engine is not "
                "naming a single cause; confirm which one to verify first."
            )
        else:
            text = (
                "No ranked driver reached a confident Attribution Confidence, so the engine is not "
                "naming a cause; confirm which lever to verify first."
            )
        return GroundedClaim(text, ("confidence_profile.attribution_status",), "CLARIFICATION_REQUEST")

    @staticmethod
    def _order_for_persona(
        groups: Sequence[tuple[list['GroundedClaim'], tuple[int, int]]],
        persona_cfg: PersonaConfig,
    ) -> tuple['GroundedClaim', ...]:
        """Select and order claim groups for one persona (Stage 8-lite).

        Each group is a list of claims plus the tail of its sort key: the lever
        family priority (0 for every non-driver group) and the payload position
        that breaks ties inside a family. The key's head is the earliest
        `claim_order` slot any of the group's *readable* claim types occupies, so
        a group survives as long as the persona reads one of its claims and sits
        where that claim type belongs.

        This is the only place persona selection, order and truncation happen.
        It cannot change a claim's text, its evidence paths or its type, so
        `validate` rebuilding the same set with the same config is a real check
        and not a tautology.
        """
        ordered: list[tuple[tuple[int, int, int], int, 'GroundedClaim']] = []
        for position, (claims, tail) in enumerate(groups):
            ranks = [
                persona_cfg.claim_rank(claim.claim_type)
                for claim in claims if persona_cfg.reads(claim.claim_type)
            ]
            if not ranks:
                continue
            primary = min(ranks)
            for claim in claims:
                if persona_cfg.reads(claim.claim_type):
                    ordered.append(((primary, tail[0], tail[1]), position, claim))
        ordered.sort(key=lambda entry: (entry[0], entry[1]))
        return tuple(claim for _, _, claim in ordered)

    @staticmethod
    def _claims(payload: dict[str, Any], persona_cfg: PersonaConfig | None = None) -> tuple['GroundedClaim', ...]:
        """The approved claims for this payload and persona.

        `persona_cfg` defaults to the persona named in the payload, so `validate`
        rebuilds exactly the set `render` built. It only changes selection, order
        and wording: every fact below is read out of the payload.
        """
        persona_cfg = persona_cfg or load_persona(payload.get("persona"))
        # Each entry is (claims, sort-key tail) = (lever family priority, payload
        # position). The key's head is filled in by _order_for_persona.
        groups: list[tuple[list[GroundedClaim], tuple[int, int]]] = []

        def add(claim: GroundedClaim) -> None:
            groups.append(([claim], (0, len(groups))))

        verdict = payload.get("verdict")
        reconciliation = payload.get("reconciliation_verdict")
        if verdict == "ACCESS_DENIED":
            return (GroundedClaim(
                "Access to the requested KPI slice was denied; no diagnostic evidence is shown.",
                ("verdict",), "ACCESS_BOUNDARY",
            ),)
        if reconciliation is not None:
            status = reconciliation["status"]
            # Per-status source claim wording
            if status == "NOT_APPLICABLE":
                claim_text = (
                    f"No independent comparison is configured for {payload.get('kpi_id', 'this KPI')}; "
                    "movement is based on the governed operational source."
                )
            elif status == "NOT_AVAILABLE_FOR_PERIOD":
                claim_text = (
                    "Independent finance comparison was not available for this period; "
                    "the movement is based on the governed operational source."
                )
            elif status == "PENDING_CLOSE":
                reason = (reconciliation.get("details") or {}).get("reason", "Finance close is not yet due for this period")
                claim_text = f"{reason}; the movement is based on the governed operational source."
            elif status == "AGREED":
                recon = payload.get('reconciliation_verdict') or {}
                gap = recon.get('gap_pct', 'n/a')
                claim_text = f"The comparable source agrees within tolerance (gap: {gap}%)."
            elif status == "DRIFT":
                recon = payload.get('reconciliation_verdict') or {}
                gap = recon.get('gap_pct', 'n/a')
                claim_text = (
                    f"The comparable source shows a gap of {gap}% — "
                    "within DRIFT range; conclusions are qualified."
                )
            else:  # CONTRADICTED or unknown
                claim_text = f"Source reconciliation status: {status}."
            add(GroundedClaim(
                claim_text,
                ("reconciliation_verdict.status",), "SOURCE_STATUS",
            ))
        if verdict == "CONTRADICTED":
            add(GroundedClaim(
                "The sources contradict each other, so no cause is diagnosed.",
                ("verdict", "reconciliation_verdict.status"), "ABSTENTION",
            ))
            return NarrativeEngine._order_for_persona(groups, persona_cfg)

        kpi = payload.get("kpi_id")
        movement = payload.get("movement_assessment")
        if movement is not None and movement.get("status") == "OK":
            delta = movement["delta"]
            add(GroundedClaim(
                f"{kpi} changed by {delta} in its declared unit on {payload['target_date']}.",
                ("kpi_id", "movement_assessment.delta", "target_date"),
                "OBSERVED_MOVEMENT",
            ))
            if movement["is_material"]:
                add(GroundedClaim(
                    "The change passed both statistical and business-materiality checks.",
                    ("movement_assessment.is_statistically_significant",
                     "movement_assessment.is_business_material",
                     "movement_assessment.is_material"), "MATERIALITY",
                ))
            elif verdict == "SEASONAL_REVIEW":
                add(GroundedClaim(
                    "Only the seasonal detector flagged this movement; it requires review, not a cause claim.",
                    ("movement_assessment.detector_agreement", "verdict"), "REVIEW",
                ))
            else:
                add(GroundedClaim(
                    "This change did not meet both materiality checks; no cause is diagnosed.",
                    ("movement_assessment.is_material", "verdict"), "ABSTENTION",
                ))
        elif verdict and verdict != "EVENT_ASSESSED_CAUSE_UNVERIFIED":
            add(GroundedClaim(
                f"Assessment stopped with status {verdict}; no cause is diagnosed.",
                ("verdict",), "ABSTENTION",
            ))

        if payload.get("decomposition_status") == "IDENTITY_HELD":
            bridge = payload["decomposition"]
            add(GroundedClaim(
                f"The accounting bridge reconciles to a change of {bridge['total_delta']} in the KPI unit.",
                ("decomposition_status", "decomposition.total_delta",
                 "decomposition.is_identity_held"), "ACCOUNTING_NOT_CAUSAL",
            ))
        if payload.get("funnel_bridge_status") == "IDENTITY_HELD":
            funnel = payload["funnel_bridge"]
            add(GroundedClaim(
                f"The funnel bridge reconciles to a change of {funnel['total_delta']} in the KPI unit "
                "across traffic, conversion and basket size.",
                ("funnel_bridge_status", "funnel_bridge.total_delta",
                 "funnel_bridge.identity_held"), "FUNNEL_BRIDGE",
            ))
        driver_analysis = payload.get("driver_analysis") or {}
        ranked_drivers = driver_analysis.get("ranked_drivers") or payload.get("correlational_candidates", [])
        if driver_analysis.get("status") in BLOCKED_DRIVER_STATUSES:
            ranked_drivers = []
        container = "driver_analysis" if driver_analysis else "correlational_candidates"
        # Stage 8-lite, driver block: order lever families first, then the
        # payload's own rank, then drop everything past max_driver_claims. The cap
        # is applied to whole driver groups, so a corroboration citation can
        # never outlive the attribution sentence it belongs to.
        driver_groups = NarrativeEngine._driver_claims(payload, ranked_drivers, container)
        driver_groups.sort(key=lambda entry: (
            persona_cfg.lever_priority(lever_family(entry[0])),
            next(
                (position for position, item in enumerate(ranked_drivers)
                 if item.get("driver_id") == entry[0]),
                len(ranked_drivers),
            ),
        ))
        for _driver_id, claims in driver_groups[: persona_cfg.max_driver_claims]:
            groups.append((claims, (persona_cfg.lever_priority(lever_family(_driver_id)), len(groups))))
        verification = payload.get("causal_verification")
        if verification is not None:
            add(GroundedClaim(
                f"Observational verification: {verification['verdict']}. This does not prove causation.",
                ("causal_verification.verdict",), "OBSERVATIONAL",
            ))
        clarification = NarrativeEngine._clarification_claim(payload)
        if clarification is not None:
            add(clarification)
        if verdict == "EVENT_ASSESSED_CAUSE_UNVERIFIED":
            add(GroundedClaim(
                f"The event window ended on {payload['post_end']}; the final-day alert was not required.",
                ("post_end", "verdict"), "EVENT_WINDOW",
            ))
        return NarrativeEngine._order_for_persona(groups, persona_cfg)

    @staticmethod
    def _resolve(payload: dict[str, Any], path: str) -> Any:
        value: Any = payload
        for part in path.split("."):
            value = value[int(part)] if isinstance(value, (list, tuple)) else value[part]
        return value

    @staticmethod
    def _causal_wording_claim(claim: 'GroundedClaim', payload: dict[str, Any]) -> bool:
        """Does the cited driver actually earn `likely caused`?

        The driver is taken from the claim's own evidence path rather than from
        claim text, so this cannot be satisfied by a sentence that merely names a
        high-confidence driver. A path that does not resolve is not a pass.
        """
        for path in claim.evidence_paths:
            if not path.endswith("driver_id"):
                continue
            try:
                # The cited path ends in the scalar id. Check its parent
                # record, which carries Attribution Confidence and the
                # driver-specific causal gate.
                driver = NarrativeEngine._resolve(payload, path.rsplit(".", 1)[0])
            except (KeyError, IndexError, TypeError, ValueError):
                return False
            if isinstance(driver, dict) and _causal_wording_allowed(driver, payload):
                return True
        return False

    def validate(self, payload: dict[str, Any], claims: tuple[GroundedClaim, ...]) -> tuple[bool, tuple[str, ...]]:
        """Only exact, evidence-resolving approved claims can pass."""
        expected = self._claims(payload)
        errors = []
        movement = payload.get("movement_assessment")
        if movement and movement.get("is_material") and not (
            movement.get("is_statistically_significant")
            and movement.get("is_business_material")
        ):
            errors.append("Materiality claim conflicts with its underlying checks")
        if payload.get("decomposition_status") == "IDENTITY_HELD" and not (
            payload.get("decomposition") or {}
        ).get("is_identity_held"):
            errors.append("Accounting identity is not supported")
        if payload.get("funnel_bridge_status") == "IDENTITY_HELD" and not (
            payload.get("funnel_bridge") or {}
        ).get("identity_held"):
            errors.append("Funnel bridge identity is not supported")
        driver_analysis = payload.get("driver_analysis") or {}
        ranked_drivers = driver_analysis.get("ranked_drivers") or payload.get("correlational_candidates", [])
        if driver_analysis.get("status") in {"BLOCKED", "INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE", "EXPLORATORY_NON_MATERIAL"}:
            ranked_drivers = []
        for candidate in ranked_drivers:
            if candidate.get("relationship_type") == "ATTRIBUTION":
                if candidate.get("claim_type") != "ATTRIBUTED_DRIVER":
                    errors.append("Attributed driver is not labeled as an attribution")
            elif candidate.get("claim_type") != "CORRELATIONAL":
                if candidate.get("relationship_type") != "ASSOCIATION":
                    errors.append("Driver ranking is not labeled association-only")
        if driver_analysis.get("status") == "BLOCKED" and driver_analysis.get("ranked_drivers"):
            errors.append("Blocked driver analysis contains ranked drivers")
        verification = payload.get("causal_verification")
        if verification and verification.get("verdict") != payload.get("causal_verdict"):
            errors.append("Causal verdict conflicts with verification evidence")
        if payload.get("verdict") == "CONTRADICTED" and (
            payload.get("reconciliation_verdict") or {}
        ).get("status") != "CONTRADICTED":
            errors.append("Contradiction verdict lacks source evidence")
        if len(claims) != len(expected):
            errors.append("Claim count differs from the approved evidence narrative")
        for index, claim in enumerate(claims):
            if (index >= len(expected)
                    or claim.evidence_paths != expected[index].evidence_paths
                    or claim.claim_type != expected[index].claim_type
                    or claim.text not in self._variants(expected[index], payload)):
                errors.append(f"Claim {index} is not an approved evidence-bound statement")
                continue
            if claim.claim_type == "ATTRIBUTED_DRIVER" and CAUSAL_PHRASE in claim.text:
                # A rewording (LLM variant or injected claim) must not smuggle a
                # causal verb past the Stage 8 gate that built the sentence.
                if not self._causal_wording_claim(claim, payload):
                    errors.append(
                        f"Claim {index} asserts a cause without a supported causal test"
                    )
                    continue
            try:
                for path in claim.evidence_paths:
                    self._resolve(payload, path)
            except (KeyError, IndexError, TypeError, ValueError):
                errors.append(f"Claim {index} cites unavailable evidence")
        return not errors, tuple(errors)

    def render(self, payload: dict[str, Any]) -> dict[str, Any]:
        claims = self._claims(payload)
        passed, errors = self.validate(payload, claims)
        if not passed:
            return asdict(NarrativeResult("", (), False, errors))
        status = "NOT_REQUESTED"
        method = "deterministic_evidence_template"
        runtime = {
            "attempted": False, "latency_ms": 0.0, "provider": None, "model": None,
            "model_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "usage_source": "NOT_APPLICABLE",
        }
        if claims and payload.get("verdict") != "ACCESS_DENIED" and (self.llm_client or self.api_key):
            started = time.monotonic_ns()
            runtime.update({
                "attempted": True, "provider": "groq" if self.api_key else "injected",
                "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b") if self.api_key else "injected",
                "model_calls": 1,
            })
            try:
                options = [list(self._variants(claim, payload)) for claim in claims]
                proposal = self._request_llm(options)
                usage = proposal.pop("_usage", None) if isinstance(proposal, dict) else None
                if isinstance(usage, dict) and usage.get("input_tokens") is not None and usage.get("output_tokens") is not None:
                    runtime.update(input_tokens=int(usage["input_tokens"]), output_tokens=int(usage["output_tokens"]), usage_source="PROVIDER_REPORTED")
                else:
                    runtime.update(input_tokens=None, output_tokens=None, usage_source="UNAVAILABLE")
                selections = proposal.get("variants") if isinstance(proposal, dict) and set(proposal) == {"variants"} else None
                if (not isinstance(selections, list) or len(selections) != len(claims)
                        or any(type(choice) is not int or choice < 0 or choice >= len(options[index])
                               for index, choice in enumerate(selections))):
                    status = "REJECTED"
                else:
                    candidate = tuple(replace(claim, text=options[index][choice])
                                      for index, (claim, choice) in enumerate(zip(claims, selections)))
                    approved, _ = self.validate(payload, candidate)
                    if approved:
                        claims, status, method = candidate, "USED", "llm_selected_approved_templates"
                    else:
                        status = "REJECTED"
            except Exception:
                status = "ERROR_FALLBACK"
                runtime.update(input_tokens=None, output_tokens=None, usage_source="UNAVAILABLE")
            finally:
                runtime["latency_ms"] = round(max(0.0, (time.monotonic_ns() - started) / 1_000_000), 3)
        rendered = asdict(NarrativeResult(
            " ".join(item.text for item in claims), claims, True, (), method, status,
        ))
        rendered["runtime_telemetry"] = runtime
        return rendered
