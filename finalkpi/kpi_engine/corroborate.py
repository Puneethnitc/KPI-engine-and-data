# IMPLEMENTATION HANDOFF — unstructured evidence corroboration (Stage 6-lite)
# Current: EvidenceCorroborator is the single owner of evidence retrieval. It is
# called from KPIEnginePipeline after attribution and writes a `corroboration`
# block onto every ranked driver. Retrieval is deterministic: tag match first,
# keyword fallback second, stance decides the verdict. Mandatory filters are
# available_at <= as_of, date inside [target - 21d, target], region/category in
# {slice, ALL}, and the persona's own server-owned access tags. A document with
# blank access_tags is readable by nobody (fail closed).
# Next: this reads a CSV. The chat path still has its own Chroma retrieval
# (backend/retrieval.py), which now applies the same four filters, but the two
# are not yet one component: a document could be in one corpus and not the
# other. Drive chunking/embedding into the engine or the corpus out of the
# backend, not both.
# Check: a future-dated or denied document never reaches a driver, a missing
# corpus is reported as RETRIEVAL_FAILED rather than as "no evidence", a
# prompt-injection document is dropped, and a document can only ever add
# support or a contradiction -- never upgrade an association into a cause.

"""Deterministic corroboration of attributed drivers by unstructured documents.

Retrieved prose is untrusted input. It is filtered for availability, scope and
entitlement before it is read, injection attempts are dropped rather than
fenced and passed on, and a document's `stance` is what moves a driver's
corroboration status -- never its mere presence.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

# A document is evidence for a movement only if it was written inside this many
# days before the target date. Backdated claims older than this are context, not
# evidence for this run.
EVIDENCE_WINDOW_DAYS = 21

PUBLIC_TAG = "public"
LIST_SEPARATOR = ";"
CORPORATE_SCOPE_VALUES = frozenset({"", "all", "*"})

REQUIRED_COLUMNS = ("doc_id", "date", "source_type", "region", "category", "text")
ENRICHED_COLUMNS = ("available_at", "access_tags", "driver_tags", "stance")

# Mirrors backend/domain_policy.py's server-owned entitlements, lower-cased.
# The engine cannot import the backend layer, so the mirror is asserted equal to
# `retrieval_tags_for_persona` in tests/test_corroboration.py -- if a persona's
# entitlement changes there, that test fails rather than the filter silently
# widening. An unknown persona gets no tags at all: fail closed.
PERSONA_ACCESS_TAGS: Dict[str, frozenset] = {
    "cfo": frozenset({
        "public", "sales", "marketing", "finance", "operations", "kpi_contract",
        "feedback_review", "candidate_evaluation", "chat_evidence",
    }),
    "marketing_manager": frozenset({"public", "sales", "marketing", "kpi_contract", "chat_evidence"}),
    "regional_manager_north": frozenset({"public", "sales", "operations", "kpi_contract", "chat_evidence"}),
    "regional_manager_south": frozenset({"public", "sales", "operations", "kpi_contract", "chat_evidence"}),
    "regional_manager_east": frozenset({"public", "sales", "operations", "kpi_contract", "chat_evidence"}),
    "regional_manager_west": frozenset({"public", "sales", "operations", "kpi_contract", "chat_evidence"}),
    "category_manager_north_electronics": frozenset({"public", "sales", "marketing", "kpi_contract", "chat_evidence"}),
}

# Instruction-override markers. A document carrying one is dropped before it is
# scored: a ticket that tries to change the agent's rules is not evidence about
# the business, whatever it claims to be evidence about.
INJECTION_PATTERNS = (
    "ignore all previous instructions",
    "ignore previous instructions",
    "ignore the above",
    "disregard all previous",
    "disregard the above",
    "disregard prior instructions",
    "system override",
    "new instructions:",
    "you are now",
    "override your instructions",
    "<|im_start|>",
    "<|im_end|>",
    "[system]",
    "###system",
)

_KEYWORD_MIN_LENGTH = 4
_SNIPPET_LENGTH = 220
# Words too generic to corroborate a driver on their own. They may still
# contribute to a multi-token match.
_GENERIC_KEYWORD_TOKENS = frozenset({
    "rate", "index", "level", "depth", "flag", "value", "data", "sales", "daily",
    "weekly", "monthly", "all", "none", "north", "south", "east", "west",
})

_WORD_RE = re.compile(r"[a-z0-9]+")
_SENTENCE_END_RE = re.compile(r"[.!?](\s|$)")


@dataclass(frozen=True)
class EvidenceDocument:
    doc_id: str
    date: str
    available_at: str
    source_type: str
    region: str
    category: str
    access_tags: Tuple[str, ...]
    driver_tags: Tuple[str, ...]
    stance: str
    text: str

    @property
    def keywords(self) -> frozenset:
        return frozenset(_WORD_RE.findall(self.text.lower()))


def _split_tags(value: Any) -> Tuple[str, ...]:
    return tuple(
        tag.strip().lower()
        for tag in str(value or "").replace(",", LIST_SEPARATOR).split(LIST_SEPARATOR)
        if tag.strip()
    )


def _normalise_date(value: Any) -> Optional[pd.Timestamp]:
    parsed = pd.to_datetime(str(value or "").strip(), errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_localize(None) if parsed.tzinfo is not None else pd.Timestamp(parsed)


def access_tags_for_persona(persona: Optional[str]) -> frozenset:
    """Return the persona's retrieval tags; an unknown persona gets none."""
    if not isinstance(persona, str) or not persona.strip():
        return frozenset()
    return PERSONA_ACCESS_TAGS.get(persona.strip().lower(), frozenset())


def contains_injection_attempt(text: str) -> bool:
    """True when a document tries to issue instructions rather than describe facts."""
    normalized = " ".join(str(text or "").lower().split())
    return any(pattern in normalized for pattern in INJECTION_PATTERNS)


def driver_keywords(driver_id: str, display_name: str = "") -> Tuple[str, ...]:
    """Tokens used for the keyword fallback when a document carries no driver tag."""
    tokens: List[str] = []
    for source in (str(driver_id or "").replace("_", " "), str(display_name or "").replace("_", " ")):
        for token in _WORD_RE.findall(source.lower()):
            if len(token) < _KEYWORD_MIN_LENGTH or token in _GENERIC_KEYWORD_TOKENS:
                continue
            if token not in tokens:
                tokens.append(token)
    return tuple(tokens)


class EvidenceCorroborator:
    """Filter, match and score unstructured evidence for attributed drivers."""

    def __init__(self, evidence_csv_path: str):
        self.evidence_path = Path(evidence_csv_path)
        self.documents = self.load_documents()

    def load_documents(self) -> List[EvidenceDocument]:
        """Load the corpus, failing loudly.

        A corpus that cannot be read is an error, not an empty result set: an
        empty corpus and a broken one mean opposite things to a reader, so the
        caller is told which one happened instead of being handed "no evidence".
        """
        if not self.evidence_path.is_file():
            raise FileNotFoundError(f"Evidence corpus is required: {self.evidence_path}")
        frame = pd.read_csv(self.evidence_path, dtype=str).fillna("")
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"Evidence corpus {self.evidence_path} is missing columns: {missing}")
        unenriched = [column for column in ENRICHED_COLUMNS if column not in frame.columns]
        if unenriched:
            raise ValueError(
                f"Evidence corpus {self.evidence_path} is missing the availability and "
                f"entitlement columns {unenriched}; run data/patches/enrich_evidence.py"
            )

        documents: List[EvidenceDocument] = []
        seen: set = set()
        for row in frame.to_dict("records"):
            doc_id = str(row.get("doc_id") or "").strip()
            if not doc_id:
                raise ValueError("Every evidence document needs a stable doc_id")
            if doc_id in seen:
                raise ValueError(f"Duplicate evidence doc_id: {doc_id}")
            seen.add(doc_id)
            document_date = _normalise_date(row.get("date"))
            if document_date is None:
                raise ValueError(f"Evidence document {doc_id} has an unparseable date")
            stance = str(row.get("stance") or "neutral").strip().lower()
            if stance not in {"supports", "refutes", "neutral"}:
                raise ValueError(f"Evidence document {doc_id} has an unknown stance: {stance}")
            documents.append(EvidenceDocument(
                doc_id=doc_id,
                date=document_date.date().isoformat(),
                # A document with no declared availability is available when it
                # was written. Availability may be later, never earlier.
                available_at=(
                    (_normalise_date(row.get("available_at")) or document_date).date().isoformat()
                ),
                source_type=str(row.get("source_type") or "evidence").strip() or "evidence",
                region=str(row.get("region") or "ALL").strip() or "ALL",
                category=str(row.get("category") or "ALL").strip() or "ALL",
                access_tags=_split_tags(row.get("access_tags")),
                driver_tags=_split_tags(row.get("driver_tags")),
                stance=stance,
                text=str(row.get("text") or ""),
            ))
        return documents

    @staticmethod
    def fence_untrusted_text(doc_id: str, raw_text: str) -> str:
        """Wrap untrusted document text in a boundary before it reaches a model.

        Fencing is a prompt-hygiene measure only. It is not authorization (that
        is the filter chain above) and it is not an injection defence on its own
        (that is INJECTION_PATTERNS) -- both are applied before this is ever
        called.
        """
        sanitized = re.sub(r"<<<.*?>>>", "", str(raw_text))
        sanitized = sanitized.replace("```", "")
        return f"<<<DOC id='{doc_id}'>>>\n{sanitized}\n<<<END>>>"

    def visible_documents(
        self,
        *,
        target_date: str,
        as_of: str,
        scope: Optional[Dict[str, str]] = None,
        persona: Optional[str] = None,
    ) -> Tuple[List[EvidenceDocument], Dict[str, int]]:
        """Apply the four mandatory filters, returning survivors and drop counts."""
        target = _normalise_date(target_date)
        cutoff = _normalise_date(as_of) if as_of else target
        if target is None:
            raise ValueError("target_date is required to retrieve evidence")
        window_start = target - pd.Timedelta(days=EVIDENCE_WINDOW_DAYS)
        scope = scope or {}
        allowed_tags = access_tags_for_persona(persona)

        def scope_ok(document: EvidenceDocument, dimension: str) -> bool:
            requested = str(scope.get(dimension) or "").strip()
            declared = document.region if dimension == "region" else document.category
            if requested.lower() in CORPORATE_SCOPE_VALUES:
                # An unscoped run may only read company-wide documents; it must
                # not read every region by omitting the filter.
                return declared.strip().lower() in CORPORATE_SCOPE_VALUES
            return declared.strip().lower() in {requested.lower(), "all"}

        survivors: List[EvidenceDocument] = []
        filtered = {
            "not_yet_available": 0,
            "outside_window": 0,
            "out_of_scope": 0,
            "not_entitled": 0,
            "prompt_injection": 0,
        }
        for document in self.documents:
            if contains_injection_attempt(document.text):
                filtered["prompt_injection"] += 1
                continue
            if _normalise_date(document.available_at) > cutoff:
                filtered["not_yet_available"] += 1
                continue
            document_date = _normalise_date(document.date)
            if document_date < window_start or document_date > target:
                filtered["outside_window"] += 1
                continue
            if not scope_ok(document, "region") or not scope_ok(document, "category"):
                filtered["out_of_scope"] += 1
                continue
            if not (set(document.access_tags) & allowed_tags):
                filtered["not_entitled"] += 1
                continue
            survivors.append(document)
        return survivors, filtered

    @staticmethod
    def _driver_tag_matches(document: EvidenceDocument, driver_id: str) -> bool:
        from kpi_engine.contracts.registry import resolve_driver_id

        wanted = {driver_id, resolve_driver_id(driver_id)}
        return bool(wanted & set(document.driver_tags))

    @staticmethod
    def _keyword_matches(document: EvidenceDocument, driver_id: str, display_name: str) -> Tuple[str, ...]:
        """Fallback match. Requires at least half the driver's tokens.

        This is deliberately more permissive than the tag match: a document with
        no driver_tags is still worth surfacing. Permissiveness cannot promote a
        driver, because only a document's stance sets CORROBORATED or
        CONTRADICTED -- a keyword hit with a neutral stance leaves the status at
        NONE.
        """
        tokens = driver_keywords(driver_id, display_name)
        if not tokens:
            return ()
        present = document.keywords
        matched = tuple(token for token in tokens if token in present)
        needed = max(1, math.ceil(0.5 * len(tokens)))
        return matched if len(matched) >= needed else ()

    @staticmethod
    def _snippet(document: EvidenceDocument, matched_terms: Sequence[str]) -> str:
        text = " ".join(str(document.text or "").split())
        if not text:
            return ""
        start = 0
        lowered = text.lower()
        for term in matched_terms:
            position = lowered.find(term)
            if position != -1:
                start = max(0, position - 60)
                break
        snippet = text[start:start + _SNIPPET_LENGTH]
        if start > 0:
            snippet = "..." + snippet
        if start + _SNIPPET_LENGTH < len(text):
            snippet = snippet.rstrip() + "..."
        return snippet

    def _document_entry(
        self,
        document: EvidenceDocument,
        match_basis: str,
        matched_terms: Sequence[str],
    ) -> Dict[str, Any]:
        return {
            "doc_id": document.doc_id,
            "date": document.date,
            "available_at": document.available_at,
            "source_type": document.source_type,
            "region": document.region,
            "category": document.category,
            "stance": document.stance,
            "matched_by": match_basis,
            "matched_terms": list(matched_terms),
            "snippet": self._snippet(document, matched_terms),
        }

    def corroborate(
        self,
        ranked_drivers: Iterable[Dict[str, Any]],
        *,
        target_date: str,
        as_of: str,
        scope: Optional[Dict[str, str]] = None,
        persona: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a per-driver corroboration block plus the run-level summary.

        Status is decided by the stance counts among the matched documents.
        A driver is CONTRADICTED only when refuting documents outnumber
        supporting ones; a tie resolves to CORROBORATED, because a document
        that both reports a problem and reports it resolved (TCK-4002 resolving
        TCK-4001's latency incident) is a real event described twice, not two
        independent pieces of evidence pulling in opposite directions. The
        contradicting document is still shown in the panel either way, so a
        reader sees the disagreement rather than a summary verdict.
        """
        drivers = [dict(driver) for driver in ranked_drivers or []]
        target = _normalise_date(target_date)
        if target is None:
            raise ValueError("target_date is required to corroborate drivers")
        visible, filtered = self.visible_documents(
            target_date=target_date, as_of=as_of, scope=scope, persona=persona,
        )

        per_driver: Dict[str, Dict[str, Any]] = {}
        for driver in drivers:
            driver_id = str(driver.get("driver_id") or "")
            if not driver_id:
                continue
            display_name = str(driver.get("display_name") or "")

            tagged = [doc for doc in visible if self._driver_tag_matches(doc, driver_id)]
            entries: List[Dict[str, Any]] = []
            match_basis = "driver_tag"
            matched_terms: List[str] = []
            for document in tagged:
                matched_terms = [tag for tag in document.driver_tags if tag == driver_id]
                entries.append(self._document_entry(document, "driver_tag", matched_terms))
            used_tag_ids = {entry["doc_id"] for entry in entries}

            if not entries:
                # Tag match found nothing; fall back to keywords for this driver.
                match_basis = "keyword"
                for document in visible:
                    if document.doc_id in used_tag_ids:
                        continue
                    hits = self._keyword_matches(document, driver_id, display_name)
                    if hits:
                        matched_terms = list(hits)
                        entries.append(self._document_entry(document, "keyword", hits))

            supports = [entry for entry in entries if entry["stance"] == "supports"]
            refutes = [entry for entry in entries if entry["stance"] == "refutes"]
            if len(refutes) > len(supports):
                status = "CONTRADICTED"
            elif supports:
                status = "CORROBORATED"
            elif refutes:
                status = "CONTRADICTED"
            else:
                status = "NONE"

            # Supporting documents first, then contradicting ones, then neutral;
            # newest first inside each stance so the panel leads with the closest
            # in-window evidence.
            entries.sort(key=lambda entry: (
                {"supports": 0, "refutes": 1, "neutral": 2}[entry["stance"]],
                [-int(entry["date"].replace("-", ""))],
            ))
            per_driver[driver_id] = {
                "status": status,
                "documents": entries,
                "document_count": len(entries),
                "match_basis": match_basis,
                "supporting_documents": [entry["doc_id"] for entry in supports],
                "refuting_documents": [entry["doc_id"] for entry in refutes],
            }

        statuses = [block["status"] for block in per_driver.values()]
        if any(status == "CONTRADICTED" for status in statuses) and any(
            status == "CORROBORATED" for status in statuses
        ):
            overall = "MIXED"
        elif any(status == "CONTRADICTED" for status in statuses):
            overall = "CONTRADICTED"
        elif any(status == "CORROBORATED" for status in statuses):
            overall = "CORROBORATED"
        elif statuses:
            overall = "NONE"
        else:
            overall = "NOT_ASSESSED"

        return {
            "status": overall,
            "target_date": target.date().isoformat(),
            "as_of": as_of,
            "window_start": (target - pd.Timedelta(days=EVIDENCE_WINDOW_DAYS)).date().isoformat(),
            "window_days": EVIDENCE_WINDOW_DAYS,
            "scope": dict(scope or {}),
            "persona": persona,
            "documents_total": len(self.documents),
            "documents_visible": len(visible),
            "filtered": filtered,
            "drivers": per_driver,
            "limitations": [
                "Unstructured documents are untrusted prose; they can support or "
                "contradict a driver but never establish causation.",
                "Corroboration is a retrieval and stance count over a "
                f"{EVIDENCE_WINDOW_DAYS}-day window ending on the target date.",
            ],
        }

    @staticmethod
    def failure_summary(reason: str) -> Dict[str, Any]:
        """A load failure, shaped like a result so the UI can say what happened."""
        return {
            "status": "RETRIEVAL_FAILED",
            "reason": reason,
            "documents_total": 0,
            "documents_visible": 0,
            "filtered": {},
            "drivers": {},
        }

    def corroborate_or_report(
        self,
        ranked_drivers: Iterable[Dict[str, Any]],
        *,
        target_date: str,
        as_of: str,
        scope: Optional[Dict[str, str]] = None,
        persona: Optional[str] = None,
        load_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        if load_error is not None:
            return self.failure_summary(load_error)
        return self.corroborate(
            ranked_drivers, target_date=target_date, as_of=as_of, scope=scope, persona=persona,
        )
