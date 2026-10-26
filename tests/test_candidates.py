import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from parking_footprint import candidates
from parking_footprint.candidates import find_candidates
from parking_footprint.cli import main
from parking_footprint.errors import SourceError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "brooks-ymca"
CONFIG = EXAMPLE / "audit.toml"


def snapshot_features(layer: str) -> list[dict[str, Any]]:
    data = json.loads((EXAMPLE / "data" / f"{layer}.geojson").read_text())
    return data["features"]


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeClient:
    """Answers each layer query with that layer's snapshot plus one extra feature."""

    calls: ClassVar[list[tuple[str, dict[str, str]]]] = []
    extra: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def get(self, url: str, params: dict[str, str]) -> FakeResponse:
        self.calls.append((url, dict(params)))
        layer = {"34": "parking", "33": "driveway", "59": "building"}[
            url.removesuffix("/query").rsplit("/", 1)[-1]
        ]
        features = snapshot_features(layer)
        if layer == "parking":
            extra = json.loads(json.dumps(features[0]))
            extra["properties"]["OBJECTID"] = 9
            features = [extra, *features]
        return FakeResponse(
            {"type": "FeatureCollection", "features": features, **self.extra}
        )


@pytest.fixture
def arcgis(monkeypatch):
    FakeClient.calls = []
    FakeClient.extra = {}
    monkeypatch.setattr(candidates.httpx, "Client", FakeClient)
    return FakeClient


def test_candidates_mark_locked_ids_and_reproduce_locked_areas(
    arcgis, tmp_path: Path
) -> None:
    found = find_candidates(
        CONFIG,
        longitude=-78.4787,
        latitude=38.0487,
        radius_ft=400,
        output_dir=tmp_path,
    )

    parking = [c for c in found if c.layer_id == "parking"]
    assert [c.feature_id for c in parking] == ["9", "12019", "27864", "28259", "28269"]
    assert [c.locked for c in parking] == [False, True, True, True, True]
    car_access = sum(
        c.area_sq_ft for c in found if c.locked and c.layer_id != "building"
    )
    assert car_access == pytest.approx(92_802.31, abs=0.01)

    params = arcgis.calls[0][1]
    assert params["geometry"] == "-78.4787,38.0487"
    assert params["inSR"] == "4326"
    assert params["distance"] == "400"
    assert params["units"] == "esriSRUnit_Foot"

    written = json.loads((tmp_path / "parking.geojson").read_text())
    assert written["features"][0]["properties"] == {
        "OBJECTID": "9",
        "area_sq_ft": round(parking[0].area_sq_ft, 2),
        "locked": False,
    }
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "building.geojson",
        "driveway.geojson",
        "parking.geojson",
    ]


def test_candidates_reject_truncated_search(arcgis) -> None:
    arcgis.extra = {"exceededTransferLimit": True}

    with pytest.raises(SourceError, match="smaller radius"):
        find_candidates(CONFIG, longitude=0, latitude=0, radius_ft=5_000)


def test_candidates_cli_prints_layers_in_config_order(
    arcgis, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "parking-footprint",
            "candidates",
            str(CONFIG),
            "--lat",
            "38.0487",
            "--lon",
            "-78.4787",
        ],
    )
    main()

    lines = capsys.readouterr().out.splitlines()
    headers = [line for line in lines if not line.startswith(" ")]
    assert headers == [
        "parking: 5 within 300 ft",
        "driveway: 1 within 300 ft",
        "building: 1 within 300 ft",
    ]
    assert lines[1].split() == ["9", "50,120.39", "sq", "ft"]
    assert lines[2].endswith("locked")
