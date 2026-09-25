# Detection methods

## Next implementation

Use one prepared metric series and a shared comparison plan from the proposed
[query service](../duckdb/README.md). `robust.py` owns the primary movement score;
`seasonal.py` owns forecast evidence; `ensemble.py` owns the decision policy;
`models.py` owns output semantics; `__init__.py` preserves public imports.
Externalize business policy defaults and record resolved settings. Mathematical
normalization constants stay with their algorithms. Define static-baseline,
unit-aware scale and missing-calendar policies before expanding supported data.

Acceptance: no future-data fitting, unchanged existing decision policy, explicit
abstentions, consistent detector/bridge baseline, and raw-versus-display precision.
Threshold quality needs independent holdout evaluation beyond SQL parity.

`robust.py` uses a prior-history rolling robust baseline to score point anomalies and sustained shifts. `seasonal.py` uses a prior-history-only MSTL/STL weekly seasonal forecast and a 21-step walk-forward error scale. `ensemble.py` retains both results and labels their agreement.

The robust branch is the current provisional material-alert policy. A seasonal-only signal is marked for review and does not automatically start diagnosis. Both branches explicitly abstain for missing targets, insufficient history, or invalid/scarce baselines.
