# HANDOFF: compatibility facade for verification/. Keep these public symbols
# stable; future policy/query changes belong in verification, not this module.
# Do not restore the removed positional API with fabricated uncertainty.

"""Compatibility imports for the explicit-design verification package.

The previous positional verify_cause API silently passed missing pretrend and
placebo data and used a fabricated confidence interval. It is intentionally
not retained; callers must supply a VerificationDesign.
"""

from kpi_engine.verification import CausalVerifier, CausalVerificationResult, VerificationDesign

__all__ = ["CausalVerifier", "CausalVerificationResult", "VerificationDesign"]
