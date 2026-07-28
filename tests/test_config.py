from pathlib import Path

import pytest

from parking_footprint.config import ConfigError, load_config


def test_duplicate_comparison_ids_are_rejected(tmp_path: Path) -> None:
    config = tmp_path / "audit.toml"
    config.write_text(
        """
[audit]
id = "duplicate-comparison"
name = "Duplicate comparison"
analysis_crs = "EPSG:2284"

[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = 100

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
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="duplicate comparison id"):
        load_config(config)


def test_layer_ids_must_be_safe_output_names(tmp_path: Path) -> None:
    config = tmp_path / "audit.toml"
    config.write_text(
        """
[audit]
id = "unsafe-layer"
name = "Unsafe layer"
analysis_crs = "EPSG:2284"

[[layers]]
id = "../outside"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = 100
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="layer id"):
        load_config(config)


def test_manual_areas_must_be_finite(tmp_path: Path) -> None:
    config = tmp_path / "audit.toml"
    config.write_text(
        """
[audit]
id = "non-finite-area"
name = "Non-finite area"
analysis_crs = "EPSG:2284"

[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = nan
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="finite, nonnegative"):
        load_config(config)


def test_absolute_snapshot_paths_are_redacted_in_provenance_reference(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "private" / "parking.geojson"
    config = tmp_path / "audit.toml"
    config.write_text(
        f"""
[audit]
id = "redacted-path"
name = "Redacted path"
analysis_crs = "EPSG:2284"

[[layers]]
id = "parking"
role = "car_access"
source_kind = "geojson"
snapshot = "{snapshot}"
""",
        encoding="utf-8",
    )

    loaded = load_config(config)

    assert loaded.layers[0].snapshot == snapshot
    assert loaded.layers[0].snapshot_reference == "parking.geojson"
