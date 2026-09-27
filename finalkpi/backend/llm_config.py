from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional RAG dependency
    OpenAI = None


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    api_key: str
    base_url: str | None
    model: str
    default_headers: dict[str, str]


def get_runtime_limits() -> dict[str, Any]:
    return {
        "timeout_ms": int(os.getenv("LLM_TIMEOUT_MS", "5000")),
        "max_model_calls": int(os.getenv("LLM_MAX_MODEL_CALLS", "2")),
        "max_input_tokens": int(os.getenv("LLM_MAX_INPUT_TOKENS", "8192")),
        "fallback_behavior": "deterministic_evidence_bound_fallback",
        "pricing_version": os.getenv("LLM_PRICING_VERSION", "unconfigured"),
    }


def get_model_economics() -> dict[str, Any]:
    settings = get_llm_settings()
    def rate(name: str) -> float | None:
        value = os.getenv(name, "").strip()
        return float(value) if value else None
    return {
        "provider": settings.provider if settings else None,
        "model": settings.model if settings else None,
        **get_runtime_limits(),
        "input_usd_per_million_tokens": rate("LLM_INPUT_USD_PER_MILLION_TOKENS"),
        "output_usd_per_million_tokens": rate("LLM_OUTPUT_USD_PER_MILLION_TOKENS"),
    }


def get_llm_settings() -> LLMSettings | None:
    """Resolve the server-side Groq configuration."""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        return LLMSettings(
            provider="groq",
            api_key=groq_key,
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            default_headers={},
        )

    return None


def create_llm_client() -> tuple[Any | None, LLMSettings | None]:
    settings = get_llm_settings()
    if settings is None or OpenAI is None:
        return None, settings
    kwargs: dict[str, Any] = {"api_key": settings.api_key}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if settings.default_headers:
        kwargs["default_headers"] = settings.default_headers
    return OpenAI(**kwargs), settings
