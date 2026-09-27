import os
import unittest
from unittest.mock import patch

from backend.llm_config import get_llm_settings


class LLMConfigTests(unittest.TestCase):
    def test_no_key_keeps_deterministic_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_llm_settings())

    def test_groq_configures_full_openai_compatible_client(self):
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "gsk-test",
            "GROQ_MODEL": "provider/model",
        }, clear=True):
            settings = get_llm_settings()
        self.assertEqual(settings.provider, "groq")
        self.assertEqual(settings.api_key, "gsk-test")
        self.assertEqual(settings.model, "provider/model")
        self.assertEqual(settings.base_url, "https://api.groq.com/openai/v1")

    def test_non_groq_keys_are_ignored(self):
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "or-test",
            "OPENAI_API_KEY": "oa-test",
        }, clear=True):
            settings = get_llm_settings()
        self.assertIsNone(settings)


if __name__ == "__main__":
    unittest.main()
