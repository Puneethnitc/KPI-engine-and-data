from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import yaml

from kpi_engine.query.models import SourceCatalogEntry, SourceFieldSpec


class SourceCatalog:
    """Catalog for the prototype query layer.

    Source metadata is loaded from configuration so additional sources can be
    added without touching Python logic. The bundled three repo fixtures remain
    the default catalog configuration.
    """

    SUPPORTED_GRAINS = {"daily", "weekly", "monthly"}

    def __init__(self, base_dir: Optional[str | Path] = None, config_path: Optional[str | Path] = None):
        self.base_dir = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parents[2] / "data"
        default_config = Path(__file__).with_name("source_catalog.yaml")
        self.config_path = self._resolve_config_path(config_path)
        self.sources: Dict[str, SourceCatalogEntry] = {}

        if default_config.exists():
            self._load_config(default_config)
        if self.config_path is not None and self.config_path.resolve() != default_config.resolve():
            self._load_config(self.config_path)

    def _resolve_config_path(self, config_path: Optional[str | Path]) -> Optional[Path]:
        if config_path is None:
            default = Path(__file__).with_name("source_catalog.yaml")
            return default if default.exists() else None
        path = Path(config_path)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path

    def _load_default_sources(self) -> None:
        default_path = Path(__file__).with_name("source_catalog.yaml")
        if default_path.exists():
            self._load_config(default_path)

    def _load_config(self, config_path: str | Path) -> None:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Source catalog config not found: {path}")

        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}

        if not isinstance(payload, dict):
            raise ValueError(f"Source catalog config must be a mapping: {path}")

        sources = payload.get("sources")
        if sources is None:
            sources = payload
        if not isinstance(sources, dict):
            raise ValueError(f"Source catalog config must contain a 'sources' mapping: {path}")

        for source_id, raw_entry in sources.items():
            entry = self._resolve_entry(source_id, raw_entry, base_path=path.parent)
            if entry.source_id in self.sources:
                raise ValueError(f"Duplicate source definition: {entry.source_id}")
            self.sources[entry.source_id] = entry

    @classmethod
    def _resolve_path(cls, raw_path: str | Path, base_path: Path) -> str:
        candidate = Path(raw_path)
        if candidate.is_absolute():
            return str(candidate)
        return str((base_path / candidate).resolve())

    @classmethod
    def _normalize_fields(cls, fields: Dict[str, Any]) -> Dict[str, SourceFieldSpec]:
        if not isinstance(fields, dict):
            raise ValueError("Source fields must be a mapping of field names to metadata.")
        normalized: Dict[str, SourceFieldSpec] = {}
        for field_name, field_spec in fields.items():
            if isinstance(field_spec, str):
                normalized[str(field_name)] = SourceFieldSpec(str(field_name), str(field_spec), required=True)
                continue
            if isinstance(field_spec, dict):
                normalized[str(field_name)] = SourceFieldSpec(
                    name=str(field_name),
                    field_type=str(field_spec.get("type") or field_spec.get("field_type") or "float"),
                    required=bool(field_spec.get("required", True)),
                    nullable=bool(field_spec.get("nullable", False)),
                )
                continue
            raise ValueError(f"Field '{field_name}' must be a string or mapping.")
        return normalized

    @classmethod
    def _resolve_entry(cls, source_id: str, raw_entry: Any, base_path: Path) -> SourceCatalogEntry:
        if not isinstance(raw_entry, dict):
            raise ValueError(f"Source definition for '{source_id}' must be a mapping.")

        resolved_id = str(raw_entry.get("source_id") or source_id)
        dimensions = tuple(raw_entry.get("dimensions") or [])
        natural_key = tuple(raw_entry.get("natural_key") or [])
        fields = cls._normalize_fields(raw_entry.get("fields") or {})

        if not resolved_id:
            raise ValueError("Every source definition must include a source_id.")
        if not raw_entry.get("table_name"):
            raise ValueError(f"Source '{resolved_id}' must include a table_name.")
        if not raw_entry.get("file_path"):
            raise ValueError(f"Source '{resolved_id}' must include a file_path.")
        if not raw_entry.get("date_column"):
            raise ValueError(f"Source '{resolved_id}' must include a date_column.")
        if not raw_entry.get("availability_column"):
            raise ValueError(f"Source '{resolved_id}' must include an availability_column.")
        if not raw_entry.get("grain"):
            raise ValueError(f"Source '{resolved_id}' must include a grain.")

        grain = str(raw_entry.get("grain"))
        if grain not in cls.SUPPORTED_GRAINS:
            raise ValueError(f"Source '{resolved_id}' has unsupported grain '{grain}'.")
        date_column = str(raw_entry.get("date_column"))
        availability_column = str(raw_entry.get("availability_column"))

        if date_column not in fields:
            raise ValueError(f"Source '{resolved_id}' date_column '{date_column}' must be declared in fields.")
        if availability_column not in fields:
            raise ValueError(f"Source '{resolved_id}' availability_column '{availability_column}' must be declared in fields.")
        if not dimensions:
            raise ValueError(f"Source '{resolved_id}' must declare at least one dimension.")
        for dimension in dimensions:
            if dimension not in fields:
                raise ValueError(f"Source '{resolved_id}' dimension '{dimension}' must be declared in fields.")
        if not natural_key:
            raise ValueError(f"Source '{resolved_id}' must declare a natural_key.")
        for key in natural_key:
            if key not in fields:
                raise ValueError(f"Source '{resolved_id}' natural_key '{key}' must be declared in fields.")

        revision_column = raw_entry.get("revision_column")
        if revision_column is not None:
            revision_column = str(revision_column)
            if revision_column not in fields:
                raise ValueError(f"Source '{resolved_id}' revision_column '{revision_column}' must be declared in fields.")

        return SourceCatalogEntry(
            source_id=resolved_id,
            table_name=str(raw_entry.get("table_name")),
            file_path=cls._resolve_path(raw_entry.get("file_path"), base_path),
            grain=grain,
            date_column=date_column,
            dimensions=tuple(str(item) for item in dimensions),
            availability_column=availability_column,
            natural_key=tuple(str(item) for item in natural_key),
            revision_column=revision_column,
            fields=fields,
        )

    def register_source(self, entry: SourceCatalogEntry) -> None:
        self.sources[entry.source_id] = entry

    def get_source(self, source_id: str) -> SourceCatalogEntry:
        if source_id not in self.sources:
            raise KeyError(f"Unknown source: {source_id}")
        return self.sources[source_id]

    def list_source_ids(self) -> Iterable[str]:
        return tuple(sorted(self.sources))
