"""Governed registry of server-authorized causal verification designs."""

from typing import Dict, Optional, Tuple
from kpi_engine.verification.models import VerificationDesign

# Server-authorized predeclared event designs.
# Clients cannot supply arbitrary slices to bypass authorization; they can only
# trigger server-governed designs for authorized target windows.
GOVERNED_DESIGNS: Dict[Tuple[str, str, str, str], VerificationDesign] = {}


def resolve_governed_design(
    kpi_id: str,
    target_date: str,
    region: Optional[str] = None,
    category: Optional[str] = None,
    design_id: Optional[str] = None,
) -> Optional[VerificationDesign]:
    """Resolve a server-authorized verification design.
    
    Arbitrary client-submitted designs are rejected; only server-governed
    predeclared designs can be resolved.
    """
    key = (kpi_id, target_date, region or "ALL", category or "ALL")
    if key in GOVERNED_DESIGNS:
        return GOVERNED_DESIGNS[key]
    
    for (g_kpi, g_date, g_reg, g_cat), design in GOVERNED_DESIGNS.items():
        if g_kpi == kpi_id and g_date == target_date:
            if (g_reg == "ALL" or g_reg == region) and (g_cat == "ALL" or g_cat == category):
                return design
    return None
