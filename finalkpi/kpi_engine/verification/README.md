# Observational verification

`did.py` implements a cautious difference-in-differences (DiD) check, not a causal proof model. A `VerificationDesign` must predeclare treated and authorized control slices, dates, driver direction, outcome direction, quiet windows, and sufficient pre/post coverage.

The verifier checks exposure, temporal ordering, pretrends, HAC confidence intervals, and placebos. It returns `SUPPORTED_CONDITIONAL`, `INCONCLUSIVE`, or an explicit abstention reason. `verify_sensitivity` reports every predeclared design rather than selecting a favourable control.
