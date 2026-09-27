"""Backend-owned prototype domain entitlements, separate from row scope."""

from __future__ import annotations

from typing import Final

DOMAINS: Final[frozenset[str]] = frozenset({
    "SALES",
    "MARKETING",
    "FINANCE",
    "OPERATIONS",
    "KPI_CONTRACT",
    "FEEDBACK_REVIEW",
    "CANDIDATE_EVALUATION",
    "CHAT_EVIDENCE",
})

_DOMAIN_ENTITLEMENTS: Final[dict[str, frozenset[str]]] = {
    "cfo": DOMAINS,
    "marketing_manager": frozenset({"SALES", "MARKETING", "KPI_CONTRACT", "CHAT_EVIDENCE"}),
    "regional_manager_north": frozenset({"SALES", "OPERATIONS", "KPI_CONTRACT", "CHAT_EVIDENCE"}),
    "regional_manager_south": frozenset({"SALES", "OPERATIONS", "KPI_CONTRACT", "CHAT_EVIDENCE"}),
    "regional_manager_east": frozenset({"SALES", "OPERATIONS", "KPI_CONTRACT", "CHAT_EVIDENCE"}),
    "regional_manager_west": frozenset({"SALES", "OPERATIONS", "KPI_CONTRACT", "CHAT_EVIDENCE"}),
    # F-S4 (plan §1.9): a category-restricted role (North/Electronics only;
    # see data/access_control.csv), for the role-based security scenario.
    "category_manager_north_electronics": frozenset({"SALES", "MARKETING", "KPI_CONTRACT", "CHAT_EVIDENCE"}),
}


def domains_for_persona(persona: str) -> frozenset[str]:
    """Return explicit entitlements; unknown personas fail closed."""
    if not isinstance(persona, str) or not persona.strip():
        raise ValueError("Unknown persona")
    domains = _DOMAIN_ENTITLEMENTS.get(persona.strip().lower())
    if domains is None:
        raise ValueError("Unknown persona")
    return domains


def has_domain(persona: str, domain: str) -> bool:
    normalized_domain = domain.strip().upper() if isinstance(domain, str) else ""
    if normalized_domain not in DOMAINS:
        raise ValueError("Unknown domain")
    return normalized_domain in domains_for_persona(persona)


def require_domain(persona: str, domain: str) -> None:
    if not has_domain(persona, domain):
        raise PermissionError(f"Persona is not entitled to {domain.strip().upper()}.")


def retrieval_tags_for_persona(persona: str) -> list[str]:
    """Return server-owned retrieval tags; clients cannot grant themselves domains."""
    return ["public", *sorted(domain.lower() for domain in domains_for_persona(persona))]
