"""Persona-specific executive summary written by an LLM from a numbered fact sheet.

The model is never a source of numbers. It receives facts F1..Fn that this
module builds from the deterministic KPI story, and must cite the facts each
sentence uses. ``guard`` then rejects the whole output (and the caller falls
back to a deterministic summary) if any number is not in a cited fact, a cited
ID does not exist, causal wording is used for a driver that is not both causally
SUPPORTED_CONDITIONAL and AC >= 0.6, an entity outside the fact sheet is named,
or the length limits are broken.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

import yaml

from kpi_engine.narrative import CAUSAL_SUPPORTED_VERDICTS, CAUSAL_WORDING_MIN_AC, GROQ_USER_AGENT
from kpi_engine.personas import load_persona

REGISTRY_DIR = Path(__file__).resolve().parent / "registry"
MIN_SENTENCES, MAX_SENTENCES = 2, 4
PROMPT_VERSION = "2"
DRIVER_THRESHOLD = 0.35
NO_ACTION_TEXT = "No action needed; keep monitoring"
CAVEAT_PHRASE = "accounting split"
MAX_SENTENCE_CHARS, MAX_ACTION_CHARS, MAX_TOTAL_CHARS = 320, 260, 1300
MAX_FACTS = 30
CACHE_LIMIT = 128
CAUSAL_WORDS = re.compile(r"\b(caused|causes|causing|cause of|due to|because of|resulted from|result of|driven by|drove|drives|led to)\b", re.I)

KPI_NAMES = {"traffic_total": "Traffic", "conversion_rate": "Conversion", "orders": "Orders", "units_sold": "Units", "net_sales_revenue": "Revenue"}
STAGE_NAMES = {"traffic": "Traffic", "conversion": "Conversion", "units": "Units per order", "basket": "Price per unit"}

PERSONA_BRIEF = {
    "cfo": "You write for the CFO: lead with the rupee impact on revenue, say whether the sources reconcile, and mention any approvals needed.",
    "marketing_manager": "You write for the marketing manager: focus on the funnel (traffic, conversion), marketing spend and promotions.",
    "regional_manager": "You write for a regional manager: focus on stock availability and operations in the region.",
}

_CACHE: dict[str, dict[str, Any]] = {}


# --------------------------------------------------------------------- facts

def _humanize(value: str) -> str:
    return value.replace("_", " ").strip()


def _money(amount: float) -> str:
    return f"{'+' if amount >= 0 else '−'}₹{abs(amount):,.0f}"


def _verb(delta: float) -> str:
    return "rose" if delta > 0 else "fell" if delta < 0 else "was unchanged"


def _pct(value: float, signed: bool = True) -> str:
    return f"{('+' if value >= 0 else '−') if signed else ''}{abs(value):.1f}%"


@lru_cache(maxsize=1)
def _entity_universe() -> frozenset[str]:
    """Every candidate-driver name the platform knows, lower-cased.

    The five funnel KPIs are always in the fact sheet, so only drivers can be "outside" it.
    """
    names: set[str] = set()
    for path in REGISTRY_DIR.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for driver in data.get("candidate_drivers") or []:
            for key in ("id", "display_name"):
                if driver.get(key):
                    names.add(_humanize(str(driver[key])).lower())
    return frozenset(name for name in names if len(name) > 3)


def build_fact_sheet(story: Mapping[str, Any], results: Mapping[str, Mapping[str, Any]], persona: str | None) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []

    def add(text: str, kind: str, **extra: Any) -> None:
        if len(facts) < MAX_FACTS:
            facts.append({"id": f"F{len(facts) + 1}", "kind": kind, "text": text, **extra})

    names: set[str] = set(KPI_NAMES.values())
    first = next(iter(results.values()), {}) or {}
    segment = first.get("segment") or {}
    add(f"Scope: region {segment.get('region') or 'all'}, category {segment.get('category') or 'all'}, target date {first.get('target_date')}.", "scope")

    revenue = next((f for f in story.get("headline_facts", []) if f.get("kind") == "revenue"), {})
    if revenue.get("delta") is not None:
        pct = revenue.get("percent_change")
        delta = revenue["delta"]
        add(f"Revenue {_verb(delta)} ₹{abs(delta):,.0f}{'' if pct is None else f' ({abs(pct):.1f}%)'} versus expected.", "revenue")
    revenue_node = next((n for n in story.get("nodes", []) if n.get("kpi_id") == "net_sales_revenue"), None)
    material = bool(revenue_node and revenue_node.get("material"))
    if revenue_node is not None:
        add(f"The revenue movement is {'a material change' if material else 'within the normal range'}.", "materiality", material=material)
    for edge in story.get("edges", []):
        share = edge.get("contribution_pct")
        add(f"{STAGE_NAMES.get(edge['stage'], edge['stage'])} accounts for {_money(edge['contribution_inr'])}{'' if share is None else f' ({abs(share):.0f}% of the revenue change)'}.", "bridge")
    if story.get("edges"):
        add("The funnel split is an accounting split, not a cause.", "caveat")
    if story.get("root_stage"):
        add(f"The largest share of the revenue change came from {STAGE_NAMES.get(story['root_stage'], story['root_stage']).lower()}.", "root")
    for node in story.get("nodes", []):
        if node.get("percent_change") is not None and node["kpi_id"] in KPI_NAMES:
            origin = node.get("consequence_of")
            downstream = f" It is a downstream result of {STAGE_NAMES.get(origin, origin).lower()}, not a separate cause." if origin else ""
            add(f"{KPI_NAMES[node['kpi_id']]} {_verb(node['percent_change'])} {abs(node['percent_change']):.1f}% versus expected ({'material' if node.get('material') else 'within the normal range'}).{downstream}", "kpi")
    if story.get("missing_stages"):
        add(f"Missing stages: {', '.join(STAGE_NAMES.get(s, s) for s in story['missing_stages'])}.", "missing")

    # Drivers: one per driver_id, highest attribution confidence, top four.
    best: dict[str, dict[str, Any]] = {}
    for kpi_id, result in results.items():
        verification = result.get("causal_verification") or {}
        for driver in ((result.get("driver_analysis") or {}).get("ranked_drivers") or []):
            ac = driver.get("attribution_confidence")
            if ac is None or driver.get("driver_id") is None:
                continue
            verdict = verification.get("verdict") if verification.get("driver_id") == driver["driver_id"] else "NOT_TESTED"
            current = best.get(driver["driver_id"])
            if current is None or ac > current["ac"]:
                best[driver["driver_id"]] = {"id": driver["driver_id"], "name": driver.get("display_name") or _humanize(driver["driver_id"]).capitalize(),
                                             "ac": float(ac), "band": driver.get("band") or driver.get("label"), "verdict": verdict or "NOT_TESTED", "kpi": kpi_id}
    chains = {c["driver_id"]: c for c in story.get("cause_chains", [])}
    for driver_id, chain in chains.items():
        entry = best.setdefault(driver_id, {"id": driver_id, "name": _humanize(driver_id).capitalize(), "ac": float(chain["attribution_confidence"]), "band": chain.get("band"), "verdict": chain.get("causal_verdict"), "kpi": chain.get("via_kpi")})
        if chain.get("causal_verdict") not in (None, "NOT_TESTED"):
            entry["verdict"] = chain["causal_verdict"]
    qualified = sorted((e for e in best.values() if e["ac"] >= DRIVER_THRESHOLD), key=lambda item: -item["ac"])
    if qualified:
        add(f"A driver reached the {DRIVER_THRESHOLD * 100:.0f}% confidence threshold: {qualified[0]['name']} at {qualified[0]['ac'] * 100:.0f}% attribution confidence.", "gate")
    else:
        add(f"No driver reached the {DRIVER_THRESHOLD * 100:.0f}% attribution-confidence threshold.", "gate")
    for entry in sorted(best.values(), key=lambda item: -item["ac"])[:4]:
        chain = chains.get(entry["id"])
        causal_ok = entry["verdict"] in CAUSAL_SUPPORTED_VERDICTS and entry["ac"] >= CAUSAL_WORDING_MIN_AC
        impact = f" Estimated revenue effect {_money(chain['revenue_impact'])}." if chain else ""
        add(f"Driver {entry['name']}: attribution confidence {entry['ac'] * 100:.0f}% ({_humanize(str(entry['band'] or 'unrated')).lower()}); causal test {_humanize(str(entry['verdict'])).lower()}.{impact}"
            f" Causal wording is {'allowed' if causal_ok else 'NOT allowed: say linked to or associated with'}.", "driver",
            driver_id=entry["id"], driver_name=entry["name"], causal_ok=causal_ok)
        names.add(entry["name"].lower())
        names.add(_humanize(entry["id"]).lower())
        if chain and chain.get("corroboration_doc_ids"):
            add(f"Documents supporting {entry['name']}: {', '.join(chain['corroboration_doc_ids'][:3])}.", "corroboration")

    for kpi_id, result in results.items():
        recon = result.get("reconciliation_verdict") or {}
        if recon.get("status") not in (None, "NOT_APPLICABLE"):
            gap = recon.get("gap_pct")
            add(f"{KPI_NAMES.get(kpi_id, kpi_id)} reconciliation with the finance source: {_humanize(recon['status']).lower()}{'' if gap is None else f' (gap {abs(gap):.1f}%)'}.", "reconciliation")
    seen: set[str] = set()
    for result in results.values():
        for card in result.get("decision_cards") or []:
            text = str(card.get("recommendation") or "").strip()
            if text and text not in seen and len(seen) < 3:
                seen.add(text)
                owner = _humanize(str(card.get("owner") or "analyst"))
                add(f"Proposed action: {text} Owner: {owner}. Approval required: {'yes' if card.get('approval_required') else 'no'}.", "action",
                    recommendation=text, owner=owner, approval=bool(card.get("approval_required")))

    if not seen:
        add("No action is recommended for this movement.", "no_action")
    action_allowed = material and bool(qualified) and any(f["kind"] == "action" for f in facts)
    config = load_persona(persona)
    return {"facts": facts, "action_allowed": action_allowed, "names": sorted(names), "persona": config.persona_id, "persona_display": config.display_name}


# ------------------------------------------------------------------- guard

def _numbers(text: str) -> list[float]:
    cleaned = re.sub(r"\bF\d+\b", " ", text)
    cleaned = re.sub(r"\d{4}-\d{2}-\d{2}", " ", cleaned)
    return [float(token.replace(",", "")) for token in re.findall(r"\d[\d,]*(?:\.\d+)?", cleaned)]


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def _number_supported(text_value: float, digits: int, fact_values: list[float]) -> bool:
    tolerance = 0.5 * 10 ** -digits + 1e-9
    return any(abs(text_value - value) <= tolerance for value in fact_values)


def guard(output: Any, sheet: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Return (accepted, reasons). Every rule must pass."""
    errors: list[str] = []
    if not isinstance(output, dict) or not isinstance(output.get("sentences"), list) or not isinstance(output.get("do_first"), dict):
        return False, ["malformed output"]
    facts = {fact["id"]: fact for fact in sheet["facts"]}
    allowed_names = {name.lower() for name in sheet.get("names", [])}
    forbidden = sorted(name for name in _entity_universe() if name not in allowed_names and not any(name in allowed for allowed in allowed_names))
    sentences = output["sentences"]
    if not MIN_SENTENCES <= len(sentences) <= MAX_SENTENCES:
        errors.append(f"expected {MIN_SENTENCES}-{MAX_SENTENCES} sentences, got {len(sentences)}")
    items = [*sentences, output["do_first"]]
    total = 0
    for index, item in enumerate(items):
        label = "do_first" if index == len(sentences) else f"sentence {index + 1}"
        text, cited = (item.get("text"), item.get("facts")) if isinstance(item, dict) else (None, None)
        is_no_action = label == "do_first" and isinstance(text, str) and text.strip().rstrip(".").lower() == NO_ACTION_TEXT.lower()
        if not isinstance(text, str) or not text.strip() or not isinstance(cited, list) or not all(isinstance(c, str) for c in cited) or (not cited and not is_no_action):
            errors.append(f"{label}: needs text and at least one fact id")
            continue
        if label == "do_first":
            kinds = {facts[c]["kind"] for c in cited if c in facts}
            if is_no_action:
                pass
            elif not sheet.get("action_allowed"):
                errors.append(f"do_first: must be '{NO_ACTION_TEXT}' when the movement is not material or no driver qualified")
            elif "action" not in kinds:
                errors.append("do_first: must cite an action fact")
            elif kinds & {"revenue", "bridge", "kpi", "root", "materiality"} or re.search(r"\brevenue\b.*\b(rose|fell)\b", text, re.I):
                errors.append("do_first: must not restate the revenue change")
        total += len(text)
        if len(text) > (MAX_ACTION_CHARS if label == "do_first" else MAX_SENTENCE_CHARS):
            errors.append(f"{label}: too long")
        unknown = [c for c in cited if c not in facts]
        if unknown:
            errors.append(f"{label}: unknown fact id {', '.join(unknown)}")
            continue
        fact_values = [value for c in cited for value in _numbers(facts[c]["text"])]
        stripped = re.sub(r"\bF\d+\b", " ", text)
        stripped = re.sub(r"\d{4}-\d{2}-\d{2}", " ", stripped)
        for token in re.findall(r"\d[\d,]*(?:\.\d+)?", stripped):
            if not _number_supported(float(token.replace(",", "")), _decimals(token), fact_values):
                errors.append(f"{label}: number {token} is not in a cited fact")
        lowered = text.lower()
        for name in forbidden:
            if re.search(rf"\b{re.escape(name)}\b", lowered):
                errors.append(f"{label}: names '{name}', which is not in the fact sheet")
        if CAUSAL_WORDS.search(text):
            drivers = [facts[c] for c in cited if facts[c].get("kind") == "driver"]
            mentioned = [f for f in sheet["facts"] if f.get("kind") == "driver" and f["driver_name"].lower() in lowered]
            if not drivers or not all(f.get("causal_ok") for f in [*drivers, *mentioned]):
                errors.append(f"{label}: causal wording without a supported causal test and AC >= {CAUSAL_WORDING_MIN_AC}")
    if total > MAX_TOTAL_CHARS:
        errors.append("summary too long")
    caveats = sum(str(item.get("text", "")).lower().count(CAVEAT_PHRASE) for item in items if isinstance(item, dict))
    if caveats > 1:
        errors.append("the accounting-split caveat may appear at most once")
    return not errors, errors


# ---------------------------------------------------------------- fallback

def fallback_summary(story: Mapping[str, Any], sheet: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic 2-4 sentence summary (what happened, where from, how sure) plus a do-first line."""
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for fact in sheet["facts"]:
        by_kind.setdefault(fact["kind"], []).append(fact)
    sentences: list[dict[str, Any]] = []
    revenue = (by_kind.get("revenue") or [None])[0]
    if revenue:
        sentences.append({"text": revenue["text"], "facts": [revenue["id"]]})
    bridge = by_kind.get("bridge", [])
    edges = sorted((e for e in story.get("edges", []) if e.get("contribution_pct") is not None), key=lambda e: -abs(e["contribution_inr"]))
    if edges and revenue:
        rising = (story.get("revenue_delta") or 0) >= 0
        by_stage = {f["text"].split(" accounts")[0]: f for f in bridge}
        parts = []
        cited: list[str] = []
        for rank, edge in enumerate(edges[:2]):
            label = STAGE_NAMES.get(edge["stage"], edge["stage"])
            fact = by_stage.get(label)
            if not fact or (rank and abs(edge["contribution_pct"]) < 10):
                continue
            cited.append(fact["id"])
            same_direction = (edge["contribution_inr"] >= 0) == rising
            if rank == 0:
                parts.append(f"Most of the {'rise' if rising else 'fall'} came from {label.lower()} ({abs(edge['contribution_pct']):.0f}%)")
            else:
                parts.append(f"{label.lower()} {'adding' if same_direction else 'offsetting'} {abs(edge['contribution_pct']):.0f}%")
        caveat = (by_kind.get("caveat") or [None])[0]
        if parts and caveat:
            sentences.append({"text": ", with ".join(parts) + "; this is an accounting split, not a cause.", "facts": [*cited, caveat["id"]]})
        elif parts:
            sentences.append({"text": ", with ".join(parts) + ".", "facts": cited})
    gate = (by_kind.get("gate") or [None])[0]
    if gate:
        sentences.append({"text": gate["text"], "facts": [gate["id"]]})
    if not sentences:
        sentences.append({"text": "A revenue comparison is unavailable for this scope.", "facts": [sheet["facts"][0]["id"]] if sheet["facts"] else []})
    action = (by_kind.get("action") or [None])[0]
    do_first = ({"text": f"{action['recommendation']} (owner: {action['owner']}{'; approval required' if action['approval'] else ''})", "facts": [action["id"]]} if sheet.get("action_allowed") and action
                else {"text": NO_ACTION_TEXT, "facts": []})
    return {"sentences": sentences, "do_first": do_first}


# -------------------------------------------------------------- LLM client

def default_client(api_key: str) -> Callable[[list[dict[str, str]]], dict[str, Any]]:
    def call(messages: list[dict[str, str]]) -> dict[str, Any]:
        endpoint = f"{os.getenv('GROQ_BASE_URL', 'https://api.groq.com/openai/v1').rstrip('/')}/chat/completions"
        body = json.dumps({"model": model_name(), "temperature": 0, "max_completion_tokens": 2000,
                           "response_format": {"type": "json_object"}, "messages": messages}).encode("utf-8")
        request = Request(endpoint, data=body, method="POST", headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": GROQ_USER_AGENT})
        with urlopen(request, timeout=30) as response:
            answer = json.load(response)
        usage = answer.get("usage") or {}
        return {"content": answer["choices"][0]["message"]["content"],
                "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}
    return call


def model_name() -> str:
    return os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")


def build_messages(sheet: Mapping[str, Any]) -> list[dict[str, str]]:
    brief = PERSONA_BRIEF.get(sheet["persona"], PERSONA_BRIEF["regional_manager"] if sheet["persona"].startswith("regional") else "You write for a business leader.")
    system = (
        f"{brief} Write a short summary in plain language using ONLY the numbered facts provided. "
        "Write 2 to 4 sentences in this order: (1) what happened; (2) where it came from, combining the funnel split into ONE sentence "
        "such as 'Most of the rise came from traffic (61%), with price per unit adding 30%'; (3) how sure we are (materiality and driver confidence). "
        "Then give a separate 'do first' line. "
        "Say 'rose' or 'fell', never 'changed +' or 'changed -'. "
        "State the 'accounting split, not a cause' caveat at most once, and only if you talk about the funnel split. "
        f"The 'do first' line must be the action from the action facts, or exactly '{NO_ACTION_TEXT}' when the movement is not material, "
        "no driver reached the confidence threshold, or there is no action fact; it must never restate the revenue change. "
        "Every sentence lists the fact IDs it uses. Copy numbers exactly as written in the facts; never compute, round or invent numbers. "
        "Never name a KPI, driver or document that is not in the facts. "
        "You may say 'came from', 'linked to' or 'associated with'. Use 'caused', 'drove', 'drives', 'due to' or 'because of' "
        "ONLY for a driver whose fact says causal wording is allowed. "
        'Return JSON only: {"sentences":[{"text":"...","facts":["F1"]}],"do_first":{"text":"...","facts":["F2"]}}'
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"facts": [{"id": f["id"], "text": f["text"]} for f in sheet["facts"]]}, ensure_ascii=False)}]


def _fact_hash(sheet: Mapping[str, Any]) -> str:
    payload = json.dumps({"facts": [(f["id"], f["text"]) for f in sheet["facts"]], "persona": sheet["persona"], "model": model_name(), "prompt": PROMPT_VERSION}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ public

def executive_summary(story: Mapping[str, Any] | None, results: Mapping[str, Mapping[str, Any]], persona: str | None, *,
                      api_key: str | None = None, client: Callable[[list[dict[str, str]]], dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Return the summary payload; ``runtime`` describes any model call for telemetry."""
    if story is None:
        return None
    sheet = build_fact_sheet(story, results, persona)
    runtime: dict[str, Any] = {"attempted": False, "latency_ms": 0.0, "provider": None, "model": None, "model_calls": 0,
                               "input_tokens": 0, "output_tokens": 0, "usage_source": "NOT_APPLICABLE", "cache_status": "NOT_APPLICABLE"}
    key = _fact_hash(sheet)
    used_client = client or (default_client(api_key) if api_key else None)
    status, reason, body = "TEMPLATE", "AI unavailable", None
    if key in _CACHE:
        cached = _CACHE[key]
        status, reason, body = cached["status"], cached["reason"], cached["body"]
        runtime["cache_status"] = "HIT"
    elif used_client is not None:
        started = time.monotonic_ns()
        runtime.update(attempted=True, provider="groq" if client is None else "injected", model=model_name() if client is None else "injected",
                       model_calls=1, cache_status="MISS", usage_source="UNAVAILABLE", input_tokens=None, output_tokens=None)
        try:
            answer = used_client(build_messages(sheet))
            if answer.get("input_tokens") is not None and answer.get("output_tokens") is not None:
                runtime.update(input_tokens=int(answer["input_tokens"]), output_tokens=int(answer["output_tokens"]), usage_source="PROVIDER_REPORTED")
            proposal = json.loads(answer["content"]) if isinstance(answer.get("content"), str) else answer.get("content")
            accepted, errors = guard(proposal, sheet)
            if accepted:
                status, reason, body = "LLM", "passed guard", proposal
            else:
                status, reason = "TEMPLATE", "AI output rejected: " + "; ".join(errors[:3])
            if len(_CACHE) >= CACHE_LIMIT:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = {"status": status, "reason": reason, "body": body}
        except Exception as exc:  # network, JSON or shape errors are never cached
            status, reason = "TEMPLATE", f"AI unavailable: {type(exc).__name__}"
            runtime["error"] = True
        finally:
            runtime["latency_ms"] = round(max(0.0, (time.monotonic_ns() - started) / 1_000_000), 3)
    if body is None:
        body = fallback_summary(story, sheet)
    return {"status": status, "reason": reason, "persona": sheet["persona"], "model": model_name() if status == "LLM" else None,
            "sentences": body["sentences"], "do_first": body["do_first"],
            "facts": [{"id": f["id"], "text": f["text"]} for f in sheet["facts"]], "runtime": runtime}
