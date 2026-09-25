# HANDOFF: public detector exports. Preserve imports and abstention states while
# consumers transition from raw frames to prepared metric series.

"""KPI movement detection with explicit abstention states."""

from kpi_engine.detection.models import MovementAssessment
from kpi_engine.detection.ensemble import AnomalyDetector

__all__ = ["AnomalyDetector", "MovementAssessment"]
