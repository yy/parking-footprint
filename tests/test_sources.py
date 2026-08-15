import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from parking_footprint import sources
from parking_footprint.config import LayerSpec
from parking_footprint.sources import SourceError, load_source


def make_spec(**overrides: Any) -> LayerSpec:
    defaults: dict[str, Any] = {
        "id": "parking",
        "role": "car_access",
        "source_kind": "arcgis",
        "source_url": "https://example.test/layer",
        "snapshot": None,
        "object_ids": (),
        "where": "1=1",
        "id_field": "OBJECTID",
        "source_crs": "EPSG:4326",
        "expected_feature_count": None,
        "manual_area_sq_ft": None,
        "quality": "authoritative-local",
        "note": None,
        "evidence_url": None,
    }
    return LayerSpec(**{**defaults, **overrides})


def _feature(object_id: int) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id, "private_editor": "not retained"},
        "geometry": None,
    }


class FakeResponse:
    def __init__(self, payload: dict[str, Any], request_number: int) -> None:
        self._payload = payload
        self.request = SimpleNamespace(
            url=f"https://example.test/query?request={request_number}"
        )

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeClient:
    """An ArcGIS service that answers the selection and feature queries."""

    selection: ClassVar[dict[str, Any]] = {
        "objectIdFieldName": "OBJECTID",
        "objectIds": [1, 2, 3],
    }
    page_extra: ClassVar[dict[str, Any]] = {}

    def __init__(self, calls: list[dict[str, str]]) -> None:
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def get(self, url: str, params: dict[str, str]) -> FakeResponse:
        self.calls.append(dict(params))
        return FakeResponse(self.selection, len(self.calls))

    def features_for(self, object_ids: list[int]) -> list[dict[str, Any]]:
        return [_feature(object_id) for object_id in object_ids]

    def post(self, url: str, data: dict[str, str]) -> FakeResponse:
        self.calls.append(dict(data))
        object_ids = [int(value) for value in data["objectIds"].split(",")]
        return FakeResponse(
            {
                "type": "FeatureCollection",
                "features": self.features_for(object_ids),
                **self.page_extra,
            },
            len(self.calls),
        )


@pytest.fixture
def arcgis(monkeypatch):
    """Install a fake ArcGIS client and return the recorded request parameters."""
    calls: list[dict[str, str]] = []

    def install(client_class: type[FakeClient] = FakeClient) -> list[dict[str, str]]:
        monkeypatch.setattr(
            sources.httpx, "Client", lambda **kwargs: client_class(calls)
        )
        return calls

    install()
    return SimpleNamespace(install=install, calls=calls, monkeypatch=monkeypatch)


def test_arcgis_fetch_batches_ids_and_requests_the_configured_crs(arcgis) -> None:
    arcgis.monkeypatch.setattr(sources, "ARCGIS_OBJECT_ID_BATCH_SIZE", 2)
    spec = make_spec(source_crs="EPSG:2284", expected_feature_count=3)

    source = sources._fetch_arcgis(spec)

    calls = arcgis.calls
    assert [
        feature["properties"]["OBJECTID"] for feature in source.geojson["features"]
    ] == [1, 2, 3]
    assert calls[0]["returnIdsOnly"] == "true"
    assert calls[1]["outSR"] == "2284"
    assert calls[1]["outFields"] == "OBJECTID"
    assert "orderByFields" not in calls[1]
    assert calls[1]["objectIds"] == "1,2"
    assert calls[2]["objectIds"] == "3"
    assert len(source.provenance["request_urls"]) == 2
    assert source.provenance["selection_request_url"] is not None
    assert source.provenance["selected_object_id_field"] == "OBJECTID"
    assert source.provenance["selected_object_ids"] == ["1", "2", "3"]
    assert all(
        set(feature["properties"]) == {"OBJECTID"}
        for feature in source.geojson["features"]
    )


def test_online_provenance_records_when_the_data_was_fetched(arcgis) -> None:
    source = sources._fetch_arcgis(make_spec())

    assert source.provenance["captured_at"].endswith("+00:00")


def test_arcgis_rejects_features_it_did_not_select(arcgis) -> None:
    class WrongIdClient(FakeClient):
        def features_for(self, object_ids: list[int]) -> list[dict[str, Any]]:
            return [_feature(object_id + 100) for object_id in object_ids]

    arcgis.install(WrongIdClient)

    with pytest.raises(SourceError, match="selected"):
        sources._fetch_arcgis(make_spec())


def test_arcgis_rejects_a_truncated_batch(arcgis) -> None:
    class TruncatingClient(FakeClient):
        page_extra: ClassVar[dict[str, Any]] = {"exceededTransferLimit": True}

    arcgis.install(TruncatingClient)

    with pytest.raises(SourceError, match="truncated"):
        sources._fetch_arcgis(make_spec())


def test_arcgis_rejects_a_non_feature_collection(arcgis) -> None:
    class HtmlErrorClient(FakeClient):
        def post(self, url: str, data: dict[str, str]) -> FakeResponse:
            self.calls.append(dict(data))
            return FakeResponse({"error": {"code": 400}}, len(self.calls))

    arcgis.install(HtmlErrorClient)

    with pytest.raises(SourceError, match="did not return a GeoJSON FeatureCollection"):
        sources._fetch_arcgis(make_spec())


def test_arcgis_rejects_a_selection_without_object_ids(arcgis) -> None:
    class NoIdsClient(FakeClient):
        selection: ClassVar[dict[str, Any]] = {"objectIdFieldName": "OBJECTID"}

    arcgis.install(NoIdsClient)

    with pytest.raises(SourceError, match="did not return object IDs"):
        sources._fetch_arcgis(make_spec())


def test_arcgis_rejects_a_different_object_id_field(arcgis) -> None:
    class OtherFieldClient(FakeClient):
        selection: ClassVar[dict[str, Any]] = {
            "objectIdFieldName": "FID",
            "objectIds": [1],
        }

    arcgis.install(OtherFieldClient)

    with pytest.raises(SourceError, match="uses ArcGIS object ID field 'FID'"):
        sources._fetch_arcgis(make_spec())


def test_arcgis_rejects_features_missing_the_id_field(arcgis) -> None:
    class NoIdFieldClient(FakeClient):
        def features_for(self, object_ids: list[int]) -> list[dict[str, Any]]:
            return [
                {"type": "Feature", "properties": {"OTHER": 1}, "geometry": None}
                for _ in object_ids
            ]

    arcgis.install(NoIdFieldClient)

    with pytest.raises(SourceError, match="required ID field 'OBJECTID'"):
        sources._fetch_arcgis(make_spec())


def test_arcgis_requires_an_epsg_source_crs() -> None:
    spec = make_spec(source_crs="+proj=aeqd +lat_0=38 +lon_0=-78")

    with pytest.raises(SourceError, match="requires an EPSG source_crs"):
        sources._fetch_arcgis(spec)


def test_load_source_fetches_an_online_arcgis_layer(arcgis) -> None:
    source = load_source(make_spec(), offline=False)

    assert source.provenance["mode"] == "online"


def test_locked_object_ids_skip_the_selection_query(arcgis) -> None:
    source = sources._fetch_arcgis(make_spec(object_ids=("1", "2", "3"), where=None))

    assert "returnIdsOnly" not in arcgis.calls[0]
    assert source.provenance["selection_request_url"] is None
    assert source.provenance["request_parameters"]["objectIds"] == "1,2,3"


def write_snapshot(tmp_path: Path, payload: Any) -> Path:
    snapshot = tmp_path / "layer.geojson"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    return snapshot


def test_snapshot_provenance_reports_the_configured_capture_date(
    tmp_path: Path,
) -> None:
    snapshot = write_snapshot(tmp_path, {"type": "FeatureCollection", "features": []})
    spec = make_spec(
        source_kind="geojson",
        snapshot=snapshot,
        snapshot_reference="data/layer.geojson",
        captured_at="2026-07-28",
    )

    source = load_source(spec, offline=True)

    assert source.provenance["mode"] == "snapshot"
    assert source.provenance["captured_at"] == "2026-07-28"
    assert source.provenance["snapshot"] == "data/layer.geojson"


def test_snapshot_must_exist(tmp_path: Path) -> None:
    spec = make_spec(source_kind="geojson", snapshot=tmp_path / "absent.geojson")

    with pytest.raises(SourceError, match="cannot read its snapshot"):
        load_source(spec, offline=True)


def test_snapshot_must_be_valid_json(tmp_path: Path) -> None:
    snapshot = tmp_path / "layer.geojson"
    snapshot.write_text("{not json", encoding="utf-8")

    with pytest.raises(SourceError, match="not valid JSON"):
        load_source(make_spec(source_kind="geojson", snapshot=snapshot), offline=True)


def test_snapshot_must_be_a_feature_collection(tmp_path: Path) -> None:
    snapshot = write_snapshot(tmp_path, {"type": "Feature"})

    with pytest.raises(SourceError, match="did not return a GeoJSON FeatureCollection"):
        load_source(make_spec(source_kind="geojson", snapshot=snapshot), offline=True)


def test_snapshot_feature_count_must_match_the_lock(tmp_path: Path) -> None:
    snapshot = write_snapshot(
        tmp_path, {"type": "FeatureCollection", "features": [_feature(1)]}
    )
    spec = make_spec(source_kind="geojson", snapshot=snapshot, expected_feature_count=2)

    with pytest.raises(SourceError, match="returned 1 features; expected 2"):
        load_source(spec, offline=True)


def test_snapshot_feature_ids_must_match_the_lock(tmp_path: Path) -> None:
    snapshot = write_snapshot(
        tmp_path, {"type": "FeatureCollection", "features": [_feature(7)]}
    )
    spec = make_spec(source_kind="geojson", snapshot=snapshot, object_ids=("9",))

    with pytest.raises(SourceError, match=r"returned feature IDs \['7'\]"):
        load_source(spec, offline=True)


def test_offline_arcgis_layer_without_a_snapshot_is_rejected() -> None:
    with pytest.raises(SourceError, match="has no snapshot"):
        load_source(make_spec(), offline=True)


def test_manual_layers_have_no_geojson() -> None:
    with pytest.raises(SourceError, match="manual layers do not contain GeoJSON"):
        load_source(make_spec(source_kind="manual"), offline=False)


def test_unsupported_source_kind_is_rejected() -> None:
    with pytest.raises(SourceError, match="unsupported source kind"):
        load_source(make_spec(source_kind="wms"), offline=False)
