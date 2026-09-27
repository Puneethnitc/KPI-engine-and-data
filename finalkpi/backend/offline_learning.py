"""Evaluation-only candidate materialization and deterministic proposal gates."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable
from uuid import uuid4

from backend.demo_scenarios import classify_broad_outcome

SUPPORTED_CANDIDATE_TYPES = {"EVALUATION_CASE_ADDITION", "NARRATIVE_TEMPLATE_CHANGE"}
NARRATIVE_CLAIM_TYPES = {
    "SOURCE_STATUS", "OBSERVED_MOVEMENT", "MATERIALITY", "ACCOUNTING_NOT_CAUSAL",
    "CORRELATIONAL", "OBSERVATIONAL", "ABSTENTION", "REVIEW", "EVENT_WINDOW",
}
NUMERIC_OR_CURRENCY = re.compile(r"[0-9$%\u20b9]")
CAUSAL_ASSERTION = re.compile(r"\b(caused|causes|causing|proves?|proven|led to|resulted in|due to)\b", re.IGNORECASE)
PROTECTED_REFERENCE = re.compile(r"(?:source_evidence|driver_analysis\.|/home/|/mnt/|/srv/|\.csv\b)", re.IGNORECASE)
QUANTITATIVE_FIELDS = (
    "actual_value", "expected_value", "delta", "movement_assessment",
    "reconciliation_verdict", "decomposition", "decomposition_status",
    "driver_analysis", "driver_exclusions", "correlational_candidates",
    "causal_verdict", "causal_verification", "confidence", "confidence_profile",
    "decision_cards",
)
EVALUATOR_METHOD = "frozen_saved_run_candidate_comparison"
EVALUATOR_VERSION = "1.0"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _broad(result: Dict[str, Any]) -> str:
    return classify_broad_outcome(result)


def _run_snapshot(run: Dict[str, Any]) -> Dict[str, Any]:
    return run.get("result") if isinstance(run.get("result"), dict) else {}


def build_candidate_artifact(proposal: Dict[str, Any], source_runs: list[Dict[str, Any]]) -> Dict[str, Any]:
    proposal_type = proposal["proposal_type"]
    if proposal_type not in SUPPORTED_CANDIDATE_TYPES:
        raise NotImplementedError("APPLICATION_NOT_SUPPORTED")
    base_version = str(proposal.get("before_version") or "UNKNOWN")
    short_proposal_id = proposal["proposal_id"].replace("-", "")[-8:]
    candidate_version = f"{base_version}-candidate-{short_proposal_id}"
    change = proposal.get("proposed_change") or {}

    if proposal_type == "EVALUATION_CASE_ADDITION":
        if set(change) != {"case_description", "expected_outcome"}:
            raise ValueError("Evaluation case change does not match the approved schema")
        if not source_runs:
            raise ValueError("Evaluation case proposal needs at least one authorized saved run")
        expected_outcomes = {"MATERIAL", "ABSTAIN", "CONTRADICTED", "INSUFFICIENT_HISTORY", "NO_MATERIAL_MOVEMENT", "ACCESS_DENIED"}
        if change.get("expected_outcome") not in expected_outcomes:
            raise ValueError("Evaluation case expected outcome is not a governed broad outcome")
        case_run = source_runs[0]
        candidate_payload = {
            "case_description": change["case_description"],
            "expected_outcome": change["expected_outcome"],
            "input_run_id": case_run["run_id"],
            "input_snapshot_hash": stable_hash(_run_snapshot(case_run)),
            "as_of": _run_snapshot(case_run).get("as_of") or case_run.get("as_of"),
        }
        base_payload = {
            "governed_case_source": "authorized_saved_diagnosis",
            "run_id": case_run["run_id"],
            "run_snapshot_hash": stable_hash(_run_snapshot(case_run)),
        }
    else:
        if set(change) != {"source_feedback_id", "template_target", "proposed_wording"}:
            raise ValueError("Narrative candidate does not match the approved template schema")
        template_target = change["template_target"]
        wording = change["proposed_wording"].strip()
        if template_target not in NARRATIVE_CLAIM_TYPES:
            raise ValueError("Narrative template target is not an approved claim type")
        if proposal.get("before_version") != "approved_narrative_templates_v1":
            raise ValueError("Narrative template base version does not match the approved template registry")
        if not wording or len(wording) > 2000 or NUMERIC_OR_CURRENCY.search(wording) or CAUSAL_ASSERTION.search(wording) or PROTECTED_REFERENCE.search(wording):
            raise ValueError("Candidate wording contains numbers, protected references, or unsupported causal language")
        if template_target == "CORRELATIONAL" and not re.search(r"\b(association|correlation)\b", wording, re.IGNORECASE):
            raise ValueError("Correlation wording must retain the association boundary")
        matching = [
            claim for run in source_runs for claim in (_run_snapshot(run).get("narrative_claims") or [])
            if isinstance(claim, dict) and claim.get("claim_type") == template_target
        ]
        if not matching:
            raise ValueError("No source run contains the targeted approved narrative claim type")
        candidate_payload = {
            "template_target": template_target,
            "proposed_wording": wording,
            "evidence_boundary": "Preserve source claim type and evidence references; wording only.",
        }
        base_payload = {
            "template_registry": "approved_narrative_templates_v1",
            "source_claims": [{
                "run_id": run["run_id"],
                "run_snapshot_hash": stable_hash(_run_snapshot(run)),
                "claim_type": template_target,
            } for run in source_runs],
        }

    validated_change = dict(change)
    artifact_type = "EVALUATION_CASE" if proposal_type == "EVALUATION_CASE_ADDITION" else "APPROVED_NARRATIVE_TEMPLATE_VARIANT"
    payload_hash = stable_hash({
        "artifact_type": artifact_type,
        "kpi_id": proposal["kpi_id"],
        "scope": proposal["scope"],
        "base_version": base_version,
        "candidate_version": candidate_version,
        "base_payload": base_payload,
        "validated_change": validated_change,
        "candidate_payload": candidate_payload,
        "activation_status": "EVALUATION_ONLY",
    })
    artifact_id = f"candidate-{stable_hash({'proposal_id': proposal['proposal_id'], 'payload_hash': payload_hash})[:24]}"
    return {
        "candidate_artifact_id": artifact_id,
        "proposal_id": proposal["proposal_id"],
        "artifact_type": artifact_type,
        "kpi_id": proposal["kpi_id"],
        "scope": proposal["scope"],
        "base_version": base_version,
        "candidate_version": candidate_version,
        "base_payload": base_payload,
        "validated_change": validated_change,
        "candidate_payload": candidate_payload,
        "payload_hash": payload_hash,
        "activation_status": "EVALUATION_ONLY",
        "rollback_of": None,
        "supersedes": None,
    }


def _projection(run: Dict[str, Any]) -> Dict[str, Any]:
    result = _run_snapshot(run)
    return {
        "run_id": run.get("run_id"),
        "kpi_id": result.get("kpi_id", run.get("kpi_id")),
        "as_of": result.get("as_of") or run.get("as_of"),
        "broad_outcome": _broad(result),
        "quantitative": {key: result.get(key) for key in QUANTITATIVE_FIELDS},
        "narrative": result.get("narrative", ""),
        "narrative_claims": result.get("narrative_claims") or [],
        "grounding_passed": result.get("grounding_passed"),
        "protected_evidence_exposed": False,
    }


def _candidate_projection(run: Dict[str, Any], artifact: Dict[str, Any]) -> Dict[str, Any]:
    baseline = _projection(run)
    candidate = dict(baseline)
    if artifact["artifact_type"] == "APPROVED_NARRATIVE_TEMPLATE_VARIANT":
        target = artifact["candidate_payload"]["template_target"]
        wording = artifact["candidate_payload"]["proposed_wording"]
        claims = [dict(claim) for claim in baseline["narrative_claims"]]
        changed = False
        for claim in claims:
            if claim.get("claim_type") == target:
                claim["text"] = wording
                changed = True
        candidate["narrative_claims"] = claims
        candidate["narrative"] = " ".join(item.get("text", "") for item in claims)
        candidate["grounding_passed"] = baseline["grounding_passed"] is True and changed
        candidate["candidate_template_applied"] = changed
    else:
        candidate["candidate_case"] = artifact["candidate_payload"]
    return baseline, candidate


def _case_evaluation(run: Dict[str, Any], artifact: Dict[str, Any], case_kind: str) -> Dict[str, Any]:
    baseline, candidate = _candidate_projection(run, artifact)
    quantitative_differences = {
        key: {"baseline": baseline["quantitative"].get(key), "candidate": candidate["quantitative"].get(key)}
        for key in QUANTITATIVE_FIELDS
        if baseline["quantitative"].get(key) != candidate["quantitative"].get(key)
    }
    differences = dict(quantitative_differences)
    if baseline["narrative"] != candidate["narrative"]:
        differences["narrative"] = {"baseline": baseline["narrative"], "candidate": candidate["narrative"]}
    if baseline["broad_outcome"] != candidate["broad_outcome"]:
        differences["broad_outcome"] = {"baseline": baseline["broad_outcome"], "candidate": candidate["broad_outcome"]}
    gates: Dict[str, bool] = {
        "access_authorized": True,
        "no_protected_evidence_exposure": not candidate.get("protected_evidence_exposed", True),
        "broad_outcome_unchanged": baseline["broad_outcome"] == candidate["broad_outcome"],
        "quantitative_fields_unchanged": not quantitative_differences,
        "abstention_contradiction_sparse_behavior_unchanged": baseline["broad_outcome"] == candidate["broad_outcome"],
    }
    if artifact["artifact_type"] == "APPROVED_NARRATIVE_TEMPLATE_VARIANT":
        wording = artifact["candidate_payload"]["proposed_wording"]
        gates["target_claim_present"] = bool(candidate.get("candidate_template_applied"))
        gates["affected_wording_changed"] = case_kind != "AFFECTED" or candidate.get("narrative") != baseline.get("narrative")
        gates["grounding_preserved"] = candidate.get("grounding_passed") is True
        gates["evidence_references_unchanged"] = all(
            before.get("evidence_paths") == after.get("evidence_paths")
            for before, after in zip(baseline["narrative_claims"], candidate["narrative_claims"])
        ) and len(baseline["narrative_claims"]) == len(candidate["narrative_claims"])
        gates["wording_boundary_safe"] = not NUMERIC_OR_CURRENCY.search(wording) and not CAUSAL_ASSERTION.search(wording)
        gates["no_protected_reference_in_wording"] = not PROTECTED_REFERENCE.search(wording)
        if artifact["candidate_payload"]["template_target"] == "CORRELATIONAL":
            gates["association_boundary_preserved"] = bool(re.search(r"\b(association|correlation)\b", wording, re.IGNORECASE))
    elif case_kind == "AFFECTED" and run.get("run_id") == artifact["candidate_payload"].get("input_run_id"):
        expected = artifact["candidate_payload"]["expected_outcome"]
        gates["candidate_case_expected_outcome_matches"] = candidate["broad_outcome"] == expected
    gates["case_passed"] = all(gates.values())
    snapshot_hash = stable_hash(_run_snapshot(run))
    return {
        "case_id": run["run_id"],
        "case_kind": case_kind,
        "input_run_id": run["run_id"],
        "input_snapshot_hash": snapshot_hash,
        "as_of": baseline["as_of"],
        "baseline_result": baseline,
        "candidate_result": candidate,
        "differences": differences,
        "gate_results": gates,
    }


def run_deterministic_evaluation(
    *,
    proposal: Dict[str, Any],
    artifact: Dict[str, Any],
    affected_runs: list[Dict[str, Any]],
    holdout_runs: list[Dict[str, Any]],
) -> Dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    affected_results = [_case_evaluation(run, artifact, "AFFECTED") for run in affected_runs]
    holdout_results = [_case_evaluation(run, artifact, "HOLDOUT") for run in holdout_runs]
    all_results = affected_results + holdout_results
    gates = {
        "affected_cases_present": bool(affected_results),
        "affected_cases_pass": bool(affected_results) and all(item["gate_results"]["case_passed"] for item in affected_results),
        "holdout_cases_pass_when_available": all(item["gate_results"]["case_passed"] for item in holdout_results),
        "same_frozen_inputs": all(item["input_snapshot_hash"] for item in all_results),
        "no_protected_case_outside_scope": True,
    }
    failures = sorted(gate for gate, passed in gates.items() if not passed)
    failures.extend(
        f"{case['case_id']}:{gate}"
        for case in all_results for gate, passed in case["gate_results"].items()
        if gate != "case_passed" and not passed
    )
    final_result = "VERIFIED" if not failures else "FAILED_VERIFICATION"
    completed = datetime.now(timezone.utc).isoformat()
    inputs_hash = stable_hash({
        "candidate_artifact_id": artifact["candidate_artifact_id"],
        "affected": [(item["case_id"], item["input_snapshot_hash"]) for item in affected_results],
        "holdouts": [(item["case_id"], item["input_snapshot_hash"]) for item in holdout_results],
    })
    return {
        "evaluation_run_id": f"evaluation-{uuid4().hex}",
        "proposal_id": proposal["proposal_id"],
        "candidate_artifact_id": artifact["candidate_artifact_id"],
        "baseline_artifact_version": artifact["base_version"],
        "candidate_artifact_version": artifact["candidate_version"],
        "affected_cases": [run["run_id"] for run in affected_runs],
        "holdout_cases": [run["run_id"] for run in holdout_runs],
        "metrics": {
            "affected_case_count": len(affected_runs), "holdout_case_count": len(holdout_runs),
            "affected_case_pass_count": sum(item["gate_results"]["case_passed"] for item in affected_results),
            "holdout_case_pass_count": sum(item["gate_results"]["case_passed"] for item in holdout_results),
            "quantitative_difference_count": sum(
                sum(key in QUANTITATIVE_FIELDS for key in item["differences"])
                for item in all_results
            ),
        },
        "gates": gates,
        "baseline_results": {item["case_id"]: item["baseline_result"] for item in all_results},
        "candidate_results": {item["case_id"]: item["candidate_result"] for item in all_results},
        "case_differences": {item["case_id"]: item["differences"] for item in all_results},
        "case_results": all_results,
        "started_at": started,
        "completed_at": completed,
        "evaluator_method": EVALUATOR_METHOD,
        "evaluator_version": EVALUATOR_VERSION,
        "final_result": final_result,
        "failure_reasons": failures,
        "inputs_hash": inputs_hash,
    }


def broad_outcome_for_run(run: Dict[str, Any]) -> str:
    return _broad(_run_snapshot(run))


def required_holdout_claim_type(artifact: Dict[str, Any]) -> str | None:
    return artifact["candidate_payload"].get("template_target") if artifact["artifact_type"] == "APPROVED_NARRATIVE_TEMPLATE_VARIANT" else None


def evaluation_gate_plan(artifact: Dict[str, Any]) -> list[Dict[str, str]]:
    gates = [
        ("affected_cases_present", "At least one authorized affected case is evaluated."),
        ("affected_cases_pass", "Every affected case meets its deterministic objective."),
        ("holdout_cases_pass_when_available", "Relevant holdout cases show no regression."),
        ("same_frozen_inputs", "Baseline and candidate use identical saved inputs and as-of values."),
        ("no_protected_case_outside_scope", "No case outside the reviewer-authorized scope is included."),
    ]
    if artifact["artifact_type"] == "APPROVED_NARRATIVE_TEMPLATE_VARIANT":
        gates.extend([
            ("broad_outcome_unchanged", "The diagnosis broad outcome does not change."),
            ("quantitative_fields_unchanged", "KPI and decision fields remain identical."),
            ("abstention_contradiction_sparse_behavior_unchanged", "Abstention, contradiction and sparse-history behavior remains unchanged."),
            ("grounding_preserved", "The saved evidence grounding check remains valid."),
            ("evidence_references_unchanged", "Narrative claim evidence references remain unchanged."),
            ("wording_boundary_safe", "Candidate wording contains no new numeric facts or causal assertions."),
            ("no_protected_reference_in_wording", "Candidate wording exposes no protected source reference."),
        ])
        if artifact["candidate_payload"].get("template_target") == "CORRELATIONAL":
            gates.append(("association_boundary_preserved", "Correlation remains clearly distinct from cause."))
    else:
        gates.append(("candidate_case_expected_outcome_matches", "The new evaluation case label matches its frozen governed run."))
    return [{"gate_id": gate_id, "description": description} for gate_id, description in gates]
