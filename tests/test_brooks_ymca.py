import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from parking_footprint import audit
from parking_footprint.audit import (
    AuditError,
    baseline_payload,
    run_audit,
    verify_against_baseline,
)
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


def test_failed_publish_restores_the_previous_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "result"
    run_audit(CONFIG, offline=True, output_dir=output)
    previous_audit = (output / "audit.json").read_bytes()

    real_replace = audit.os.replace
    calls: list[tuple[object, object]] = []

    def flaky_replace(src, dst):
        # Call 1 moves the old output aside; call 2 swaps the new result in and
        # is the one that must be recoverable; call 3 is the restore itself.
        calls.append((src, dst))
        if len(calls) == 2:
            raise OSError("simulated rename failure")
        return real_replace(src, dst)

    monkeypatch.setattr(audit.os, "replace", flaky_replace)

    with pytest.raises(OSError, match="simulated rename failure"):
        run_audit(CONFIG, offline=True, output_dir=output)

    assert len(calls) == 3
    assert (output / "audit.json").read_bytes() == previous_audit
    assert sorted(path.name for path in tmp_path.iterdir()) == ["result"]


def test_publish_refuses_a_filesystem_root(tmp_path: Path) -> None:
    with pytest.raises(AuditError, match="cannot be a filesystem root"):
        run_audit(CONFIG, offline=True, output_dir=Path(tmp_path.anchor))


def test_publish_refuses_an_output_path_that_is_a_file(tmp_path: Path) -> None:
    output = tmp_path / "result"
    output.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(AuditError, match="not a directory"):
        run_audit(CONFIG, offline=True, output_dir=output)

    assert output.read_text(encoding="utf-8") == "not a directory\n"


def test_provenance_records_the_snapshot_capture_date() -> None:
    result = run_audit(CONFIG, offline=True)

    captured = {
        layer["id"]: layer.get("captured_at")
        for layer in result["provenance"]["layers"]
    }

    assert captured["parking"] == "2026-07-28"
    assert captured["driveway"] == "2026-07-28"
    assert captured["building"] == "2026-07-28"
    # The illustrative bicycle scenario has no archived capture date.
    assert captured["bike_storage"] is None


def test_baseline_omits_manual_layers_from_source_hashes() -> None:
    payload = baseline_payload(run_audit(CONFIG, offline=True))

    assert set(payload["source_sha256"]) == {"parking", "driveway", "building"}


def test_verification_reports_missing_layers_roles_and_comparisons() -> None:
    result = run_audit(CONFIG, offline=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = deepcopy(result)
    changed["layers"] = [
        layer for layer in changed["layers"] if layer["id"] != "driveway"
    ]
    changed["roles"].pop("bike_storage")
    changed["roles"]["scooter_parking"] = dict(changed["roles"]["building"])
    changed["comparisons"].pop("car_to_bike")
    changed["comparisons"]["car_to_scooter"] = {
        "numerator": "car_access",
        "denominator": "scooter_parking",
        "ratio": 1.0,
    }
    changed["provenance"]["layers"] = [
        layer for layer in changed["provenance"]["layers"] if layer["id"] != "driveway"
    ]

    issues = verify_against_baseline(changed, baseline, area_tolerance_pct=0.1)

    assert "missing layer: driveway" in issues
    assert "missing source hash: driveway" in issues
    assert "missing role: bike_storage" in issues
    assert "unexpected role: scooter_parking" in issues
    assert "missing comparison: car_to_bike" in issues
    assert "unexpected comparison: car_to_scooter" in issues


def test_verification_reports_an_unexpected_source_hash() -> None:
    result = run_audit(CONFIG, offline=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = deepcopy(result)
    changed["provenance"]["layers"].append({"id": "extra", "sha256": "0" * 64})

    issues = verify_against_baseline(changed, baseline, area_tolerance_pct=0.1)

    assert "unexpected source hash: extra" in issues


def test_verification_reports_schema_and_audit_metadata_changes() -> None:
    result = run_audit(CONFIG, offline=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = deepcopy(result)
    changed["schema_version"] = result["schema_version"] + 1
    changed["audit"]["analysis_crs"] = "EPSG:26918"

    issues = verify_against_baseline(changed, baseline, area_tolerance_pct=0.1)

    assert any(issue.startswith("schema version changed") for issue in issues)
    assert any(issue.startswith("audit metadata changed") for issue in issues)


def test_verification_reports_a_comparison_that_became_undefined() -> None:
    result = run_audit(CONFIG, offline=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = deepcopy(result)
    changed["comparisons"]["car_to_building"]["ratio"] = None
    changed["comparisons"]["car_to_bike"]["denominator"] = "scooter_parking"

    issues = verify_against_baseline(changed, baseline, area_tolerance_pct=0.1)

    assert any("car_to_building: ratio changed" in issue for issue in issues)
    assert any("car_to_bike: denominator changed" in issue for issue in issues)


def test_verification_reports_a_nonnumeric_area() -> None:
    result = run_audit(CONFIG, offline=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = deepcopy(result)
    changed["layers"][0]["area_sq_ft"] = "not a number"

    issues = verify_against_baseline(changed, baseline, area_tolerance_pct=0.1)

    assert any("contains a nonnumeric value" in issue for issue in issues)


def test_verification_reports_a_changed_feature_count() -> None:
    result = run_audit(CONFIG, offline=True)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed = deepcopy(result)
    parking = next(layer for layer in changed["layers"] if layer["id"] == "parking")
    parking["feature_count"] = 3
    parking["feature_ids"] = ["12019", "27864", "28259"]

    issues = verify_against_baseline(changed, baseline, area_tolerance_pct=0.1)

    assert any("parking: feature count changed" in issue for issue in issues)
    assert any("parking: feature IDs changed" in issue for issue in issues)
