# Observational verification

## Next implementation

`models.py` owns explicit event designs and evidence results; `did.py` owns the
observational method and sensitivity helper; `__init__.py` owns public imports.
Resolve window lengths, confidence level, HAC lag and placebo/pretrend thresholds
from a shared policy also used by `../confidence.py`. Obtain authorized, complete
series through the [query service](../duckdb/README.md); authorize every sensitivity
design, not just the first one. Persist design provenance if claiming predeclaration.

Acceptance: deny unauthorized controls; preserve temporal/coverage/exposure gates;
record all sensitivity outcomes; label effects with units and averaging periods.
Passing checks remains conditional observational support, not proved causation.

`did.py` implements a cautious difference-in-differences (DiD) check, not a causal proof model. A `VerificationDesign` must predeclare treated and authorized control slices, dates, driver direction, outcome direction, quiet windows, and sufficient pre/post coverage.

The verifier checks exposure, temporal ordering, pretrends, HAC confidence intervals, and placebos. It returns `SUPPORTED_CONDITIONAL`, `INCONCLUSIVE`, or an explicit abstention reason. `verify_sensitivity` reports every predeclared design rather than selecting a favourable control.
