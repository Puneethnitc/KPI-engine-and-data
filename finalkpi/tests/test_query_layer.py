import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend import service as backend_service
from backend.service import diagnose_scope
from kpi_engine.contracts import KPIRegistry
from kpi_engine.query.catalog import SourceCatalog
from kpi_engine.contracts.metrics import ComparisonPlan, daily_values, prepare_metric_request
from kpi_engine.query import QueryCompiler, QueryRequest, QueryService, QueryValidationError, SourceCatalog, SourceCatalogEntry, SourceFieldSpec


class QueryLayerTests(unittest.TestCase):
    def test_catalog_exposes_expected_sources(self):
        catalog = SourceCatalog()
        self.assertIn("sales_daily", catalog.list_source_ids())
        self.assertIn("marketing_weekly", catalog.list_source_ids())
        self.assertIn("finance_monthly", catalog.list_source_ids())

    def test_sum_sql_compiles_with_bound_filters(self):
        compiler = QueryCompiler(SourceCatalog())
        request = QueryRequest(
            source_id="sales_daily",
            aggregation="sum",
            value_column="net_sales_revenue",
            scope={"region": "North", "category": "Electronics"},
            as_of="2023-07-25 12:00:00",
        )
        compiled = compiler.compile(request)
        self.assertIn('SUM("net_sales_revenue")', compiled.sql)
        self.assertEqual(compiled.params, ["North", "Electronics", "2023-07-25 12:00:00"])
        self.assertIn('"available_at" <= ?', compiled.sql)

    def test_ratio_sql_compiles_with_required_components(self):
        compiler = QueryCompiler(SourceCatalog())
        request = QueryRequest(
            source_id="sales_daily",
            aggregation="ratio_of_sums",
            numerator_column="orders",
            denominator_column="traffic_total",
            scope={"region": "North"},
            as_of="2023-07-25 12:00:00",
        )
        compiled = compiler.compile(request)
        self.assertIn('SUM("orders") / NULLIF(SUM("traffic_total"), 0)', compiled.sql)
        self.assertEqual(compiled.params, ["North", "2023-07-25 12:00:00"])

    def test_service_applies_as_of_and_revision_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            finance_path = Path(directory, "finance_monthly.csv")
            pd.DataFrame({
                "region": ["North", "North"],
                "category": ["Electronics", "Electronics"],
                "month_start": ["2024-01-01", "2024-01-01"],
                "month_end": ["2024-01-31", "2024-01-31"],
                "net_sales_revenue": [100.0, 150.0],
                "available_at": ["2024-01-01 00:00:00", "2024-01-05 00:00:00"],
                "revision": [1, 2],
            }).to_csv(finance_path, index=False)

            catalog = SourceCatalog()
            catalog.register_source(SourceCatalogEntry(
                source_id="finance_monthly",
                table_name="finance_monthly",
                file_path=str(finance_path),
                grain="monthly",
                date_column="month_start",
                dimensions=("region", "category"),
                availability_column="available_at",
                natural_key=("region", "category", "month_end"),
                revision_column="revision",
                fields={
                    "region": SourceFieldSpec("region", "string", True),
                    "category": SourceFieldSpec("category", "string", True),
                    "month_start": SourceFieldSpec("month_start", "date", True),
                    "month_end": SourceFieldSpec("month_end", "date", True),
                    "available_at": SourceFieldSpec("available_at", "datetime", True),
                    "net_sales_revenue": SourceFieldSpec("net_sales_revenue", "float", True),
                },
            ))
            service = QueryService(catalog)
            rows = service.load_source("finance_monthly", scope={"region": "North"}, as_of="2024-01-10 00:00:00")
            self.assertEqual(len(rows), 1)
            self.assertAlmostEqual(float(rows.iloc[0]["net_sales_revenue"]), 150.0)

    def test_compiler_rejects_missing_ratio_components(self):
        compiler = QueryCompiler(SourceCatalog())
        request = QueryRequest(
            source_id="sales_daily",
            aggregation="ratio_of_sums",
            numerator_column="orders",
            denominator_column="traffic_total",
            as_of="2023-07-25 12:00:00",
        )
        self.assertIsNotNone(compiler.compile(request).sql)

        bad = QueryRequest(
            source_id="sales_daily",
            aggregation="ratio_of_sums",
            numerator_column="orders",
            denominator_column="missing_denominator",
            as_of="2023-07-25 12:00:00",
        )
        with self.assertRaises(QueryValidationError):
            compiler.compile(bad)

    def test_service_accepts_generic_scope_and_as_of(self):
        result = diagnose_scope(
            kpis=["net_sales_revenue"],
            scope={"region": "North", "category": "Electronics"},
            target_date="2023-07-24",
            as_of="2023-07-25T12:00:00",
            persona="CFO",
        )
        self.assertIn("net_sales_revenue", result["results"])
        self.assertEqual(result["results"]["net_sales_revenue"]["as_of"], "2023-07-25T12:00:00")

    def test_service_rejects_mixed_invalid_kpis(self):
        with self.assertRaisesRegex(ValueError, "Unknown KPI ID"):
            diagnose_scope(
                kpis=["net_sales_revenue", "not_a_real_kpi"],
                scope={"region": "North", "category": "Electronics"},
                target_date="2023-07-24",
                persona="CFO",
            )

    def test_backend_scope_validation_accepts_configured_dimensions_without_hardcoded_region_category(self):
        with tempfile.TemporaryDirectory() as directory:
            registry_dir = Path(directory) / "registry"
            registry_dir.mkdir()
            (registry_dir / "channel_market_revenue.yaml").write_text(
                """schema_version: 1
kpi_id: channel_market_revenue
version: 1
definition: Channel-market revenue summary.
value_column: revenue
aggregation: sum
formula: revenue
unit: USD
grain: daily
source: channel_market_daily
dimensions: [channel, market]
materiality:
  z_threshold: 2.5
  abs_threshold: 10.0
seasonal_period: 7
min_history_periods: 30
owner: analytics
access_tags: [internal]
""".strip(),
                encoding="utf-8",
            )

            source_path = Path(directory) / "channel_market_daily.csv"
            pd.DataFrame([
                {"date": "2024-01-01", "channel": "web", "market": "NA", "revenue": 120.0, "available_at": "2024-01-01 12:00:00"},
                {"date": "2024-01-02", "channel": "web", "market": "NA", "revenue": 150.0, "available_at": "2024-01-02 12:00:00"},
                {"date": "2024-01-02", "channel": "social", "market": "NA", "revenue": 75.0, "available_at": "2024-01-02 12:00:00"},
            ]).to_csv(source_path, index=False)

            catalog_path = Path(directory) / "source_catalog.yaml"
            catalog_path.write_text(
                """sources:
  channel_market_daily:
    source_id: channel_market_daily
    table_name: channel_market_daily
    file_path: ./channel_market_daily.csv
    grain: daily
    date_column: date
    dimensions: [channel, market]
    availability_column: available_at
    natural_key: [date, channel, market]
    fields:
      date:
        type: date
        required: true
      channel:
        type: string
        required: true
      market:
        type: string
        required: true
      revenue:
        type: float
        required: true
      available_at:
        type: datetime
        required: true
""".strip(),
                encoding="utf-8",
            )

            original_registry_dir = backend_service.ENGINE_REGISTRY_DIR
            original_catalog = backend_service.SourceCatalog
            original_catalog_cls = SourceCatalog
            try:
                backend_service.ENGINE_REGISTRY_DIR = str(registry_dir)
                backend_service.SourceCatalog = lambda *args, **kwargs: original_catalog_cls(config_path=str(catalog_path))

                filters = backend_service.get_available_filters()
                self.assertIn("channel", filters["dimensions"])
                self.assertIn("market", filters["dimensions"])
                self.assertIn("web", filters["allowed_values"]["channel"])
                self.assertIn("NA", filters["allowed_values"]["market"])

                backend_service._validate_scope(
                    scope={"channel": "web", "market": "NA", "target_date": "2024-01-02"},
                    persona="CFO",
                )
            finally:
                backend_service.ENGINE_REGISTRY_DIR = original_registry_dir
                backend_service.SourceCatalog = original_catalog

    def test_service_allows_access_policy_role_instead_of_fixed_cfo_only(self):
        result = diagnose_scope(
            kpis=["net_sales_revenue"],
            scope={"region": "North", "category": "Electronics"},
            target_date="2023-07-24",
            persona="regional_manager_north",
        )
        self.assertIn("net_sales_revenue", result["results"])

    def test_configured_custom_source_supports_revision_and_restricted_scope(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "channel_daily.csv"
        catalog = SourceCatalog()
        catalog.register_source(SourceCatalogEntry(
            source_id="channel_daily",
            table_name="channel_daily",
            file_path=str(fixture),
            grain="daily",
            date_column="date",
            dimensions=("channel", "region"),
            availability_column="available_at",
            natural_key=("date", "channel", "region"),
            revision_column="revision",
            fields={
                "date": SourceFieldSpec("date", "date", True),
                "channel": SourceFieldSpec("channel", "string", True),
                "region": SourceFieldSpec("region", "string", True),
                "orders": SourceFieldSpec("orders", "float", True),
                "visits": SourceFieldSpec("visits", "float", True),
                "available_at": SourceFieldSpec("available_at", "datetime", True),
                "revision": SourceFieldSpec("revision", "int", True),
            },
        ))

        service = QueryService(catalog)
        rows = service.load_source("channel_daily", scope={"channel": "web", "region": "EMEA"}, as_of="2024-01-08 00:00:00")

        self.assertEqual(list(rows["date"].astype(str)), ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
        self.assertEqual(rows.iloc[0]["revision"], 2)
        self.assertEqual(rows.iloc[0]["orders"], 130.0)
        self.assertEqual(len(rows), 4)

        compiler = QueryCompiler(catalog)
        compiled = compiler.compile(QueryRequest(
            source_id="channel_daily",
            aggregation="ratio_of_sums",
            numerator_column="orders",
            denominator_column="visits",
            scope={"channel": "web", "region": "EMEA"},
            as_of="2024-01-08 00:00:00",
        ))
        self.assertIn('SUM("orders") / NULLIF(SUM("visits"), 0)', compiled.sql)
        self.assertEqual(compiled.params, ["web", "EMEA", "2024-01-08 00:00:00"])

    def test_catalog_supports_configured_sources_without_source_id_branching(self):
        config_path = Path(__file__).resolve().parent / "fixtures" / "source_catalog_config.yaml"
        catalog = SourceCatalog(config_path=str(config_path))

        self.assertIn("channel_daily", catalog.list_source_ids())
        source = catalog.get_source("channel_daily")
        self.assertEqual(source.dimensions, ("channel", "region"))
        self.assertEqual(source.natural_key, ("date", "channel", "region"))
        self.assertEqual(source.date_column, "date")
        self.assertEqual(source.availability_column, "available_at")
        self.assertEqual(source.grain, "daily")
        self.assertEqual(source.revision_column, "revision")

        service = QueryService(catalog)
        rows = service.load_source("channel_daily", scope={"channel": "web", "region": "EMEA"}, as_of="2024-01-08 00:00:00")
        self.assertEqual(len(rows), 4)

        prepared = service.prepare_metric(QueryRequest(
            source_id="channel_daily",
            aggregation="ratio_of_sums",
            numerator_column="orders",
            denominator_column="visits",
            scope={"channel": "web", "region": "EMEA"},
            as_of="2024-01-08 00:00:00",
        ))
        self.assertGreater(len(prepared.rows), 0)
        self.assertIn("metric_value", prepared.rows[0])

    def test_prepare_metric_matches_daily_values_for_registered_kpis(self):
        registry = KPIRegistry("./kpi_engine/registry")
        catalog = SourceCatalog()
        service = QueryService(catalog)

        for kpi_id in registry.list_ids():
            contract = registry.get(kpi_id)
            source = catalog.get_source(contract.source)
            frame = pd.read_csv(source.file_path)

            scope = {}
            if "region" in frame.columns:
                region_values = list(frame["region"].astype(str).dropna().unique())
                if region_values:
                    scope["region"] = region_values[0]
            if "category" in frame.columns:
                category_values = list(frame["category"].astype(str).dropna().unique())
                if category_values:
                    scope["category"] = category_values[0]

            filtered = frame.copy()
            for key, value in scope.items():
                filtered = filtered[filtered[key].astype(str) == str(value)]

            as_of = pd.Timestamp(filtered[source.availability_column].max()).strftime("%Y-%m-%d %H:%M:%S")
            request = QueryRequest(
                source_id=contract.source,
                aggregation=contract.aggregation,
                value_column=contract.value_column,
                numerator_column=contract.numerator_column,
                denominator_column=contract.denominator_column,
                weight_column=contract.weight_column,
                scope=scope,
                as_of=as_of,
            )
            prepared = service.prepare_metric(request)

            self.assertGreater(len(prepared.rows), 0)
            self.assertIn("metric_value", prepared.rows[0])
            self.assertIn("SUM(", prepared.query.sql) if contract.aggregation == "sum" else True
            self.assertIn("AVG(", prepared.query.sql) if contract.aggregation == "mean" else True
            self.assertIn("SUM(", prepared.query.sql) if contract.aggregation == "weighted_mean" else True
            self.assertIn("SUM(", prepared.query.sql) if contract.aggregation == "ratio_of_sums" else True

            actual = pd.Series(
                {
                    pd.Timestamp(row[source.date_column]).normalize(): float(row["metric_value"])
                    for row in prepared.rows
                }
            ).sort_index()
            expected = daily_values(filtered, contract).sort_index()
            expected.index = pd.to_datetime(expected.index)
            pd.testing.assert_series_equal(actual, expected.rename(contract.kpi_id), check_names=False)

    def test_prepared_metric_request_reuses_one_comparison_plan(self):
        registry = KPIRegistry("./kpi_engine/registry")
        contract = registry.get("net_sales_revenue")
        frame = pd.read_csv("./data/sales_daily.csv")
        target = pd.Timestamp("2023-02-15")
        filtered = frame[frame["region"].eq("North") & frame["category"].eq("Electronics")].copy()
        prepared = prepare_metric_request(filtered, contract, target)

        self.assertIsInstance(prepared.comparison, ComparisonPlan)
        self.assertEqual(prepared.comparison.target_date, target.normalize())
        self.assertTrue((prepared.comparison.baseline_frame["date"] < target).all())
        self.assertTrue((prepared.comparison.current_frame["date"] == target).all())
        self.assertEqual(prepared.series.name, contract.kpi_id)


if __name__ == "__main__":
    unittest.main()
