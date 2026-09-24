"""Use robust movement for provisional alerts; retain seasonal review evidence."""

from kpi_engine.detection.robust import RobustBaselineDetector
from kpi_engine.detection.seasonal import SeasonalForecastDetector


class AnomalyDetector:
    def __init__(self):
        self.robust = RobustBaselineDetector()
        self.seasonal = SeasonalForecastDetector()

    def evaluate_movement(self, df, kpi_contract, target_date, dimension_slice=None,
                          metric_col="net_sales_revenue", window_days=30):
        robust = self.robust.evaluate_movement(
            df, kpi_contract, target_date, dimension_slice, metric_col, window_days
        )
        robust.robust_is_material = robust.is_material
        if robust.status != "OK":
            return robust
        seasonal = self.seasonal.evaluate(
            df, kpi_contract, target_date, dimension_slice
        )
        robust.seasonal_status = seasonal.status
        robust.seasonal_score = seasonal.score
        robust.seasonal_expected = seasonal.expected
        robust.seasonal_is_material = seasonal.is_material
        robust.seasonal_calibration_count = seasonal.calibration_count
        robust.detector_agreement = (
            "BOTH" if robust.robust_is_material and seasonal.is_material else
            "ROBUST_ONLY" if robust.robust_is_material else
            "SEASONAL_ONLY" if seasonal.is_material else "NEITHER"
        )
        # A seasonal-only hit is evidence to review, not an automatic alert.
        # The prior OR rule sent unvalidated seasonal flags into diagnosis.
        robust.is_material = robust.robust_is_material
        robust.method = "robust_plus_mstl_forecast"
        return robust
