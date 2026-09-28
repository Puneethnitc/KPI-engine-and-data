import tempfile
import unittest
from pathlib import Path

from kpi_engine.kpi_graph import build_kpi_story, load_kpi_graph
from backend.service import diagnose_scope


def result(actual, expected, material=True, drivers=None):
    return {"movement_assessment": {"actual_value": actual, "expected_value": expected,
                                    "is_material": material},
            "driver_analysis": {"ranked_drivers": drivers or []}}


class KpiGraphTests(unittest.TestCase):
    def setUp(self):
        self.results = {
            "traffic_total": result(80, 100, drivers=[{"driver_id": "marketing_spend", "explained_share": .7, "attribution_confidence": .8, "band": "HIGH"}]),
            "conversion_rate": result(.1, .1, False),
            "orders": result(8, 10),
            "units_sold": result(16, 20),
            "net_sales_revenue": result(160, 200),
        }

    def test_edges_balance_and_consequences(self):
        story = build_kpi_story(self.results)
        self.assertEqual(story["root_stage"], "traffic")
        self.assertEqual(sum(round(edge["contribution_inr"] * 100) for edge in story["edges"]), -4000)
        self.assertEqual(sum(round(edge["contribution_pct"] * 100) for edge in story["edges"]), 10000)
        nodes = {node["kpi_id"]: node for node in story["nodes"]}
        self.assertEqual(nodes["orders"]["consequence_of"], "traffic")
        self.assertEqual(nodes["net_sales_revenue"]["consequence_of"], "traffic")
        self.assertIsNone(nodes["traffic_total"]["consequence_of"])

    def test_shared_driver_is_one_chain(self):
        self.results["conversion_rate"] = result(.08, .1, True, [{"driver_id": "marketing_spend", "explained_share": .5, "attribution_confidence": .6, "band": "MODERATE"}])
        self.results["orders"] = result(6.4, 10)
        self.results["units_sold"] = result(12.8, 20)
        self.results["net_sales_revenue"] = result(128, 200)
        story = build_kpi_story(self.results)
        self.assertEqual(len(story["cause_chains"]), 1)
        self.assertTrue(story["cause_chains"][0]["shared_cause"])
        self.assertEqual(story["cause_chains"][0]["stages"], ["traffic", "conversion"])

    def test_missing_kpi_still_builds(self):
        del self.results["units_sold"]
        story = build_kpi_story(self.results)
        self.assertIn("units", story["missing_stages"])
        self.assertEqual(round(sum(edge["contribution_inr"] for edge in story["edges"]), 2), -40)

    def test_zero_funnel_does_not_crash(self):
        for kpi_id in self.results:
            self.results[kpi_id]["movement_assessment"]["actual_value"] = 0
        story = build_kpi_story(self.results)
        self.assertEqual(sum(round(edge["contribution_inr"] * 100) for edge in story["edges"]), -20000)

    def test_quiet_funnel_has_no_root(self):
        for item in self.results.values():
            movement = item["movement_assessment"]
            movement["actual_value"] = movement["expected_value"]
            movement["is_material"] = False
        story = build_kpi_story(self.results)
        self.assertIsNone(story["root_stage"])
        self.assertTrue(all(node["consequence_of"] is None for node in story["nodes"]))

    def test_config_loading_and_validation(self):
        graph = load_kpi_graph()
        self.assertEqual(graph["relationships"]["orders"], ["traffic_total", "conversion_rate"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.yaml"
            path.write_text("version: 2\nrelationships: {}\nstages: []\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_kpi_graph(path)

    def test_real_data_connected_stories(self):
        cases = [
            ("North", "Electronics", "2023-07-31", "traffic", "marketing_spend"),
            ("South", "Apparel", "2024-02-13", "conversion", "stock_availability"),
            ("ALL", "ALL", "2024-05-15", "conversion", "checkout_latency"),
        ]
        for region, category, date, root, top_driver in cases:
            with self.subTest(date=date, region=region, category=category):
                results = diagnose_scope(region=region, category=category, target_date=date, persona="CFO")["results"]
                story = build_kpi_story(results)
                self.assertEqual(story["root_stage"], root)
                self.assertEqual(round(sum(edge["contribution_inr"] for edge in story["edges"]), 2), story["revenue_delta"])
                self.assertEqual(story["cause_chains"][0]["driver_id"], top_driver)

    def test_all_all_traffic_is_not_a_consequence(self):
        # Traffic is upstream of the root (conversion) and not material, so it must
        # never be labelled a consequence; only material downstream KPIs may be.
        results = diagnose_scope(region="ALL", category="ALL", target_date="2024-05-15", persona="CFO")["results"]
        story = build_kpi_story(results)
        nodes = {node["kpi_id"]: node for node in story["nodes"]}
        self.assertFalse(nodes["traffic_total"]["material"])
        self.assertIsNone(nodes["traffic_total"]["consequence_of"])
        self.assertIsNone(nodes["conversion_rate"]["consequence_of"])
        for node in story["nodes"]:
            if node["consequence_of"]:
                self.assertTrue(node["material"])
                self.assertIn(node["kpi_id"], {"orders", "units_sold", "net_sales_revenue"})

    def test_parallel_and_non_material_nodes_are_never_consequences(self):
        # Conversion is the root; traffic is a parallel input and units is not material.
        self.results = {
            "traffic_total": result(100, 100, False),
            "conversion_rate": result(.08, .1),
            "orders": result(8, 10),
            "units_sold": result(16, 20, False),
            "net_sales_revenue": result(160, 200),
        }
        story = build_kpi_story(self.results)
        self.assertEqual(story["root_stage"], "conversion")
        nodes = {node["kpi_id"]: node for node in story["nodes"]}
        self.assertIsNone(nodes["traffic_total"]["consequence_of"])
        self.assertIsNone(nodes["conversion_rate"]["consequence_of"])
        self.assertIsNone(nodes["units_sold"]["consequence_of"])
        self.assertEqual(nodes["orders"]["consequence_of"], "conversion")

    def test_untested_driver_is_not_tested_not_untestable(self):
        story = build_kpi_story(self.results)
        self.assertEqual(story["cause_chains"][0]["causal_verdict"], "NOT_TESTED")

    def test_borrowed_driver_uses_highest_ac_downstream_result(self):
        results = diagnose_scope(region="North", category="Electronics", target_date="2023-07-31", persona="CFO")["results"]
        story = build_kpi_story(results)
        chain = next(item for item in story["cause_chains"] if item["driver_id"] == "marketing_spend")
        revenue_ac = next(d["attribution_confidence"] for d in results["net_sales_revenue"]["driver_analysis"]["ranked_drivers"] if d["driver_id"] == "marketing_spend")
        self.assertAlmostEqual(revenue_ac, 0.75, places=2)
        self.assertAlmostEqual(chain["attribution_confidence"], revenue_ac)


if __name__ == "__main__":
    unittest.main()
