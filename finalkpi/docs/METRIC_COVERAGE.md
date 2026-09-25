# Metric coverage

The dataset has several numeric columns, but a numeric column is not automatically a KPI. The engine diagnoses only a versioned KPI contract in `kpi_engine/registry/` because the contract supplies its aggregation, unit, materiality threshold, ownership, access scope, and allowed evidence sources.

## Installed diagnosis paths

| KPI | Source calculation | Engine result on 2023-07-24, North/Electronics |
| --- | --- | --- |
| `net_sales_revenue` | Daily sum of net sales revenue | Material movement; cause unverified |
| `orders` | Daily sum of orders | Material movement; cause unverified |
| `traffic_total` | Daily sum of total traffic | Material movement; cause unverified |
| `units_sold` | Daily sum of units | No material movement |
| `conversion_rate` | Sum(orders) / sum(traffic), never an average of displayed rates | No material movement |

All five paths returned grounded narratives in the checked scenario. This confirms that the engine supports five installed KPI definitions, not every numeric column in the CSVs.

## Fields that are intentionally not standalone KPIs

`lost_units_stockout`, `aov`, `stock_availability`, `checkout_latency_ms`, `traffic_online`, `traffic_instore`, `traffic_wholesale`, `price_discount_depth`, `weather_temp_c`, and `competitor_price_index` are currently driver, decomposition, or contextual inputs. Marketing and finance files also contain supporting measurements rather than installed primary KPIs.

To add a sixth KPI safely, create a contract with an explicit business definition, source/grain, aggregation, unit, materiality policy, ownership, access tags, and tests. The current public pipeline supports only daily `sales_daily` primary KPI paths; registering a weekly, monthly, or other-source KPI alone is deliberately rejected until its native pipeline path exists.
