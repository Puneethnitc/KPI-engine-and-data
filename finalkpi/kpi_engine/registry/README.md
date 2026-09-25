# Installed KPI definitions

## Next implementation

The comments in each YAML explain authoritative inputs, assumptions and edge cases.
They add no new executable fields. Work with `../contracts/` before changing the
schema; the existing loader rejects unknown top-level fields. Read
[the handoff](../IMPLEMENTATION_HANDOFF.md) for versioning and policy ownership.

| Contract | Preserve | Clarify next |
| --- | --- | --- |
| `net_sales_revenue.yaml` | Recorded revenue, exact quantity/rate bridge | Currency/refunds, rate naming, comparison and reconciliation tolerances |
| `orders.yaml` | Recorded orders and traffic-derived bridge rate | Fractional counts, cancellation/zero-traffic policy |
| `conversion_rate.yaml` | Ratio of sums at every rollup | Paired missing-input policy, denominator validity, fraction vs percentage-point display |
| `units_sold.yaml` | Source units, optional capabilities absent | Returns/sign rules and complete slice coverage |
| `traffic_total.yaml` | Source traffic totals | Additivity/overlap across channels and missing versus zero |

Acceptance: a new KPI using implemented operators needs only validated metadata,
not Python/UI allowlist edits. Unsupported calculations must fail explicitly.

Each YAML file is one installed KPI contract. The current registry contains five primary diagnosis paths: revenue, orders, units sold, total traffic, and conversion rate. A contract is governed metadata, not executable SQL and not an automatic guarantee that every declared source/grain is implemented by the public pipeline.
