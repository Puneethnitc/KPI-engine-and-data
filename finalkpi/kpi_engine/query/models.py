from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SourceFieldSpec:
    name: str
    field_type: str = "float"
    required: bool = True
    nullable: bool = False


@dataclass(frozen=True)
class SourceCatalogEntry:
    source_id: str
    table_name: str
    file_path: str
    grain: str
    date_column: str
    dimensions: Tuple[str, ...]
    availability_column: str
    natural_key: Tuple[str, ...]
    revision_column: Optional[str] = None
    fields: Dict[str, SourceFieldSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryScope:
    filters: Dict[str, str] = field(default_factory=dict)

    def normalized(self) -> Dict[str, str]:
        return {key: str(value) for key, value in self.filters.items() if value is not None}


@dataclass(frozen=True)
class QueryRequest:
    source_id: str
    aggregation: str
    value_column: Optional[str] = None
    numerator_column: Optional[str] = None
    denominator_column: Optional[str] = None
    weight_column: Optional[str] = None
    scope: Optional[Dict[str, str]] = None
    as_of: Optional[str] = None
    revision: Optional[str] = None
    group_by: Tuple[str, ...] = ("date",)


@dataclass(frozen=True)
class CompiledQuery:
    source_id: str
    aggregation: str
    sql: str
    params: List[Any]
    source_grain: str
    scope: Dict[str, str]
    as_of: Optional[str]


@dataclass
class PreparedSeries:
    source_id: str
    aggregation: str
    rows: List[Dict[str, Any]]
    query: CompiledQuery
