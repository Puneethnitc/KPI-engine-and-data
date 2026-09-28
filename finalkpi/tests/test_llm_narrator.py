import json
import unittest
from unittest import mock

from kpi_engine import llm_narrator
from kpi_engine.llm_narrator import build_fact_sheet, executive_summary, guard

STORY = {
    "nodes": [
        {"kpi_id": "traffic_total", "percent_change": 8.6, "material": True},
        {"kpi_id": "net_sales_revenue", "percent_change": 14.4, "material": True},
    ],
    "edges": [{"stage": "traffic", "from": "traffic_total", "to": "net_sales_revenue", "contribution_inr": 232.0, "contribution_pct": 61.4, "factor_percent_change": 8.6}],
    "root_stage": "traffic", "missing_stages": [], "revenue_delta": 377.0,
    "headline_facts": [{"kind": "revenue", "delta": 377.0, "percent_change": 14.4}, {"kind": "root_stage", "stage": "traffic"}],
    "cause_chains": [],
}


def results(verdict="NOT_TESTED", ac=0.72):
    return {"net_sales_revenue": {
        "target_date": "2024-03-31", "segment": {"region": "North", "category": "Electronics"},
        "driver_analysis": {"ranked_drivers": [{"driver_id": "stock_availability", "display_name": "Stock availability", "attribution_confidence": ac, "band": "HIGH"}]},
        "causal_verification": {"driver_id": "stock_availability", "verdict": verdict},
        "reconciliation_verdict": {"status": "AGREED", "gap_pct": 0.4},
        "decision_cards": [],
    }}


def ids(sheet, kind):
    return [f["id"] for f in sheet["facts"] if f["kind"] == kind]


def output(sheet, texts, do_first=None):
    rev, bridge, driver = ids(sheet, "revenue")[0], ids(sheet, "bridge")[0], ids(sheet, "driver")[0]
    body = {"sentences": [{"text": t, "facts": [rev, bridge, driver]} for t in texts],
            "do_first": {"text": do_first or "Check stock availability first.", "facts": [driver]}}
    return body


GOOD = ["Revenue rose ₹377 (+14.4%) versus expected.", "Traffic accounts for ₹232 (61%) of that change.", "Stock availability is linked to the movement at 72% attribution confidence."]


class ConsequenceFactTests(unittest.TestCase):
    def test_result_of_appears_only_for_material_downstream_nodes(self):
        story = {**STORY, "nodes": [
            {"kpi_id": "traffic_total", "percent_change": 1.0, "material": False, "consequence_of": None},
            {"kpi_id": "orders", "percent_change": -9.0, "material": True, "consequence_of": "conversion"},
            {"kpi_id": "units_sold", "percent_change": -1.0, "material": False, "consequence_of": None},
        ]}
        sheet = build_fact_sheet(story, results(), "cfo")
        texts = {f["text"].split(" changed")[0]: f["text"] for f in sheet["facts"] if f["kind"] == "kpi"}
        self.assertIn("downstream result of conversion", texts["Orders"])
        self.assertNotIn("result of", texts["Traffic"])
        self.assertNotIn("result of", texts["Units"])


class Client:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload, error, 0

    def __call__(self, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return {"content": json.dumps(self.payload), "input_tokens": 100, "output_tokens": 50}


class GuardTests(unittest.TestCase):
    def setUp(self):
        llm_narrator._CACHE.clear()
        self.sheet = build_fact_sheet(STORY, results(), "cfo")

    def test_valid_output_passes(self):
        ok, errors = guard(output(self.sheet, GOOD), self.sheet)
        self.assertTrue(ok, errors)

    def test_invented_number_is_rejected(self):
        bad = [GOOD[0].replace("377", "450"), *GOOD[1:]]
        ok, errors = guard(output(self.sheet, bad), self.sheet)
        self.assertFalse(ok)
        self.assertTrue(any("450" in e for e in errors))

    def test_causal_wording_on_unverified_driver_is_rejected(self):
        bad = [*GOOD[:2], "Revenue rose because of Stock availability."]
        ok, errors = guard(output(self.sheet, bad), self.sheet)
        self.assertFalse(ok)
        self.assertTrue(any("causal wording" in e for e in errors))

    def test_causal_wording_allowed_when_verified_and_confident(self):
        sheet = build_fact_sheet(STORY, results("SUPPORTED_CONDITIONAL", 0.72), "cfo")
        ok, errors = guard(output(sheet, [*GOOD[:2], "Revenue rose due to Stock availability."]), sheet)
        self.assertTrue(ok, errors)
        low = build_fact_sheet(STORY, results("SUPPORTED_CONDITIONAL", 0.5), "cfo")
        self.assertFalse(guard(output(low, [*GOOD[:2], "Revenue rose due to Stock availability."]), low)[0])

    def test_unknown_fact_id_is_rejected(self):
        body = output(self.sheet, GOOD)
        body["sentences"][0]["facts"] = ["F99"]
        ok, errors = guard(body, self.sheet)
        self.assertFalse(ok)
        self.assertTrue(any("unknown fact id" in e for e in errors))

    def test_driver_outside_fact_sheet_and_length_are_rejected(self):
        self.assertFalse(guard(output(self.sheet, [*GOOD[:2], "Checkout latency is linked to the drop."]), self.sheet)[0])
        self.assertFalse(guard(output(self.sheet, GOOD[:2]), self.sheet)[0])
        self.assertFalse(guard(output(self.sheet, [GOOD[0] + " x" * 200, *GOOD[1:]]), self.sheet)[0])


class ExecutiveSummaryTests(unittest.TestCase):
    def setUp(self):
        llm_narrator._CACHE.clear()
        self.sheet = build_fact_sheet(STORY, results(), "cfo")

    def run_summary(self, client):
        with mock.patch("kpi_engine.llm_narrator.urlopen", side_effect=AssertionError("network call")):
            return executive_summary(STORY, results(), "cfo", client=client)

    def test_valid_llm_output_is_used_and_cached(self):
        client = Client(output(self.sheet, GOOD))
        first = self.run_summary(client)
        second = self.run_summary(client)
        self.assertEqual(first["status"], "LLM")
        self.assertEqual(client.calls, 1)
        self.assertEqual(second["runtime"]["cache_status"], "HIT")
        self.assertEqual(first["runtime"]["input_tokens"], 100)

    def test_rejected_output_falls_back_to_template(self):
        summary = self.run_summary(Client(output(self.sheet, [GOOD[0].replace("377", "999"), *GOOD[1:]])))
        self.assertEqual(summary["status"], "TEMPLATE")
        self.assertIn("rejected", summary["reason"])
        self.assertIn("₹377", summary["sentences"][0]["text"])

    def test_error_falls_back_and_is_not_cached(self):
        client = Client(error=TimeoutError())
        self.assertEqual(self.run_summary(client)["status"], "TEMPLATE")
        self.run_summary(client)
        self.assertEqual(client.calls, 2)

    def test_no_client_uses_template_without_network(self):
        summary = self.run_summary(None)
        self.assertEqual(summary["status"], "TEMPLATE")
        self.assertFalse(summary["runtime"]["attempted"])

    def test_no_story_returns_none(self):
        self.assertIsNone(executive_summary(None, {}, "cfo"))


if __name__ == "__main__":
    unittest.main()
