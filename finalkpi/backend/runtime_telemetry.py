from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import time
from typing import Any, Iterator
from uuid import uuid4


_SAFE_DETAIL_KEYS = {"reason_code", "result", "source_mode"}


def estimate_cost_usd(input_tokens: int | None, output_tokens: int | None,
                      input_rate: float | None, output_rate: float | None) -> float | None:
    if None in (input_tokens, output_tokens, input_rate, output_rate):
        return None
    return (int(input_tokens) * float(input_rate) + int(output_tokens) * float(output_rate)) / 1_000_000


class RuntimeTelemetry:
    def __init__(self, *, limits: dict[str, Any] | None = None,
                 clock=time.monotonic_ns) -> None:
        self.execution_id = f"exec-{uuid4()}"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._clock = clock
        self._started_ns = clock()
        self._completed: dict[str, Any] | None = None
        self._stages: list[dict[str, Any]] = []
        self.limits = dict(limits or {})

    def add_stage(self, *, stage: str, processing_type: str, method: str,
                  latency_ms: float, status: str = "COMPLETED",
                  cache_status: str = "NOT_APPLICABLE", provider: str | None = None,
                  model: str | None = None, model_calls: int = 0,
                  input_tokens: int | None = 0, output_tokens: int | None = 0,
                  estimated_cost_usd: float | None = 0, usage_source: str = "NOT_APPLICABLE",
                  details: dict[str, Any] | None = None) -> None:
        if processing_type != "LLM":
            provider = model = None
            model_calls, input_tokens, output_tokens, estimated_cost_usd = 0, 0, 0, 0
            usage_source = "NOT_APPLICABLE"
        elif model_calls and usage_source == "UNAVAILABLE":
            input_tokens = output_tokens = estimated_cost_usd = None
        safe_details = {k: v for k, v in (details or {}).items()
                        if k in _SAFE_DETAIL_KEYS and (v is None or isinstance(v, (str, int, float, bool)))}
        self._stages.append({
            "stage": stage, "processing_type": processing_type, "method": method,
            "latency_ms": round(max(0.0, float(latency_ms)), 3), "status": status,
            "cache_status": cache_status, "provider": provider, "model": model,
            "model_calls": max(0, int(model_calls)), "input_tokens": input_tokens,
            "output_tokens": output_tokens, "estimated_cost_usd": estimated_cost_usd,
            "usage_source": usage_source, "details": safe_details,
        })

    @contextmanager
    def stage(self, *, stage: str, processing_type: str, method: str,
              cache_status: str = "NOT_APPLICABLE", **usage: Any) -> Iterator[None]:
        started = self._clock()
        status, details = "COMPLETED", {}
        try:
            yield
        except Exception:
            status, details = "ERROR", {"reason_code": "STAGE_ERROR"}
            raise
        finally:
            self.add_stage(stage=stage, processing_type=processing_type, method=method,
                           latency_ms=(self._clock() - started) / 1_000_000,
                           status=status, cache_status=cache_status, details=details, **usage)

    def finalize(self) -> dict[str, Any]:
        if self._completed is not None:
            return self._completed
        completed_at = datetime.now(timezone.utc).isoformat()
        calls = sum(item["model_calls"] for item in self._stages)
        llm = [item for item in self._stages if item["processing_type"] == "LLM" and item["model_calls"]]
        usage_available = bool(llm) and all(item["usage_source"] != "UNAVAILABLE" for item in llm)
        input_tokens = sum(item["input_tokens"] for item in llm) if usage_available else None
        output_tokens = sum(item["output_tokens"] for item in llm) if usage_available else None
        costs_available = usage_available and all(item["estimated_cost_usd"] is not None for item in llm)
        cost = sum(item["estimated_cost_usd"] for item in llm) if costs_available else (0 if not llm else None)
        cache = {name: sum(item["cache_status"] == name for item in self._stages)
                 for name in ("HIT", "MISS", "NOT_APPLICABLE")}
        self._completed = {
            "execution_id": self.execution_id, "started_at": self.started_at,
            "completed_at": completed_at,
            "total_latency_ms": round(max(0.0, (self._clock() - self._started_ns) / 1_000_000), 3),
            "stages": list(self._stages),
            "llm_summary": {
                "provider": llm[0]["provider"] if llm else None,
                "model": llm[0]["model"] if llm else None,
                "model_calls": calls, "input_tokens": input_tokens if llm else 0,
                "output_tokens": output_tokens if llm else 0,
                "estimated_cost_usd": cost,
                "usage_source": ("UNAVAILABLE" if llm and not usage_available else
                                 llm[0]["usage_source"] if llm else "NOT_APPLICABLE"),
            },
            "cache_summary": {"hits": cache["HIT"], "misses": cache["MISS"],
                              "not_applicable": cache["NOT_APPLICABLE"]},
            "limits": self.limits,
        }
        return self._completed
