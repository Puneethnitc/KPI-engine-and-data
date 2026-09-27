"""The API projection, executable registry, and historical contract snapshots agree."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi import HTTPException

from backend import storage
from backend.app import api_kpi_contract, api_kpis, api_diagnosis_contract
import backend.service as backend_service
from backend.service import get_current_kpi_contract, get_run_kpi_contract
from kpi_engine.contracts.registry import KPIRegistry
from kpi_engine.contracts.semantic import canonical_json
from backend.storage import save_diagnosis_run

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIR = ROOT / "kpi_engine" / "registry"


class SemanticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = KPIRegistry(str(REGISTRY_DIR))

    def write_contract(self, directory: str, source: dict) -> None:
        Path(directory, f"{source['kpi_id']}.yaml").write_text(yaml.safe_dump(source))

    def test_registry_contains_all_five_executable_kpis(self):
        self.assertEqual(set(self.registry.list_ids()), {
            "traffic_total", "conversion_rate", "orders", "units_sold", "net_sales_revenue",
        })
        for kpi_id in self.registry.list_ids():
            snapshot = self.registry.semantic_snapshot(kpi_id, allowed_roles=["CFO"])
            self.assertEqual(snapshot["governance"]["validation_status"], "VALID")
            self.assertEqual(snapshot["identity"]["kpi_id"], kpi_id)
            self.assertTrue(snapshot["governance"]["contract_hash"])

    def test_current_contract_uses_one_canonical_shape_and_contract_specific_policies(self):
        expected_sections = {
            "schema_version", "identity", "calculation", "grain_and_scope", "source",
            "materiality", "drivers", "reconciliation", "decomposition", "security",
            "governance", "capabilities",
        }
        for kpi_id in self.registry.list_ids():
            snapshot = api_kpi_contract(kpi_id, user_id="demo-cfo")
            self.assertEqual(set(snapshot), expected_sections)

        conversion = api_kpi_contract("conversion_rate", user_id="demo-cfo")
        self.assertEqual(conversion["calculation"]["operator"], "RATIO_OF_SUMS")
        self.assertEqual(conversion["calculation"]["numerator_column"], "orders")
        self.assertEqual(conversion["calculation"]["denominator_column"], "traffic_total")

        revenue = api_kpi_contract("net_sales_revenue", user_id="demo-cfo")
        self.assertEqual(revenue["calculation"]["value_column"], "net_sales_revenue")
        self.assertEqual(revenue["calculation"]["formula"], "net_sales_revenue")

        orders = api_kpi_contract("orders", user_id="demo-cfo")
        self.assertFalse(orders["reconciliation"]["applicable"])
        units = api_kpi_contract("units_sold", user_id="demo-cfo")
        self.assertEqual(units["capabilities"]["decomposition"], "NOT_APPLICABLE")
        traffic = api_kpi_contract("traffic_total", user_id="demo-cfo")
        self.assertIn("channel overlap", " ".join(traffic["calculation"]["aggregation_notes"]).lower())

        configured = {
            kpi_id for kpi_id in self.registry.list_ids()
            if self.registry.get(kpi_id).reconciliation is not None
        }
        exposed = {
            kpi_id for kpi_id in self.registry.list_ids()
            if api_kpi_contract(kpi_id, user_id="demo-cfo")["reconciliation"]["applicable"]
        }
        self.assertEqual(exposed, configured)

    def test_conversion_rate_projection_matches_executable_ratio_of_sums(self):
        contract = self.registry.get("conversion_rate")
        projection = self.registry.semantic_snapshot("conversion_rate", allowed_roles=["CFO"])
        self.assertEqual(contract.resolved_calculation().operator, "ratio_of_sums")
        self.assertEqual(projection["calculation"]["operator"], "RATIO_OF_SUMS")
        self.assertEqual(projection["calculation"]["numerator_column"], "orders")
        self.assertEqual(projection["calculation"]["denominator_column"], "traffic_total")
        self.assertIn("never average displayed daily rates", " ".join(projection["calculation"]["aggregation_notes"]))

    def test_hash_is_canonical_and_changes_with_semantics(self):
        baseline = self.registry.semantic_snapshot("orders", allowed_roles=["CFO"])
        reordered = dict(reversed(list(baseline.items())))
        self.assertEqual(canonical_json(baseline), canonical_json(reordered))
        changed_contract = copy.deepcopy(self.registry.get("orders"))
        changed_contract.definition += " This changes meaning."
        source = self.registry.source_catalog.get_source("sales_daily")
        from kpi_engine.contracts.semantic import semantic_contract_projection
        changed = semantic_contract_projection(changed_contract, source, allowed_roles=["CFO"])
        self.assertNotEqual(
            baseline["governance"]["contract_hash"],
            changed["governance"]["contract_hash"],
        )

    def test_hash_changes_for_threshold_driver_and_security_changes(self):
        from kpi_engine.contracts.semantic import semantic_contract_projection

        baseline_contract = copy.deepcopy(self.registry.get("orders"))
        source = self.registry.source_catalog.get_source("sales_daily")
        baseline = semantic_contract_projection(baseline_contract, source, allowed_roles=["CFO"])
        changes = (
            lambda contract: setattr(contract.materiality, "abs_threshold", contract.materiality.abs_threshold + 1),
            lambda contract: contract.candidate_drivers[0].update(min_pairs=contract.candidate_drivers[0].get("min_pairs", 14) + 1),
            lambda contract: contract.access_tags.append("internal"),
        )
        for change in changes:
            changed_contract = copy.deepcopy(baseline_contract)
            change(changed_contract)
            changed = semantic_contract_projection(changed_contract, source, allowed_roles=["CFO"])
            self.assertNotEqual(baseline["governance"]["contract_hash"], changed["governance"]["contract_hash"])

    def test_redaction_preserves_canonical_hash_and_does_not_expose_paths(self):
        from kpi_engine.contracts.semantic import redact_contract_projection

        canonical = self.registry.semantic_snapshot("net_sales_revenue", allowed_roles=["CFO"])
        original_hash = canonical["governance"]["contract_hash"]
        redacted = redact_contract_projection(canonical, "marketing_manager")
        self.assertEqual(canonical["governance"]["contract_hash"], original_hash)
        self.assertEqual(redacted["governance"]["contract_hash"], original_hash)
        self.assertIsNone(redacted["reconciliation"]["comparison_metric"])
        self.assertNotIn("/mnt/storage", canonical_json(redacted))
        self.assertNotIn("file_path", canonical_json(redacted))

    def test_missing_source_and_source_field_fail_with_contract_field(self):
        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["source"] = "missing_source"
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "orders.source"):
                KPIRegistry(directory)

        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["value_column"] = "not_in_catalog"
        source["calculation"]["value_column"] = "not_in_catalog"
        source["formula"] = "not_in_catalog"
        source["calculation"]["formula"] = "not_in_catalog"
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "calculation.*not_in_catalog"):
                KPIRegistry(directory)

    def test_invalid_dimensions_driver_source_and_driver_field_fail(self):
        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["dimensions"] = ["country"]
        # Isolate the top-level dimensions check: weather_temp's
        # expected_direction_by_scope references "category", which would
        # otherwise (correctly) fail its own validation first.
        for driver in source["candidate_drivers"]:
            driver.pop("expected_direction_by_scope", None)
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "dimensions.*country"):
                KPIRegistry(directory)

        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["candidate_drivers"][0]["source"] = "missing_source"
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "candidate_drivers\\[0\\].source"):
                KPIRegistry(directory)

        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["candidate_drivers"][0]["column"] = "unknown_driver_field"
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "candidate_drivers\\[0\\].column"):
                KPIRegistry(directory)

    def test_mechanical_component_driver_is_rejected(self):
        # F-R2 (plan §1.4): a candidate driver may not be the KPI's own
        # decomposition/mechanical component (e.g. traffic), even under a
        # different driver id, or Stage 0's "traffic always wins" bug returns.
        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["candidate_drivers"][0]["column"] = "traffic_total"  # orders' own decomposition quantity_column
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "mechanical KPI component"):
                KPIRegistry(directory)

        source = yaml.safe_load((REGISTRY_DIR / "net_sales_revenue.yaml").read_text())
        source["candidate_drivers"][0]["column"] = "traffic_online"  # declared in mechanical_components
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "mechanical KPI component"):
                KPIRegistry(directory)

    def test_reconciliation_and_decomposition_are_kpi_specific_and_validated(self):
        orders = self.registry.semantic_snapshot("orders", allowed_roles=["CFO"])
        revenue = self.registry.semantic_snapshot("net_sales_revenue", allowed_roles=["CFO"])
        units = self.registry.semantic_snapshot("units_sold", allowed_roles=["CFO"])
        self.assertFalse(orders["reconciliation"]["applicable"])
        self.assertTrue(revenue["reconciliation"]["applicable"])
        self.assertEqual(revenue["reconciliation"]["comparison_source_id"], "finance_monthly")
        self.assertEqual(revenue["reconciliation"]["unit"], "INR")
        self.assertEqual(units["decomposition"]["applicable"], False)
        self.assertEqual(units["capabilities"]["decomposition"], "NOT_APPLICABLE")

        source = yaml.safe_load((REGISTRY_DIR / "net_sales_revenue.yaml").read_text())
        source["reconciliation"]["unit"] = "units"
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "reconciliation.unit"):
                KPIRegistry(directory)

        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["decomposition"]["quantity_column"] = "not_declared"
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "decomposition.*not_declared"):
                KPIRegistry(directory)

        for field, value, message in (
            ("finance_source", "missing_source", "reconciliation.finance_source"),
            ("finance_column", "missing_field", "reconciliation.finance_column"),
            ("keys", ["region"], "reconciliation.keys"),
            ("unit", "units", "reconciliation.unit"),
        ):
            source = yaml.safe_load((REGISTRY_DIR / "net_sales_revenue.yaml").read_text())
            source["reconciliation"][field] = value
            with tempfile.TemporaryDirectory() as directory:
                self.write_contract(directory, source)
                with self.assertRaisesRegex(ValueError, message):
                    KPIRegistry(directory)

    def test_duplicate_driver_and_unsupported_operator_fail(self):
        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["candidate_drivers"].append(dict(source["candidate_drivers"][0]))
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "duplicate candidate driver"):
                KPIRegistry(directory)

        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["aggregation"] = "invented_operator"
        source["calculation"]["operator"] = "invented_operator"
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "unsupported aggregation"):
                KPIRegistry(directory)

        source = yaml.safe_load((REGISTRY_DIR / "orders.yaml").read_text())
        source["candidate_drivers"][0]["aggregation"] = "weighted_mean"
        with tempfile.TemporaryDirectory() as directory:
            self.write_contract(directory, source)
            with self.assertRaisesRegex(ValueError, "candidate driver aggregation"):
                KPIRegistry(directory)

    def test_unknown_and_duplicate_yaml_keys_fail_actionably(self):
        text = (REGISTRY_DIR / "orders.yaml").read_text()
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "orders.yaml").write_text(text + "\nunknown_semantic: true\n")
            with self.assertRaisesRegex(ValueError, "unknown contract fields"):
                KPIRegistry(directory)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "orders.yaml").write_text(text + "\nversion: 99\n")
            with self.assertRaisesRegex(ValueError, "Duplicate YAML key: version"):
                KPIRegistry(directory)

    def test_contract_api_redacts_restricted_finance_metadata_and_denies_unknown(self):
        cfo = api_kpi_contract("net_sales_revenue", user_id="demo-cfo")
        marketing = api_kpi_contract("net_sales_revenue", user_id="demo-marketing")
        self.assertEqual(cfo["reconciliation"]["comparison_metric"], "net_sales_revenue")
        self.assertIsNone(marketing["reconciliation"]["comparison_metric"])
        self.assertTrue(marketing["reconciliation"]["redacted"])
        self.assertNotIn("file_path", canonical_json(marketing))
        self.assertNotIn("/mnt/storage", canonical_json(cfo))
        exposed_ratio = api_kpi_contract("conversion_rate", user_id="demo-cfo")
        self.assertEqual(exposed_ratio["calculation"]["operator"], "RATIO_OF_SUMS")
        self.assertEqual(exposed_ratio["calculation"]["numerator_column"], "orders")
        with self.assertRaises(HTTPException) as unknown:
            api_kpi_contract("orders", user_id="nobody")
        self.assertEqual(unknown.exception.status_code, 401)
        with self.assertRaises(HTTPException) as scope_denied:
            api_kpi_contract("orders", user_id="demo-regional-north")
        self.assertEqual(scope_denied.exception.status_code, 403)
        self.assertEqual(len(api_kpis(user_id="demo-cfo")["items"]), 5)

    def test_saved_contract_snapshot_survives_current_registry_change(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory) / "runs.sqlite3"):
            old = self.registry.semantic_snapshot("orders", allowed_roles=["CFO", "marketing_manager"])
            old["identity"]["version"] = 0
            old["identity"]["definition"] = "Historical definition at run time"
            old["governance"]["contract_hash"] = "historical-hash"
            save_diagnosis_run({
                "run_id": "run-contract-snapshot-test",
                "kpi_id": "orders",
                "target_date": "2023-07-24",
                "as_of": "2023-07-25T12:00:00+00:00",
                "persona": "CFO",
                "verdict": "NO_MATERIAL_MOVEMENT",
                "contract_version": 0,
                "contract_hash": "historical-hash",
                "contract_snapshot": old,
            }, scope={"region": "North", "category": "Electronics"}, access_context={"authorized": True})
            fetched = get_run_kpi_contract("run-contract-snapshot-test", "demo-cfo")
            self.assertEqual(fetched["contract_snapshot"]["identity"]["definition"], "Historical definition at run time")
            self.assertEqual(fetched["contract_snapshot"]["governance"]["contract_hash"], "historical-hash")
            self.assertTrue(fetched["comparison"]["changed_since_run"])

    def test_run_contract_authorizes_before_loading_saved_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory) / "runs.sqlite3"):
            save_diagnosis_run({
                "run_id": "run-contract-auth-order",
                "kpi_id": "orders",
                "target_date": "2023-07-24",
                "as_of": "2023-07-25T12:00:00+00:00",
                "persona": "regional_manager_north",
                "verdict": "NO_MATERIAL_MOVEMENT",
                "contract_snapshot": self.registry.semantic_snapshot(
                    "orders", allowed_roles=["regional_manager_north"]
                ),
            }, scope={"region": "North", "category": "Electronics"}, access_context={"authorized": True})
            with patch.object(backend_service, "get_run", side_effect=AssertionError("snapshot loaded before authorization")) as load_saved:
                with self.assertRaises(PermissionError):
                    get_run_kpi_contract("run-contract-auth-order", "demo-marketing")
                load_saved.assert_not_called()
            with self.assertRaises(HTTPException) as denied:
                api_diagnosis_contract("run-contract-auth-order", user_id="demo-marketing")
            self.assertEqual(denied.exception.status_code, 404)

    def test_run_disappearing_after_authorization_fails_closed_without_full_result_read(self):
        from backend.app import api_diagnosis_contract

        metadata = {
            "run_id": "vanishing-run",
            "kpi_id": "orders",
            "persona": "CFO",
            "scope": {"region": "North", "category": "Electronics"},
        }
        with patch.object(backend_service, "get_run_access_metadata", return_value=metadata), \
             patch.object(backend_service, "get_run_contract_metadata", return_value=None), \
             patch.object(backend_service, "get_run", side_effect=AssertionError("full result was loaded")) as full_result:
            with self.assertRaises(HTTPException) as disappeared:
                api_diagnosis_contract("vanishing-run", user_id="demo-cfo")
            self.assertEqual(disappeared.exception.status_code, 404)
            full_result.assert_not_called()

    def test_existing_run_without_contract_snapshot_is_not_reconstructed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory) / "runs.sqlite3"):
            save_diagnosis_run({
                "run_id": "run-no-contract-snapshot",
                "kpi_id": "orders",
                "target_date": "2023-07-24",
                "as_of": "2023-07-25T12:00:00+00:00",
                "persona": "CFO",
                "verdict": "NO_MATERIAL_MOVEMENT",
            }, scope={"region": "North", "category": "Electronics"}, access_context={"authorized": True})
            fetched = get_run_kpi_contract("run-no-contract-snapshot", "demo-cfo")
            self.assertIsNone(fetched["contract_snapshot"])
            self.assertEqual(fetched["comparison"]["snapshot_status"], "MISSING")
            self.assertIsNone(fetched["comparison"]["changed_since_run"])

    def test_storage_fallback_hash_is_not_presented_as_canonical_snapshot_hash(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory) / "runs.sqlite3"):
            save_diagnosis_run({
                "run_id": "run-partial-contract-metadata",
                "kpi_id": "orders",
                "target_date": "2023-07-24",
                "as_of": "2023-07-25T12:00:00+00:00",
                "persona": "CFO",
                "contract": {"kpi_id": "orders", "version": 1, "source": "sales_daily"},
            }, scope={"region": "North", "category": "Electronics"}, access_context={"authorized": True})
            metadata = storage.get_run_contract_metadata("run-partial-contract-metadata")
            fetched = get_run_kpi_contract("run-partial-contract-metadata", "demo-cfo")
            current_hash = self.registry.semantic_snapshot("orders", allowed_roles=["CFO"])["governance"]["contract_hash"]
            self.assertIsNotNone(metadata["contract_hash"])
            self.assertNotEqual(metadata["contract_hash"], current_hash)
            self.assertIsNone(metadata["contract_snapshot"])
            self.assertEqual(fetched["comparison"]["snapshot_status"], "MISSING")
            self.assertIsNone(fetched["comparison"]["changed_since_run"])


if __name__ == "__main__":
    unittest.main()
