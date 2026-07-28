from types import SimpleNamespace
from typing import Any

import pytest

from parking_footprint import sources
from parking_footprint.config import LayerSpec
from parking_footprint.sources import SourceError


def _feature(object_id: int) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id, "private_editor": "not retained"},
        "geometry": None,
    }


def test_arcgis_fetch_batches_ids_and_requests_the_configured_crs(
    monkeypatch,
) -> None:
    calls: list[dict[str, str]] = []

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
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url: str, params: dict[str, str]) -> FakeResponse:
            calls.append(dict(params))
            return FakeResponse(
                {
                    "objectIdFieldName": "OBJECTID",
                    "objectIds": [1, 2, 3],
                },
                len(calls),
            )

        def post(self, url: str, data: dict[str, str]) -> FakeResponse:
            calls.append(dict(data))
            object_ids = [int(value) for value in data["objectIds"].split(",")]
            return FakeResponse(
                {
                    "type": "FeatureCollection",
                    "features": [_feature(object_id) for object_id in object_ids],
                },
                len(calls),
            )

    monkeypatch.setattr(sources.httpx, "Client", lambda **kwargs: FakeClient())
    monkeypatch.setattr(sources, "ARCGIS_OBJECT_ID_BATCH_SIZE", 2)
    spec = LayerSpec(
        id="parking",
        role="car_access",
        source_kind="arcgis",
        source_url="https://example.test/layer",
        snapshot=None,
        object_ids=(),
        where="1=1",
        id_field="OBJECTID",
        source_crs="EPSG:2284",
        expected_feature_count=3,
        manual_area_sq_ft=None,
        quality="authoritative-local",
        note=None,
        evidence_url=None,
    )

    source = sources._fetch_arcgis(spec)

    assert [
        feature["properties"]["OBJECTID"] for feature in source.geojson["features"]
    ] == [
        1,
        2,
        3,
    ]
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

    class WrongIdClient(FakeClient):
        def post(self, url: str, data: dict[str, str]) -> FakeResponse:
            calls.append(dict(data))
            object_ids = [int(value) + 100 for value in data["objectIds"].split(",")]
            return FakeResponse(
                {
                    "type": "FeatureCollection",
                    "features": [_feature(object_id) for object_id in object_ids],
                },
                len(calls),
            )

    monkeypatch.setattr(
        sources.httpx,
        "Client",
        lambda **kwargs: WrongIdClient(),
    )
    with pytest.raises(SourceError, match="selected"):
        sources._fetch_arcgis(spec)
