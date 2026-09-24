"""Deterministic, evidence-bound diagnosis narrative.

This renderer accepts no arbitrary prose. Validation rebuilds the permitted
claims from the evidence payload, so changed numbers, entities, or causal
language cannot pass merely because some matching token exists elsewhere.
"""

from dataclasses import asdict, dataclass, replace
import json
from typing import Any, Callable
from urllib.request import Request, urlopen


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
    def _variants(claim: GroundedClaim, payload: dict[str, Any]) -> tuple[str, ...]:
        alternatives = {
            "SOURCE_STATUS": lambda: f"The source comparison is {payload['reconciliation_verdict']['status']}.",
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
        body = json.dumps({
            "model": "openai/gpt-oss-20b",
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
        request = Request(
            "https://api.groq.com/openai/v1/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            answer = json.load(response)
        return json.loads(answer["choices"][0]["message"]["content"])

    @staticmethod
    def _claims(payload: dict[str, Any]) -> tuple[GroundedClaim, ...]:
        claims = []
        verdict = payload.get("verdict")
        reconciliation = payload.get("reconciliation_verdict")
        if verdict == "ACCESS_DENIED":
            return (GroundedClaim(
                "Access to the requested KPI slice was denied; no diagnostic evidence is shown.",
                ("verdict",), "ACCESS_BOUNDARY",
            ),)
        if reconciliation is not None:
            status = reconciliation["status"]
            claims.append(GroundedClaim(
                f"Source reconciliation status: {status}.",
                ("reconciliation_verdict.status",), "SOURCE_STATUS",
            ))
        if verdict == "CONTRADICTED":
            claims.append(GroundedClaim(
                "The sources contradict each other, so no cause is diagnosed.",
                ("verdict", "reconciliation_verdict.status"), "ABSTENTION",
            ))
            return tuple(claims)

        kpi = payload.get("kpi_id")
        movement = payload.get("movement_assessment")
        if movement is not None and movement.get("status") == "OK":
            delta = movement["delta"]
            claims.append(GroundedClaim(
                f"{kpi} changed by {delta} in its declared unit on {payload['target_date']}.",
                ("kpi_id", "movement_assessment.delta", "target_date"),
                "OBSERVED_MOVEMENT",
            ))
            if movement["is_material"]:
                claims.append(GroundedClaim(
                    "The change passed both statistical and business-materiality checks.",
                    ("movement_assessment.is_statistically_significant",
                     "movement_assessment.is_business_material",
                     "movement_assessment.is_material"), "MATERIALITY",
                ))
            elif verdict == "SEASONAL_REVIEW":
                claims.append(GroundedClaim(
                    "Only the seasonal detector flagged this movement; it requires review, not a cause claim.",
                    ("movement_assessment.detector_agreement", "verdict"), "REVIEW",
                ))
            else:
                claims.append(GroundedClaim(
                    "This change did not meet both materiality checks; no cause is diagnosed.",
                    ("movement_assessment.is_material", "verdict"), "ABSTENTION",
                ))
        elif verdict and verdict != "EVENT_ASSESSED_CAUSE_UNVERIFIED":
            claims.append(GroundedClaim(
                f"Assessment stopped with status {verdict}; no cause is diagnosed.",
                ("verdict",), "ABSTENTION",
            ))

        if payload.get("decomposition_status") == "IDENTITY_HELD":
            bridge = payload["decomposition"]
            claims.append(GroundedClaim(
                f"The accounting bridge reconciles to a change of {bridge['total_delta']} in the KPI unit.",
                ("decomposition_status", "decomposition.total_delta",
                 "decomposition.is_identity_held"), "ACCOUNTING_NOT_CAUSAL",
            ))
        for index, candidate in enumerate(payload.get("correlational_candidates", [])):
            claims.append(GroundedClaim(
                f"{candidate['driver_id']} is a correlational candidate, not an established cause.",
                (f"correlational_candidates.{index}.driver_id",
                 f"correlational_candidates.{index}.claim_type"), "CORRELATIONAL",
            ))
        verification = payload.get("causal_verification")
        if verification is not None:
            status = verification["verdict"]
            claims.append(GroundedClaim(
                f"Observational verification: {status}. This does not prove causation.",
                ("causal_verification.verdict",), "OBSERVATIONAL",
            ))
        if verdict == "EVENT_ASSESSED_CAUSE_UNVERIFIED":
            claims.append(GroundedClaim(
                f"The event window ended on {payload['post_end']}; the final-day alert was not required.",
                ("post_end", "verdict"), "EVENT_WINDOW",
            ))
        return tuple(claims)

    @staticmethod
    def _resolve(payload: dict[str, Any], path: str) -> Any:
        value: Any = payload
        for part in path.split("."):
            value = value[int(part)] if isinstance(value, (list, tuple)) else value[part]
        return value

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
        for candidate in payload.get("correlational_candidates", []):
            if candidate.get("claim_type") != "CORRELATIONAL":
                errors.append("Driver ranking is not labeled correlational")
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
        if claims and payload.get("verdict") != "ACCESS_DENIED" and (self.llm_client or self.api_key):
            try:
                options = [list(self._variants(claim, payload)) for claim in claims]
                proposal = self._request_llm(options)
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
        return asdict(NarrativeResult(
            " ".join(item.text for item in claims), claims, True, (), method, status,
        ))
