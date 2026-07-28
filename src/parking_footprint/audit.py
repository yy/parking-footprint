from __future__ import annotations

import json
import math
import os
import platform
import shutil
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .config import load_config
from .geometry import acres, measure_feature_collection, union_area_sq_ft
from .sources import load_source, write_source_snapshot


def _rounded(value: float) -> float:
    return round(value, 6)


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _publish_output(
    output: Path,
    *,
    result: dict[str, Any],
    provenance: dict[str, Any],
    source_snapshots: list[tuple[str, Any]],
) -> None:
    if output == Path(output.anchor):
        raise ValueError("output directory cannot be a filesystem root")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent)
    )
    backup = staging.with_name(f"{staging.name}.previous")
    try:
        for layer_id, source in source_snapshots:
            write_source_snapshot(
                source,
                staging / "sources" / f"{layer_id}.geojson",
            )
        (staging / "audit.json").write_text(
            _json_text(result),
            encoding="utf-8",
        )
        (staging / "provenance.json").write_text(
            _json_text(provenance),
            encoding="utf-8",
        )

        if output.exists():
            if not output.is_dir():
                raise ValueError(f"output path is not a directory: {output}")
            allowed_entries = {"audit.json", "provenance.json", "sources"}
            unexpected = sorted(
                child.name
                for child in output.iterdir()
                if child.name not in allowed_entries
            )
            if unexpected:
                raise ValueError(
                    f"output directory contains unmanaged entries: {unexpected}"
                )
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except BaseException:
            if backup.exists():
                os.replace(backup, output)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def run_audit(
    config_path: str | Path,
    *,
    offline: bool = False,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    output = Path(output_dir).resolve() if output_dir else None

    role_geometries: dict[str, list[Any]] = defaultdict(list)
    role_manual_sq_ft: dict[str, float] = defaultdict(float)
    layers: list[dict[str, Any]] = []
    provenance_layers: list[dict[str, Any]] = []
    source_snapshots: list[tuple[str, Any]] = []

    for spec in config.layers:
        if spec.source_kind == "manual":
            assert spec.manual_area_sq_ft is not None
            area_sq_ft = spec.manual_area_sq_ft
            role_manual_sq_ft[spec.role] += area_sq_ft
            layer_result = {
                "id": spec.id,
                "role": spec.role,
                "source_kind": spec.source_kind,
                "quality": spec.quality,
                "area_sq_ft": _rounded(area_sq_ft),
                "area_acres": _rounded(acres(area_sq_ft)),
                "note": spec.note,
                "evidence_url": spec.evidence_url,
            }
            layers.append(layer_result)
            provenance_layers.append(
                {
                    "id": spec.id,
                    "source_kind": "manual",
                    "manual_area_sq_ft": area_sq_ft,
                    "note": spec.note,
                    "evidence_url": spec.evidence_url,
                }
            )
            continue

        source = load_source(spec, offline=offline)
        measurement = measure_feature_collection(
            source.geojson,
            source_crs=spec.source_crs,
            analysis_crs=config.analysis_crs,
            id_field=spec.id_field,
        )
        role_geometries[spec.role].append(measurement.union_geometry)
        layer_result = {
            "id": spec.id,
            "role": spec.role,
            "source_kind": spec.source_kind,
            "quality": spec.quality,
            "area_sq_ft": _rounded(measurement.union_area_sq_ft),
            "area_acres": _rounded(acres(measurement.union_area_sq_ft)),
            "feature_count": measurement.feature_count,
            "feature_ids": list(measurement.feature_ids),
            "summed_feature_area_sq_ft": _rounded(
                measurement.summed_feature_area_sq_ft
            ),
            "within_layer_overlap_sq_ft": _rounded(measurement.overlap_sq_ft),
            "note": spec.note,
        }
        layers.append(layer_result)
        provenance_layers.append(
            {
                "id": spec.id,
                "id_field": spec.id_field,
                "locked_object_ids": list(spec.object_ids),
                "source_crs": spec.source_crs,
                **source.provenance,
            }
        )
        source_snapshots.append((spec.id, source))

    roles: dict[str, dict[str, float]] = {}
    all_roles = sorted(set(role_geometries) | set(role_manual_sq_ft))
    for role in all_roles:
        geometric_sq_ft = union_area_sq_ft(
            role_geometries[role],
            analysis_crs=config.analysis_crs,
        )
        total_sq_ft = geometric_sq_ft + role_manual_sq_ft[role]
        roles[role] = {
            "area_sq_ft": _rounded(total_sq_ft),
            "area_acres": _rounded(acres(total_sq_ft)),
            "geometric_area_sq_ft": _rounded(geometric_sq_ft),
            "manual_area_sq_ft": _rounded(role_manual_sq_ft[role]),
        }

    comparisons = {}
    for comparison in config.comparisons:
        numerator = roles[comparison.numerator]["area_sq_ft"]
        denominator = roles[comparison.denominator]["area_sq_ft"]
        comparisons[comparison.id] = {
            "numerator": comparison.numerator,
            "denominator": comparison.denominator,
            "ratio": _rounded(numerator / denominator) if denominator else None,
        }

    result = {
        "schema_version": 2,
        "audit": {
            "id": config.id,
            "name": config.name,
            "analysis_crs": config.analysis_crs,
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "offline" if offline else "online",
        "layers": layers,
        "roles": roles,
        "comparisons": comparisons,
    }
    provenance = {
        "schema_version": 2,
        "audit_id": config.id,
        "config_path": config.path.name,
        "config_sha256": config.config_sha256,
        "analysis_crs": config.analysis_crs,
        "software": {
            "package": "parking-footprint",
            "version": __version__,
            "python": platform.python_version(),
        },
        "layers": provenance_layers,
    }

    if output:
        _publish_output(
            output,
            result=result,
            provenance=provenance,
            source_snapshots=source_snapshots,
        )

    result["provenance"] = provenance
    return result


def baseline_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": result["schema_version"],
        "audit": result["audit"],
        "config_sha256": result["provenance"]["config_sha256"],
        "source_sha256": {
            layer["id"]: layer["sha256"]
            for layer in result["provenance"]["layers"]
            if "sha256" in layer
        },
        "layers": [
            {
                key: layer[key]
                for key in (
                    "id",
                    "role",
                    "area_sq_ft",
                    "feature_count",
                    "feature_ids",
                )
                if key in layer
            }
            for layer in result["layers"]
        ],
        "roles": result["roles"],
        "comparisons": result["comparisons"],
    }


def verify_against_baseline(
    result: dict[str, Any],
    baseline: dict[str, Any],
    *,
    area_tolerance_pct: float,
) -> list[str]:
    if not math.isfinite(area_tolerance_pct) or area_tolerance_pct < 0:
        raise ValueError("area_tolerance_pct must be finite and nonnegative")

    def compare_number(
        label: str,
        current_value: float | None,
        expected_value: float | None,
    ) -> None:
        if expected_value is None or current_value is None:
            if current_value != expected_value:
                issues.append(
                    f"{label} changed from {expected_value} to {current_value}"
                )
            return
        try:
            expected_number = float(expected_value)
            current_number = float(current_value)
        except (TypeError, ValueError):
            issues.append(
                f"{label} contains a nonnumeric value: "
                f"{expected_value!r} or {current_value!r}"
            )
            return
        if not math.isfinite(expected_number) or not math.isfinite(current_number):
            issues.append(
                f"{label} contains a non-finite value: "
                f"{expected_value!r} or {current_value!r}"
            )
            return
        allowed = abs(expected_number) * area_tolerance_pct / 100
        if abs(current_number - expected_number) > allowed:
            issues.append(
                f"{label} changed from {expected_number:.6f} to {current_number:.6f}"
            )

    issues: list[str] = []
    if baseline.get("schema_version") != result.get("schema_version"):
        issues.append(
            "schema version changed from "
            f"{baseline.get('schema_version')} to {result.get('schema_version')}"
        )
    if baseline.get("audit") != result.get("audit"):
        issues.append(
            f"audit metadata changed from {baseline.get('audit')} "
            f"to {result.get('audit')}"
        )
    current_config_sha256 = result.get("provenance", {}).get("config_sha256")
    if baseline.get("config_sha256") != current_config_sha256:
        issues.append(
            "configuration hash changed from "
            f"{baseline.get('config_sha256')} to {current_config_sha256}"
        )

    current_source_sha256 = {
        layer["id"]: layer["sha256"]
        for layer in result.get("provenance", {}).get("layers", [])
        if "sha256" in layer
    }
    expected_source_sha256 = baseline.get("source_sha256", {})
    for layer_id in sorted(set(current_source_sha256) - set(expected_source_sha256)):
        issues.append(f"unexpected source hash: {layer_id}")
    for layer_id in sorted(set(expected_source_sha256) - set(current_source_sha256)):
        issues.append(f"missing source hash: {layer_id}")
    for layer_id in sorted(set(expected_source_sha256) & set(current_source_sha256)):
        if expected_source_sha256[layer_id] != current_source_sha256[layer_id]:
            issues.append(
                f"{layer_id}: source hash changed from "
                f"{expected_source_sha256[layer_id]} to "
                f"{current_source_sha256[layer_id]}"
            )

    current_layers = {layer["id"]: layer for layer in result["layers"]}
    expected_layers = {layer["id"]: layer for layer in baseline.get("layers", [])}
    for layer_id in sorted(set(current_layers) - set(expected_layers)):
        issues.append(f"unexpected layer: {layer_id}")
    for expected in baseline.get("layers", []):
        layer_id = expected["id"]
        current = current_layers.get(layer_id)
        if current is None:
            issues.append(f"missing layer: {layer_id}")
            continue
        if expected.get("role") != current.get("role"):
            issues.append(
                f"{layer_id}: role changed from "
                f"{expected.get('role')} to {current.get('role')}"
            )
        if expected.get("feature_count") != current.get("feature_count"):
            issues.append(
                f"{layer_id}: feature count changed from "
                f"{expected.get('feature_count')} to {current.get('feature_count')}"
            )
        if expected.get("feature_ids") != current.get("feature_ids"):
            issues.append(
                f"{layer_id}: feature IDs changed from "
                f"{expected.get('feature_ids')} to {current.get('feature_ids')}"
            )
        compare_number(
            f"{layer_id}: area",
            current.get("area_sq_ft"),
            expected.get("area_sq_ft"),
        )

    current_roles = result.get("roles", {})
    expected_roles = baseline.get("roles", {})
    for role in sorted(set(current_roles) - set(expected_roles)):
        issues.append(f"unexpected role: {role}")
    for role in sorted(set(expected_roles) - set(current_roles)):
        issues.append(f"missing role: {role}")
    for role in sorted(set(expected_roles) & set(current_roles)):
        expected_values = expected_roles[role]
        current_values = current_roles[role]
        for key in (
            "area_sq_ft",
            "area_acres",
            "geometric_area_sq_ft",
            "manual_area_sq_ft",
        ):
            compare_number(
                f"{role}: {key}",
                current_values.get(key),
                expected_values.get(key),
            )

    current_comparisons = result.get("comparisons", {})
    expected_comparisons = baseline.get("comparisons", {})
    for comparison_id in sorted(set(current_comparisons) - set(expected_comparisons)):
        issues.append(f"unexpected comparison: {comparison_id}")
    for comparison_id in sorted(set(expected_comparisons) - set(current_comparisons)):
        issues.append(f"missing comparison: {comparison_id}")
    for comparison_id in sorted(set(expected_comparisons) & set(current_comparisons)):
        expected = expected_comparisons[comparison_id]
        current = current_comparisons[comparison_id]
        for key in ("numerator", "denominator"):
            if expected.get(key) != current.get(key):
                issues.append(
                    f"{comparison_id}: {key} changed from "
                    f"{expected.get(key)} to {current.get(key)}"
                )
        compare_number(
            f"{comparison_id}: ratio",
            current.get("ratio"),
            expected.get("ratio"),
        )
    return issues
