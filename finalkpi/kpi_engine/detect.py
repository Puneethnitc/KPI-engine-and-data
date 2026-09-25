# HANDOFF: compatibility facade; the actual detector is detection/ensemble.py.
# Preserve this import path during the data-layer migration. Do not duplicate
# logic here or remove it until callers/tests have deliberately migrated.

"""Compatibility import for the detector now housed in ``kpi_engine.detection``."""

from kpi_engine.detection import AnomalyDetector, MovementAssessment

__all__ = ["AnomalyDetector", "MovementAssessment"]
