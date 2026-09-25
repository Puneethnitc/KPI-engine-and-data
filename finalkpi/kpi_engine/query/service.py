from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from kpi_engine.query.catalog import SourceCatalog
from kpi_engine.query.compiler import QueryCompiler
from kpi_engine.query.connection import DuckDBConnection
from kpi_engine.query.models import CompiledQuery, PreparedSeries, QueryRequest
from kpi_engine.query.validation import QueryValidator


class QueryService:
    def __init__(self, catalog: Optional[SourceCatalog] = None):
        self.catalog = catalog or SourceCatalog()
        self.compiler = QueryCompiler(self.catalog)

    def load_source(self, source_id: str, scope: Optional[Dict[str, str]] = None, as_of: Optional[str] = None) -> pd.DataFrame:
        source = self.catalog.get_source(source_id)
        frame = pd.read_csv(source.file_path)

        scope = (scope or {}).copy()
        for key, value in scope.items():
            if key not in frame.columns:
                continue
            frame = frame[frame[key].astype(str) == str(value)]

        if source.availability_column in frame.columns:
            cutoff = pd.Timestamp(as_of) if as_of is not None else None
            series = pd.to_datetime(frame[source.availability_column], errors="coerce")
            if cutoff is not None:
                frame = frame[series <= cutoff].copy()

        if source.revision_column and source.revision_column in frame.columns:
            natural_key = list(source.natural_key)
            if natural_key and frame.duplicated(subset=natural_key).any():
                frame = frame.sort_values([*natural_key, source.revision_column]).drop_duplicates(subset=natural_key, keep="last")

        default_field = source.fields.get("net_sales_revenue")
        QueryValidator.validate_frame(frame, source, QueryRequest(
            source_id=source_id,
            aggregation="sum",
            value_column=default_field.name if default_field is not None else None,
            scope=scope,
            as_of=as_of,
        ))
        return frame

    def prepare_metric(self, request: QueryRequest) -> PreparedSeries:
        source = self.catalog.get_source(request.source_id)
        frame = self.load_source(request.source_id, scope=request.scope, as_of=request.as_of)
        QueryValidator.validate_request(request, source)
        QueryValidator.validate_frame(frame, source, request)

        compiled = self.compiler.compile(request)
        table_name = f"{source.table_name}_prepared"
        actual_sql = compiled.sql.replace(f'"{source.table_name}"', f'"{table_name}"')

        with DuckDBConnection(database=":memory:") as conn:
            conn.register_frame(table_name, frame)
            cursor = conn.connection.execute(actual_sql, tuple(compiled.params))
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, values)) for values in cursor.fetchall()]

        executed = CompiledQuery(
            source_id=compiled.source_id,
            aggregation=compiled.aggregation,
            sql=actual_sql,
            params=list(compiled.params),
            source_grain=compiled.source_grain,
            scope=dict(compiled.scope),
            as_of=compiled.as_of,
        )
        return PreparedSeries(source_id=request.source_id, aggregation=request.aggregation, rows=rows, query=executed)
