"""Governed registry of server-authorized causal verification designs."""

from typing import Dict, Optional, Tuple
from kpi_engine.verification.models import VerificationDesign

# Server-authorized predeclared event designs.
# Clients cannot supply arbitrary slices to bypass authorization; they can only
# trigger server-governed designs for authorized target windows.
GOVERNED_DESIGNS: Dict[Tuple[str, str, str, str], VerificationDesign] = {
    # Key: (kpi_id, target_date, region, category)
    # Stage 1 (plan §1.8, F-V1): the old traffic_drop design is deleted --
    # traffic_drop was removed as a driver (F-R2) and this design could never
    # succeed anyway (its Saturday-adjacent dates never lined up with a
    # governed Monday treatment start). The marketing design is corrected to
    # the real cut date (2023-07-17, a Monday) with the current driver id;
    # South remains the control for now even though it ran its own campaign
    # (F-V2) -- Stage 5 replaces this whole registry with auto-generated,
    # control-validated designs.
    ("net_sales_revenue", "2023-08-13", "North", "Electronics"): VerificationDesign(
        driver_id="marketing_spend",
        treated_slice={"region": "North", "category": "Electronics"},
        control_slice={"region": "South", "category": "Electronics"},
        pre_start="2023-06-05",
        treatment_start="2023-07-17",
        post_end="2023-08-13",
        quiet_windows=(("2023-04-01", "2023-04-14"), ("2023-05-01", "2023-05-14")),
        expected_driver_direction=-1,
        expected_outcome_direction=-1,
    ),
}


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
