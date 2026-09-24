"""Narrative claims must be exact projections of the evidence payload."""

import unittest
from dataclasses import replace
from io import BytesIO
from unittest.mock import patch
import json

from kpi_engine.narrative import NarrativeEngine


class NarrativeTests(unittest.TestCase):
    def setUp(self):
        self.engine = NarrativeEngine()
        self.payload = {
            "kpi_id": "orders", "target_date": "2023-07-24",
            "verdict": "MATERIAL_CAUSE_UNVERIFIED",
            "reconciliation_verdict": {"status": "NOT_RECONCILED"},
            "movement_assessment": {
                "status": "OK", "delta": -12.5, "is_material": True,
                "is_statistically_significant": True,
                "is_business_material": True,
            },
            "decomposition_status": "IDENTITY_HELD",
            "decomposition": {"total_delta": -12.5, "is_identity_held": True},
            "correlational_candidates": [
                {"driver_id": "traffic_drop", "claim_type": "CORRELATIONAL"}
            ],
            "causal_verdict": "INCONCLUSIVE",
            "causal_verification": {"verdict": "INCONCLUSIVE"},
        }

    def test_claims_are_bound_and_noncausal(self):
        rendered = self.engine.render(self.payload)
        self.assertTrue(rendered["grounding_passed"])
        self.assertIn("traffic_drop is a correlational candidate", rendered["text"])
        self.assertIn("This does not prove causation", rendered["text"])
        self.assertNotIn("caused by", rendered["text"])
        self.assertEqual(rendered["method"], "deterministic_evidence_template")

    def test_tampered_number_entity_and_causal_claim_are_rejected(self):
        original = self.engine._claims(self.payload)
        for index, replacement in (
            (1, "orders changed by -999 in its declared unit on 2023-07-24."),
            (4, "stockout is a correlational candidate, not an established cause."),
            (5, "Observational verification: INCONCLUSIVE. Caused by traffic_drop."),
        ):
            with self.subTest(index=index):
                claims = list(original)
                claims[index] = replace(claims[index], text=replacement)
                passed, errors = self.engine.validate(self.payload, tuple(claims))
                self.assertFalse(passed)
                self.assertTrue(errors)

    def test_inconsistent_evidence_is_not_rendered(self):
        self.payload["movement_assessment"]["is_business_material"] = False
        rendered = self.engine.render(self.payload)
        self.assertFalse(rendered["grounding_passed"])
        self.assertEqual(rendered["text"], "")

    def test_access_denied_leaks_no_slice(self):
        payload = {"verdict": "ACCESS_DENIED", "kpi_id": "orders",
                   "treated_slice": {"region": "Secret"}}
        rendered = self.engine.render(payload)
        self.assertTrue(rendered["grounding_passed"])
        self.assertNotIn("Secret", rendered["text"])

    def test_llm_may_select_only_approved_wording(self):
        engine = NarrativeEngine(llm_client=lambda options: {
            "variants": [len(group) - 1 for group in options]
        })
        rendered = engine.render(self.payload)
        self.assertEqual(rendered["llm_status"], "USED")
        self.assertEqual(rendered["method"], "llm_selected_approved_templates")
        self.assertTrue(rendered["grounding_passed"])
        self.assertIn("causation remains unproven", rendered["text"])

    def test_malicious_or_broken_llm_falls_back(self):
        for client in (
            lambda options: {"variants": [0] * len(options),
                             "text": "traffic_drop caused a 9000 INR loss"},
            lambda options: {"variants": [999] * len(options)},
            lambda options: {"variants": [True] * len(options)},
        ):
            with self.subTest(client=client):
                rendered = NarrativeEngine(llm_client=client).render(self.payload)
                self.assertEqual(rendered["llm_status"], "REJECTED")
                self.assertTrue(rendered["grounding_passed"])
                self.assertNotIn("caused a 9000", rendered["text"])
        def broken(_):
            raise TimeoutError("provider unavailable")
        rendered = NarrativeEngine(llm_client=broken).render(self.payload)
        self.assertEqual(rendered["llm_status"], "ERROR_FALLBACK")
        self.assertTrue(rendered["grounding_passed"])

    def test_provider_response_is_parsed_then_bound_to_approved_variants(self):
        class Response(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        options = self.engine._claims(self.payload)
        response = {"choices": [{"message": {"content": json.dumps({
            "variants": [0] * len(options),
        })}}]}
        with patch("kpi_engine.narrative.urlopen", return_value=Response(
            json.dumps(response).encode("utf-8")
        )) as provider:
            rendered = NarrativeEngine(api_key="test-only-key").render(self.payload)
        self.assertTrue(provider.called)
        self.assertEqual(rendered["llm_status"], "USED")
        self.assertTrue(rendered["grounding_passed"])


if __name__ == "__main__":
    unittest.main()
