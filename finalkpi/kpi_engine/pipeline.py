# IMPLEMENTATION HANDOFF — orchestration
# Current: access gate -> CSV normalization -> reconciliation -> movement gate
# -> accounting bridge (+ funnel bridge for revenue) -> explained-movement
# attribution (Stage 3, F-R2/F-R3) -> optional event verification -> narrative.
# _attribute_drivers() is now the single driver call site shared by
# run_diagnosis and verify_event: AttributionEngine is primary, and
# CorrelationalRanker's own evaluate_candidates output is kept alongside as
# driver_analysis.association_diagnostics (a diagnostic cross-check), not
# deleted (plan Stage 3, step B.11).
# Next: inject a shared metric-series/query service described in duckdb/README.md.
# Resolve source, dimensions, periods, baseline and analysis policies from validated
# contracts. Preserve early exits and evidence labels while migrating one stage
# at a time. run_diagnosis and verify_event must share the same prepared inputs.
# Check: current five KPI outputs match before broadening supported source/grain;
# future or unavailable rows, denied controls and missing coverage still abstain.
# verify_event mirrors run_diagnosis's approved_causal_design flag (Stage 1, F-C4)
# so a completed event's causal dimension is not silently forced to NOT_ASSESSED.
# See IMPLEMENTATION_HANDOFF.md for acceptance criteria and integration consumers.

"""As-of KPI diagnosis with explicit boundaries between facts and hypotheses.

The public path stops after correlational ranking until an event exposure and
eligible control group are supplied. It never promotes a correlation to cause.
"""

from dataclasses import asdict, replace
from pathlib import Path
import time
from typing import Any, Dict, Optional
from uuid import uuid4

import numpy as np
import pandas as pd
import yaml

from kpi_engine.access import AccessController
from kpi_engine.action import ActionRecommendationEngine
from kpi_engine.attribution import AttributionEngine
from kpi_engine.contracts import KPIRegistry
from kpi_engine.contracts.metrics import prepare_metric_request, same_weekday_expected
from kpi_engine.contracts.registry import resolve_driver_id
from kpi_engine.contribute import ContributionScenario, ShapleyContributor
from kpi_engine.confidence import ConfidenceEngine
from kpi_engine.decompose import DeterministicDecomposer
from kpi_engine.detection import AnomalyDetector
from kpi_engine.feedback import DEFAULT_FEEDBACK_LOG_PATH, FeedbackLogger
from kpi_engine.normalize import DataNormalizer
from kpi_engine.narrative import NarrativeEngine
from kpi_engine.processing_transparency import build_processing_transparency
from kpi_engine.rank import CorrelationalRanker
from kpi_engine.rank import DriverExclusion
from kpi_engine.reconcile import SourceReconciler
from kpi_engine.verification import CausalVerifier, CausalVerificationResult, VerificationDesign


class KPIEnginePipeline:
    """Produce a reproducible diagnosis from data available at a given time."""

    def __init__(
        self,
        registry_dir: str,
        evidence_csv: str,
        groq_api_key: Optional[str] = None,
        access_csv: Optional[str] = None,
        feedback_log_path: str = DEFAULT_FEEDBACK_LOG_PATH,
        source_schema_path: Optional[str] = None,
    ):
        # Setup: source mappings rename fields inside three fixed source roles.
        # NEXT: replace the role allowlist with a validated source catalog; this
        # mapping alone cannot describe new grains, dimensions or join semantics.
        self.registry = KPIRegistry(registry_dir)
        source_schemas = {}
        if source_schema_path:
            with Path(source_schema_path).open("r", encoding="utf-8") as source_file:
                spec = yaml.safe_load(source_file)
            if not isinstance(spec, dict) or set(spec) - {"sales_daily", "marketing_weekly", "finance_monthly"}:
                raise ValueError("Source schema must map known source roles to column mappings")
            source_schemas = spec
        self.normalizer = DataNormalizer(source_schemas)
        self.reconciler = SourceReconciler()
        self.detector = AnomalyDetector()
        self.decomposer = DeterministicDecomposer()
        self.ranker = CorrelationalRanker()
        self.attribution_engine = AttributionEngine()
        self.verifier = CausalVerifier()
        self.contributor = ShapleyContributor()
        self.confidence_engine = ConfidenceEngine()
        self.narrator = NarrativeEngine(api_key=groq_api_key)
        self.recommender = ActionRecommendationEngine()
        access_path = Path(access_csv) if access_csv else Path(evidence_csv).with_name("access_control.csv")
        if not access_path.is_file():
            raise FileNotFoundError(f"Access policy is required: {access_path}")
        self.access_controller = AccessController(str(access_path))
        self.feedback_logger = FeedbackLogger(log_filepath=feedback_log_path)

    def submit_feedback(
        self,
        run_id: str,
        user_id: str,
        kpi_id: str,
        target_date: str,
        feedback_type: str,
        comments: str = "",
        original_text: str | None = None,
        corrected_text: str | None = None,
    ) -> Dict[str, Any]:
        return asdict(self.feedback_logger.log_feedback(
            run_id, user_id, kpi_id, target_date, feedback_type, comments,
            original_text, corrected_text,
        ))

    def quantify_scenario(self, scenario: ContributionScenario) -> Dict[str, Any]:
        """Allocate an explicitly modeled scenario; not a causal pipeline verdict."""
        if not isinstance(scenario, ContributionScenario):
            raise TypeError("A ContributionScenario is required")
        # Scenario allocation consumes supplied coalition outcomes. It does not
        # fit a driver model or infer contribution from correlation coefficients.
        contract = self.registry.get(scenario.kpi_id)
        declared = {driver["id"] for driver in contract.candidate_drivers}
        # A caller may replay a scenario built against a pre-rename driver id
        # (plan §1.3, e.g. "ad_spend_drop"); resolve it to the current id
        # before checking it against the live contract's declared drivers.
        canonical_drivers = tuple(resolve_driver_id(driver_id) for driver_id in scenario.drivers)
        if canonical_drivers != scenario.drivers:
            scenario = replace(
                scenario,
                drivers=canonical_drivers,
                coalition_values={
                    tuple(resolve_driver_id(driver_id) for driver_id in subset): value
                    for subset, value in scenario.coalition_values.items()
                },
            )
        if set(scenario.drivers) - declared:
            raise ValueError("Scenario contains drivers not declared for this KPI")
        if scenario.unit != contract.unit:
            raise ValueError("Scenario unit does not match the KPI contract")
        return asdict(self.contributor.quantify(scenario))

    @staticmethod
    def _build_evidence_profile(result: Dict[str, Any]) -> Dict[str, Any]:
        movement = result.get("movement_assessment") or {}
        verdict = result.get("verdict")

        if verdict == "ACCESS_DENIED":
            movement_status = "UNAUTHORIZED"
        elif not movement or movement.get("status") != "OK":
            movement_status = "INSUFFICIENT"
        elif verdict == "SEASONAL_REVIEW" or (not movement.get("is_material") and movement.get("detector_agreement") == "SEASONAL_ONLY"):
            movement_status = "SEASONAL_REVIEW"
        elif not movement.get("is_material"):
            movement_status = "NOT_MATERIAL"
        elif movement.get("detector_agreement") == "BOTH":
            movement_status = "CONFIRMED_BOTH"
        elif movement.get("detector_agreement") == "ROBUST_ONLY":
            movement_status = "ROBUST_ONLY"
        else:
            movement_status = "INSUFFICIENT"

        movement_limitations = []
        if movement and movement.get("status") == "OK":
            if not movement.get("is_statistically_significant"):
                movement_limitations.append("Movement did not pass the statistical z-score threshold")
            if not movement.get("is_business_material"):
                movement_limitations.append("Movement did not pass the absolute business materiality threshold")
            if movement.get("detector_agreement") == "ROBUST_ONLY":
                movement_limitations.append("Seasonal MSTL detector did not confirm the robust point anomaly")
            elif movement.get("detector_agreement") == "SEASONAL_ONLY":
                movement_limitations.append("Primary robust detector did not confirm the seasonal anomaly")
        else:
            movement_limitations.append("Insufficient historical observations to score baseline")

        recon = result.get("reconciliation_verdict") or {}
        recon_status = recon.get("status", "NOT_ASSESSED")
        details = recon.get("details") or {}

        if recon_status == "CONTRADICTED":
            sq_status = "CONTRADICTED"
        elif recon_status == "DRIFT":
            sq_status = "DRIFT"
        elif details.get("quality_flag"):
            sq_status = "QUALITY_FAILED"
        elif recon_status == "NOT_AVAILABLE_FOR_PERIOD":
            sq_status = "LIMITED"
        elif recon_status in ("AGREED", "NOT_APPLICABLE"):
            sq_status = "READY"
        else:
            sq_status = "NOT_ASSESSED"

        sq_limitations = []
        if details.get("reason"):
            sq_limitations.append(details["reason"])
        elif recon_status == "NOT_AVAILABLE_FOR_PERIOD":
            sq_limitations.append("Independent finance comparison unavailable for requested period")
        elif recon_status == "NOT_APPLICABLE":
            sq_limitations.append("No independent second-source comparison configured for this KPI")

        candidates = result.get("correlational_candidates") or []
        exclusions = result.get("driver_exclusions") or []

        if candidates:
            driver_status = "CANDIDATES_FOUND"
        elif exclusions or verdict in ("MATERIAL_CAUSE_UNVERIFIED", "EVENT_ASSESSED_CAUSE_UNVERIFIED"):
            driver_status = "NO_CANDIDATE_PASSED"
        else:
            driver_status = "INSUFFICIENT_DATA"

        driver_limitations = [
            "Lagged correlation indicates co-movement, not causal attribution",
            "Optimal lag selected over candidate search window without multiple-testing penalty",
        ]
        if not candidates and exclusions:
            driver_limitations.append("No candidate driver met the minimum correlation threshold of 0.3")

        confidence = result.get("confidence") or {}
        causal_status = confidence.get("status", "NOT_ASSESSED")
        reasons = confidence.get("reasons") or ()
        causal_limitations = list(reasons)
        if causal_status == "NOT_ASSESSED":
            causal_limitations.append("No approved server-side causal comparison design was supplied")

        return {
            "movement": {
                "status": movement_status,
                "detector_agreement": movement.get("detector_agreement", "NEITHER"),
                "statistical_materiality": bool(movement.get("is_statistically_significant")),
                "business_materiality": bool(movement.get("is_business_material")),
                "baseline_count": movement.get("baseline_count"),
                "limitations": movement_limitations,
            },
            "source_quality": {
                "status": sq_status,
                "freshness": [{"source": result.get("kpi_id", "sales_daily"), "as_of": result.get("as_of")}],
                "coverage": [result["source_coverage"]] if result.get("source_coverage") else [],
                "limitations": sq_limitations,
            },
            "driver_evidence": {
                "status": driver_status,
                "method": "lagged first-difference correlation",
                "candidates": candidates,
                "exclusions": exclusions,
                "limitations": driver_limitations,
            },
            "causal_evidence": {
                "status": causal_status,
                "reason_code": reasons[0] if reasons else "NO_DESIGN",
                "sub_scores": confidence.get("sub_scores") or {
                    "outcome_window_coverage": None,
                    "temporal_precedence": None,
                    "did_interval_precision": None,
                },
                "limitations": causal_limitations,
            },
        }

    def _finalize(self, result: Dict[str, Any]) -> Dict[str, Any]:
        causal_design_approved = bool(result.pop("_causal_design_approved", False))
        decision_started = time.monotonic_ns()
        result["confidence_profile"] = self.confidence_engine.build_profile(
            result,
            causal_design_approved=causal_design_approved,
        )
        result["confidence_deprecated"] = True
        result["evidence_profile"] = self._build_evidence_profile(result)
        result["decision_cards"] = self.recommender.recommend(result)
        if result["confidence_profile"]["overall"]["status"] == "CONFLICTING_EVIDENCE":
            result["decision_cards"] = []
        self._record_runtime(result, "confidence_and_actions", "BUSINESS_RULE", "rules_and_evidence_scoring", decision_started)
        narrative_started = time.monotonic_ns()
        rendered = self.narrator.render(result)
        result["narrative"] = rendered["text"]
        result["narrative_claims"] = rendered["claims"]
        result["grounding_passed"] = rendered["grounding_passed"]
        result["grounding_errors"] = rendered["rejected_claims"]
        result["narrative_method"] = rendered["method"]
        result["llm_status"] = rendered["llm_status"]
        result["narrative_runtime"] = rendered.get("runtime_telemetry")
        self._record_runtime(result, "narrative_synthesis", "DETERMINISTIC", "evidence_bound_template", narrative_started)
        result["processing_transparency"] = build_processing_transparency(
            result,
            causal_design_approved=causal_design_approved,
        )
        return result

    @staticmethod
    def _slice(frame: pd.DataFrame, dimension_slice: Optional[Dict[str, str]]) -> pd.DataFrame:
        result = frame
        for key, value in (dimension_slice or {}).items():
            if key not in result.columns:
                raise ValueError(f"Unknown dimension: {key}")
            result = result[result[key] == value]
        return result

    @staticmethod
    def _attach_monthly_driver_values(
        frame: pd.DataFrame,
        finance: pd.DataFrame,
        driver_specs: Dict[str, Dict[str, Any]],
        dimension_slice: Optional[Dict[str, str]],
    ) -> pd.DataFrame:
        monthly_specs = [
            spec for spec in driver_specs.values()
            if spec.get("source") == "finance_monthly" and spec.get("grain") == "monthly"
        ]
        if not monthly_specs or finance.empty:
            return frame
        required_columns = {spec["column"] for spec in monthly_specs}
        if not required_columns.issubset(finance.columns):
            return frame

        finance_rows = finance.copy()
        if "month_end" in finance_rows and not frame.empty:
            target_date = pd.to_datetime(frame["date"]).max()
            finance_rows = finance_rows[pd.to_datetime(finance_rows["month_end"]) <= target_date]
        for dimension, value in (dimension_slice or {}).items():
            if dimension in finance_rows:
                finance_rows = finance_rows[finance_rows[dimension] == value]
        finance_rows["_driver_month"] = pd.to_datetime(finance_rows["date"]).dt.to_period("M").dt.to_timestamp()
        key_columns = ["_driver_month", *[key for key in ("region", "category") if key in finance_rows.columns]]
        selected_columns = {}
        for spec in monthly_specs:
            source_column = spec["column"]
            selected_columns[source_column] = f"finance_monthly_{source_column}"
        finance_rows = finance_rows[[*key_columns, *selected_columns]].rename(columns=selected_columns)
        if finance_rows.duplicated(key_columns).any():
            raise ValueError("finance_monthly driver alignment is not unique at month and scope grain")
        ranked = frame.copy()
        ranked["_driver_month"] = pd.to_datetime(ranked["date"]).dt.to_period("M").dt.to_timestamp()
        merged = ranked.merge(finance_rows, on=key_columns, how="left", validate="many_to_one")
        return merged.drop(columns=["_driver_month"])

    def _attribute_drivers(
        self,
        frame: pd.DataFrame,
        kpi_id: str,
        driver_specs: Dict[str, Dict[str, Any]],
        contract: Any,
        target_date: str,
        driver_columns: Dict[str, str],
        scope: Optional[Dict[str, str]],
        as_of: str,
        assessment: Any,
    ) -> Dict[str, Any]:
        """Stage 3 (F-R3, F-R6): explained-movement attribution is now the
        primary driver method in both run_diagnosis and verify_event.
        CorrelationalRanker is kept as a secondary diagnostic view
        (driver_analysis.association_diagnostics), not deleted (plan §Stage 3,
        step B.11), since it is still a cheap, well-tested cross-check on
        marginal association independent of the joint model's assumptions.
        """
        attribution = self.attribution_engine.attribute(
            frame, kpi_id, list(driver_specs), assessment, target_date,
            driver_columns=driver_columns, contract=contract, scope=scope, as_of=as_of,
        )
        association = self.ranker.evaluate_candidates(
            frame, kpi_id, list(driver_specs), target_date=target_date,
            driver_columns=driver_columns, contract=contract, scope=scope, as_of=as_of,
        )
        driver_analysis = dict(attribution.driver_analysis)
        driver_analysis["association_diagnostics"] = association.driver_analysis
        return driver_analysis

    def verify_event(
        self,
        kpi_id: str,
        verification_design: VerificationDesign,
        sales_csv: str,
        marketing_csv: str,
        finance_csv: str,
        persona: str = "CFO",
        as_of: Optional[str] = None,
        approved_causal_design: bool = False,
    ) -> Dict[str, Any]:
        """Assess a predeclared completed event, independent of a daily alert."""
        if not isinstance(verification_design, VerificationDesign):
            raise TypeError("verification_design must be a VerificationDesign")
        end = pd.Timestamp(verification_design.post_end).normalize()
        cutoff = pd.Timestamp(as_of) if as_of else end + pd.Timedelta(days=1, hours=12)
        if cutoff < end:
            raise ValueError("as_of cannot precede the event post_end")
        result: Dict[str, Any] = {
            "run_id": f"run-{uuid4().hex[:12]}",
            "kpi_id": kpi_id,
            "post_end": end.date().isoformat(),
            "as_of": cutoff.isoformat(),
            "persona": persona,
            "treated_slice": verification_design.treated_slice,
            "control_slice": verification_design.control_slice,
            "reconciliation_verdict": None,
            "causal_verdict": None,
            "causal_verification": None,
            "confidence": None,
            # F-C4: mirrors run_diagnosis so build_profile's causal dimension
            # is not silently forced to NOT_ASSESSED after a real DiD ran.
            "_causal_design_approved": approved_causal_design,
        }
        for label, group in (("treated", verification_design.treated_slice),
                             ("control", verification_design.control_slice)):
            access = self.access_controller.check(persona, group)
            if not access.allowed:
                result.update(verdict="ACCESS_DENIED", narrative=f"{label} slice: {access.reason}")
                return self._finalize(result)

        contract = self.registry.get(kpi_id)
        contract_snapshot = self.registry.semantic_snapshot(
            kpi_id,
            allowed_roles=sorted(set(self.access_controller.df["owner_role"].astype(str))),
        )
        result["contract_snapshot"] = contract_snapshot
        result["contract_version"] = contract.version
        result["contract_hash"] = contract_snapshot["governance"]["contract_hash"]
        if contract.source != "sales_daily" or contract.grain != "daily":
            raise ValueError("Event verification currently supports daily sales KPIs only")
        unsupported = {driver["source"] for driver in contract.candidate_drivers} - {
            "sales_daily", "marketing_weekly", "finance_monthly"
        }
        if unsupported:
            raise ValueError(f"Unsupported driver sources: {sorted(unsupported)}")
        daily, finance = self.normalizer.align_sources(
            sales_csv,
            marketing_csv if any(driver["source"] == "marketing_weekly"
                                 for driver in contract.candidate_drivers) else None,
            finance_csv if contract.reconciliation is not None or any(
                driver["source"] == "finance_monthly" for driver in contract.candidate_drivers
            ) else None,
            as_of=cutoff,
        )
        if contract.aggregation == "sum" and contract.value_column != kpi_id:
            if contract.value_column not in daily.columns:
                raise ValueError(f"Missing KPI source column: {contract.value_column}")
            daily[kpi_id] = daily[contract.value_column]
        daily = daily[daily["date"] <= end].copy()
        if contract.reconciliation is None:
            reconciliation = self.reconciler.not_applicable(
                f"No comparable second-source measure is declared for {kpi_id}; "
                "cross-source comparison is not expected for this KPI."
            )
        else:
            reconciliation = self.reconciler.reconcile_mtd(
                daily, finance,
                target_year_month=end.strftime("%Y-%m"),
                metric_sales=kpi_id,
                metric_finance=contract.reconciliation["finance_column"],
                historical_tolerance_pct=contract.reconciliation.get("tolerance_pct", 3.5),
                contradiction_multiple=contract.reconciliation.get("contradiction_multiple", 2.5),
                target_date=end.date().isoformat(),
                dimension_slice=verification_design.treated_slice,
                mode=contract.reconciliation.get("mode", "closed_period"),
                as_of=cutoff.isoformat() if cutoff else None,
                require_matching_coverage=contract.reconciliation.get("require_matching_coverage", True),
            )
        result["reconciliation_verdict"] = asdict(reconciliation)

        # Build exact source evidence bound to this run
        from kpi_engine.evidence import SourceEvidenceBuilder
        builder = SourceEvidenceBuilder()

        # Load raw frames for metadata extraction
        sales_df = self.normalizer.load_and_normalize_sales(sales_csv, as_of=cutoff)

        marketing_df = None
        if marketing_csv and any(driver['source'] == 'marketing_weekly' for driver in contract.candidate_drivers):
            marketing_df = self.normalizer._read_source(marketing_csv, "marketing_weekly")
            self.normalizer._require_columns(marketing_df, "marketing_weekly", ("week_start", "region", "category", "available_at"))
            marketing_df['week_start'] = pd.to_datetime(marketing_df['week_start'], errors='coerce')
            marketing_df['available_at'] = pd.to_datetime(marketing_df['available_at'], errors='coerce')
            marketing_df = marketing_df[marketing_df['available_at'] <= cutoff].copy()

        finance_df = None
        if finance_csv and (contract.reconciliation is not None or any(
            driver["source"] == "finance_monthly" for driver in contract.candidate_drivers
        )):
            finance_df = self.normalizer.load_and_normalize_finance(finance_csv, as_of=cutoff)

        result["source_evidence"] = builder.build(
            result=result,
            scope=verification_design.treated_slice,
            sales_frame=sales_df,
            marketing_frame=marketing_df,
            finance_frame=finance_df,
            sales_path=sales_csv,
            marketing_path=marketing_csv if marketing_df is not None else None,
            finance_path=finance_csv if finance_df is not None else None,
        )

        driver_specs = {item["id"]: item for item in contract.candidate_drivers}
        event_rank_frame = self._attach_monthly_driver_values(
            daily, finance, driver_specs, verification_design.treated_slice,
        )
        driver_columns = {
            driver_id: f"finance_monthly_{spec['column']}"
            if spec.get("source") == "finance_monthly" else spec["column"]
            for driver_id, spec in driver_specs.items()
        }
        # event_rank_frame is not sliced to verification_design.treated_slice
        # (a pre-existing limitation of this path, unchanged by Stage 3: the
        # causal verifier below does its own treated/control slicing; only
        # this driver-evaluation frame is company-wide). Movement and
        # attribution below share that same limitation, as the correlational
        # ranker they replace always did.
        event_assessment = self.detector.evaluate_movement(
            event_rank_frame, contract, end.date().isoformat(), metric_col=kpi_id,
        )
        driver_analysis = self._attribute_drivers(
            event_rank_frame, kpi_id, driver_specs, contract, end.date().isoformat(),
            driver_columns, verification_design.treated_slice, cutoff.isoformat(), event_assessment,
        )
        result["driver_analysis"] = driver_analysis
        result["correlational_candidates"] = driver_analysis["ranked_drivers"]
        result["driver_exclusions"] = driver_analysis["excluded_drivers"]

        # Only CONTRADICTED is a hard gate. NOT_APPLICABLE and NOT_AVAILABLE_FOR_PERIOD
        # are informational; diagnosis continues for those statuses.
        if reconciliation.status == "CONTRADICTED":
            result["driver_analysis"] = self.ranker.excluded_analysis(
                contract,
                target_kpi=kpi_id,
                target_date=end.date().isoformat(),
                scope=verification_design.treated_slice,
                reason_code="BLOCKED_BY_RECONCILIATION",
                reason="Contradictory source reconciliation blocks driver interpretation.",
                status="BLOCKED",
            )
            result["correlational_candidates"] = []
            result["driver_exclusions"] = result["driver_analysis"]["excluded_drivers"]
            result.update(verdict="CONTRADICTED", narrative="Source systems disagree; verify postings first.")
            return self._finalize(result)
        if verification_design.driver_id not in {
            driver["id"] for driver in contract.candidate_drivers
        }:
            verification = CausalVerificationResult(
                verification_design.driver_id, "UNTESTABLE", "UNDECLARED_DRIVER",
                "The proposed driver is not declared in the KPI contract",
            )
        else:
            verification = self.verifier.verify(daily, contract, verification_design)
        result.update(
            verdict="EVENT_ASSESSED_CAUSE_UNVERIFIED",
            causal_verdict=verification.verdict,
            causal_verification=asdict(verification),
            confidence=asdict(self.confidence_engine.assess(verification)),
            narrative=("Predeclared event window assessed independently of the final-day alert. "
                       f"Observational verification: {verification.verdict}; no cause is proven."),
        )
        return self._finalize(result)

    def run_diagnosis(
        self,
        kpi_id: str,
        target_date: str,
        sales_csv: str,
        marketing_csv: str,
        finance_csv: str,
        persona: str = "CFO",
        dimension_slice: Optional[Dict[str, str]] = None,
        candidate_drivers: Optional[list[str]] = None,
        bypass_reconciliation: bool = False,
        force_material: bool = False,
        as_of: Optional[str] = None,
        verification_design: Optional[VerificationDesign] = None,
        prepared_request: Optional[Any] = None,
        approved_causal_design: bool = False,
    ) -> Dict[str, Any]:
        if bypass_reconciliation or force_material:
            raise ValueError("Demo overrides are not supported in diagnosis")

        target = pd.Timestamp(target_date).normalize()
        cutoff = pd.Timestamp(as_of) if as_of else target + pd.Timedelta(days=1, hours=12)
        if cutoff < target:
            raise ValueError("as_of cannot precede target_date")

        run_id = f"run-{uuid4().hex[:12]}"
        result: Dict[str, Any] = {
            "run_id": run_id,
            "kpi_id": kpi_id,
            "target_date": target.date().isoformat(),
            "as_of": cutoff.isoformat(),
            "persona": persona,
            "segment": dimension_slice or {},
            "reconciliation_verdict": None,
            "source_coverage": None,
            "movement_assessment": None,
            "decomposition": None,
            "decomposition_status": "NOT_EVALUATED",
            "funnel_bridge": None,
            "funnel_bridge_status": "NOT_EVALUATED",
            "correlational_candidates": [],
            "driver_exclusions": [],
            "driver_analysis": None,
            "causal_verdict": None,
            "causal_verification": None,
            "confidence": None,
            "decision_cards": [],
            "grounding_passed": True,
            "telemetry": None,
            "_causal_design_approved": approved_causal_design and verification_design is not None,
        }

        stage_started = time.monotonic_ns()
        access = self.access_controller.check(persona, dimension_slice)
        self._record_runtime(result, "authorization", "BUSINESS_RULE", "role_and_row_scope_policy", stage_started)
        if not access.allowed:
            result.update(verdict="ACCESS_DENIED", narrative=access.reason)
            return self._finalize(result)

        contract = self.registry.get(kpi_id)
        contract_snapshot = self.registry.semantic_snapshot(
            kpi_id,
            allowed_roles=sorted(set(self.access_controller.df["owner_role"].astype(str))),
        )
        result["contract_snapshot"] = contract_snapshot
        result["contract_version"] = contract.version
        result["contract_hash"] = contract_snapshot["governance"]["contract_hash"]
        if contract.source != "sales_daily":
            raise ValueError(
                f"Unsupported primary KPI source: {contract.source}. "
                "This pipeline currently diagnoses sales_daily KPIs only."
            )
        if contract.grain != "daily":
            raise ValueError(f"Unsupported grain for this pipeline: {contract.grain}")
        unsupported_drivers = {
            driver['source'] for driver in contract.candidate_drivers
        } - {'sales_daily', 'marketing_weekly', 'finance_monthly'}
        if unsupported_drivers:
            raise ValueError(f"Unsupported driver sources: {sorted(unsupported_drivers)}")

        stage_started = time.monotonic_ns()
        daily, finance = self.normalizer.align_sources(
            sales_csv,
            marketing_csv if any(driver['source'] == 'marketing_weekly'
                                 for driver in contract.candidate_drivers) else None,
            finance_csv if contract.reconciliation is not None or any(
                driver['source'] == 'finance_monthly' for driver in contract.candidate_drivers
            ) else None,
            as_of=cutoff,
        )
        if contract.aggregation == "sum" and contract.value_column != kpi_id:
            if contract.value_column not in daily.columns:
                raise ValueError(f"Missing KPI source column: {contract.value_column}")
            daily[kpi_id] = daily[contract.value_column]
        daily = daily[daily["date"] <= target].copy()
        scoped = self._slice(daily, dimension_slice)
        prepared_request = prepared_request or prepare_metric_request(
            scoped, contract, target, dimension_slice=dimension_slice, as_of=cutoff,
        )
        if 'marketing_coverage' in scoped.columns:
            available_rows = int((scoped['marketing_coverage'] == 'AVAILABLE').sum())
            target_rows = scoped[scoped['date'] == target]
            result['source_coverage'] = {
                'marketing_available_rows': available_rows,
                'sales_rows': int(len(scoped)),
                'target_marketing_status': (
                    'NO_SALES_ROW' if target_rows.empty else
                    'NOT_DECLARED' if target_rows['marketing_coverage'].eq('NOT_DECLARED').all() else
                    'AVAILABLE' if target_rows['marketing_coverage'].eq('AVAILABLE').all() else
                    'PARTIAL' if target_rows['marketing_coverage'].eq('AVAILABLE').any() else
                    'UNAVAILABLE_OR_MISSING'
                ),
            }
        self._record_runtime(result, "source_preparation", "DETERMINISTIC", "grain_cadence_and_as_of_alignment", stage_started)

        stage_started = time.monotonic_ns()
        if contract.reconciliation is None:
            reconciliation = self.reconciler.not_applicable(
                f"No comparable second-source measure is declared for {kpi_id}; "
                "cross-source comparison is not expected for this KPI."
            )
        else:
            reconciliation = self.reconciler.reconcile_mtd(
                daily, finance,
                target_year_month=target.strftime("%Y-%m"),
                metric_sales=kpi_id,
                metric_finance=contract.reconciliation["finance_column"],
                historical_tolerance_pct=contract.reconciliation.get("tolerance_pct", 3.5),
                contradiction_multiple=contract.reconciliation.get("contradiction_multiple", 2.5),
                target_date=target.date().isoformat(),
                dimension_slice=dimension_slice,
                mode=contract.reconciliation.get("mode", "closed_period"),
                as_of=cutoff.isoformat() if cutoff else None,
                require_matching_coverage=contract.reconciliation.get("require_matching_coverage", True),
            )
        result["reconciliation_verdict"] = asdict(reconciliation)
        self._record_runtime(result, "reconciliation", "DETERMINISTIC", "independent_source_comparison", stage_started)

        # Build exact source evidence bound to this run
        from kpi_engine.evidence import SourceEvidenceBuilder
        builder = SourceEvidenceBuilder()

        # Load raw frames for metadata extraction
        sales_df = self.normalizer.load_and_normalize_sales(sales_csv, as_of=cutoff)

        marketing_df = None
        if marketing_csv and any(driver['source'] == 'marketing_weekly' for driver in contract.candidate_drivers):
            marketing_df = self.normalizer._read_source(marketing_csv, "marketing_weekly")
            self.normalizer._require_columns(marketing_df, "marketing_weekly", ("week_start", "region", "category", "available_at"))
            marketing_df['week_start'] = pd.to_datetime(marketing_df['week_start'], errors='coerce')
            marketing_df['available_at'] = pd.to_datetime(marketing_df['available_at'], errors='coerce')
            marketing_df = marketing_df[marketing_df['available_at'] <= cutoff].copy()

        finance_df = None
        if finance_csv and (contract.reconciliation is not None or any(
            driver['source'] == 'finance_monthly' for driver in contract.candidate_drivers
        )):
            finance_df = self.normalizer.load_and_normalize_finance(finance_csv, as_of=cutoff)

        result["source_evidence"] = builder.build(
            result=result,
            scope=dimension_slice or {},
            sales_frame=sales_df,
            marketing_frame=marketing_df,
            finance_frame=finance_df,
            sales_path=sales_csv,
            marketing_path=marketing_csv if marketing_df is not None else None,
            finance_path=finance_csv if finance_df is not None else None,
        )

        # Only CONTRADICTED is a hard gate. Continue for NOT_APPLICABLE,
        # NOT_AVAILABLE_FOR_PERIOD, AGREED, and DRIFT.
        if reconciliation.status == "CONTRADICTED":
            result["driver_analysis"] = self.ranker.excluded_analysis(
                contract,
                target_kpi=kpi_id,
                target_date=target.date().isoformat(),
                scope=dimension_slice,
                reason_code="BLOCKED_BY_RECONCILIATION",
                reason="Contradictory source reconciliation blocks driver interpretation.",
                status="BLOCKED",
            )
            result["driver_exclusions"] = result["driver_analysis"]["excluded_drivers"]
            result.update(
                verdict="CONTRADICTED",
                narrative="The source systems disagree about this movement. Check the postings before diagnosing a cause.",
            )
            return self._finalize(result)

        stage_started = time.monotonic_ns()
        assessment = self.detector.evaluate_movement(
            scoped, contract, target.date().isoformat(), metric_col=kpi_id,
            comparison_plan=prepared_request.comparison,
        )
        result["movement_assessment"] = asdict(assessment)
        self._record_runtime(result, "movement_detection", "STATISTICAL", "statistical_and_business_materiality", stage_started)
        if assessment.status != "OK":
            result["driver_analysis"] = self.ranker.excluded_analysis(
                contract,
                target_kpi=kpi_id,
                target_date=target.date().isoformat(),
                scope=dimension_slice,
                reason_code="INSUFFICIENT_HISTORY",
                reason="The KPI history did not meet the movement-analysis baseline requirement.",
                status="INSUFFICIENT_EVIDENCE",
            )
            result["driver_exclusions"] = result["driver_analysis"]["excluded_drivers"]
            result.update(
                verdict=assessment.status,
                narrative=f"This KPI cannot be assessed yet: {assessment.status.lower().replace('_', ' ')}.",
            )
            return self._finalize(result)

        driver_specs = {driver["id"]: driver for driver in contract.candidate_drivers}
        governed_driver_ids = list(driver_specs)
        unknown_drivers = set(candidate_drivers or []) - set(governed_driver_ids)
        if unknown_drivers:
            raise ValueError(f"Drivers not declared for {kpi_id}: {sorted(unknown_drivers)}")
        if candidate_drivers is not None and set(candidate_drivers) != set(governed_driver_ids):
            raise ValueError("Candidate driver selection must match the complete governed KPI driver set")
        stage_started = time.monotonic_ns()
        driver_analysis = self._attribute_drivers(
            self._attach_monthly_driver_values(scoped, finance, driver_specs, dimension_slice),
            kpi_id, driver_specs, contract, target.date().isoformat(),
            {
                driver_id: f"finance_monthly_{spec['column']}"
                if spec.get("source") == "finance_monthly" else spec["column"]
                for driver_id, spec in driver_specs.items()
            },
            dimension_slice, cutoff.isoformat(), assessment,
        )
        result["driver_analysis"] = driver_analysis
        result["correlational_candidates"] = driver_analysis["ranked_drivers"]
        result["driver_exclusions"] = driver_analysis["excluded_drivers"]
        self._record_runtime(result, "driver_analysis", "STATISTICAL", "joint_robust_regression_explained_movement", stage_started)
        if not assessment.is_material:
            if assessment.detector_agreement == "SEASONAL_ONLY":
                result.update(
                    verdict="SEASONAL_REVIEW",
                    narrative=(
                        "The seasonal forecast found an unusual value, but the primary "
                        "movement detector did not confirm a material change. Review the "
                        "seasonal evidence; no cause is diagnosed automatically."
                    ),
                )
                return self._finalize(result)
            delta_display = f"{assessment.delta:.6f}" if contract.aggregation != "sum" else f"{assessment.delta:.2f}"
            result.update(
                verdict="NO_MATERIAL_MOVEMENT",
                narrative=f"The observed {kpi_id} change of {delta_display} {contract.unit} did not pass both materiality checks.",
            )
            return self._finalize(result)

        # Stage 2 (F-D1/F-D2): detection's expected value is now a same-weekday
        # median, not the arithmetic mean of every baseline day. The bridge
        # must still land on exactly the same total (assessment.expected_value)
        # so "identity_held" keeps meaning something: per-segment same-weekday
        # medians are computed for their robust shape (the mix), then rescaled
        # so they sum to assessment.expected_value exactly, rather than being
        # used as independently-estimated, possibly-inconsistent totals.
        stage_started = time.monotonic_ns()
        baseline = prepared_request.comparison.baseline_frame.copy()
        current = prepared_request.comparison.current_frame.copy()
        quantity_col = contract.decomposition.get("quantity_column")
        result["decomposition_status"] = (
            "NOT_APPLICABLE" if not quantity_col else "INSUFFICIENT_COMPONENTS"
        )
        if quantity_col and not current.empty and not baseline.empty:
            if quantity_col not in scoped or kpi_id not in scoped:
                result["decomposition_reason"] = "Declared bridge inputs are missing"
            else:
                remaining_dims = [name for name in contract.dimensions
                                  if name not in (dimension_slice or {})]

                def segment_parts(frame: pd.DataFrame, divisor: int) -> pd.DataFrame:
                    if remaining_dims:
                        parts = frame.groupby(remaining_dims, dropna=False)[
                            [quantity_col, kpi_id]
                        ].sum(min_count=1).reset_index()
                        parts["segment"] = list(parts[remaining_dims].itertuples(
                            index=False, name=None
                        ))
                    else:
                        parts = pd.DataFrame({
                            "segment": [("ALL",)],
                            quantity_col: [frame[quantity_col].sum(min_count=1)],
                            kpi_id: [frame[kpi_id].sum(min_count=1)],
                        })
                    return pd.DataFrame({
                        "segment": parts["segment"],
                        "quantity": parts[quantity_col] / divisor,
                        "value": parts[kpi_id] / divisor,
                    })

                def segment_same_weekday_baseline(value_col: str) -> Dict[tuple, float]:
                    totals: Dict[tuple, float] = {}
                    groups = (
                        baseline.groupby(remaining_dims, dropna=False)
                        if remaining_dims else [((), baseline)]
                    )
                    for segment_key, group in groups:
                        segment = segment_key if isinstance(segment_key, tuple) else (segment_key,)
                        segment = segment or ("ALL",)
                        series = group.groupby("date")[value_col].sum(min_count=1).sort_index()
                        value, _ = same_weekday_expected(series, target)
                        totals[segment] = value if value is not None else float(series.mean() or 0.0)
                    return totals

                def rescale_to_total(totals: Dict[tuple, float], target_total: Optional[float]) -> Dict[tuple, float]:
                    raw_total = sum(totals.values())
                    if target_total is None or abs(raw_total) < 1e-9:
                        return totals
                    factor = target_total / raw_total
                    return {segment: value * factor for segment, value in totals.items()}

                scoped_quantity_series = scoped.groupby("date")[quantity_col].sum(min_count=1).sort_index()
                expected_quantity_total, _ = same_weekday_expected(scoped_quantity_series, target)
                seg_value = rescale_to_total(segment_same_weekday_baseline(kpi_id), assessment.expected_value)
                seg_quantity = rescale_to_total(segment_same_weekday_baseline(quantity_col), expected_quantity_total)
                segments = list(seg_value)
                base_parts = pd.DataFrame({
                    "segment": segments,
                    "quantity": [seg_quantity.get(segment, 0.0) for segment in segments],
                    "value": [seg_value[segment] for segment in segments],
                })
                current_parts = segment_parts(current, 1)
                try:
                    bridge = self.decomposer.decompose_product_by_segments(
                        base_parts, current_parts, kpi_id=kpi_id
                    )
                except ValueError as error:
                    result["decomposition_reason"] = str(error)
                else:
                    if not bridge.is_identity_held or abs(bridge.total_delta - assessment.delta) > 0.02:
                        raise ValueError("The decomposition does not match the detected movement")
                    # reference_rate_column labels the derived value/quantity
                    # rate; the decomposer does not read that source rate column.
                    result["decomposition"] = {
                        **asdict(bridge),
                        "effect_labels": {
                            "volume_effect": quantity_col,
                            "mix_effect": remaining_dims,
                            "price_effect": contract.decomposition["reference_rate_column"],
                        },
                    }
                    result["decomposition_status"] = "IDENTITY_HELD"

        # Stage 3 (F-R2, step A): the funnel/accounting bridge answers WHERE
        # a revenue movement happened (traffic vs. conversion vs. basket
        # size), ahead of and independent from the statistical attribution
        # engine's WHY. Only net_sales_revenue has the full traffic-orders-
        # revenue chain declared on sales_daily; other KPIs get None, not a
        # forced or approximated bridge.
        result["funnel_bridge"] = None
        result["funnel_bridge_status"] = "NOT_APPLICABLE"
        if kpi_id == "net_sales_revenue" and not current.empty and not baseline.empty:
            required_columns = {"traffic_total", "orders", kpi_id}
            if not required_columns.issubset(scoped.columns):
                result["funnel_bridge_status"] = "INSUFFICIENT_COMPONENTS"
            else:
                baseline_traffic = baseline.groupby("date")["traffic_total"].sum(min_count=1).sort_index()
                baseline_orders = baseline.groupby("date")["orders"].sum(min_count=1).sort_index()
                traffic0, _ = same_weekday_expected(baseline_traffic, target)
                orders0, _ = same_weekday_expected(baseline_orders, target)
                revenue0 = assessment.expected_value
                traffic1 = float(current["traffic_total"].sum(min_count=1))
                orders1 = float(current["orders"].sum(min_count=1))
                revenue1 = assessment.actual_value
                values = (traffic0, orders0, revenue0, traffic1, orders1, revenue1)
                if any(value is None or not np.isfinite(value) for value in values) or traffic0 <= 0 or orders0 <= 0 or traffic1 <= 0 or orders1 <= 0:
                    result["funnel_bridge_status"] = "INSUFFICIENT_COMPONENTS"
                else:
                    conversion0, conversion1 = orders0 / traffic0, orders1 / traffic1
                    aov0, aov1 = revenue0 / orders0, revenue1 / orders1
                    try:
                        funnel = self.decomposer.decompose_funnel(
                            traffic0, traffic1, conversion0, conversion1, aov0, aov1,
                        )
                    except ValueError as error:
                        result["funnel_bridge_status"] = "INSUFFICIENT_COMPONENTS"
                        result["funnel_bridge_reason"] = str(error)
                    else:
                        result["funnel_bridge"] = funnel
                        result["funnel_bridge_status"] = "IDENTITY_HELD"
        self._record_runtime(result, "contribution_analysis", "DETERMINISTIC", "deterministic_accounting_bridge", stage_started)

        stage_started = time.monotonic_ns()
        if verification_design is None:
            verification = CausalVerificationResult(
                "", "UNTESTABLE", "NO_DESIGN",
                "No predeclared treatment, authorized control, and quiet windows were supplied",
            )
        elif not isinstance(verification_design, VerificationDesign):
            raise TypeError("verification_design must be a VerificationDesign")
        elif verification_design.driver_id not in driver_specs:
            verification = CausalVerificationResult(
                verification_design.driver_id, "UNTESTABLE", "UNDECLARED_DRIVER",
                "The proposed driver is not declared in the KPI contract",
            )
        elif verification_design.treated_slice != (dimension_slice or {}):
            verification = CausalVerificationResult(
                verification_design.driver_id, "UNTESTABLE", "TREATMENT_SLICE_MISMATCH",
                "The proposed treated slice does not match the diagnosed KPI slice",
            )
        elif (pd.notna(pd.to_datetime(verification_design.post_end, errors="coerce"))
              and pd.to_datetime(verification_design.post_end, errors="coerce").normalize() > target):
            verification = CausalVerificationResult(
                verification_design.driver_id, "UNTESTABLE", "FUTURE_POST_PERIOD",
                "The proposed post-period extends beyond the target date",
            )
        elif not self.access_controller.check(persona, verification_design.control_slice).allowed:
            verification = CausalVerificationResult(
                verification_design.driver_id, "UNTESTABLE", "CONTROL_NOT_AUTHORIZED",
                "The requested role cannot access the proposed control slice",
            )
        else:
            verification = self.verifier.verify(daily, contract, verification_design)
        result["causal_verdict"] = verification.verdict
        result["causal_verification"] = asdict(verification)
        result["confidence"] = asdict(self.confidence_engine.assess(verification))
        self._record_runtime(result, "causal_verification", "CAUSAL", "predeclared_observational_design", stage_started)
        delta_display = f"{assessment.delta:.6f}" if contract.aggregation != "sum" else f"{assessment.delta:.2f}"
        result.update(
            verdict="MATERIAL_CAUSE_UNVERIFIED",
            narrative=(
                f"{kpi_id} changed by {delta_display} {contract.unit} and passed both "
                "materiality checks. Candidate associations are listed separately from "
                f"the observational verification result ({verification.verdict}); no cause "
                "is automatically asserted."
            ),
        )
        return self._finalize(result)
    @staticmethod
    def _record_runtime(result: Dict[str, Any], stage: str, processing_type: str,
                        method: str, started_ns: int) -> None:
        result.setdefault("_runtime_stages", []).append({
            "stage": stage,
            "processing_type": processing_type,
            "method": method,
            "latency_ms": max(0.0, (time.monotonic_ns() - started_ns) / 1_000_000),
        })
