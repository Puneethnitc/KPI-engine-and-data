"""Governed registry of server-authorized causal verification designs."""

from typing import Dict, Optional, Tuple
from kpi_engine.verification.models import VerificationDesign

# Server-authorized predeclared event designs.
# Clients cannot supply arbitrary slices to bypass authorization; they can only
# trigger server-governed designs for authorized target windows.
GOVERNED_DESIGNS: Dict[Tuple[str, str, str, str], VerificationDesign] = {
    # Key: (kpi_id, target_date, region, category)
    # Stage 1 (plan §1.8, F-V1): the old traffic_drop design (keyed at
    # 2023-08-06) is deleted outright, simply because traffic_drop was
    # removed as a driver entirely (F-R2, F-R4 mechanical-component guard) --
    # it is no longer a declared driver for any KPI, so no design can
    # reference it. The other original design (ad_spend_drop,
    # treatment_start 2023-07-01, a Saturday) is corrected below instead of
    # deleted: it now uses the current driver id and a real Monday treatment
    # start (2023-07-17). South remains the control for now even though it
    # ran its own campaign (F-V2) -- Stage 5 replaces this whole registry
    # with auto-generated, control-validated designs.
    # The key's target_date must be a date where the movement is actually
    # material for this slice (run_diagnosis only reaches the causal step
    # when assessment.is_material). Re-keyed again for the Stage 2 review's
    # log-residual scoring fix: 2023-08-06 stopped being material once
    # scoring moved from a pooled absolute-residual MAD to a log-ratio one
    # (F-D3); 2023-07-25 (also this dataset's "material-multi-driver" demo
    # date) is material under the corrected scoring.
    ("net_sales_revenue", "2023-07-25", "North", "Electronics"): VerificationDesign(
        driver_id="marketing_spend",
        treated_slice={"region": "North", "category": "Electronics"},
        control_slice={"region": "South", "category": "Electronics"},
        pre_start="2023-06-05",
        treatment_start="2023-07-17",
        post_end="2023-07-25",
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
