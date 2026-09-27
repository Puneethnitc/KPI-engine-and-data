from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "1.0"
QUANTITATIVE_POLICY = (
    "Quantitative truth comes from governed source data, deterministic business rules, "
    "statistical calculations, SQL when explicitly executed, and approved causal methods. "
    "LLMs may select approved wording only and never calculate KPI facts."
)


def _ref(result: dict[str, Any], *paths: str) -> list[str]:
    return [path for path in paths if _path_exists(result, path)]


def _path_exists(payload: Any, path: str) -> bool:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False
    return True


def _stage(
    stage_id: str,
    label: str,
    category: str,
    status: str,
    quantitative_truth: bool,
    purpose: str,
    method_id: str,
    refs: list[str] | None = None,
    limitation: str | None = None,
    llm_role: str | None = None,
) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "label": label,
        "method_category": category,
        "execution_status": status,
        "quantitative_truth": quantitative_truth,
        "purpose": purpose,
        "method_id": method_id,
        "evidence_refs": refs or [],
        "limitation": limitation,
        "llm_role": llm_role,
    }


def build_processing_transparency(
    result: dict[str, Any],
    *,
    causal_design_approved: bool = False,
) -> dict[str, Any]:
    """Build stable public processing provenance from the completed result."""
    denied = result.get("verdict") == "ACCESS_DENIED"
    if denied:
        stages = [
            _stage(
                "scope_contract_validation", "Scope and contract validation", "BUSINESS_RULE", "BLOCKED", False,
                "The requested diagnosis was blocked by access control.", "scope_contract_validation_v1",
            )
        ]
        return {
            "contract_version": CONTRACT_VERSION,
            "quantitative_truth_policy": QUANTITATIVE_POLICY,
            "stages": stages,
            "summary": {
                "quantitative_stages": 0,
                "llm_used": False,
                "retrieval_used": False,
                "sql_executed": False,
                "causal_method_used": False,
            },
        }

    source_refs = _ref(result, "source_evidence", "source_evidence.sources", "source_coverage")
    movement_refs = _ref(result, "movement_assessment")
    driver_refs = _ref(result, "driver_analysis.ranked_drivers", "driver_analysis.excluded_drivers")
    decomposition_refs = _ref(result, "decomposition", "decomposition_status")
    causal_refs = _ref(result, "causal_verification", "causal_verdict")
    confidence_refs = _ref(result, "confidence_profile")
    action_refs = _ref(result, "decision_cards")
    narrative_refs = _ref(result, "narrative_claims", "narrative")

    reconciliation = result.get("reconciliation_verdict")
    driver_analysis = result.get("driver_analysis")
    decomposition_status = result.get("decomposition_status")
    llm_status = result.get("llm_status", "NOT_REQUESTED")
    narrative_method = result.get("narrative_method", "deterministic_evidence_template")

    if causal_design_approved and isinstance(result.get("causal_verification"), dict):
        causal_status = "USED"
    elif result.get("verdict") == "CONTRADICTED":
        causal_status = "BLOCKED"
    else:
        causal_status = "NOT_REQUESTED"

    if isinstance(driver_analysis, dict):
        analysis_status = driver_analysis.get("status")
        if analysis_status == "BLOCKED":
            driver_status = "BLOCKED"
        elif analysis_status in {"ASSESSED", "COMPLETED"}:
            driver_status = "USED"
        else:
            driver_status = "SKIPPED"
    else:
        driver_status = "SKIPPED"

    if decomposition_status == "NOT_EVALUATED" or decomposition_status is None:
        decomposition_execution = "SKIPPED"
    else:
        decomposition_execution = "USED"

    if llm_status == "USED":
        narrative_execution = "USED"
        llm_execution = "USED"
        llm_limitation = "The LLM selected approved wording variants only; it did not create quantitative facts."
    elif llm_status in {"REJECTED", "ERROR_FALLBACK"}:
        narrative_execution = "FALLBACK"
        llm_execution = "FALLBACK"
        llm_limitation = "Optional LLM wording was rejected or failed; deterministic approved wording was retained."
    elif narrative_method == "deterministic_evidence_template":
        narrative_execution = "USED"
        llm_execution = "NOT_REQUESTED"
        llm_limitation = "No narrative LLM was requested or configured."
    else:
        narrative_execution = "USED"
        llm_execution = "UNAVAILABLE"
        llm_limitation = "Narrative was generated without an available LLM provider."

    stages = [
        _stage(
            "scope_contract_validation", "Scope and contract validation", "BUSINESS_RULE", "USED", False,
            "Validates identity, scope, KPI contract and access policy before diagnosis.", "scope_contract_validation_v1",
            _ref(result, "contract_snapshot"),
        ),
        _stage(
            "source_loading_normalization", "Source loading and normalization", "DETERMINISTIC", "USED", True,
            "Loads governed source records, applies availability rules and normalizes source fields.", "governed_source_loading_v1",
            source_refs, "Source loading is direct catalog-backed file access in the normal diagnosis path.",
        ),
        _stage(
            "reconciliation", "Source reconciliation", "BUSINESS_RULE", "USED" if reconciliation is not None else "SKIPPED", True,
            "Compares declared primary and secondary sources when the KPI contract requires it.", "source_reconciliation_v1",
            _ref(result, "reconciliation_verdict"), "Not applicable when no comparison source is declared." if reconciliation and reconciliation.get("status") == "NOT_APPLICABLE" else None,
        ),
        _stage(
            "movement_materiality", "Movement and materiality detection", "STATISTICAL", "USED" if "movement_assessment" in result else "SKIPPED", True,
            "Computes the governed baseline movement and statistical/business materiality checks.", "robust_seasonal_movement_gates_v1",
            movement_refs,
        ),
        _stage(
            "driver_ranking", "Driver association ranking", "STATISTICAL", driver_status, True,
            "Ranks declared driver associations using governed lags, coverage and stability checks.", "lagged_first_difference_association_v1",
            driver_refs, "Associations do not establish contribution or causation.",
        ),
        _stage(
            "accounting_decomposition", "Accounting decomposition", "DETERMINISTIC", decomposition_execution, True,
            "Computes an accounting identity when the KPI contract declares a supported bridge.", "accounting_identity_decomposition_v1",
            decomposition_refs, "An accounting identity explains observed change but does not establish operational causality." if decomposition_execution == "USED" else None,
        ),
        _stage(
            "causal_verification", "Causal verification", "CAUSAL", causal_status, True if causal_status == "USED" else False,
            "Evaluates an approved observational design when one was governed for this diagnosis.", "approved_observational_design_v1",
            causal_refs, "No approved causal design was executed." if causal_status == "NOT_REQUESTED" else None,
        ),
        _stage(
            "confidence_evaluation", "Confidence evaluation", "STATISTICAL", "USED", False,
            "Summarizes movement, source, driver and causal evidence statuses without producing a probability.", "blocking_evidence_profile_v1",
            confidence_refs, "Categorical evidence status is not a calibrated probability.",
        ),
        _stage(
            "action_recommendation", "Action recommendation", "BUSINESS_RULE", "USED", False,
            "Applies deterministic eligibility, confidence, contradiction and ownership rules to recommendations.", "evidence_limited_action_rules_v1",
            action_refs, "Recommendations are guidance and do not estimate impact without a validated method.",
        ),
        _stage(
            "narrative_generation", "Narrative generation", "DETERMINISTIC", narrative_execution, False,
            "Renders approved evidence-bound narrative wording.", "approved_narrative_templates_v1",
            narrative_refs,
        ),
        _stage(
            "llm_wording_selection", "Optional LLM wording selection", "LLM", llm_execution, False,
            "Optionally selects among approved narrative wording variants.", "approved_wording_selector_v1",
            narrative_refs if llm_status == "USED" else [], llm_limitation, "WORDING_ONLY" if llm_status in {"USED", "FALLBACK"} else None,
        ),
        _stage(
            "sql_query_execution", "SQL query execution", "SQL_QUERY", "SKIPPED", False,
            "No SQL query was executed by the normal direct-source diagnosis path.", "catalog_query_execution_v1",
        ),
        _stage(
            "retrieval", "Evidence retrieval", "RETRIEVAL", "SKIPPED", False,
            "No vector or prose retrieval is part of the diagnosis pipeline; retrieval is a separate chat path.", "chat_retrieval_path_v1",
        ),
    ]
    quantitative_stages = sum(
        1 for stage in stages
        if stage["quantitative_truth"] and stage["execution_status"] == "USED"
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "quantitative_truth_policy": QUANTITATIVE_POLICY,
        "stages": stages,
        "summary": {
            "quantitative_stages": quantitative_stages,
            "llm_used": llm_status == "USED",
            "retrieval_used": False,
            "sql_executed": False,
            "causal_method_used": causal_status == "USED",
        },
    }
