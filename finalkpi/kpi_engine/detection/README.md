# Detection methods

`robust.py` uses a prior-history rolling robust baseline to score point anomalies and sustained shifts. `seasonal.py` uses a prior-history-only MSTL/STL weekly seasonal forecast and a 21-step walk-forward error scale. `ensemble.py` retains both results and labels their agreement.

The robust branch is the current provisional material-alert policy. A seasonal-only signal is marked for review and does not automatically start diagnosis. Both branches explicitly abstain for missing targets, insufficient history, or invalid/scarce baselines.
