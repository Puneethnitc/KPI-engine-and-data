from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.service import get_diagnosis
from backend.storage import append_message, create_conversation, get_conversation


def grounded_chat(*, run_id: str, question: str, user_id: str = "demo-user", persona: str = "CFO") -> Dict[str, Any]:
    diagnosis = get_diagnosis(run_id)
    if diagnosis is None:
        raise ValueError(f"Unknown diagnosis run_id: {run_id}")

    result = diagnosis["result"]
    kpi_id = result.get("kpi_id")
    scope = diagnosis.get("scope", {})
    if persona != "CFO":
        raise ValueError("Demo backend only supports the CFO identity for chat.")

    context = {
        "run_id": run_id,
        "kpi_id": kpi_id,
        "region": scope.get("region"),
        "category": scope.get("category"),
        "as_of": result.get("as_of"),
        "persona": persona,
    }
    conversation_id = create_conversation(run_id, user_id, context)

    answer = {
        "answer": (
            f"The diagnosis for {kpi_id} on {result.get('target_date')} in {scope.get('region')} / {scope.get('category')} "
            f"is {result.get('verdict')}. The engine reported the current evidence state and did not claim a proven cause."
        ),
        "citations": [
            {
                "id": f"run:{run_id}",
                "kind": "diagnosis",
                "source": "KPIEnginePipeline",
                "summary": "Saved diagnosis run for the selected KPI and scope.",
            }
        ],
        "evidence_status": "limited",
        "limitations": [
            "This prototype uses the saved diagnosis as the authoritative context and does not infer unsupported causal claims.",
            "No live LLM is required for the demo; the response is grounded in the engine result and the active evidence state.",
        ],
        "suggested_followups": [
            "Review the KPI verdict and source coverage in the saved diagnosis.",
            "Ask about the exact driver signals and model limitations for this KPI.",
        ],
    }

    append_message(conversation_id, "user", question, answer["citations"])
    append_message(conversation_id, "assistant", answer["answer"], answer["citations"])
    return {
        **answer,
        "conversation_id": conversation_id,
        "run_id": run_id,
        "kpi_id": kpi_id,
        "grounding": "engine-trace",
    }
