from pathlib import Path

import pytest

from parking_footprint.config import ConfigError, load_config

HEADER = """
[audit]
id = "example"
name = "Example"
analysis_crs = "EPSG:2284"
"""


def write_config(tmp_path: Path, body: str, header: str = HEADER) -> Path:
    config = tmp_path / "audit.toml"
    config.write_text(header + body, encoding="utf-8")
    return config


MANUAL_LAYER = """
[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = 100
"""


def test_duplicate_comparison_ids_are_rejected(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        MANUAL_LAYER
        + """
[[layers]]
id = "building"
role = "building"
source_kind = "manual"
manual_area_sq_ft = 50

[[comparisons]]
id = "car_to_building"
numerator = "car_access"
denominator = "building"

[[comparisons]]
id = "car_to_building"
numerator = "building"
denominator = "car_access"
""",
    )

    with pytest.raises(ConfigError, match="duplicate comparison id"):
        load_config(config)


def test_layer_ids_must_be_safe_output_names(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "../outside"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = 100
""",
    )

    with pytest.raises(ConfigError, match="layer id"):
        load_config(config)


def test_duplicate_layer_ids_are_rejected(tmp_path: Path) -> None:
    config = write_config(tmp_path, MANUAL_LAYER + MANUAL_LAYER)

    with pytest.raises(ConfigError, match="duplicate layer id"):
        load_config(config)


def test_manual_areas_must_be_finite(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = nan
""",
    )

    with pytest.raises(ConfigError, match="finite, nonnegative"):
        load_config(config)


def test_manual_areas_must_be_numeric(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = "about an acre"
""",
    )

    with pytest.raises(ConfigError, match="finite, nonnegative"):
        load_config(config)


def test_manual_layers_require_an_area(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
""",
    )

    with pytest.raises(ConfigError, match="finite, nonnegative"):
        load_config(config)


def test_absolute_snapshot_paths_are_redacted_in_provenance_reference(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "private" / "parking.geojson"
    config = write_config(
        tmp_path,
        f"""
[[layers]]
id = "parking"
role = "car_access"
source_kind = "geojson"
snapshot = "{snapshot}"
""",
    )

    loaded = load_config(config)

    assert loaded.layers[0].snapshot == snapshot
    assert loaded.layers[0].snapshot_reference == "parking.geojson"


def test_object_ids_are_locked_in_numeric_order(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "parking"
role = "car_access"
source_kind = "arcgis"
source_url = "https://example.test/layer"
object_ids = [9, 10, 100, 2]
""",
    )

    assert load_config(config).layers[0].object_ids == ("2", "9", "10", "100")


def test_repeated_object_ids_are_rejected(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "parking"
role = "car_access"
source_kind = "arcgis"
source_url = "https://example.test/layer"
object_ids = [12019, 12019, 27864]
""",
    )

    with pytest.raises(ConfigError, match="repeats object_ids"):
        load_config(config)


def test_expected_feature_count_must_match_locked_object_ids(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "parking"
role = "car_access"
source_kind = "arcgis"
source_url = "https://example.test/layer"
object_ids = [1, 2]
expected_feature_count = 3
""",
    )

    with pytest.raises(ConfigError, match="locks 2 object_ids but expects 3"):
        load_config(config)


def test_expected_feature_count_must_be_nonnegative(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "parking"
role = "car_access"
source_kind = "arcgis"
source_url = "https://example.test/layer"
where = "1=1"
expected_feature_count = -1
""",
    )

    with pytest.raises(ConfigError, match="nonnegative expected_feature_count"):
        load_config(config)


def test_unknown_evidence_grades_are_rejected(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = 100
quality = "authoritative"
""",
    )

    with pytest.raises(ConfigError, match="unknown quality 'authoritative'"):
        load_config(config)


def test_captured_at_accepts_a_bare_toml_date(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = 100
captured_at = 2026-07-28
""",
    )

    assert load_config(config).layers[0].captured_at == "2026-07-28"


def test_captured_at_rejects_a_non_iso_value(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = 100
captured_at = "last summer"
""",
    )

    with pytest.raises(ConfigError, match="invalid captured_at"):
        load_config(config)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            """
[[layers]]
id = "parking"
role = "car_access"
source_kind = "arcgis"
""",
            "requires source_url",
        ),
        (
            """
[[layers]]
id = "parking"
role = "car_access"
source_kind = "arcgis"
source_url = "https://example.test/layer"
""",
            "requires object_ids or where",
        ),
        (
            """
[[layers]]
id = "parking"
role = "car_access"
source_kind = "geojson"
""",
            "requires snapshot",
        ),
        (
            """
[[layers]]
id = "parking"
role = "car_access"
source_kind = "wms"
""",
            "unsupported source_kind",
        ),
        (
            """
[[layers]]
role = "car_access"
source_kind = "manual"
""",
            "requires id, role, and source_kind",
        ),
        ("", "at least one layer is required"),
    ],
)
def test_layer_requirements(tmp_path: Path, body: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(write_config(tmp_path, body))


def test_audit_header_fields_are_required(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        MANUAL_LAYER,
        header='[audit]\nid = "example"\nname = "Example"\n',
    )

    with pytest.raises(ConfigError, match="analysis_crs are required"):
        load_config(config)


def test_comparisons_require_known_roles(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        MANUAL_LAYER
        + """
[[comparisons]]
id = "car_to_building"
numerator = "car_access"
denominator = "building"
""",
    )

    with pytest.raises(ConfigError, match="missing roles: \\['building'\\]"):
        load_config(config)


def test_comparisons_require_all_three_fields(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        MANUAL_LAYER
        + """
[[comparisons]]
id = "car_to_building"
numerator = "car_access"
""",
    )

    with pytest.raises(ConfigError, match="id, numerator, and denominator"):
        load_config(config)


def test_unparsable_toml_is_reported_as_a_configuration_error(tmp_path: Path) -> None:
    config = tmp_path / "audit.toml"
    config.write_text("[audit\nid = ", encoding="utf-8")

    with pytest.raises(ConfigError, match="not readable TOML"):
        load_config(config)
