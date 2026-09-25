# KPI contracts

## Next implementation

Read [the handoff](../IMPLEMENTATION_HANDOFF.md) and [query plan](../duckdb/README.md).
`models.py` owns typed semantic validation; `registry.py` owns loading/versioning;
`metrics.py` is the current pandas calculation reference; `__init__.py` exposes
the public imports. Keep those responsibilities while introducing structured
calculation/source/coverage/comparison policies. A schema version is separate from
a metric's business version. `formula` remains descriptive today. Do not add new
YAML fields until the loader/model/compiler support and validate them together.

Acceptance: current contracts migrate without numerical drift; bad types, nested
unknown keys, non-finite thresholds, unsupported capabilities and missing source
fields fail explicitly. Check partial-null ratio populations and temporal rollups.

Contracts are YAML-backed semantic definitions, loaded by `registry.py`. Each contract states a KPI's source column, aggregation, unit, temporal grain, thresholds, dimensions, access tags, decomposition inputs, reconciliation policy, and candidate-driver metadata.

`metrics.py` calculates daily KPI values using the contract. In particular, `ratio_of_sums` calculates a rate from summed numerator and denominator values; it must not average row-level rates. The registry rejects duplicate YAML keys, unknown fields, duplicate IDs, and files whose names do not match their KPI IDs.
