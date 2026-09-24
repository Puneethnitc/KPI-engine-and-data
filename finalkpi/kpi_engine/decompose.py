import pandas as pd
import numpy as np
from itertools import permutations
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

@dataclass
class DecompositionResult:
    kpi_id: str
    total_delta: float
    volume_effect: float
    price_effect: float
    mix_effect: float
    residual: float
    is_identity_held: bool  # True if volume + price + mix == total_delta (Zero Residual)

class DeterministicDecomposer:
    """Stage 3: Deterministic Price-Volume-Mix (PVM) Structural Decomposition.
    Decomposes multi-segment revenue shifts into Volume, Price, and Mix effects with
    a strict zero-residual assertion.
    """

    @staticmethod
    def decompose_revenue(
        units_t0: float,
        units_t1: float,
        aov_t0: float,
        aov_t1: float,
        kpi_id: str = "net_sales_revenue"
    ) -> DecompositionResult:
        """2-Factor Symmetric Price-Volume Decomposition (Single Segment Fallback)."""
        rev_t0 = units_t0 * aov_t0
        rev_t1 = units_t1 * aov_t1
        total_delta = rev_t1 - rev_t0

        avg_price = 0.5 * (aov_t0 + aov_t1)
        avg_units = 0.5 * (units_t0 + units_t1)

        volume_effect = (units_t1 - units_t0) * avg_price
        price_effect = (aov_t1 - aov_t0) * avg_units
        mix_effect = 0.0

        calculated_total = volume_effect + price_effect
        residual = abs(total_delta - calculated_total)
        is_identity_held = residual < 1e-4

        # Balance the displayed rounding penny in the second effect. The raw
        # identity is checked above; the published two-decimal bridge must also
        # add exactly to its published total.
        shown_total = round(total_delta, 2)
        shown_volume = round(volume_effect, 2)
        shown_price = round(shown_total - shown_volume, 2)
        return DecompositionResult(
            kpi_id=kpi_id,
            total_delta=shown_total,
            volume_effect=shown_volume,
            price_effect=shown_price,
            mix_effect=round(mix_effect, 2),
            residual=round(residual, 4),
            is_identity_held=is_identity_held
        )

    @staticmethod
    def decompose_product_by_segments(
        base: pd.DataFrame,
        current: pd.DataFrame,
        kpi_id: str,
    ) -> DecompositionResult:
        """Exact, order-independent quantity/mix/rate bridge.

        Inputs have one row per segment and columns `segment`, `quantity`,
        `value`. A missing segment inherits its observed rate from the other
        period, so a launch/exit is mix rather than a fabricated rate change.
        """
        required = {"segment", "quantity", "value"}
        if not required.issubset(base) or not required.issubset(current):
            raise ValueError("Segment bridge requires segment, quantity, and value")
        if base.empty or current.empty:
            raise ValueError("Segment bridge requires both periods")
        if base["segment"].duplicated().any() or current["segment"].duplicated().any():
            raise ValueError("Segment bridge requires unique segment keys")
        for period in (base, current):
            if period["segment"].isna().any():
                raise ValueError("Segment bridge keys cannot be null")
            for column in ("quantity", "value"):
                values = pd.to_numeric(period[column], errors="raise")
                if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
                    raise ValueError("Segment bridge inputs must be finite")
        merged = base.merge(current, on="segment", how="outer", suffixes=("_0", "_1"))
        for column in ("quantity_0", "quantity_1", "value_0", "value_1"):
            merged[column] = merged[column].fillna(0.0).astype(float)
            if not np.isfinite(merged[column]).all():
                raise ValueError("Segment bridge values must be finite")
        q0 = merged["quantity_0"].to_numpy()
        q1 = merged["quantity_1"].to_numpy()
        v0 = merged["value_0"].to_numpy()
        v1 = merged["value_1"].to_numpy()
        if (q0 < 0).any() or (q1 < 0).any():
            raise ValueError("Segment bridge quantities cannot be negative")
        if (((q0 == 0) & (np.abs(v0) > 1e-9)) |
                ((q1 == 0) & (np.abs(v1) > 1e-9))).any():
            raise ValueError("Nonzero value with zero quantity has no valid rate")
        active_segments = (q0 > 0) | (q1 > 0)
        q0, q1 = q0[active_segments], q1[active_segments]
        v0, v1 = v0[active_segments], v1[active_segments]
        total_q0, total_q1 = float(q0.sum()), float(q1.sum())
        if total_q0 <= 0:
            raise ValueError("Segment bridge needs a positive baseline quantity")

        r0 = np.divide(v0, q0, out=np.full_like(v0, np.nan), where=q0 > 0)
        r1 = np.divide(v1, q1, out=np.full_like(v1, np.nan), where=q1 > 0)
        r0 = np.where(np.isnan(r0), r1, r0)
        r1 = np.where(np.isnan(r1), r0, r1)
        shares = (q0 / total_q0, q1 / total_q1 if total_q1 > 0 else q0 / total_q0)
        rates = (r0, r1)
        quantities = (total_q0, total_q1)

        def value(active: frozenset[str]) -> float:
            return float(quantities["quantity" in active] * np.dot(
                shares["mix" in active], rates["rate" in active]
            ))

        effects = {name: 0.0 for name in ("quantity", "mix", "rate")}
        for order in permutations(effects):
            active: frozenset[str] = frozenset()
            for name in order:
                next_active = active | {name}
                effects[name] += (value(next_active) - value(active)) / 6.0
                active = next_active

        total_delta = float(v1.sum() - v0.sum())
        raw_residual = total_delta - sum(effects.values())
        if abs(raw_residual) > 1e-6:
            raise ValueError("Segment decomposition does not reconcile")
        shown_total = round(total_delta, 2)
        shown_quantity = round(effects["quantity"], 2)
        shown_mix = round(effects["mix"], 2)
        shown_rate = round(shown_total - shown_quantity - shown_mix, 2)
        return DecompositionResult(
            kpi_id=kpi_id, total_delta=shown_total,
            volume_effect=shown_quantity, mix_effect=shown_mix,
            price_effect=shown_rate, residual=round(abs(raw_residual), 6),
            is_identity_held=True,
        )

    def decompose_pvm_multi_segment(
        self,
        segment_data_t0: List[Dict[str, float]],
        segment_data_t1: List[Dict[str, float]],
        kpi_id: str = "net_sales_revenue"
    ) -> DecompositionResult:
        """Legacy input shape; use the same symmetric bridge as the pipeline."""
        def adapt(rows: List[Dict[str, float]]) -> pd.DataFrame:
            frame = pd.DataFrame(rows)
            required = {"segment", "units", "aov"}
            if not required.issubset(frame):
                raise ValueError("Legacy segment rows require segment, units, and aov")
            return pd.DataFrame({
                "segment": frame["segment"],
                "quantity": frame["units"],
                "value": frame["units"] * frame["aov"],
            })

        return self.decompose_product_by_segments(
            adapt(segment_data_t0), adapt(segment_data_t1), kpi_id
        )
