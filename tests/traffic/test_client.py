"""Unit tests for the TomTom client, with all HTTP calls faked.

No real network calls: `_client.get` is monkeypatched, matching the style
used for osmnx in tests/graph/test_download.py.
"""

import httpx
import pytest

from router.traffic.client import TomTomAPIError, TomTomClient

VALID_BODY = {
    "flowSegmentData": {
        "frc": "FRC2",
        "currentSpeed": 30,
        "freeFlowSpeed": 60,
        "currentTravelTime": 20,
        "freeFlowTravelTime": 10,
        "confidence": 0.9,
        "roadClosure": False,
        "coordinates": {
            "coordinate": [
                {"latitude": 45.43, "longitude": 10.99},
                {"latitude": 45.44, "longitude": 10.995},
            ]
        },
    }
}


def _fake_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=json_body, request=httpx.Request("GET", "http://x"))


def test_no_api_key_never_calls_network(monkeypatch):
    client = TomTomClient(api_key=None)

    def _fail_if_called(*_a, **_k):
        raise AssertionError("should not call the network with no API key")

    monkeypatch.setattr(client._client, "get", _fail_if_called)

    assert client.is_available is False
    assert client.get_flow_segment(45.0, 11.0) is None


def test_reads_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "env-key")
    client = TomTomClient()
    assert client.is_available is True
    assert client.api_key == "env-key"


def test_explicit_api_key_overrides_environment(monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "env-key")
    client = TomTomClient(api_key="explicit-key")
    assert client.api_key == "explicit-key"


def test_parses_a_valid_response(monkeypatch):
    client = TomTomClient(api_key="k")
    monkeypatch.setattr(client._client, "get", lambda *a, **k: _fake_response(200, VALID_BODY))

    segment = client.get_flow_segment(45.43, 10.99)

    assert segment is not None
    assert segment.current_speed_kph == 30
    assert segment.free_flow_speed_kph == 60
    assert segment.road_closure is False
    assert segment.coordinates == [(45.43, 10.99), (45.44, 10.995)]


def test_non_200_status_raises(monkeypatch):
    client = TomTomClient(api_key="k")
    monkeypatch.setattr(client._client, "get", lambda *a, **k: _fake_response(403, {}))

    with pytest.raises(TomTomAPIError):
        client.get_flow_segment(45.0, 11.0)


def test_malformed_body_raises(monkeypatch):
    client = TomTomClient(api_key="k")
    monkeypatch.setattr(
        client._client, "get", lambda *a, **k: _fake_response(200, {"unexpected": {}})
    )

    with pytest.raises(TomTomAPIError):
        client.get_flow_segment(45.0, 11.0)


def test_request_includes_point_and_key(monkeypatch):
    client = TomTomClient(api_key="secret", style="absolute", zoom=12)
    captured = {}

    def _capture(url, params=None, **_k):
        captured["url"] = url
        captured["params"] = params
        return _fake_response(200, VALID_BODY)

    monkeypatch.setattr(client._client, "get", _capture)
    client.get_flow_segment(45.43, 10.99)

    assert "absolute/12" in captured["url"]
    assert captured["params"]["key"] == "secret"
    assert captured["params"]["point"] == "45.43,10.99"
