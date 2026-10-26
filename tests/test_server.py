"""HTTP boundary checks for local requests, planner inputs, and key separation."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from runorwalk import server

VALID_JOURNEY = {
    "origin": "ETH Zürich",
    "destination": "Zürich Tiefenbrunnen",
    "departure": "2026-10-26T08:00:00+00:00",
    "mode": "demo",
    "profile_id": "young_athletic",
}


@pytest.fixture(scope="module")
def local_server():
    # An ephemeral port never conflicts with the user's local services.
    instance = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=5)


def request(instance, method="GET", path="/api/config", body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", instance.server_port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def post(instance, payload, headers=None):
    return request(
        instance,
        "POST",
        "/api/plan",
        json.dumps(payload),
        {"Content-Type": "application/json", **(headers or {})},
    )


def test_config_exposes_only_browser_key_and_reports_server_key_availability(
    local_server, monkeypatch
):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "private-server-key-do-not-return")
    monkeypatch.setenv("GOOGLE_MAPS_BROWSER_KEY", "public-referrer-restricted-browser-key")
    status, headers, body = request(local_server)
    data = json.loads(body)
    assert status == 200
    assert data["google_available"] is True
    assert data["google_browser_key"] == "public-referrer-restricted-browser-key"
    assert b"private-server-key" not in body
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert {profile["id"] for profile in data["profiles"]} == {
        "young_athletic",
        "young_casual",
        "forties",
        "older",
    }


def test_health_and_static_entry_point(local_server):
    status, _, body = request(local_server, path="/api/health")
    assert status == 200
    assert json.loads(body)["status"] == "ok"
    status, headers, body = request(local_server, path="/?origin=ETH%20Z%C3%BCrich")
    assert status == 200
    assert headers["Content-Type"] == "text/html"
    assert b'id="journey-form"' in body


@pytest.mark.parametrize("path", ["/../server.py", "/%2e%2e/server.py", "/%2e%2e/%2e%2e/.env"])
def test_static_paths_cannot_escape_static_directory(local_server, path):
    status, _, _ = request(local_server, path=path)
    assert status == 404


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "attacker.example"},
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
    ],
)
def test_cross_site_and_rebinding_requests_cannot_invoke_planner(
    local_server, monkeypatch, headers
):
    called = []

    async def forbidden(_body):
        called.append(True)
        raise AssertionError("Rejected request invoked the planner")

    monkeypatch.setattr(server, "create_plan", forbidden)
    status, _, _ = post(local_server, VALID_JOURNEY, headers)
    assert status == 403
    assert not called


def test_same_origin_json_reaches_planner_with_decoded_payload(local_server, monkeypatch):
    received = []

    async def fake_plan(body):
        received.append(body)
        return {"ok": True}

    monkeypatch.setattr(server, "create_plan", fake_plan)
    status, _, body = post(
        local_server,
        VALID_JOURNEY,
        {"Origin": f"http://127.0.0.1:{local_server.server_port}"},
    )
    assert status == 200
    assert json.loads(body) == {"ok": True}
    assert received == [VALID_JOURNEY]


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded"])
def test_non_json_posts_are_rejected(local_server, content_type):
    status, _, _ = post(local_server, VALID_JOURNEY, {"Content-Type": content_type})
    assert status == 415


@pytest.mark.parametrize("body", ["", "{invalid json", "x" * 16385])
def test_missing_malformed_and_oversized_bodies_return_400(local_server, body):
    status, _, response = request(
        local_server, "POST", "/api/plan", body, {"Content-Type": "application/json"}
    )
    assert status == 400
    assert "error" in json.loads(response)


@pytest.mark.parametrize("body", [None, [], "journey"])
def test_json_body_must_be_an_object(local_server, body):
    status, _, response = post(local_server, body)
    assert status == 400
    assert json.loads(response)["error"] == "Send a journey object."


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("origin", " "),
        ("destination", "x" * 301),
        ("origin", ["ETH Zürich"]),
        ("mode", "unknown"),
        ("profile_id", "unknown"),
        ("profile_id", 3),
        ("departure", "not a date"),
        ("departure", "2026-10-26T08:00:00"),
        ("vma_kmh", True),
        ("vma_kmh", float("nan")),
        ("max_run_minutes", 31),
        ("effort", 0.1),
        ("transfer_buffer_s", -1),
    ],
)
def test_invalid_journey_fields_are_rejected_before_provider_calls(local_server, field, value):
    status, _, body = post(local_server, {**VALID_JOURNEY, field: value})
    assert status == 400
    assert "error" in json.loads(body)


def test_missing_google_key_gives_setup_guidance(local_server, monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    status, _, body = post(local_server, {**VALID_JOURNEY, "mode": "google"})
    assert status == 400
    assert "not connected" in json.loads(body)["error"]


def test_provider_errors_do_not_echo_server_secrets(local_server, monkeypatch):
    async def broken_provider(_body):
        raise RuntimeError("request failed with key=private-server-key-do-not-return")

    monkeypatch.setattr(server, "create_plan", broken_provider)
    status, _, body = post(local_server, VALID_JOURNEY)
    assert status == 502
    assert b"private-server-key" not in body
    assert "unavailable" in json.loads(body)["error"]


def test_timeout_is_presented_as_retryable(local_server, monkeypatch):
    async def slow_provider(_body):
        raise TimeoutError

    monkeypatch.setattr(server, "create_plan", slow_provider)
    status, _, body = post(local_server, VALID_JOURNEY)
    assert status == 504
    assert "try again" in json.loads(body)["error"]


@pytest.mark.asyncio
async def test_each_ui_profile_returns_matching_pace_and_settings():
    for profile_id, vma in [
        ("young_athletic", 16),
        ("young_casual", 11),
        ("forties", 12),
        ("older", 9),
    ]:
        result = await server.create_plan({**VALID_JOURNEY, "profile_id": profile_id})
        assert result["profile"]["id"] == profile_id
        assert result["profile"]["vma_kmh"] == vma
        assert result["profile"]["run_speed_kmh"] == pytest.approx(vma * 0.65)
        assert result["settings"]["max_run_minutes"] == 10
        assert result["settings"]["transfer_buffer_s"] == 60
        assert result["mode"] == "demo"


@pytest.mark.parametrize("field", ["origin", "destination"])
@pytest.mark.parametrize(
    "coordinates",
    [
        {"lat": 47.3764, "lng": 8.5481, "name": "Current location"},
    ],
)
def test_demo_coordinates_cannot_be_silently_snapped_to_demo_places(
    local_server, field, coordinates
):
    status, _, body = post(local_server, {**VALID_JOURNEY, field: coordinates})
    assert status == 400
    assert "require Google Maps mode" in json.loads(body)["error"]


@pytest.mark.parametrize(
    "coordinates",
    [
        {},
        {"lat": 47.37},
        {"lng": 8.54},
        {"lat": True, "lng": 8.54},
        {"lat": 47.37, "lng": False},
        {"lat": "47.37", "lng": 8.54},
        {"lat": 91, "lng": 8.54},
        {"lat": -91, "lng": 8.54},
        {"lat": 47.37, "lng": 181},
        {"lat": 47.37, "lng": -181},
        {"lat": float("nan"), "lng": 8.54},
        {"lat": 47.37, "lng": float("inf")},
        {"lat": 47.37, "lng": 8.54, "name": None},
        {"lat": 47.37, "lng": 8.54, "name": ["Current location"]},
        {"lat": 47.37, "lng": 8.54, "name": "x" * 201},
    ],
)
def test_invalid_coordinate_objects_fail_before_google_provider_construction(
    local_server, monkeypatch, coordinates
):
    from runorwalk import providers

    def forbidden_provider(_key):
        raise AssertionError("Invalid coordinates reached the provider")

    monkeypatch.setattr(providers, "GoogleRoutesProvider", forbidden_provider)
    status, _, body = post(local_server, {**VALID_JOURNEY, "mode": "google", "origin": coordinates})
    assert status == 400
    assert "error" in json.loads(body)


@pytest.mark.parametrize("coordinate_field", ["origin", "destination"])
def test_google_provider_receives_exact_validated_coordinates(
    local_server, monkeypatch, coordinate_field
):
    import datetime as dt

    from runorwalk import providers

    coordinates = {"lat": 47.3764321, "lng": 8.5481234, "name": "Current location"}
    opposite = {"lat": 47.3505, "lng": 8.56145, "name": "Zürich Tiefenbrunnen"}
    calls = []

    class FakeGoogleProvider:
        mode = "google"

        def __init__(self, _key):
            pass

        async def routes(self, origin, destination, departure):
            calls.append((origin, destination))
            start = origin if isinstance(origin, dict) else opposite
            end = destination if isinstance(destination, dict) else opposite
            return [
                providers.TransitRoute(
                    (
                        providers.RouteStep(
                            "TRANSIT",
                            start,
                            end,
                            300,
                            1000,
                            departure=departure + dt.timedelta(seconds=120),
                            arrival=departure + dt.timedelta(seconds=420),
                        ),
                    )
                )
            ]

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key-for-mocked-provider")
    monkeypatch.setattr(providers, "GoogleRoutesProvider", FakeGoogleProvider)
    status, _, body = post(
        local_server,
        {
            **VALID_JOURNEY,
            "mode": "google",
            "departure": (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)).isoformat(),
            coordinate_field: coordinates,
            "max_run_minutes": 0,
        },
    )
    assert status == 200
    assert len(calls) == 1
    assert calls[0][0 if coordinate_field == "origin" else 1] == coordinates
    opposite_field = "destination" if coordinate_field == "origin" else "origin"
    assert calls[0][1 if coordinate_field == "origin" else 0] == VALID_JOURNEY[opposite_field]
    result = json.loads(body)
    assert result["mode"] == "google"
    assert result[coordinate_field] == coordinates
