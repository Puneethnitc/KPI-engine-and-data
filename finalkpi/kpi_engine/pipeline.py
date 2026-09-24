"""As-of KPI diagnosis with explicit boundaries between facts and hypotheses.

The public path stops after correlational ranking until an event exposure and
eligible control group are supplied. It never promotes a correlation to cause.
"""

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

import pandas as pd
import yaml

from kpi_engine.access import AccessController
from kpi_engine.action import ActionRecommendationEngine
from kpi_engine.contracts import KPIRegistry
from kpi_engine.contribute import ContributionScenario, ShapleyContributor
from kpi_engine.confidence import ConfidenceEngine
from kpi_engine.decompose import DeterministicDecomposer
from kpi_engine.detection import AnomalyDetector
from kpi_engine.feedback import FeedbackLogger
from kpi_engine.normalize import DataNormalizer
from kpi_engine.narrative import NarrativeEngine
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
        feedback_log_path: str = "data/feedback_log.jsonl",
        source_schema_path: Optional[str] = None,
    ):
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
        contract = self.registry.get(scenario.kpi_id)
        declared = {driver["id"] for driver in contract.candidate_drivers}
        if set(scenario.drivers) - declared:
            raise ValueError("Scenario contains drivers not declared for this KPI")
        if scenario.unit != contract.unit:
            raise ValueError("Scenario unit does not match the KPI contract")
        return asdict(self.contributor.quantify(scenario))

    def _finalize(self, result: Dict[str, Any]) -> Dict[str, Any]:
        result["decision_cards"] = self.recommender.recommend(result)
        rendered = self.narrator.render(result)
        result["narrative"] = rendered["text"]
        result["narrative_claims"] = rendered["claims"]
        result["grounding_passed"] = rendered["grounding_passed"]
        result["grounding_errors"] = rendered["rejected_claims"]
        result["narrative_method"] = rendered["method"]
        result["llm_status"] = rendered["llm_status"]
        return result

    @staticmethod
    def _slice(frame: pd.DataFrame, dimension_slice: Optional[Dict[str, str]]) -> pd.DataFrame:
        result = frame
        for key, value in (dimension_slice or {}).items():
            if key not in result.columns:
                raise ValueError(f"Unknown dimension: {key}")
            result = result[result[key] == value]
        return result

    def verify_event(
        self,
        kpi_id: str,
        verification_design: VerificationDesign,
        sales_csv: str,
        marketing_csv: str,
        finance_csv: str,
        persona: str = "CFO",
        as_of: Optional[str] = None,
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
        }
        for label, group in (("treated", verification_design.treated_slice),
                             ("control", verification_design.control_slice)):
            access = self.access_controller.check(persona, group)
            if not access.allowed:
                result.update(verdict="ACCESS_DENIED", narrative=f"{label} slice: {access.reason}")
                return self._finalize(result)

        contract = self.registry.get(kpi_id)
        if contract.source != "sales_daily" or contract.grain != "daily":
            raise ValueError("Event verification currently supports daily sales KPIs only")
        unsupported = {driver["source"] for driver in contract.candidate_drivers} - {
            "sales_daily", "marketing_weekly"
        }
        if unsupported:
            raise ValueError(f"Unsupported driver sources: {sorted(unsupported)}")
        daily, finance = self.normalizer.align_sources(
            sales_csv,
            marketing_csv if any(driver["source"] == "marketing_weekly"
                                 for driver in contract.candidate_drivers) else None,
            finance_csv if contract.reconciliation is not None else None,
            as_of=cutoff,
        )
        if contract.aggregation == "sum" and contract.value_column != kpi_id:
            if contract.value_column not in daily.columns:
                raise ValueError(f"Missing KPI source column: {contract.value_column}")
            daily[kpi_id] = daily[contract.value_column]
        daily = daily[daily["date"] <= end].copy()
        if contract.reconciliation is None:
            reconciliation = self.reconciler.not_reconciled(
                f"No comparable second source is declared for {kpi_id}"
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
            )
        result["reconciliation_verdict"] = asdict(reconciliation)
        if reconciliation.status == "CONTRADICTED":
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
            "correlational_candidates": [],
            "driver_exclusions": [],
            "causal_verdict": None,
            "causal_verification": None,
            "confidence": None,
            "decision_cards": [],
            "grounding_passed": True,
            "telemetry": None,
        }

        access = self.access_controller.check(persona, dimension_slice)
        if not access.allowed:
            result.update(verdict="ACCESS_DENIED", narrative=access.reason)
            return self._finalize(result)

        contract = self.registry.get(kpi_id)
        if contract.source != "sales_daily":
            raise ValueError(
                f"Unsupported primary KPI source: {contract.source}. "
                "This pipeline currently diagnoses sales_daily KPIs only."
            )
        if contract.grain != "daily":
            raise ValueError(f"Unsupported grain for this pipeline: {contract.grain}")
        unsupported_drivers = {
            driver['source'] for driver in contract.candidate_drivers
        } - {'sales_daily', 'marketing_weekly'}
        if unsupported_drivers:
            raise ValueError(f"Unsupported driver sources: {sorted(unsupported_drivers)}")

        daily, finance = self.normalizer.align_sources(
            sales_csv,
            marketing_csv if any(driver['source'] == 'marketing_weekly'
                                 for driver in contract.candidate_drivers) else None,
            finance_csv if contract.reconciliation is not None else None,
            as_of=cutoff,
        )
        if contract.aggregation == "sum" and contract.value_column != kpi_id:
            if contract.value_column not in daily.columns:
                raise ValueError(f"Missing KPI source column: {contract.value_column}")
            daily[kpi_id] = daily[contract.value_column]
        daily = daily[daily["date"] <= target].copy()
        scoped = self._slice(daily, dimension_slice)
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

        if contract.reconciliation is None:
            reconciliation = self.reconciler.not_reconciled(
                f"No comparable second source is declared for {kpi_id}"
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
            )
        result["reconciliation_verdict"] = asdict(reconciliation)
        if reconciliation.status == "CONTRADICTED":
            result.update(
                verdict="CONTRADICTED",
                narrative="The source systems disagree about this movement. Check the postings before diagnosing a cause.",
            )
            return self._finalize(result)

        assessment = self.detector.evaluate_movement(
            scoped, contract, target.date().isoformat(), metric_col=kpi_id
        )
        result["movement_assessment"] = asdict(assessment)
        if assessment.status != "OK":
            result.update(
                verdict=assessment.status,
                narrative=f"This KPI cannot be assessed yet: {assessment.status.lower().replace('_', ' ')}.",
            )
            return self._finalize(result)
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

        # The detector compares the target observation to the preceding
        # arithmetic mean. The bridge uses exactly those same periods.
        history_days = max(30, contract.min_history_periods)
        baseline = scoped[
            (scoped["date"] < target)
            & (scoped["date"] >= target - pd.Timedelta(days=history_days))
        ]
        current = scoped[scoped["date"] == target]
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

                base_parts = segment_parts(baseline, baseline["date"].nunique())
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
                    result["decomposition"] = {
                        **asdict(bridge),
                        "effect_labels": {
                            "volume_effect": quantity_col,
                            "mix_effect": remaining_dims,
                            "price_effect": contract.decomposition["reference_rate_column"],
                        },
                    }
                    result["decomposition_status"] = "IDENTITY_HELD"

        driver_specs = {driver["id"]: driver for driver in contract.candidate_drivers}
        driver_columns = {driver_id: spec["column"] for driver_id, spec in driver_specs.items()}
        candidates = candidate_drivers if candidate_drivers is not None else list(driver_columns)
        unknown_drivers = set(candidates) - set(driver_columns)
        if unknown_drivers:
            raise ValueError(f"Drivers not declared for {kpi_id}: {sorted(unknown_drivers)}")
        # A weekly signal that is not yet available on the target day cannot
        # support a candidate explanation for that target-day movement.
        target_rows = scoped[scoped['date'] == target]
        unavailable_weekly = [driver_id for driver_id in candidates if (
            driver_specs[driver_id]['source'] == 'marketing_weekly'
            and (
                target_rows.empty
                or driver_specs[driver_id]['column'] not in target_rows.columns
                or not target_rows[driver_specs[driver_id]['column']].notna().all()
            )
        )]
        candidates = [driver_id for driver_id in candidates if driver_id not in unavailable_weekly]
        evaluation = self.ranker.evaluate_candidates(
            scoped, kpi_id, candidates, target_date=target.date().isoformat(),
            driver_columns=driver_columns, contract=contract,
        )
        result["correlational_candidates"] = [asdict(candidate) for candidate in evaluation.candidates]
        result["driver_exclusions"] = [asdict(exclusion) for exclusion in (
            [DriverExclusion(
                driver_id, "UNAVAILABLE_AT_TARGET",
                "Weekly driver report was not available for the target slice at the as-of cutoff",
            ) for driver_id in unavailable_weekly] + evaluation.exclusions
        )]
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
