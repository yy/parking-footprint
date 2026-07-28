from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyproj import CRS, Transformer
from shapely import make_valid
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

SQ_FT_PER_SQ_METER = 10.763910416709722
SQ_FT_PER_ACRE = 43_560.0


class GeometryError(ValueError):
    """Raised when parking-footprint geometry cannot be measured."""


@dataclass(frozen=True)
class GeometryMeasurement:
    union_geometry: BaseGeometry
    feature_ids: tuple[str, ...]
    feature_count: int
    summed_feature_area_sq_ft: float
    union_area_sq_ft: float
    overlap_sq_ft: float


def _square_feet_per_native_square_unit(crs: CRS) -> float:
    if not crs.is_projected:
        raise GeometryError(f"analysis CRS must be projected: {crs.to_string()}")
    if not crs.axis_info:
        raise GeometryError(f"analysis CRS has no unit metadata: {crs.to_string()}")
    meters_per_unit = crs.axis_info[0].unit_conversion_factor
    return meters_per_unit**2 * SQ_FT_PER_SQ_METER


def _polygonal(geometry: BaseGeometry) -> BaseGeometry:
    valid = make_valid(geometry)
    if valid.geom_type in {"Polygon", "MultiPolygon"}:
        return valid
    if valid.geom_type == "GeometryCollection":
        polygons = [
            part
            for part in valid.geoms
            if part.geom_type in {"Polygon", "MultiPolygon"}
        ]
        if polygons:
            return unary_union(polygons)
    raise GeometryError(f"area layer contains non-polygon geometry: {valid.geom_type}")


def measure_feature_collection(
    data: dict[str, Any],
    *,
    source_crs: str,
    analysis_crs: str,
    id_field: str,
) -> GeometryMeasurement:
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(analysis_crs)
    transformer = Transformer.from_crs(source, target, always_xy=True)
    area_factor = _square_feet_per_native_square_unit(target)

    geometries: list[BaseGeometry] = []
    feature_ids: list[str] = []
    for index, feature in enumerate(data["features"]):
        geometry = feature.get("geometry")
        if geometry is None:
            raise GeometryError(f"feature {index} has no geometry")
        projected = transform(transformer.transform, shape(geometry))
        polygon = _polygonal(projected)
        if polygon.is_empty:
            raise GeometryError(f"feature {index} has empty geometry")
        geometries.append(polygon)
        properties = feature.get("properties") or {}
        feature_ids.append(str(properties.get(id_field, index)))

    if not geometries:
        raise GeometryError("area layer contains no features")

    union = unary_union(geometries)
    summed_native = sum(geometry.area for geometry in geometries)
    union_native = union.area
    summed_sq_ft = summed_native * area_factor
    union_sq_ft = union_native * area_factor
    return GeometryMeasurement(
        union_geometry=union,
        feature_ids=tuple(sorted(feature_ids)),
        feature_count=len(geometries),
        summed_feature_area_sq_ft=summed_sq_ft,
        union_area_sq_ft=union_sq_ft,
        overlap_sq_ft=max(0.0, summed_sq_ft - union_sq_ft),
    )


def union_area_sq_ft(
    geometries: list[BaseGeometry],
    *,
    analysis_crs: str,
) -> float:
    if not geometries:
        return 0.0
    target = CRS.from_user_input(analysis_crs)
    area_factor = _square_feet_per_native_square_unit(target)
    return unary_union(geometries).area * area_factor


def acres(square_feet: float) -> float:
    return square_feet / SQ_FT_PER_ACRE
