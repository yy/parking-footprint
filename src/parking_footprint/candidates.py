from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pyproj import CRS

from .config import LayerSpec, load_config
from .errors import SourceError
from .geometry import measure_feature_collection
from .ids import id_sort_key

__all__ = ["Candidate", "find_candidates"]


@dataclass(frozen=True)
class Candidate:
    layer_id: str
    feature_id: str
    area_sq_ft: float
    locked: bool


def _query_near_point(
    spec: LayerSpec,
    *,
    longitude: float,
    latitude: float,
    radius_ft: float,
) -> list[dict[str, Any]]:
    assert spec.source_url is not None
    source_epsg = CRS.from_user_input(spec.source_crs).to_epsg()
    if source_epsg is None:
        raise SourceError(
            f"ArcGIS layer {spec.id} requires an EPSG source_crs for online queries"
        )
    params = {
        "geometry": f"{longitude},{latitude}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": str(radius_ft),
        "units": "esriSRUnit_Foot",
        "outFields": spec.id_field,
        "returnGeometry": "true",
        "outSR": str(source_epsg),
        "f": "geojson",
    }
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        response = client.get(f"{spec.source_url.rstrip('/')}/query", params=params)
        response.raise_for_status()
        page = response.json()
    if page.get("type") != "FeatureCollection" or not isinstance(
        page.get("features"), list
    ):
        raise SourceError(f"{spec.id} did not return a GeoJSON FeatureCollection")
    if page.get("exceededTransferLimit", False):
        raise SourceError(
            f"{spec.id} truncated its candidate search; use a smaller radius"
        )
    return page["features"]


def find_candidates(
    config_path: str | Path,
    *,
    longitude: float,
    latitude: float,
    radius_ft: float,
    output_dir: Path | None = None,
) -> list[Candidate]:
    """List ArcGIS features near a point so a reviewer can choose which to lock.

    This is a discovery aid, not a selection rule: every candidate still needs
    review on a map before its ID goes into ``object_ids``.
    """
    config = load_config(config_path)
    candidates: list[Candidate] = []
    for spec in config.layers:
        if spec.source_kind != "arcgis":
            continue
        features = _query_near_point(
            spec, longitude=longitude, latitude=latitude, radius_ft=radius_ft
        )
        features.sort(
            key=lambda feature: id_sort_key(
                str((feature.get("properties") or {}).get(spec.id_field))
            )
        )
        locked = set(spec.object_ids)
        annotated = []
        for feature in features:
            feature_id = str((feature.get("properties") or {}).get(spec.id_field))
            area = measure_feature_collection(
                {"features": [feature]},
                source_crs=spec.source_crs,
                analysis_crs=config.analysis_crs,
                id_field=spec.id_field,
            ).union_area_sq_ft
            candidate = Candidate(spec.id, feature_id, area, feature_id in locked)
            candidates.append(candidate)
            annotated.append(
                {
                    "type": "Feature",
                    "properties": {
                        spec.id_field: feature_id,
                        "area_sq_ft": round(area, 2),
                        "locked": candidate.locked,
                    },
                    "geometry": feature.get("geometry"),
                }
            )
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / f"{spec.id}.geojson").write_text(
                json.dumps({"type": "FeatureCollection", "features": annotated}) + "\n",
                encoding="utf-8",
            )
    return candidates
