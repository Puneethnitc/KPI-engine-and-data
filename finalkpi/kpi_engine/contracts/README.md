# KPI contracts

Contracts are YAML-backed semantic definitions, loaded by `registry.py`. Each contract states a KPI's source column, aggregation, unit, temporal grain, thresholds, dimensions, access tags, decomposition inputs, reconciliation policy, and candidate-driver metadata.

`metrics.py` calculates daily KPI values using the contract. In particular, `ratio_of_sums` calculates a rate from summed numerator and denominator values; it must not average row-level rates. The registry rejects duplicate YAML keys, unknown fields, duplicate IDs, and files whose names do not match their KPI IDs.
