import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from parking_footprint import audit
from parking_footprint.audit import run_audit, verify_against_baseline
from parking_footprint.sources import SourceError

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "brooks-ymca" / "audit.toml"
BASELINE = ROOT / "examples" / "brooks-ymca" / "baseline.json"


def test_offline_example_matches_baseline(tmp_path: Path) -> None:
    result = run_audit(CONFIG, offline=True, output_dir=tmp_path)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    issues = verify_against_baseline(
        result,
        baseline,
        area_tolerance_pct=0.1,
    )

    assert issues == []
    assert result["comparisons"]["car_to_building"]["ratio"] > 1
    assert result["comparisons"]["car_to_bike"]["ratio"] > 100
    assert (tmp_path / "audit.json").exists()
    assert (tmp_path / "provenance.json").exists()

    source_paths = sorted((tmp_path / "sources").glob("*.geojson"))
    assert [path.stem for path in source_paths] == [
        "building",
        "driveway",
        "parking",
    ]
    provenance_by_id = {layer["id"]: layer for layer in result["provenance"]["layers"]}
    result_layers = {layer["id"]: layer for layer in result["layers"]}
    assert result["provenance"]["config_path"] == "audit.toml"
    assert baseline["config_sha256"] == result["provenance"]["config_sha256"]
    assert baseline["source_sha256"] == {
        layer_id: provenance["sha256"]
        for layer_id, provenance in provenance_by_id.items()
        if "sha256" in provenance
    }
    for path in source_paths:
        source_bytes = path.read_bytes().removesuffix(b"\n")
        provenance = provenance_by_id[path.stem]
        assert not Path(provenance["snapshot"]).is_absolute()
        assert hashlib.sha256(source_bytes).hexdigest() == provenance["sha256"]
        assert (
            provenance["locked_object_ids"] == result_layers[path.stem]["feature_ids"]
        )

    (tmp_path / "sources" / "stale.geojson").write_text(
        "{}\n",
        encoding="utf-8",
    )
    rerun = run_audit(CONFIG, offline=True, output_dir=tmp_path)
    assert (
        verify_against_baseline(
            rerun,
            baseline,
            area_tolerance_pct=0.1,
        )
        == []
    )
    assert not (tmp_path / "sources" / "stale.geojson").exists()

    unmanaged = tmp_path / "notes.txt"
    unmanaged.write_text("keep me\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unmanaged entries"):
        run_audit(CONFIG, offline=True, output_dir=tmp_path)
    assert unmanaged.read_text(encoding="utf-8") == "keep me\n"


def test_verification_rejects_changes_outside_existing_layer_areas() -> None:
    result = run_audit(CONFIG, offline=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = deepcopy(result)
    changed["layers"][0]["role"] = "building"
    changed["layers"].append(
        {
            "id": "extra",
            "role": "car_access",
            "area_sq_ft": 999_999,
        }
    )
    changed["roles"]["car_access"]["area_sq_ft"] += 999_999
    changed["comparisons"]["car_to_building"]["ratio"] = 999

    issues = verify_against_baseline(
        changed,
        baseline,
        area_tolerance_pct=0.1,
    )

    assert "unexpected layer: extra" in issues
    assert "parking: role changed from car_access to building" in issues
    assert any(issue.startswith("car_access: area_sq_ft changed") for issue in issues)
    assert any(issue.startswith("car_to_building: ratio changed") for issue in issues)


def test_verification_rejects_configuration_and_source_hash_changes() -> None:
    result = run_audit(CONFIG, offline=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = deepcopy(result)
    changed["provenance"]["config_sha256"] = "0" * 64
    changed["provenance"]["layers"][0]["sha256"] = "1" * 64

    issues = verify_against_baseline(
        changed,
        baseline,
        area_tolerance_pct=0.1,
    )

    assert any(issue.startswith("configuration hash changed") for issue in issues)
    assert any(issue.startswith("parking: source hash changed") for issue in issues)


def test_verification_rejects_non_finite_numbers() -> None:
    result = run_audit(CONFIG, offline=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="finite and nonnegative"):
        verify_against_baseline(
            result,
            baseline,
            area_tolerance_pct=float("nan"),
        )

    changed = deepcopy(result)
    changed["layers"][0]["area_sq_ft"] = float("nan")
    issues = verify_against_baseline(
        changed,
        baseline,
        area_tolerance_pct=0.1,
    )
    assert any("contains a non-finite value" in issue for issue in issues)


def test_failed_run_preserves_previous_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_audit(CONFIG, offline=True, output_dir=tmp_path)
    previous_audit = (tmp_path / "audit.json").read_bytes()
    previous_sources = {
        path.name: path.read_bytes() for path in (tmp_path / "sources").iterdir()
    }

    def fail_to_load(*args, **kwargs):
        raise SourceError("simulated source failure")

    monkeypatch.setattr(audit, "load_source", fail_to_load)
    with pytest.raises(SourceError, match="simulated"):
        run_audit(CONFIG, offline=True, output_dir=tmp_path)

    assert (tmp_path / "audit.json").read_bytes() == previous_audit
    assert {
        path.name: path.read_bytes() for path in (tmp_path / "sources").iterdir()
    } == previous_sources
