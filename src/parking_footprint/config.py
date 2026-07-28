from __future__ import annotations

import hashlib
import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a parking-footprint configuration is incomplete."""


SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class LayerSpec:
    id: str
    role: str
    source_kind: str
    source_url: str | None
    snapshot: Path | None
    object_ids: tuple[str, ...]
    where: str | None
    id_field: str
    source_crs: str
    expected_feature_count: int | None
    manual_area_sq_ft: float | None
    quality: str
    note: str | None
    evidence_url: str | None
    snapshot_reference: str | None = None


@dataclass(frozen=True)
class ComparisonSpec:
    id: str
    numerator: str
    denominator: str


@dataclass(frozen=True)
class AuditConfig:
    path: Path
    id: str
    name: str
    analysis_crs: str
    layers: tuple[LayerSpec, ...]
    comparisons: tuple[ComparisonSpec, ...]
    config_sha256: str


def _optional_path(value: Any, base_dir: Path) -> Path | None:
    if value is None:
        return None
    return (base_dir / str(value)).resolve()


def _safe_path_reference(value: Any) -> str | None:
    if value is None:
        return None
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        return path.name
    return path.as_posix()


def load_config(path: str | Path) -> AuditConfig:
    config_path = Path(path).resolve()
    raw_bytes = config_path.read_bytes()
    raw = tomllib.loads(raw_bytes.decode("utf-8"))
    base_dir = config_path.parent

    audit = raw.get("audit", {})
    audit_id = str(audit.get("id", "")).strip()
    name = str(audit.get("name", "")).strip()
    analysis_crs = str(audit.get("analysis_crs", "")).strip()
    if not audit_id or not name or not analysis_crs:
        raise ConfigError("audit.id, audit.name, and audit.analysis_crs are required")

    layers = []
    seen_ids: set[str] = set()
    for item in raw.get("layers", []):
        layer_id = str(item.get("id", "")).strip()
        role = str(item.get("role", "")).strip()
        source_kind = str(item.get("source_kind", "")).strip()
        if not layer_id or not role or not source_kind:
            raise ConfigError("each layer requires id, role, and source_kind")
        if not SAFE_ID_PATTERN.fullmatch(layer_id):
            raise ConfigError(
                f"layer id {layer_id!r} must start with a letter or number and "
                "contain only letters, numbers, dots, underscores, or hyphens"
            )
        if layer_id in seen_ids:
            raise ConfigError(f"duplicate layer id: {layer_id}")
        seen_ids.add(layer_id)

        object_ids = tuple(sorted(str(value) for value in item.get("object_ids", [])))
        source_url = item.get("source_url")
        snapshot_value = item.get("snapshot")
        snapshot = _optional_path(snapshot_value, base_dir)
        manual_area = item.get("manual_area_sq_ft")

        if source_kind == "manual":
            if manual_area is None:
                raise ConfigError(
                    f"manual layer {layer_id} requires finite, nonnegative "
                    "manual_area_sq_ft"
                )
            manual_area = float(manual_area)
            if not math.isfinite(manual_area) or manual_area < 0:
                raise ConfigError(
                    f"manual layer {layer_id} requires finite, nonnegative "
                    "manual_area_sq_ft"
                )
        elif source_kind == "arcgis":
            if not source_url:
                raise ConfigError(f"ArcGIS layer {layer_id} requires source_url")
            if not object_ids and not item.get("where"):
                raise ConfigError(
                    f"ArcGIS layer {layer_id} requires object_ids or where"
                )
        elif source_kind == "geojson":
            if snapshot is None:
                raise ConfigError(f"GeoJSON layer {layer_id} requires snapshot")
        else:
            raise ConfigError(
                f"unsupported source_kind {source_kind!r} for layer {layer_id}"
            )

        layers.append(
            LayerSpec(
                id=layer_id,
                role=role,
                source_kind=source_kind,
                source_url=str(source_url) if source_url else None,
                snapshot=snapshot,
                object_ids=object_ids,
                where=str(item["where"]) if item.get("where") else None,
                id_field=str(item.get("id_field", "OBJECTID")),
                source_crs=str(item.get("source_crs", "EPSG:4326")),
                expected_feature_count=(
                    int(item["expected_feature_count"])
                    if item.get("expected_feature_count") is not None
                    else None
                ),
                manual_area_sq_ft=(
                    float(manual_area) if manual_area is not None else None
                ),
                quality=str(item.get("quality", "unrated")),
                note=str(item["note"]) if item.get("note") else None,
                evidence_url=(
                    str(item["evidence_url"]) if item.get("evidence_url") else None
                ),
                snapshot_reference=_safe_path_reference(snapshot_value),
            )
        )

    if not layers:
        raise ConfigError("at least one layer is required")

    comparisons = []
    seen_comparison_ids: set[str] = set()
    roles = {layer.role for layer in layers}
    for item in raw.get("comparisons", []):
        comparison = ComparisonSpec(
            id=str(item.get("id", "")).strip(),
            numerator=str(item.get("numerator", "")).strip(),
            denominator=str(item.get("denominator", "")).strip(),
        )
        if not comparison.id or not comparison.numerator or not comparison.denominator:
            raise ConfigError("each comparison requires id, numerator, and denominator")
        if comparison.id in seen_comparison_ids:
            raise ConfigError(f"duplicate comparison id: {comparison.id}")
        seen_comparison_ids.add(comparison.id)
        missing = {comparison.numerator, comparison.denominator} - roles
        if missing:
            raise ConfigError(
                f"comparison {comparison.id} refers to missing roles: {sorted(missing)}"
            )
        comparisons.append(comparison)

    return AuditConfig(
        path=config_path,
        id=audit_id,
        name=name,
        analysis_crs=analysis_crs,
        layers=tuple(layers),
        comparisons=tuple(comparisons),
        config_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )
