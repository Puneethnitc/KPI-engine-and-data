"""Small JSON bridge for the mentor-demo frontend.

This runs the existing engine unchanged. It intentionally returns its evidence
verdicts instead of fabricating dashboard-friendly confidence or causal claims.
"""

import argparse
import json

from run_full_demo import run


KPI_IDS = (
    "net_sales_revenue",
    "orders",
    "units_sold",
    "traffic_total",
    "conversion_rate",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kpi", choices=(*KPI_IDS, "all"), default="all")
    parser.add_argument("--date", default="2023-07-24")
    parser.add_argument("--region", default="North")
    parser.add_argument("--category", default="Electronics")
    args = parser.parse_args()

    selected = KPI_IDS if args.kpi == "all" else (args.kpi,)
    results = {
        kpi_id: run(
            kpi_id=kpi_id,
            target_date=args.date,
            region=args.region,
            category=args.category,
            persona="CFO",
        )
        for kpi_id in selected
    }
    print(json.dumps({"results": results}, allow_nan=False))


if __name__ == "__main__":
    main()
