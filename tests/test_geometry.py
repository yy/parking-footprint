from parking_footprint.geometry import measure_feature_collection


def test_overlapping_features_are_unioned() -> None:
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"OBJECTID": 1},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-78.5000, 38.0000],
                            [-78.4990, 38.0000],
                            [-78.4990, 38.0010],
                            [-78.5000, 38.0010],
                            [-78.5000, 38.0000],
                        ]
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"OBJECTID": 2},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-78.4995, 38.0000],
                            [-78.4985, 38.0000],
                            [-78.4985, 38.0010],
                            [-78.4995, 38.0010],
                            [-78.4995, 38.0000],
                        ]
                    ],
                },
            },
        ],
    }

    measurement = measure_feature_collection(
        data,
        source_crs="EPSG:4326",
        analysis_crs="EPSG:2284",
        id_field="OBJECTID",
    )

    assert measurement.feature_ids == ("1", "2")
    assert measurement.union_area_sq_ft < measurement.summed_feature_area_sq_ft
    assert measurement.overlap_sq_ft > 0
