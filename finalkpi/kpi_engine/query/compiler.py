from __future__ import annotations

from typing import Any, Dict, List, Optional

from kpi_engine.query.catalog import SourceCatalog
from kpi_engine.query.models import CompiledQuery, QueryRequest
from kpi_engine.query.validation import QueryValidationError, QueryValidator


class QueryCompiler:
    def __init__(self, catalog: Optional[SourceCatalog] = None):
        self.catalog = catalog or SourceCatalog()

    def _build_predicates(self, request: QueryRequest, source_id: str) -> tuple[List[str], List[Any]]:
        source = self.catalog.get_source(source_id)
        predicates: List[str] = []
        params: List[Any] = []
        scope = (request.scope or {}).copy()

        for key, value in scope.items():
            if key not in source.dimensions:
                raise QueryValidationError(f"Scope {key!r} is not a valid dimension for {source_id}.")
            predicates.append(f'"{key}" = ?')
            params.append(value)

        if request.as_of is not None:
            predicates.append(f'"{source.availability_column}" <= ?')
            params.append(request.as_of)

        return predicates, params

    def _aggregate_expression(self, request: QueryRequest) -> str:
        if request.aggregation == "sum":
            return f'SUM("{request.value_column}")'
        if request.aggregation == "mean":
            return f'AVG("{request.value_column}")'
        if request.aggregation == "weighted_mean":
            return f'SUM("{request.value_column}" * "{request.weight_column}") / NULLIF(SUM("{request.weight_column}"), 0)'
        if request.aggregation == "ratio_of_sums":
            return f'SUM("{request.numerator_column}") / NULLIF(SUM("{request.denominator_column}"), 0)'
        raise QueryValidationError(f"Unsupported aggregation: {request.aggregation}")

    def compile(self, request: QueryRequest) -> CompiledQuery:
        source = self.catalog.get_source(request.source_id)
        QueryValidator.validate_request(request, source)
        query_scope = (request.scope or {}).copy()

        predicates, params = self._build_predicates(request, request.source_id)

        group_by = list(request.group_by or ())
        if not group_by or (len(group_by) == 1 and group_by[0] == "date" and source.date_column != "date"):
            group_by = [source.date_column]

        select_parts = [f'"{column}"' for column in group_by]
        if group_by != [source.date_column]:
            select_parts = [f'"{col}"' for col in group_by]

        sql = (
            f'SELECT {", ".join(select_parts)}, {self._aggregate_expression(request)} AS metric_value '
            f'FROM "{source.table_name}" '
        )
        if predicates:
            sql += f'WHERE {" AND ".join(predicates)} '
        sql += f'GROUP BY {", ".join(select_parts)} ORDER BY {", ".join(select_parts)}'
        sql = QueryValidator.validate_sql(sql)
        return CompiledQuery(
            source_id=request.source_id,
            aggregation=request.aggregation,
            sql=sql,
            params=params,
            source_grain=source.grain,
            scope=query_scope,
            as_of=request.as_of,
        )
