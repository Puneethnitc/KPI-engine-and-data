"""Regression checks for the source, access and conclusion boundaries."""

import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd
import yaml

from kpi_engine.normalize import DataNormalizer
from kpi_engine.access import AccessController
from kpi_engine.contracts import KPIRegistry
from kpi_engine.contracts.metrics import daily_values
from kpi_engine.decompose import DeterministicDecomposer
from kpi_engine.contribute import ContributionScenario
from kpi_engine.pipeline import KPIEnginePipeline
from kpi_engine.reconcile import SourceReconciler
from kpi_engine.verification import VerificationDesign


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class PipelineRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = KPIEnginePipeline(
            registry_dir=str(ROOT / "kpi_engine" / "registry"),
            evidence_csv=str(DATA / "unstructured_evidence.csv"),
            access_csv=str(DATA / "access_control.csv"),
            feedback_log_path="/tmp/finalkpi-test-feedback.jsonl",
        )
        cls.paths = {
            "sales_csv": str(DATA / "sales_daily.csv"),
            "marketing_csv": str(DATA / "marketing_weekly.csv"),
            "finance_csv": str(DATA / "finance_monthly.csv"),
        }

    def run_case(self, **overrides):
        args = {
            "kpi_id": "net_sales_revenue",
            "target_date": "2023-07-24",
            "persona": "regional_manager_north",
            "dimension_slice": {"region": "North", "category": "Electronics"},
            **self.paths,
        }
        args.update(overrides)
        return self.pipeline.run_diagnosis(**args)

    def test_scenario_allocation_requires_declared_drivers_and_unit(self):
        values = {(): 100, ("traffic_drop",): 90, ("stockout",): 80,
                  ("traffic_drop", "stockout"): 60}
        scenario = ContributionScenario(
            "orders", "count", ("traffic_drop", "stockout"), values, -50,
        )
        result = self.pipeline.quantify_scenario(scenario)
        self.assertEqual(result["claim_type"], "MODEL_BASED_SCENARIO")
        self.assertEqual(result["unexplained_residual"], -10)
        with self.assertRaisesRegex(ValueError, "unit"):
            self.pipeline.quantify_scenario(replace(scenario, unit="INR"))
        with self.assertRaisesRegex(ValueError, "not declared"):
            self.pipeline.quantify_scenario(replace(
                scenario, drivers=("traffic_drop", "invented"),
            ))

    def test_material_event_has_matching_bridge_and_no_invented_cause(self):
        result = self.run_case()
        self.assertEqual(result["verdict"], "MATERIAL_CAUSE_UNVERIFIED")
        self.assertEqual(result["causal_verdict"], "UNTESTABLE")
        self.assertEqual(result["confidence"]["status"], "NOT_ASSESSED")
        self.assertIsNone(result["confidence"]["calibrated_probability"])
        self.assertEqual(result["reconciliation_verdict"]["status"], "NOT_RECONCILED")
        self.assertEqual(result["source_coverage"]["target_marketing_status"], "UNAVAILABLE_OR_MISSING")
        self.assertIn(
            ("ad_spend_drop", "UNAVAILABLE_AT_TARGET"),
            {(row["driver_id"], row["reason_code"]) for row in result["driver_exclusions"]},
        )
        self.assertAlmostEqual(
            result["movement_assessment"]["delta"],
            result["decomposition"]["total_delta"],
            places=2,
        )
        self.assertEqual(result["decomposition_status"], "IDENTITY_HELD")
        bridge = result["decomposition"]
        self.assertEqual(
            round(bridge["volume_effect"] + bridge["price_effect"] + bridge["mix_effect"], 2),
            bridge["total_delta"],
        )
        self.assertEqual(bridge["effect_labels"]["price_effect"], "aov")
        self.assertEqual(result["decision_cards"][0]["kind"], "NEXT_CHECK")
        self.assertIsNone(result["decision_cards"][0]["expected_impact"])
        self.assertTrue(result["grounding_passed"])
        self.assertTrue(result["narrative_claims"])
        json.dumps(result, allow_nan=False)

    def test_displayed_bridge_balances_after_rounding(self):
        bridge = DeterministicDecomposer.decompose_revenue(
            units_t0=21.443185, units_t1=38.104662,
            aov_t0=43.299387, aov_t1=47.800124,
        )
        self.assertTrue(bridge.is_identity_held)
        self.assertEqual(
            round(bridge.volume_effect + bridge.price_effect + bridge.mix_effect, 2),
            bridge.total_delta,
        )

    def test_orders_bridge_labels_rate_as_conversion_not_price(self):
        result = self.run_case(kpi_id="orders")
        self.assertEqual(result["decomposition_status"], "IDENTITY_HELD")
        self.assertEqual(result["decomposition"]["effect_labels"], {
            "volume_effect": "traffic_total",
            "mix_effect": [],
            "price_effect": "conversion_rate",
        })

    def test_segment_bridge_separates_quantity_mix_and_rate(self):
        base = pd.DataFrame({
            "segment": [("A",), ("B",)],
            "quantity": [100.0, 100.0], "value": [1000.0, 2000.0],
        })
        cases = (
            ([80.0, 80.0], [800.0, 1600.0], "volume_effect", -600.0),
            ([150.0, 50.0], [1500.0, 1000.0], "mix_effect", -500.0),
            ([100.0, 100.0], [500.0, 2000.0], "price_effect", -500.0),
        )
        for quantities, values, expected_leg, expected_delta in cases:
            with self.subTest(expected_leg=expected_leg):
                current = pd.DataFrame({
                    "segment": [("A",), ("B",)],
                    "quantity": quantities, "value": values,
                })
                bridge = DeterministicDecomposer.decompose_product_by_segments(
                    base, current, "net_sales_revenue"
                )
                self.assertEqual(bridge.total_delta, expected_delta)
                self.assertEqual(getattr(bridge, expected_leg), expected_delta)
                for other in {"volume_effect", "mix_effect", "price_effect"} - {expected_leg}:
                    self.assertEqual(getattr(bridge, other), 0.0)

    def test_new_segment_is_mix_not_fabricated_rate(self):
        base = pd.DataFrame({
            "segment": [("A",), ("B",)],
            "quantity": [100.0, 100.0], "value": [1000.0, 2000.0],
        })
        current = pd.DataFrame({
            "segment": [("A",), ("B",), ("NEW",)],
            "quantity": [100.0, 100.0, 40.0],
            "value": [1000.0, 2000.0, 800.0],
        })
        bridge = DeterministicDecomposer.decompose_product_by_segments(
            base, current, "net_sales_revenue"
        )
        self.assertEqual(bridge.price_effect, 0.0)
        self.assertEqual(
            round(bridge.volume_effect + bridge.mix_effect, 2),
            bridge.total_delta,
        )

    def test_bridge_rejects_missing_or_unexplained_values(self):
        base = pd.DataFrame({
            "segment": [("A",)], "quantity": [10.0], "value": [100.0],
        })
        missing = base.copy()
        missing.loc[0, "value"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            DeterministicDecomposer.decompose_product_by_segments(
                base, missing, "orders"
            )
        impossible = base.copy()
        impossible.loc[0, "quantity"] = 0.0
        with self.assertRaisesRegex(ValueError, "zero quantity"):
            DeterministicDecomposer.decompose_product_by_segments(
                base, impossible, "orders"
            )

    def test_segment_bridge_reconciles_random_movements(self):
        rng = random.Random(4)
        for _ in range(100):
            count = rng.randint(1, 6)
            names = [(f"S{i}",) for i in range(count)]
            q0 = [rng.uniform(1, 100) for _ in names]
            q1 = [rng.uniform(1, 100) for _ in names]
            r0 = [rng.uniform(2, 50) for _ in names]
            r1 = [rng.uniform(2, 50) for _ in names]
            base = pd.DataFrame({"segment": names, "quantity": q0,
                                 "value": [q * r for q, r in zip(q0, r0)]})
            current = pd.DataFrame({"segment": names, "quantity": q1,
                                    "value": [q * r for q, r in zip(q1, r1)]})
            bridge = DeterministicDecomposer.decompose_product_by_segments(
                base, current, "net_sales_revenue"
            )
            self.assertTrue(bridge.is_identity_held)
            self.assertEqual(
                round(bridge.volume_effect + bridge.mix_effect + bridge.price_effect, 2),
                bridge.total_delta,
            )

    def test_wide_slice_uses_real_segment_mix(self):
        result = self.run_case(
            target_date="2023-10-30", persona="CFO", dimension_slice={"category": "Home"}
        )
        self.assertEqual(result["decomposition_status"], "IDENTITY_HELD")
        bridge = result["decomposition"]
        self.assertEqual(bridge["effect_labels"]["mix_effect"], ["region"])
        self.assertNotEqual(bridge["mix_effect"], 0.0)
        self.assertEqual(
            round(bridge["volume_effect"] + bridge["mix_effect"] + bridge["price_effect"], 2),
            bridge["total_delta"],
        )

    def test_seasonal_only_signal_does_not_start_diagnosis(self):
        result = self.run_case(target_date="2023-07-22")
        self.assertEqual(result["movement_assessment"]["detector_agreement"], "SEASONAL_ONLY")
        self.assertFalse(result["movement_assessment"]["is_material"])
        self.assertEqual(result["verdict"], "SEASONAL_REVIEW")
        self.assertIsNone(result["decomposition"])

    def test_cross_region_control_is_not_read_by_regional_manager(self):
        design = VerificationDesign(
            driver_id="traffic_drop",
            treated_slice={"region": "North", "category": "Electronics"},
            control_slice={"region": "South", "category": "Electronics"},
            pre_start="2023-06-20", treatment_start="2023-07-20",
            post_end="2023-07-24",
            quiet_windows=(("2023-04-01", "2023-04-14"),
                           ("2023-05-01", "2023-05-14")),
            expected_driver_direction=-1, expected_outcome_direction=-1,
        )
        result = self.run_case(verification_design=design)
        self.assertEqual(result["causal_verdict"], "UNTESTABLE")
        self.assertEqual(result["causal_verification"]["reason_code"],
                         "CONTROL_NOT_AUTHORIZED")

    def test_authorized_observational_design_runs_without_inventing_a_cause(self):
        design = VerificationDesign(
            driver_id="traffic_drop",
            treated_slice={"region": "North", "category": "Electronics"},
            control_slice={"region": "South", "category": "Electronics"},
            pre_start="2023-06-20", treatment_start="2023-07-20",
            post_end="2023-08-06",
            quiet_windows=(("2023-04-01", "2023-04-14"),
                           ("2023-05-01", "2023-05-14")),
            expected_driver_direction=-1, expected_outcome_direction=-1,
        )
        result = self.run_case(
            target_date="2023-08-06", persona="CFO", verification_design=design,
        )
        self.assertEqual(result["verdict"], "MATERIAL_CAUSE_UNVERIFIED")
        self.assertEqual(result["causal_verdict"], "INCONCLUSIVE")
        self.assertEqual(result["causal_verification"]["reason_code"], "CI_INCLUDES_ZERO")
        self.assertEqual(result["confidence"]["status"], "INCONCLUSIVE")
        self.assertEqual(result["decision_cards"][0]["kind"], "NEXT_CHECK")
        self.assertEqual(result["decision_cards"][0]["status"], "AWAITING_REVIEW")

    def test_event_verification_runs_when_final_day_is_not_material(self):
        design = VerificationDesign(
            driver_id="traffic_drop",
            treated_slice={"region": "North", "category": "Electronics"},
            control_slice={"region": "South", "category": "Electronics"},
            pre_start="2023-06-20", treatment_start="2023-07-20",
            post_end="2023-08-13",
            quiet_windows=(("2023-04-01", "2023-04-14"),
                           ("2023-05-01", "2023-05-14")),
            expected_driver_direction=-1, expected_outcome_direction=-1,
        )
        daily = self.run_case(target_date="2023-08-13", persona="CFO",
                              verification_design=design)
        self.assertFalse(daily["movement_assessment"]["is_material"])
        self.assertIsNone(daily["causal_verification"])
        event = self.pipeline.verify_event(
            "net_sales_revenue", design, persona="CFO", **self.paths,
        )
        self.assertEqual(event["verdict"], "EVENT_ASSESSED_CAUSE_UNVERIFIED")
        self.assertIsNotNone(event["causal_verification"])
        self.assertIsNotNone(event["confidence"])
        json.dumps(event, allow_nan=False)

    def test_event_verification_checks_control_access_before_loading_data(self):
        design = VerificationDesign(
            driver_id="traffic_drop",
            treated_slice={"region": "North", "category": "Electronics"},
            control_slice={"region": "South", "category": "Electronics"},
            pre_start="2023-06-20", treatment_start="2023-07-20",
            post_end="2023-08-13", quiet_windows=(),
        )
        result = self.pipeline.verify_event(
            "net_sales_revenue", design, persona="regional_manager_north",
            sales_csv="nonexistent.csv", marketing_csv="nonexistent.csv",
            finance_csv="nonexistent.csv",
        )
        self.assertEqual(result["verdict"], "ACCESS_DENIED")
        self.assertIsNone(result["causal_verification"])
        with self.assertRaisesRegex(ValueError, "as_of cannot precede"):
            self.pipeline.verify_event(
                "net_sales_revenue", design, as_of="2023-08-12", **self.paths,
            )

    def test_manager_cannot_omit_region(self):
        result = self.run_case(dimension_slice=None)
        self.assertEqual(result["verdict"], "ACCESS_DENIED")
        self.assertIsNone(result["movement_assessment"])
        self.assertTrue(result["grounding_passed"])
        self.assertNotIn("North", result["narrative"])

    def test_no_history_is_not_normal(self):
        result = self.run_case(target_date="2023-01-06")
        self.assertEqual(result["verdict"], "INSUFFICIENT_HISTORY")
        self.assertIsNone(result["movement_assessment"]["delta"])

    def test_unavailable_target_day_is_not_read_early(self):
        result = self.run_case(as_of="2023-07-24 23:00:00")
        self.assertEqual(result["verdict"], "NO_DATA_FOR_DATE")
        self.assertIsNone(result["movement_assessment"]["actual_value"])

    def test_provisional_month_is_not_a_contradiction_without_snapshot_time(self):
        result = self.run_case(
            target_date="2024-12-15",
            persona="CFO",
            dimension_slice={"region": "North", "category": "Beauty"},
        )
        self.assertEqual(result["reconciliation_verdict"]["status"], "NOT_RECONCILED")
        self.assertEqual(result["verdict"], "INSUFFICIENT_HISTORY")

    def test_orders_are_not_reconciled_against_revenue(self):
        result = self.run_case(kpi_id="orders")
        self.assertEqual(result["reconciliation_verdict"]["status"], "NOT_RECONCILED")

    def test_orders_do_not_require_unrelated_finance_file(self):
        result = self.run_case(kpi_id="orders", finance_csv="/not/a/finance/file.csv")
        self.assertEqual(result["movement_assessment"]["status"], "OK")
        self.assertIn("No comparable second source", result["reconciliation_verdict"]["details"]["reason"])

    def test_contracts_declare_supported_sources_and_drivers(self):
        revenue = self.pipeline.registry.get("net_sales_revenue")
        orders = self.pipeline.registry.get("orders")
        self.assertEqual(revenue.reconciliation["finance_column"], "net_sales_revenue")
        self.assertIsNone(orders.reconciliation)
        self.assertEqual(revenue.decomposition["quantity_column"], "units_sold")
        self.assertEqual(orders.decomposition["quantity_column"], "traffic_total")
        self.assertEqual(len(revenue.candidate_drivers), 5)

    def test_undeclared_driver_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Drivers not declared"):
            self.run_case(candidate_drivers=["invented_signal"])

    def test_five_supported_kpis_are_registered(self):
        self.assertEqual(
            set(self.pipeline.registry.list_ids()), {
                "net_sales_revenue", "orders", "units_sold", "traffic_total",
                "conversion_rate",
            }
        )

    def test_all_five_kpis_produce_grounded_diagnoses(self):
        for kpi_id in self.pipeline.registry.list_ids():
            with self.subTest(kpi_id=kpi_id):
                result = self.run_case(kpi_id=kpi_id, persona="CFO")
                self.assertTrue(result["grounding_passed"])
                self.assertEqual(result["movement_assessment"]["status"], "OK")
                self.assertIn(result["verdict"], {
                    "MATERIAL_CAUSE_UNVERIFIED", "NO_MATERIAL_MOVEMENT", "SEASONAL_REVIEW",
                })
                json.dumps(result, allow_nan=False)

    def test_conversion_rate_uses_ratio_of_sums_not_mean_displayed_rate(self):
        contract = self.pipeline.registry.get("conversion_rate")
        sales = self.pipeline.normalizer.load_and_normalize_sales(
            self.paths["sales_csv"], as_of=pd.Timestamp("2023-07-25 12:00")
        )
        day = sales[sales["date"].eq(pd.Timestamp("2023-07-24"))]
        self.assertAlmostEqual(
            daily_values(day, contract).iloc[0],
            day["orders"].sum() / day["traffic_total"].sum(),
        )

    def test_contract_registry_can_validate_six_future_definitions(self):
        """Capacity test only: these synthetic contracts are not installed KPIs."""
        source = yaml.safe_load((ROOT / "kpi_engine" / "registry" / "orders.yaml").read_text())
        with tempfile.TemporaryDirectory() as directory:
            for index in range(6):
                item = dict(source)
                item["kpi_id"] = f"future_kpi_{index}"
                item["value_column"] = item["kpi_id"]
                item["formula"] = item["kpi_id"]
                if index % 2:
                    item["aggregation"] = "ratio_of_sums"
                    item["numerator_column"] = "orders"
                    item["denominator_column"] = "traffic_total"
                    item["decomposition"] = None
                else:
                    item["decomposition"] = None
                Path(directory, f"{item['kpi_id']}.yaml").write_text(yaml.safe_dump(item))
            registry = KPIRegistry(directory)
            self.assertEqual(len(registry), 6)
            self.assertEqual(registry.get("future_kpi_1").aggregation, "ratio_of_sums")

    def test_ratio_contract_requires_both_components(self):
        source = yaml.safe_load((ROOT / "kpi_engine" / "registry" / "orders.yaml").read_text())
        source.update(kpi_id="future_ratio", value_column="future_ratio",
                      aggregation="ratio_of_sums", decomposition=None,
                      numerator_column="orders")
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "future_ratio.yaml").write_text(yaml.safe_dump(source))
            with self.assertRaisesRegex(ValueError, "ratio requires numerator and denominator"):
                KPIRegistry(directory)

    def test_daily_ratio_contract_runs_without_installing_a_new_kpi(self):
        source = yaml.safe_load((ROOT / "kpi_engine" / "registry" / "orders.yaml").read_text())
        source.update(kpi_id="conversion_probe", value_column="conversion_probe",
                      formula="sum(orders) / sum(traffic_total)", unit="ratio",
                      aggregation="ratio_of_sums", numerator_column="orders",
                      denominator_column="traffic_total", decomposition=None,
                      reconciliation=None, candidate_drivers=[])
        source["materiality"] = {"z_threshold": 2.5, "abs_threshold": 0.001}
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "conversion_probe.yaml").write_text(yaml.safe_dump(source))
            pipeline = KPIEnginePipeline(
                directory, str(DATA / "unstructured_evidence.csv"),
                access_csv=str(DATA / "access_control.csv"),
            )
            result = pipeline.run_diagnosis(
                kpi_id="conversion_probe", target_date="2023-07-24",
                persona="CFO", dimension_slice={"region": "North"}, **self.paths,
            )
            self.assertEqual(result["movement_assessment"]["status"], "OK")
            self.assertIsNone(result["decomposition"])
            sales = DataNormalizer().load_and_normalize_sales(self.paths["sales_csv"])
            rows = sales[(sales["date"] == pd.Timestamp("2023-07-24")) &
                         (sales["region"] == "North")]
            expected = rows["orders"].sum() / rows["traffic_total"].sum()
            self.assertAlmostEqual(result["movement_assessment"]["actual_value"], expected, places=6)
            self.assertNotAlmostEqual(expected, rows["conversion_rate"].mean(), places=6)

    def test_source_column_can_differ_from_kpi_id(self):
        source = yaml.safe_load((ROOT / "kpi_engine" / "registry" / "orders.yaml").read_text())
        source.update(kpi_id="order_count_probe", value_column="orders",
                      formula="orders", decomposition=None, reconciliation=None,
                      candidate_drivers=[])
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "order_count_probe.yaml").write_text(yaml.safe_dump(source))
            pipeline = KPIEnginePipeline(
                directory, str(DATA / "unstructured_evidence.csv"),
                access_csv=str(DATA / "access_control.csv"),
            )
            result = pipeline.run_diagnosis(
                kpi_id="order_count_probe", target_date="2023-07-24",
                persona="CFO", dimension_slice={"region": "North", "category": "Electronics"},
                sales_csv=self.paths["sales_csv"],
                marketing_csv="/not/a/marketing/file.csv",
                finance_csv="/not/a/finance/file.csv",
            )
            self.assertEqual(result["movement_assessment"]["status"], "OK")
            self.assertIsNone(result["decomposition"])
            self.assertEqual(result["source_coverage"]["target_marketing_status"], "NOT_DECLARED")

    def test_mean_and_weighted_mean_contract_aggregation(self):
        base = self.pipeline.registry.get("orders")
        frame = pd.DataFrame({
            "date": pd.to_datetime(["2023-07-24", "2023-07-24"]),
            "score": [10.0, 20.0], "weight": [1.0, 9.0],
        })
        mean = replace(base, value_column="score", aggregation="mean", decomposition={})
        mean.validate_grain()
        self.assertAlmostEqual(daily_values(frame, mean).iloc[0], 15.0)
        weighted = replace(mean, aggregation="weighted_mean", weight_column="weight")
        weighted.validate_grain()
        self.assertAlmostEqual(daily_values(frame, weighted).iloc[0], 19.0)

    def test_zero_ratio_denominator_is_missing_not_zero(self):
        base = self.pipeline.registry.get("orders")
        ratio = replace(base, aggregation="ratio_of_sums", decomposition={},
                        numerator_column="orders", denominator_column="traffic_total")
        ratio.validate_grain()
        frame = pd.DataFrame({"date": pd.to_datetime(["2023-07-24"]),
                              "orders": [0.0], "traffic_total": [0.0]})
        self.assertTrue(pd.isna(daily_values(frame, ratio).iloc[0]))

    def test_weekly_contract_fails_before_daily_pipeline(self):
        source = yaml.safe_load((ROOT / "kpi_engine" / "registry" / "orders.yaml").read_text())
        source["grain"] = "weekly"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "orders.yaml").write_text(yaml.safe_dump(source))
            pipeline = KPIEnginePipeline(
                directory, str(DATA / "unstructured_evidence.csv"),
                access_csv=str(DATA / "access_control.csv"),
            )
            with self.assertRaisesRegex(ValueError, "Unsupported grain"):
                pipeline.run_diagnosis(
                    "orders", "2023-07-24", self.paths["sales_csv"],
                    self.paths["marketing_csv"], self.paths["finance_csv"],
                    persona="CFO",
                )

    def test_reconciliation_tolerance_is_configurable(self):
        daily = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]),
                              "region": ["North"], "category": ["Electronics"],
                              "net_sales_revenue": [100.0]})
        finance = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]),
                                "month_end": pd.to_datetime(["2024-01-01"]),
                                "region": ["North"], "category": ["Electronics"],
                                "net_sales_revenue": [108.0]})
        reconciler = SourceReconciler()
        normal = reconciler.reconcile_mtd(daily, finance, "2024-01", target_date="2024-01-01")
        wider = reconciler.reconcile_mtd(daily, finance, "2024-01", target_date="2024-01-01",
                                         historical_tolerance_pct=10.0)
        self.assertEqual(normal.status, "DRIFT")
        self.assertEqual(wider.status, "AGREED")

    def test_snapshot_reconciliation_requires_cutoff_and_unit_match(self):
        daily = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "region": ["North", "North", "North"],
            "category": ["Electronics", "Electronics", "Electronics"],
            "available_at": pd.to_datetime(["2024-01-02 00:00:00", "2024-01-02 00:00:00", "2024-01-02 00:00:00"]),
            "net_sales_revenue": [100.0, 100.0, 100.0],
            "unit": ["USD", "USD", "USD"],
        })
        finance = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "month_end": pd.to_datetime(["2024-01-31"]),
            "region": ["North"],
            "category": ["Electronics"],
            "available_at": pd.to_datetime(["2024-02-10 00:00:00"]),
            "net_sales_revenue": [300.0],
            "unit": ["USD"],
        })
        reconciler = SourceReconciler()
        result = reconciler.reconcile_mtd(
            daily, finance, "2024-01",
            target_date="2024-01-31",
            as_of="2024-02-01 00:00:00",
            mode="snapshot",
        )
        self.assertEqual(result.status, "NOT_RECONCILED")
        self.assertIn("snapshot", result.details["reason"].lower())

    def test_source_schema_yaml_handles_renamed_sales_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            sales = pd.read_csv(self.paths["sales_csv"])
            sales = sales.rename(columns={"date": "business_day", "available_at": "extract_time",
                                          "net_sales_revenue": "sales_value"})
            sales_path = Path(directory, "renamed_sales.csv")
            sales.to_csv(sales_path, index=False)
            schema_path = Path(directory, "source_schema.yaml")
            schema_path.write_text(yaml.safe_dump({"sales_daily": {
                "date": "business_day", "available_at": "extract_time",
                "net_sales_revenue": "sales_value",
            }}))
            pipeline = KPIEnginePipeline(
                str(ROOT / "kpi_engine" / "registry"),
                str(DATA / "unstructured_evidence.csv"),
                access_csv=str(DATA / "access_control.csv"),
                source_schema_path=str(schema_path),
            )
            result = pipeline.run_diagnosis(
                "net_sales_revenue", "2023-07-24", str(sales_path),
                self.paths["marketing_csv"], self.paths["finance_csv"],
                persona="CFO", dimension_slice={"region": "North", "category": "Electronics"},
            )
            expected = self.run_case(persona="CFO")
            self.assertEqual(result["movement_assessment"], expected["movement_assessment"])

    def test_contract_loader_rejects_duplicate_yaml_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "bad.yaml").write_text("kpi_id: bad\nkpi_id: other\n")
            with self.assertRaisesRegex(ValueError, "Duplicate YAML key"):
                KPIRegistry(directory)

    def test_contract_loader_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source = (ROOT / "kpi_engine" / "registry" / "orders.yaml").read_text()
            Path(directory, "orders.yaml").write_text(source + "\nunsupported_claim: true\n")
            with self.assertRaisesRegex(ValueError, "unknown contract fields"):
                KPIRegistry(directory)

    def test_contract_loader_supports_versioned_schema_and_source_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "sales_revenue_v2.yaml").write_text(
                yaml.safe_dump({
                    "schema_version": 2,
                    "kpi_id": "sales_revenue_v2",
                    "version": 2,
                    "definition": "Daily net sales revenue.",
                    "formula": "net_sales_revenue # descriptive text",
                    "unit": "INR",
                    "grain": "daily",
                    "source": "sales_daily",
                    "dimensions": ["region", "category"],
                    "materiality": {"z_threshold": 2.5, "abs_threshold": 500.0},
                    "seasonal_period": 7,
                    "min_history_periods": 30,
                    "owner": "regional_manager",
                    "access_tags": ["region_scoped"],
                    "calculation": {
                        "operator": "sum",
                        "value_column": "net_sales_revenue",
                        "formula": "net_sales_revenue",
                    },
                    "source_catalog": {
                        "source_id": "sales_daily",
                        "format": "csv",
                        "grain": "daily",
                        "dimensions": ["region", "category"],
                        "natural_key": ["date", "region", "category"],
                        "unit": "INR",
                        "fields": {
                            "date": {"type": "date", "required": True},
                            "region": {"type": "string", "required": True},
                            "category": {"type": "string", "required": True},
                            "available_at": {"type": "datetime", "required": True},
                            "net_sales_revenue": {"type": "float", "required": True},
                        },
                        "availability": {"field": "available_at", "cutoff_policy": "as_of"},
                        "missing_data": {"null_policy": "reject", "partial_group_policy": "reject"},
                    },
                    "comparison_policy": {
                        "period": "same_slice_closed_month_only",
                        "weighting": "none",
                        "completeness": "required",
                    },
                    "candidate_drivers": [],
                })
            )
            registry = KPIRegistry(directory)
            contract = registry.get("sales_revenue_v2")
            self.assertEqual(contract.schema_version, 2)
            self.assertEqual(contract.calculation.operator, "sum")
            self.assertEqual(contract.source_catalog.source_id, "sales_daily")
            self.assertEqual(contract.comparison_policy.period, "same_slice_closed_month_only")
            self.assertEqual(contract.formula, "net_sales_revenue # descriptive text")

    def test_closed_month_reconciles_after_posting(self):
        result = self.run_case(
            target_date="2023-02-28", as_of="2023-03-07 12:00:00", persona="CFO"
        )
        self.assertEqual(result["reconciliation_verdict"]["status"], "AGREED")
        self.assertEqual(result["reconciliation_verdict"]["gap_pct"], 0.0)

    def test_demo_overrides_are_rejected(self):
        for flag in ("force_material", "bypass_reconciliation"):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.run_case(**{flag: True})

    def test_source_availability_and_lineage(self):
        sales, finance = DataNormalizer().align_sources(
            *[self.paths[k] for k in ("sales_csv", "marketing_csv", "finance_csv")],
            as_of=pd.Timestamp("2023-07-25 12:00:00"),
        )
        row = sales.loc[
            (sales["date"] == pd.Timestamp("2023-07-24"))
            & (sales["region"] == "North")
            & (sales["category"] == "Electronics")
        ].iloc[0]
        self.assertEqual(row["source_system"], "sales_ops_db")
        self.assertTrue(pd.isna(row["marketing_spend"]))
        self.assertFalse((sales["available_at"] > pd.Timestamp("2023-07-25 12:00:00")).any())
        self.assertTrue(finance.empty or
                        (finance["available_at"] <= pd.Timestamp("2023-07-25 12:00:00")).all())

    def test_null_values_cannot_be_reconciled_as_two_zeroes(self):
        daily = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]), "region": ["North"],
            "category": ["Electronics"], "net_sales_revenue": [float("nan")],
        })
        finance = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "month_end": pd.to_datetime(["2024-01-01"]),
            "region": ["North"], "category": ["Electronics"],
            "net_sales_revenue": [float("nan")],
        })
        result = SourceReconciler().reconcile_mtd(
            daily, finance, "2024-01", target_date="2024-01-01",
        )
        self.assertEqual(result.status, "NOT_RECONCILED")
        self.assertIn("Missing", result.details["reason"])

    def test_incomplete_sales_period_or_finance_slice_cannot_reconcile(self):
        daily = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-03"]),
            "region": ["North", "North"],
            "category": ["Electronics", "Electronics"],
            "net_sales_revenue": [100.0, 100.0],
        })
        finance = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "month_end": pd.to_datetime(["2024-01-03"]),
            "region": ["North"], "category": ["Electronics"],
            "net_sales_revenue": [200.0],
        })
        reconciler = SourceReconciler()
        result = reconciler.reconcile_mtd(daily, finance, "2024-01", target_date="2024-01-03")
        self.assertEqual(result.status, "NOT_RECONCILED")
        self.assertIn("coverage", result.details["reason"])
        daily.loc[len(daily)] = [pd.Timestamp("2024-01-02"), "North", "Apparel", 0.0]
        result = reconciler.reconcile_mtd(daily, finance, "2024-01", target_date="2024-01-03")
        self.assertEqual(result.status, "NOT_RECONCILED")
        self.assertIn("different", result.details["reason"])

    def test_weekly_join_reports_missing_coverage_without_fanout(self):
        with tempfile.TemporaryDirectory() as directory:
            marketing = pd.read_csv(self.paths["marketing_csv"])
            missing = ((marketing["week_start"] == "2023-07-24") &
                       (marketing["region"] == "North") &
                       (marketing["category"] == "Electronics"))
            self.assertEqual(int(missing.sum()), 1)
            marketing_path = Path(directory, "marketing_missing.csv")
            marketing.loc[~missing].to_csv(marketing_path, index=False)
            daily, _ = DataNormalizer().align_sources(
                self.paths["sales_csv"], str(marketing_path), self.paths["finance_csv"],
                as_of=pd.Timestamp("2023-08-10 12:00:00"),
            )
            target = daily[(daily["date"] == pd.Timestamp("2023-07-24")) &
                           (daily["region"] == "North") &
                           (daily["category"] == "Electronics")]
            self.assertEqual(len(target), 1)
            self.assertEqual(target.iloc[0]["marketing_coverage"], "UNAVAILABLE_OR_MISSING")

    def test_missing_sales_availability_is_rejected_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            sales = pd.read_csv(self.paths["sales_csv"]).drop(columns=["available_at"])
            path = Path(directory, "sales_without_availability.csv")
            sales.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "available_at"):
                DataNormalizer().load_and_normalize_sales(str(path))

    def test_sales_rejects_non_finite_numeric_values(self):
        with tempfile.TemporaryDirectory() as directory:
            sales = pd.read_csv(self.paths["sales_csv"])
            sales.loc[0, "net_sales_revenue"] = float("nan")
            path = Path(directory, "sales_bad_numeric.csv")
            sales.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "non-finite"):
                DataNormalizer().load_and_normalize_sales(str(path))

    def test_finance_revision_keeps_latest_posting_for_same_slice(self):
        with tempfile.TemporaryDirectory() as directory:
            finance = pd.DataFrame({
                "region": ["North", "North"],
                "category": ["Electronics", "Electronics"],
                "month_start": ["2024-01-01", "2024-01-01"],
                "month_end": ["2024-01-31", "2024-01-31"],
                "net_sales_revenue": [100.0, 150.0],
                "available_at": ["2024-01-01 00:00:00", "2024-01-05 00:00:00"],
                "revision": [1, 2],
            })
            path = Path(directory, "finance_revision.csv")
            finance.to_csv(path, index=False)
            result = DataNormalizer().load_and_normalize_finance(str(path))
            self.assertEqual(len(result), 1)
            self.assertEqual(result.iloc[0]["net_sales_revenue"], 150.0)

    def test_category_scoped_role_rejects_omitted_category(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "access_control.csv")
            pd.DataFrame({
                "region": ["North"],
                "owner_role": ["regional_manager_north"],
                "can_view_categories": ["Electronics"],
            }).to_csv(path, index=False)
            access = AccessController(str(path))
            decision = access.check("regional_manager_north", {"region": "North"})
            self.assertFalse(decision.allowed)
            self.assertIn("category", decision.reason.lower())

    def test_future_duplicate_does_not_break_historical_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            sales = pd.read_csv(self.paths["sales_csv"])
            future = sales.loc[sales["date"] == "2024-12-30"].iloc[[0]]
            sales = pd.concat([sales, future], ignore_index=True)
            path = Path(directory, "sales_future_duplicate.csv")
            sales.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "duplicate rows"):
                DataNormalizer().load_and_normalize_sales(str(path))
            result = self.run_case(sales_csv=str(path))
            self.assertEqual(result["movement_assessment"]["status"], "OK")

    def test_declared_marketing_primary_source_is_not_read_as_sales(self):
        source = yaml.safe_load((ROOT / "kpi_engine" / "registry" / "orders.yaml").read_text())
        source["source"] = "marketing_weekly"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "orders.yaml").write_text(yaml.safe_dump(source))
            pipeline = KPIEnginePipeline(
                directory, str(DATA / "unstructured_evidence.csv"),
                access_csv=str(DATA / "access_control.csv"),
            )
            with self.assertRaisesRegex(ValueError, "Unsupported primary KPI source"):
                pipeline.run_diagnosis(
                    "orders", "2023-07-24", self.paths["sales_csv"],
                    self.paths["marketing_csv"], self.paths["finance_csv"], persona="CFO",
                )

    def test_reconciliation_uses_same_segment_and_date(self):
        daily = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "region": ["North", "North", "South"],
            "category": ["Electronics"] * 3,
            "net_sales_revenue": [100.0, 200.0, 900.0],
        })
        finance = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "month_end": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "region": ["North", "South"],
            "category": ["Electronics", "Electronics"],
            "net_sales_revenue": [100.0, 900.0],
        })
        result = SourceReconciler().reconcile_mtd(
            daily, finance, "2024-01", target_date="2024-01-01",
            dimension_slice={"region": "North", "category": "Electronics"},
        )
        self.assertEqual(result.status, "AGREED")
        self.assertEqual(result.details["sales_mtd_total"], 100.0)


if __name__ == "__main__":
    unittest.main()
