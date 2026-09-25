# HANDOFF: public verification exports. Keep explicit design/result boundaries
# and compatibility imports stable when adding resolved policies and query inputs.

"""Conservative observational verification of declared event designs."""

from kpi_engine.verification.did import CausalVerifier
from kpi_engine.verification.models import (
    CausalVerificationResult, VerificationDesign, VerificationSensitivityResult,
)

__all__ = ["CausalVerifier", "CausalVerificationResult", "VerificationDesign",
           "VerificationSensitivityResult"]
