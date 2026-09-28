"""The health route reports the live Chroma collection state."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend import app as app_module


class HealthTests(unittest.TestCase):
    def test_health_reports_collection_count_and_readiness(self):
        collection = SimpleNamespace(count=lambda: 17)
        with patch.object(app_module, "context_builder", SimpleNamespace(collection=collection)):
            result = app_module.health()
        self.assertTrue(result["retrieval_ready"])
        self.assertEqual(result["document_count"], 17)
        self.assertEqual(result["collection"], "kpi_knowledge_base")

    def test_health_reports_unavailable_retrieval(self):
        with patch.object(app_module, "context_builder", SimpleNamespace(collection=None)):
            result = app_module.health()
        self.assertFalse(result["retrieval_ready"])
        self.assertEqual(result["document_count"], 0)


if __name__ == "__main__":
    unittest.main()
