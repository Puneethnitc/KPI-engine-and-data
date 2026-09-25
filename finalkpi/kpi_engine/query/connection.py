from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb
import pandas as pd

from kpi_engine.query.models import SourceCatalogEntry


class DuckDBConnection:
    """Small, bounded DuckDB connection wrapper for catalog-backed source queries."""

    def __init__(
        self,
        database: str | Path = ":memory:",
        *,
        memory_limit: str = "256MB",
        threads: int = 1,
        read_only: bool = False,
    ):
        self.database = str(database)
        self.memory_limit = memory_limit
        self.threads = max(1, int(threads))
        self.read_only = read_only
        self._conn: duckdb.DuckDBPyConnection | None = None

    def open(self) -> "DuckDBConnection":
        if self._conn is None:
            self._conn = duckdb.connect(database=self.database, read_only=self.read_only)
            self._conn.execute(f"SET memory_limit = '{self.memory_limit}'")
            self._conn.execute(f"SET threads = {self.threads}")
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "DuckDBConnection":
        return self.open()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @staticmethod
    def _safe_identifier(name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
        if not cleaned:
            raise ValueError("Source table names must contain a valid identifier")
        if cleaned[0].isdigit():
            cleaned = f"_{cleaned}"
        return cleaned

    @staticmethod
    def _resolve_source_path(path: str | Path) -> Path:
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = (Path.cwd() / resolved).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Catalog source does not exist: {resolved}")
        return resolved

    @staticmethod
    def _sql_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def register_frame(self, table_name: str, frame: Any) -> str:
        self.open()
        assert self._conn is not None

        normalized = frame.copy()
        for column in normalized.columns:
            dtype = normalized[column].dtype
            if isinstance(dtype, pd.StringDtype) or pd.api.types.is_string_dtype(dtype):
                normalized[column] = normalized[column].astype(object)

        safe_name = self._safe_identifier(table_name)
        self._conn.execute(f"DROP TABLE IF EXISTS {safe_name}")
        self._conn.execute(f"DROP VIEW IF EXISTS {safe_name}")
        self._conn.register(safe_name, normalized)
        return safe_name

    def register_source(self, source: SourceCatalogEntry) -> str:
        if not isinstance(source, SourceCatalogEntry):
            raise TypeError("register_source expects a SourceCatalogEntry")

        self.open()
        assert self._conn is not None

        source_path = self._resolve_source_path(source.file_path)
        table_name = self._safe_identifier(source.table_name)
        source_sql = self._sql_literal(str(source_path))
        lower_path = source_path.suffix.lower()

        self._conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        self._conn.execute(f"DROP VIEW IF EXISTS {table_name}")

        if lower_path == ".csv":
            self._conn.execute(
                f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM read_csv_auto({source_sql}, header = true)",
            )
        elif lower_path == ".parquet":
            self._conn.execute(
                f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM read_parquet({source_sql})",
            )
        else:
            raise ValueError(f"Unsupported catalog source format for {source.source_id}: {source_path.suffix}")

        return table_name

    def register_catalog_sources(self, sources: Iterable[SourceCatalogEntry]) -> list[str]:
        registered: list[str] = []
        for source in sources:
            registered.append(self.register_source(source))
        return registered

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
        self.open()
        assert self._conn is not None
        query_params = tuple(params) if params is not None else ()
        return self._conn.execute(sql, query_params).fetchall()

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        self.open()
        assert self._conn is not None
        return self._conn
