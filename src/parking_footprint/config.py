from __future__ import annotations

import hashlib
import math
import re
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .ids import id_sort_key, sorted_ids

__all__ = [
    "EVIDENCE_GRADES",
    "AuditConfig",
    "ComparisonSpec",
    "ConfigError",
    "LayerSpec",
    "load_config",
]

SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# The evidence grades defined in docs/METHOD.md. Comparisons are only
# meaningful when these labels mean the same thing across audits, so a typo
# must fail rather than silently invent a sixth grade.
EVIDENCE_GRADES = frozenset(
    {
        "unrated",
        "authoritative-local",
        "derived-local",
        "observed-estimate",
        "illustrative-assumption",
        "national-estimate",
    }
)


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
    captured_at: str | None = None


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


def _captured_at(value: Any, layer_id: str) -> str | None:
    if value is None:
        return None
    # TOML parses a bare date or timestamp into a date/datetime object; both
    # render back to an ISO 8601 string.
    text = (
        value.isoformat() if isinstance(value, date | datetime) else str(value).strip()
    )
    try:
        datetime.fromisoformat(text)
    except ValueError as error:
        raise ConfigError(
            f"layer {layer_id} has an invalid captured_at {text!r}; "
            "use an ISO 8601 date or timestamp"
        ) from error
    return text


def _object_ids(item: dict[str, Any], layer_id: str) -> tuple[str, ...]:
    values = [str(value) for value in item.get("object_ids", [])]
    duplicates = sorted_ids({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ConfigError(f"layer {layer_id} repeats object_ids: {duplicates}")
    return tuple(sorted(values, key=id_sort_key))


def _expected_feature_count(
    item: dict[str, Any],
    layer_id: str,
    object_ids: tuple[str, ...],
) -> int | None:
    value = item.get("expected_feature_count")
    if value is None:
        return None
    count = int(value)
    if count < 0:
        raise ConfigError(
            f"layer {layer_id} requires a nonnegative expected_feature_count"
        )
    if object_ids and count != len(object_ids):
        raise ConfigError(
            f"layer {layer_id} locks {len(object_ids)} object_ids but expects "
            f"{count} features"
        )
    return count


def _quality(item: dict[str, Any], layer_id: str) -> str:
    quality = str(item.get("quality", "unrated")).strip()
    if quality not in EVIDENCE_GRADES:
        raise ConfigError(
            f"layer {layer_id} has unknown quality {quality!r}; expected one of "
            f"{sorted(EVIDENCE_GRADES)}"
        )
    return quality


def _manual_area_sq_ft(item: dict[str, Any], layer_id: str) -> float:
    value = item.get("manual_area_sq_ft")
    invalid = ConfigError(
        f"manual layer {layer_id} requires finite, nonnegative manual_area_sq_ft"
    )
    if value is None:
        raise invalid
    try:
        area = float(value)
    except (TypeError, ValueError) as error:
        raise invalid from error
    if not math.isfinite(area) or area < 0:
        raise invalid
    return area


def load_config(path: str | Path) -> AuditConfig:
    config_path = Path(path).resolve()
    raw_bytes = config_path.read_bytes()
    try:
        raw = tomllib.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(
            f"{config_path.name} is not readable TOML: {error}"
        ) from error
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

        object_ids = _object_ids(item, layer_id)
        source_url = item.get("source_url")
        snapshot_value = item.get("snapshot")
        snapshot = _optional_path(snapshot_value, base_dir)
        manual_area: float | None = None

        if source_kind == "manual":
            manual_area = _manual_area_sq_ft(item, layer_id)
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
                expected_feature_count=_expected_feature_count(
                    item, layer_id, object_ids
                ),
                manual_area_sq_ft=manual_area,
                quality=_quality(item, layer_id),
                note=str(item["note"]) if item.get("note") else None,
                evidence_url=(
                    str(item["evidence_url"]) if item.get("evidence_url") else None
                ),
                snapshot_reference=_safe_path_reference(snapshot_value),
                captured_at=_captured_at(item.get("captured_at"), layer_id),
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
