# IMPLEMENTATION HANDOFF — local scope guard
# Current: a CSV maps supplied roles to region/category permissions; this is not
# authenticated identity or database row security. Contract access_tags are not
# enforced here. The pipeline checks access before loading diagnostic sources.
# Next: resolve an explicit allowed scope and apply it to all query-service reads,
# including metadata, evidence, saved runs and controls. Keep local role config
# for the prototype, but do not treat client-provided tags as proof of access.
# Fix omitted-category semantics: a category-restricted row currently permits
# category=None, which then allows the pipeline to include every category.
# Check: omitted dimensions cannot broaden scope, and inaccessible control/data
# rows never reach narratives. Do not add an authentication project in this pass.

import pandas as pd
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class AccessDecision:
    allowed: bool
    reason: str
    matched_role: Optional[str] = None


class AccessController:
    """Row-level security gate, built against the *actual* access_control.csv
    schema: columns are (region, owner_role, can_view_categories) -- there is
    no persona/kpi_id column, so a persona is checked by matching it against
    owner_role (e.g. persona='regional_manager_north' or persona='cfo'), and
    the requested region/category from dimension_slice is checked against
    that role's row.
    """

    def __init__(self, access_csv_path: str):
        self.df = pd.read_csv(access_csv_path)

    def check(self, persona: str, dimension_slice: Optional[Dict[str, str]]) -> AccessDecision:
        if not persona:
            return AccessDecision(allowed=False, reason="No persona/role supplied.")

        persona_norm = persona.strip().lower()
        matches = self.df[self.df['owner_role'].str.lower() == persona_norm]

        if matches.empty:
            return AccessDecision(
                allowed=False,
                reason=f"Role '{persona}' is not registered in access_control.csv."
            )

        requested_region = (dimension_slice or {}).get("region")
        requested_category = (dimension_slice or {}).get("category")

        # An unrestricted request is only valid for an explicitly all-region
        # role. Otherwise a manager could omit the region and read all rows.
        if requested_region is None and not (matches['region'] == 'ALL').any():
            return AccessDecision(
                allowed=False,
                reason="A region is required for this role.",
            )

        if requested_category is None and not (matches['can_view_categories'] == 'ALL').any():
            return AccessDecision(
                allowed=False,
                reason="A category is required for this role.",
            )

        for _, row in matches.iterrows():
            region_ok = (
                requested_region is None
                or row['region'] == 'ALL'
                or row['region'] == requested_region
            )
            category_ok = (
                requested_category is None
                or row['can_view_categories'] == 'ALL'
                or row['can_view_categories'] == requested_category
            )
            if region_ok and category_ok:
                return AccessDecision(allowed=True, reason="Access granted.", matched_role=row['owner_role'])

        return AccessDecision(
            allowed=False,
            reason=(
                f"Role '{persona}' is not entitled to region="
                f"'{requested_region}', category='{requested_category}'."
            )
        )
