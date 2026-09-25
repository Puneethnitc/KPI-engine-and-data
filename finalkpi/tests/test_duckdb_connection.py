import csv
import tempfile
import unittest
from pathlib import Path

from kpi_engine.query.connection import DuckDBConnection
from kpi_engine.query.models import SourceCatalogEntry


class DuckDBConnectionTests(unittest.TestCase):
    def test_register_csv_source_can_execute_select(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "sales_test.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["date", "region", "category", "available_at", "net_sales_revenue"])
                writer.writerow(["2023-01-01", "North", "Electronics", "2023-01-02T00:00:00", "100.0"])
                writer.writerow(["2023-01-02", "North", "Electronics", "2023-01-03T00:00:00", "200.0"])
                writer.writerow(["2023-01-01", "South", "Electronics", "2023-01-02T00:00:00", "75.0"])

            source = SourceCatalogEntry(
                source_id="sales_test",
                table_name="sales_test",
                file_path=str(csv_path),
                grain="daily",
                date_column="date",
                dimensions=("region", "category"),
                availability_column="available_at",
                natural_key=("date", "region", "category"),
                fields={
                    "date": {"name": "date"},
                    "region": {"name": "region"},
                    "category": {"name": "category"},
                    "available_at": {"name": "available_at"},
                    "net_sales_revenue": {"name": "net_sales_revenue"},
                },
            )

            connection = DuckDBConnection()
            try:
                connection.register_source(source)
                rows = connection.query(
                    "SELECT region, SUM(net_sales_revenue) AS total FROM sales_test WHERE region = ? GROUP BY region ORDER BY region",
                    ("North",),
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], "North")
                self.assertAlmostEqual(rows[0][1], 300.0)
            finally:
                connection.close()

    def test_register_parquet_source_can_execute_select(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            parquet_path = Path(tmpdir) / "marketing_test.parquet"
            connection = DuckDBConnection()
            try:
                source_table = connection.connection
                source_table.execute(
                    "CREATE TABLE marketing_test AS SELECT 'North' AS region, 'Electronics' AS category, 25.0 AS marketing_spend, '2023-01-02T00:00:00' AS available_at"
                )
                quoted_path = str(parquet_path).replace("'", "''")
                source_table.execute(
                    f"COPY marketing_test TO '{quoted_path}' (FORMAT PARQUET)",
                )

                source = SourceCatalogEntry(
                    source_id="marketing_test",
                    table_name="marketing_test",
                    file_path=str(parquet_path),
                    grain="daily",
                    date_column="available_at",
                    dimensions=("region", "category"),
                    availability_column="available_at",
                    natural_key=("region", "category"),
                    fields={
                        "region": {"name": "region"},
                        "category": {"name": "category"},
                        "marketing_spend": {"name": "marketing_spend"},
                        "available_at": {"name": "available_at"},
                    },
                )

                connection.register_source(source)
                rows = connection.query(
                    "SELECT region, SUM(marketing_spend) AS total FROM marketing_test GROUP BY region ORDER BY region"
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], "North")
                self.assertAlmostEqual(rows[0][1], 25.0)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
