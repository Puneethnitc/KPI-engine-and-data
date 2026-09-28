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
            "do_first": {"text": do_first or "No action needed; keep monitoring", "facts": []}}
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
        texts = {f["text"].split(" ")[0]: f["text"] for f in sheet["facts"] if f["kind"] == "kpi"}
        self.assertIn("downstream result of conversion", texts["Orders"])
        self.assertNotIn("result of", texts["Traffic"])
        self.assertNotIn("result of", texts["Units"])


def material_story(material=True):
    story = {**STORY, "nodes": [{"kpi_id": "net_sales_revenue", "percent_change": 14.4, "material": material, "consequence_of": None}],
             "edges": [*STORY["edges"], {"stage": "basket", "from": "net_sales_revenue", "to": "net_sales_revenue", "contribution_inr": 112.0, "contribution_pct": 29.7, "factor_percent_change": 3.0}]}
    return story


def action_results(ac=0.72):
    data = results("NOT_TESTED", ac)
    data["net_sales_revenue"]["decision_cards"] = [{"recommendation": "Restore stock availability at the North warehouse.", "owner": "operations_lead", "approval_required": True}]
    return data


class SummaryStructureTests(unittest.TestCase):
    def setUp(self):
        llm_narrator._CACHE.clear()

    def test_do_first_never_restates_the_revenue_change(self):
        sheet = build_fact_sheet(material_story(), action_results(), "cfo")
        self.assertTrue(sheet["action_allowed"])
        rev = ids(sheet, "revenue")[0]
        bad = {"sentences": [{"text": t, "facts": [rev]} for t in GOOD[:2]], "do_first": {"text": "Revenue rose ₹377 (14.4%) versus expected.", "facts": [rev]}}
        self.assertFalse(guard(bad, sheet)[0])
        summary = executive_summary(material_story(), action_results(), "cfo")
        self.assertNotEqual(summary["do_first"]["text"], summary["sentences"][0]["text"])
        self.assertIn("Restore stock availability", summary["do_first"]["text"])

    def test_action_fact_is_accepted_as_do_first_when_material_and_qualified(self):
        sheet = build_fact_sheet(material_story(), action_results(), "cfo")
        action = ids(sheet, "action")[0]
        body = {"sentences": [{"text": t, "facts": [ids(sheet, "revenue")[0]]} for t in GOOD[:1]] + [{"text": "Stock availability is linked to the movement.", "facts": [ids(sheet, "driver")[0]]}],
                "do_first": {"text": "Restore stock availability at the North warehouse.", "facts": [action]}}
        ok, errors = guard(body, sheet)
        self.assertTrue(ok, errors)

    def test_non_material_movement_yields_no_action_needed(self):
        sheet = build_fact_sheet(material_story(False), action_results(), "cfo")
        self.assertFalse(sheet["action_allowed"])
        summary = executive_summary(material_story(False), action_results(), "cfo")
        self.assertEqual(summary["do_first"]["text"], "No action needed; keep monitoring")
        action = ids(sheet, "action")[0]
        bad = {"sentences": [{"text": t, "facts": [ids(sheet, "revenue")[0]]} for t in GOOD[:2]],
               "do_first": {"text": "Restore stock availability at the North warehouse.", "facts": [action]}}
        self.assertFalse(guard(bad, sheet)[0])

    def test_no_qualified_driver_also_means_no_action(self):
        sheet = build_fact_sheet(material_story(), action_results(0.2), "cfo")
        self.assertFalse(sheet["action_allowed"])
        self.assertIn("No driver reached", next(f["text"] for f in sheet["facts"] if f["kind"] == "gate"))

    def test_caveat_appears_at_most_once(self):
        sheet = build_fact_sheet(material_story(), action_results(), "cfo")
        rev, caveat = ids(sheet, "revenue")[0], ids(sheet, "caveat")[0]
        twice = {"sentences": [{"text": "Revenue rose ₹377 (14.4%) versus expected.", "facts": [rev]},
                               {"text": "This is an accounting split, not a cause.", "facts": [caveat]},
                               {"text": "Again, an accounting split, not a cause.", "facts": [caveat]}],
                 "do_first": {"text": "No action needed; keep monitoring", "facts": []}}
        ok, errors = guard(twice, sheet)
        self.assertFalse(ok)
        self.assertTrue(any("at most once" in e for e in errors))
        summary = executive_summary(material_story(), action_results(), "cfo")
        joined = " ".join(item["text"] for item in [*summary["sentences"], summary["do_first"]])
        self.assertLessEqual(joined.lower().count("accounting split"), 1)
        self.assertTrue(2 <= len(summary["sentences"]) <= 4)

    def test_drove_is_rejected_for_unverified_driver_but_allowed_when_verified(self):
        sheet = build_fact_sheet(material_story(), action_results(), "cfo")
        driver, rev = ids(sheet, "driver")[0], ids(sheet, "revenue")[0]
        body = {"sentences": [{"text": "Revenue rose ₹377 (14.4%) versus expected.", "facts": [rev]}, {"text": "Stock availability drove the rise.", "facts": [driver]}],
                "do_first": {"text": "No action needed; keep monitoring", "facts": []}}
        self.assertFalse(guard(body, sheet)[0])
        verified = build_fact_sheet(material_story(), {**action_results(), "net_sales_revenue": {**action_results()["net_sales_revenue"], "causal_verification": {"driver_id": "stock_availability", "verdict": "SUPPORTED_CONDITIONAL"}}}, "cfo")
        body["sentences"][1]["facts"] = [ids(verified, "driver")[0]]
        ok, errors = guard(body, verified)
        self.assertTrue(ok, errors)

    def test_facts_use_rose_or_fell(self):
        sheet = build_fact_sheet(material_story(), action_results(), "cfo")
        texts = " ".join(f["text"] for f in sheet["facts"])
        self.assertNotIn("changed +", texts)
        self.assertIn("Revenue rose", texts)


class ConfidenceAndOffsetTests(unittest.TestCase):
    def test_attribution_confidence_is_capped_never_100(self):
        for ac, expected in ((0.998, "99.8%"), (1.0, "99.9%"), (0.72, "72%")):
            sheet = build_fact_sheet(STORY, results(ac=ac), "cfo")
            text = " ".join(f["text"] for f in sheet["facts"] if f["kind"] in ("driver", "gate"))
            self.assertIn(f"{expected} attribution confidence", text)
            self.assertNotIn("100%", text)

    def test_share_over_100_names_the_offsetting_stage(self):
        story = {**STORY, "revenue_delta": -100.0, "headline_facts": [{"kind": "revenue", "delta": -100.0, "percent_change": -20.0}],
                 "edges": [{"stage": "conversion", "from": "conversion_rate", "to": "net_sales_revenue", "contribution_inr": -103.0, "contribution_pct": 103.0, "factor_percent_change": -9.0},
                           {"stage": "basket", "from": "net_sales_revenue", "to": "net_sales_revenue", "contribution_inr": 3.0, "contribution_pct": -3.0, "factor_percent_change": 1.0}]}
        sheet = build_fact_sheet(story, results(), "cfo")
        text = next(f["text"] for f in sheet["facts"] if f["kind"] == "bridge" and f["text"].startswith("Conversion"))
        self.assertIn("more than the whole fall (103%), partly offset by price per unit", text)
        summary = executive_summary(story, results(), "cfo")
        self.assertIn("More than the whole fall came from conversion (103%), partly offset by price per unit", summary["sentences"][1]["text"])

    def test_fallback_caveat_is_its_own_sentence(self):
        summary = executive_summary(material_story(), action_results(), "cfo")
        caveat = [s for s in summary["sentences"] if "accounting split" in s["text"]]
        self.assertEqual(len(caveat), 1)
        self.assertEqual(caveat[0]["text"], "This is an accounting split, not a cause.")


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
        self.assertFalse(guard(output(self.sheet, GOOD[:1]), self.sheet)[0])
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
