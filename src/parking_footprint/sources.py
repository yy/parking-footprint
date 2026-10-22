from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pyproj import CRS

from .config import LayerSpec
from .errors import SourceError
from .ids import id_sort_key, sorted_ids

__all__ = [
    "ARCGIS_OBJECT_ID_BATCH_SIZE",
    "SourceData",
    "SourceError",
    "canonical_geojson_bytes",
    "load_source",
    "write_source_snapshot",
]

ARCGIS_OBJECT_ID_BATCH_SIZE = 500


@dataclass(frozen=True)
class SourceData:
    geojson: dict[str, Any]
    canonical_bytes: bytes
    provenance: dict[str, Any]


def canonical_geojson_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _feature_ids(
    spec: LayerSpec,
    features: list[dict[str, Any]],
    *,
    id_field: str | None = None,
) -> list[str]:
    field = id_field or spec.id_field
    try:
        return sorted_ids(
            str((feature.get("properties") or {})[field]) for feature in features
        )
    except KeyError as error:
        raise SourceError(
            f"{spec.id} returned a feature without the required ID field {field!r}"
        ) from error


def _validate_feature_collection(spec: LayerSpec, data: dict[str, Any]) -> None:
    if data.get("type") != "FeatureCollection" or not isinstance(
        data.get("features"), list
    ):
        raise SourceError(f"{spec.id} did not return a GeoJSON FeatureCollection")

    count = len(data["features"])
    if spec.expected_feature_count is not None and count != spec.expected_feature_count:
        raise SourceError(
            f"{spec.id} returned {count} features; "
            f"expected {spec.expected_feature_count}"
        )

    if spec.object_ids:
        returned = _feature_ids(spec, data["features"])
        expected = list(spec.object_ids)
        if returned != expected:
            raise SourceError(
                f"{spec.id} returned feature IDs {returned}; expected {expected}"
            )


def _read_snapshot(spec: LayerSpec) -> SourceData:
    if spec.snapshot is None:
        raise SourceError(f"offline source {spec.id} has no snapshot")
    try:
        text = spec.snapshot.read_text(encoding="utf-8")
    except OSError as error:
        raise SourceError(f"{spec.id} cannot read its snapshot: {error}") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise SourceError(f"{spec.id} snapshot is not valid JSON: {error}") from error
    _validate_feature_collection(spec, data)
    canonical = canonical_geojson_bytes(data)
    return SourceData(
        geojson=data,
        canonical_bytes=canonical,
        provenance={
            "mode": "snapshot",
            "snapshot": spec.snapshot_reference or spec.snapshot.name,
            # Declared in the configuration: a snapshot file cannot carry its own
            # capture date without changing the bytes that are hashed.
            "captured_at": spec.captured_at,
            "sha256": hashlib.sha256(canonical).hexdigest(),
        },
    )


def _fetch_arcgis(spec: LayerSpec) -> SourceData:
    assert spec.source_url is not None
    source_crs = CRS.from_user_input(spec.source_crs)
    source_epsg = source_crs.to_epsg()
    if source_epsg is None:
        raise SourceError(
            f"ArcGIS layer {spec.id} requires an EPSG source_crs for online queries"
        )

    feature_params: dict[str, str] = {
        "outFields": spec.id_field,
        "returnGeometry": "true",
        "outSR": str(source_epsg),
        "f": "geojson",
    }

    query_url = f"{spec.source_url.rstrip('/')}/query"
    features: list[dict[str, Any]] = []
    request_urls: list[str] = []
    feature_request_parameters: list[dict[str, str]] = []
    selection_request_url: str | None = None
    selected_id_field = spec.id_field
    requested_at = datetime.now(UTC).isoformat()
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        if spec.object_ids:
            selected_ids = list(spec.object_ids)
        else:
            selection_params = {
                "where": spec.where or "1=1",
                "returnIdsOnly": "true",
                "f": "json",
            }
            response = client.get(query_url, params=selection_params)
            response.raise_for_status()
            selection = response.json()
            selection_request_url = str(response.request.url)
            object_ids = selection.get("objectIds")
            if not isinstance(object_ids, list):
                raise SourceError(
                    f"{spec.id} did not return object IDs for its ArcGIS query"
                )
            selected_id_field = str(selection.get("objectIdFieldName") or spec.id_field)
            if selected_id_field != spec.id_field:
                raise SourceError(
                    f"{spec.id} uses ArcGIS object ID field {selected_id_field!r}; "
                    f"configured id_field is {spec.id_field!r}"
                )
            selected_ids = sorted_ids(str(object_id) for object_id in object_ids)

        for start in range(0, len(selected_ids), ARCGIS_OBJECT_ID_BATCH_SIZE):
            batch = selected_ids[start : start + ARCGIS_OBJECT_ID_BATCH_SIZE]
            page_params = {
                **feature_params,
                "objectIds": ",".join(batch),
            }
            response = client.post(query_url, data=page_params)
            response.raise_for_status()
            page = response.json()
            request_urls.append(str(response.request.url))
            feature_request_parameters.append(page_params)
            if page.get("type") != "FeatureCollection" or not isinstance(
                page.get("features"), list
            ):
                raise SourceError(
                    f"{spec.id} did not return a GeoJSON FeatureCollection"
                )
            if page.get("exceededTransferLimit", False):
                raise SourceError(
                    f"{spec.id} truncated an ArcGIS object-ID batch of "
                    f"{len(batch)} features"
                )
            features.extend(page["features"])

    returned_ids = _feature_ids(spec, features, id_field=selected_id_field)
    if returned_ids != selected_ids:
        raise SourceError(
            f"{spec.id} returned ArcGIS object IDs {returned_ids}; "
            f"selected {selected_ids}"
        )
    data = {
        "type": "FeatureCollection",
        "features": sorted(
            (
                {
                    "type": "Feature",
                    "properties": {
                        spec.id_field: (feature.get("properties") or {})[spec.id_field]
                    },
                    "geometry": feature.get("geometry"),
                }
                for feature in features
            ),
            key=lambda feature: id_sort_key(
                str((feature.get("properties") or {}).get(spec.id_field, ""))
            ),
        ),
    }
    # A count check would be unreachable here: returned_ids holds one entry per
    # feature and has already been compared with selected_ids element by element.
    _validate_feature_collection(spec, data)
    canonical = canonical_geojson_bytes(data)
    request_parameters = dict(feature_params)
    if spec.object_ids:
        request_parameters["objectIds"] = ",".join(spec.object_ids)
    else:
        request_parameters["where"] = spec.where or "1=1"
    return SourceData(
        geojson=data,
        canonical_bytes=canonical,
        provenance={
            "mode": "online",
            "layer_url": spec.source_url,
            "captured_at": requested_at,
            # Feature batches are POSTed, so their parameters live in the request
            # body rather than in these URLs.
            "request_urls": request_urls,
            "feature_request_parameters": feature_request_parameters,
            "selection_request_url": selection_request_url,
            "selected_object_id_field": selected_id_field,
            "selected_object_ids": selected_ids,
            "request_parameters": request_parameters,
            "sha256": hashlib.sha256(canonical).hexdigest(),
        },
    )


def load_source(spec: LayerSpec, *, offline: bool) -> SourceData:
    if spec.source_kind == "manual":
        raise SourceError("manual layers do not contain GeoJSON")
    if offline or spec.source_kind == "geojson":
        return _read_snapshot(spec)
    if spec.source_kind == "arcgis":
        return _fetch_arcgis(spec)
    raise SourceError(f"unsupported source kind: {spec.source_kind}")


def write_source_snapshot(source: SourceData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source.canonical_bytes + b"\n")
