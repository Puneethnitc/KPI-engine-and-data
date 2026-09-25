from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from kpi_engine.query.models import QueryRequest, SourceCatalogEntry


class QueryValidationError(ValueError):
    pass


class QueryValidator:
    SUPPORTED_AGGREGATIONS = {"sum", "mean", "weighted_mean", "ratio_of_sums"}

    @staticmethod
    def validate_as_of(as_of: str | None) -> str | None:
        if as_of is None:
            return None
        try:
            pd.Timestamp(as_of)
        except (TypeError, ValueError) as exc:
            raise QueryValidationError(f"Invalid as_of timestamp: {as_of!r}") from exc
        return str(as_of)

    @classmethod
    def validate_request(cls, request: QueryRequest, source: SourceCatalogEntry) -> None:
        if request.aggregation not in cls.SUPPORTED_AGGREGATIONS:
            raise QueryValidationError(f"Unsupported aggregation: {request.aggregation}")

        if request.source_id != source.source_id:
            raise QueryValidationError("Request source does not match catalog entry.")

        if request.value_column and request.value_column not in source.fields:
            raise QueryValidationError(f"Value column '{request.value_column}' is not declared for {source.source_id}.")

        if request.aggregation == "weighted_mean":
            if not request.value_column or not request.weight_column:
                raise QueryValidationError("weighted_mean requires value_column and weight_column.")
            if request.weight_column not in source.fields:
                raise QueryValidationError(f"Weight column '{request.weight_column}' is not declared for {source.source_id}.")

        if request.aggregation == "ratio_of_sums":
            if not request.numerator_column or not request.denominator_column:
                raise QueryValidationError("ratio_of_sums requires numerator_column and denominator_column.")
            if request.numerator_column not in source.fields or request.denominator_column not in source.fields:
                raise QueryValidationError("ratio_of_sums source columns must be declared in the catalog.")

        if request.scope:
            unknown = set(request.scope) - set(source.dimensions)
            if unknown:
                raise QueryValidationError(f"Scope filters contain undeclared dimensions for {source.source_id}: {sorted(unknown)}")

        cls.validate_as_of(request.as_of)

    @staticmethod
    def validate_sql(sql: str) -> str:
        cleaned = (sql or "").strip()
        if not cleaned:
            raise QueryValidationError("Compiled SQL cannot be empty.")
        bad_tokens = (";", "--", "DROP", "DELETE", "UPDATE", "INSERT", "ALTER")
        upper = cleaned.upper()
        for token in bad_tokens:
            if token in upper:
                raise QueryValidationError(f"Unsafe SQL token detected: {token}")
        return cleaned

    @staticmethod
    def validate_frame(frame: "pd.DataFrame", source: SourceCatalogEntry, request: QueryRequest) -> None:
        if frame.empty:
            return
        if source.natural_key and frame.duplicated(subset=list(source.natural_key)).any():
            raise QueryValidationError(f"{source.source_id}: duplicate rows remain after revision selection.")

        numeric_columns = [c for c in [request.value_column, request.numerator_column, request.denominator_column, request.weight_column] if c]
        for column in numeric_columns:
            if column not in frame.columns:
                continue
            series = pd.to_numeric(frame[column], errors="coerce")
            values = series.to_numpy(dtype=float)
            if not pd.isna(series).all() and not np.isfinite(values).all():
                raise QueryValidationError(f"{source.source_id}: non-finite values are not allowed in {column}.")
