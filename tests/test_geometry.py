from types import SimpleNamespace
from typing import Any, cast

import pytest
from pyproj import CRS

from parking_footprint.geometry import (
    GeometryError,
    _square_feet_per_native_square_unit,
    measure_feature_collection,
    union_area_sq_ft,
)


def polygon_feature(ring: list[list[float]], object_id: int = 1) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def collection(*features: dict[str, Any]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}


def measure(data: dict[str, Any], **overrides: str):
    return measure_feature_collection(
        data,
        **{
            "source_crs": "EPSG:4326",
            "analysis_crs": "EPSG:2284",
            "id_field": "OBJECTID",
            **overrides,
        },
    )


def test_overlapping_features_are_unioned() -> None:
    measurement = measure(
        collection(
            polygon_feature(
                [
                    [-78.5000, 38.0000],
                    [-78.4990, 38.0000],
                    [-78.4990, 38.0010],
                    [-78.5000, 38.0010],
                    [-78.5000, 38.0000],
                ],
                object_id=1,
            ),
            polygon_feature(
                [
                    [-78.4995, 38.0000],
                    [-78.4985, 38.0000],
                    [-78.4985, 38.0010],
                    [-78.4995, 38.0010],
                    [-78.4995, 38.0000],
                ],
                object_id=2,
            ),
        )
    )

    assert measurement.feature_ids == ("1", "2")
    assert measurement.union_area_sq_ft < measurement.summed_feature_area_sq_ft
    assert measurement.overlap_sq_ft > 0


def test_invalid_polygon_keeps_its_area_and_drops_linear_remnants() -> None:
    # make_valid splits this spiked ring into a GeometryCollection holding the
    # square plus a zero-area LineString for the dangling edge.
    spiked = measure(
        collection(
            polygon_feature(
                [
                    [-78.5000, 38.0000],
                    [-78.4990, 38.0000],
                    [-78.4990, 38.0010],
                    [-78.5000, 38.0010],
                    [-78.5005, 38.0015],
                    [-78.5000, 38.0010],
                    [-78.5000, 38.0000],
                ]
            )
        )
    )
    square = measure(
        collection(
            polygon_feature(
                [
                    [-78.5000, 38.0000],
                    [-78.4990, 38.0000],
                    [-78.4990, 38.0010],
                    [-78.5000, 38.0010],
                    [-78.5000, 38.0000],
                ]
            )
        )
    )

    assert spiked.union_area_sq_ft == pytest.approx(square.union_area_sq_ft)


def test_non_polygon_geometry_is_rejected() -> None:
    data = collection(
        {
            "type": "Feature",
            "properties": {"OBJECTID": 1},
            "geometry": {
                "type": "LineString",
                "coordinates": [[-78.5000, 38.0000], [-78.4990, 38.0010]],
            },
        }
    )

    with pytest.raises(GeometryError, match="non-polygon geometry"):
        measure(data)


def test_missing_geometry_is_rejected() -> None:
    data = collection(
        {"type": "Feature", "properties": {"OBJECTID": 1}, "geometry": None}
    )

    with pytest.raises(GeometryError, match="feature 0 has no geometry"):
        measure(data)


def test_empty_geometry_is_rejected() -> None:
    data = collection(
        {
            "type": "Feature",
            "properties": {"OBJECTID": 1},
            "geometry": {"type": "Polygon", "coordinates": []},
        }
    )

    with pytest.raises(GeometryError, match="feature 0 has empty geometry"):
        measure(data)


def test_empty_feature_collection_is_rejected() -> None:
    with pytest.raises(GeometryError, match="contains no features"):
        measure(collection())


def test_features_without_the_id_field_fall_back_to_position() -> None:
    data = collection(
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-78.5000, 38.0000],
                        [-78.4990, 38.0000],
                        [-78.4990, 38.0010],
                        [-78.5000, 38.0000],
                    ]
                ],
            },
        }
    )

    assert measure(data).feature_ids == ("0",)


def test_geographic_analysis_crs_is_rejected() -> None:
    data = collection(
        polygon_feature(
            [
                [-78.5000, 38.0000],
                [-78.4990, 38.0000],
                [-78.4990, 38.0010],
                [-78.5000, 38.0000],
            ]
        )
    )

    with pytest.raises(GeometryError, match="must be projected"):
        measure(data, analysis_crs="EPSG:4326")


def test_area_conversion_follows_the_crs_unit() -> None:
    # A 100-metre square near Charlottesville is 10,000 m2; the same ring
    # measured through a US-survey-foot CRS must agree up to the two
    # projections' scale distortion (~0.04% here).
    x, y = 720_000.0, 4_212_000.0
    ring = [[x, y], [x + 100, y], [x + 100, y + 100], [x, y + 100], [x, y]]
    data = collection(polygon_feature(ring))
    metric = measure(data, source_crs="EPSG:26917", analysis_crs="EPSG:26917")
    feet = measure(data, source_crs="EPSG:26917", analysis_crs="EPSG:2284")

    assert metric.union_area_sq_ft == pytest.approx(107639.10416709722)
    assert feet.union_area_sq_ft == pytest.approx(metric.union_area_sq_ft, rel=1e-3)


def test_union_area_of_no_geometries_is_zero() -> None:
    assert union_area_sq_ft([], analysis_crs="EPSG:2284") == 0.0


class StubCRS:
    """Stands in for CRS metadata that no published EPSG code produces."""

    def __init__(self, axis_info: list[Any]) -> None:
        self.is_projected = True
        self.axis_info = axis_info

    def to_string(self) -> str:
        return "STUB"


def axis(unit_name: str, factor: float) -> Any:
    return SimpleNamespace(unit_name=unit_name, unit_conversion_factor=factor)


def test_crs_without_unit_metadata_is_rejected() -> None:
    stub = cast(CRS, StubCRS([]))

    with pytest.raises(GeometryError, match="no unit metadata"):
        _square_feet_per_native_square_unit(stub)


def test_crs_with_mixed_axis_units_is_rejected() -> None:
    stub = cast(
        CRS, StubCRS([axis("metre", 1.0), axis("US survey foot", 0.3048006096012192)])
    )

    with pytest.raises(GeometryError, match="mixes axis units"):
        _square_feet_per_native_square_unit(stub)
