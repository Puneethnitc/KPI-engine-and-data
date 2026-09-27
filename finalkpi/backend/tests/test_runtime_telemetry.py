from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from backend.llm_config import get_model_economics
from backend.runtime_telemetry import RuntimeTelemetry, estimate_cost_usd
from backend.service import _build_timeseries_points, get_timeseries


class Clock:
    def __init__(self): self.value = 0
    def __call__(self):
        self.value += 1_000_000
        return self.value


class RuntimeTelemetryTests(unittest.TestCase):
    def test_deterministic_stage_and_cache_summary(self):
        telemetry = RuntimeTelemetry(limits={"timeout_ms": 5000}, clock=Clock())
        with telemetry.stage(stage="reconciliation", processing_type="DETERMINISTIC",
                             method="grain_alignment", cache_status="MISS"):
            pass
        result = telemetry.finalize()
        self.assertTrue(result["execution_id"].startswith("exec-"))
        self.assertGreaterEqual(result["total_latency_ms"], 0)
        self.assertEqual(0, result["llm_summary"]["model_calls"])
        self.assertEqual(0, result["llm_summary"]["estimated_cost_usd"])
        self.assertEqual(1, result["cache_summary"]["misses"])
        self.assertEqual(0, result["stages"][0]["model_calls"])

    def test_unavailable_llm_usage_stays_null_and_metadata_is_allowlisted(self):
        telemetry = RuntimeTelemetry(clock=Clock())
        telemetry.add_stage(
            stage="narrative", processing_type="LLM", method="approved_wording_selection",
            latency_ms=4, provider="provider", model="model", model_calls=1,
            input_tokens=999, output_tokens=999, estimated_cost_usd=9,
            usage_source="UNAVAILABLE", details={"reason_code": "NO_USAGE", "prompt": "secret", "path": "/tmp/x"},
        )
        result = telemetry.finalize()
        summary = result["llm_summary"]
        self.assertIsNone(summary["input_tokens"])
        self.assertIsNone(summary["output_tokens"])
        self.assertIsNone(summary["estimated_cost_usd"])
        self.assertEqual({"reason_code": "NO_USAGE"}, result["stages"][0]["details"])
        self.assertNotIn("secret", json.dumps(result))

    def test_cost_requires_usage_and_both_rates(self):
        self.assertEqual(0.0025, estimate_cost_usd(1000, 500, 2.0, 1.0))
        self.assertIsNone(estimate_cost_usd(None, 500, 2.0, 1.0))
        self.assertIsNone(estimate_cost_usd(1000, 500, None, 1.0))

    def test_configuration_never_exposes_credentials(self):
        env = {
            "GROQ_API_KEY": "do-not-expose", "GROQ_MODEL": "test-model",
            "LLM_INPUT_USD_PER_MILLION_TOKENS": "2.0",
            "LLM_OUTPUT_USD_PER_MILLION_TOKENS": "3.0",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_model_economics()
        encoded = json.dumps(config)
        self.assertNotIn("do-not-expose", encoded)
        self.assertEqual("test-model", config["model"])
        self.assertEqual(2.0, config["input_usd_per_million_tokens"])

    def test_error_stage_is_recorded_and_execution_can_finalize(self):
        telemetry = RuntimeTelemetry(clock=Clock())
        with self.assertRaises(RuntimeError):
            with telemetry.stage(stage="source", processing_type="DETERMINISTIC", method="load"):
                raise RuntimeError("failure")
        result = telemetry.finalize()
        self.assertEqual("ERROR", result["stages"][0]["status"])
        self.assertNotIn("failure", json.dumps(result))

    def test_timeseries_reports_real_cache_miss_then_hit(self):
        _build_timeseries_points.cache_clear()
        first = get_timeseries("traffic_total", "North", "Electronics", user_id="demo-cfo")
        second = get_timeseries("traffic_total", "North", "Electronics", user_id="demo-cfo")
        self.assertEqual(1, first["telemetry"]["cache_summary"]["misses"])
        self.assertEqual(1, second["telemetry"]["cache_summary"]["hits"])
        self.assertGreaterEqual(first["telemetry"]["total_latency_ms"], 0)


if __name__ == "__main__":
    unittest.main()
