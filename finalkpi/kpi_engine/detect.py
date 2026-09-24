"""Compatibility import for the detector now housed in ``kpi_engine.detection``."""

from kpi_engine.detection import AnomalyDetector, MovementAssessment

__all__ = ["AnomalyDetector", "MovementAssessment"]
