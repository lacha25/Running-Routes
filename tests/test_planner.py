"""Behavior checks for scheduled transit, prefixes, running budgets and providers."""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest

from runorwalk.planner import plan_trip
from runorwalk.profiles import resolve_profile
from runorwalk.providers import (
    GoogleRoutesProvider,
    ProviderError,
    RouteStep,
    TransitRoute,
    parse_google_routes,
    point,
)

NOW = dt.datetime(2026, 10, 26, 8, tzinfo=dt.UTC)
A = point(47.37, 8.54, "Origin")
B = point(47.371, 8.54, "First stop")
C = point(47.372, 8.54, "Second stop")
D = point(47.373, 8.54, "Destination")


def walk(a, b, duration=300, distance=400):
    return RouteStep("WALK", a, b, duration, distance)


def transit(a, b, departure, arrival, line="4"):
    return RouteStep(
        "TRANSIT",
        a,
        b,
        arrival - departure,
        1000,
        departure=NOW + dt.timedelta(seconds=departure),
        arrival=NOW + dt.timedelta(seconds=arrival),
        line={"short_name": line, "name": line, "vehicle": "TRAM"},
    )


class Stub:
    mode = "test"

    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    async def routes(self, origin, destination, departure):
        self.calls.append((origin, destination, departure))
        return self.fn(origin, destination, departure)


@pytest.mark.asyncio
async def test_demo_finds_multiple_earlier_connections_and_preserves_complete_trip():
    result = await plan_trip("ETH Zürich", "Zürich Tiefenbrunnen", NOW)
    assert result["savings_s"] == 1200
    best = result["best"]
    assert best["transit_count"] == 2
    assert [s["mode"] for s in best["steps"]] == [
        "RUN",
        "WAIT",
        "TRANSIT",
        "RUN",
        "WAIT",
        "TRANSIT",
    ]
    assert best["steps"][0]["start"]["name"] == "ETH Zürich"
    assert best["steps"][-1]["end"]["name"] == "Zürich Tiefenbrunnen"
    assert best["run_duration_s"] < 600
    assert result["search"]["queries"] <= 12
    assert any("synthetic" in item for item in result["warnings"])
    for before, after in zip(best["steps"], best["steps"][1:], strict=False):
        assert before["end_time"] == after["start_time"]


@pytest.mark.asyncio
async def test_zero_budget_matches_walking_baseline_and_uses_one_request():
    result = await plan_trip("ETH Zürich", "Zürich Tiefenbrunnen", NOW, max_run_minutes=0)
    assert result["savings_s"] == 0
    assert result["best"]["run_duration_s"] == 0
    assert result["search"]["queries"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", [1, 3, 5, 7])
async def test_budget_is_cumulative_across_all_legs(minutes):
    result = await plan_trip("ETH Zürich", "Zürich Tiefenbrunnen", NOW, max_run_minutes=minutes)
    for route in result["alternatives"]:
        assert route["run_duration_s"] <= minutes * 60
        assert (
            sum(step["duration_s"] for step in route["steps"] if step["mode"] == "RUN")
            <= minutes * 60 + 0.02
        )


@pytest.mark.asyncio
async def test_baseline_is_earliest_arrival_even_if_provider_alternatives_are_unsorted():
    provider = Stub(
        lambda *_: [
            TransitRoute((transit(A, D, 600, 1000),)),
            TransitRoute((transit(A, D, 120, 500),)),
        ]
    )
    result = await plan_trip(A, D, NOW, provider=provider)
    assert result["baseline"]["duration_s"] == 500


@pytest.mark.asyncio
async def test_running_keeps_waiting_when_it_does_not_change_departure():
    provider = Stub(
        lambda origin, *_: (
            [TransitRoute((walk(A, B), transit(B, D, 600, 900)))]
            if origin == A
            else [TransitRoute((transit(B, D, 600, 900),))]
        )
    )
    result = await plan_trip(A, D, NOW, provider=provider)
    assert result["savings_s"] == 0
    assert result["best"]["run_duration_s"] == 0
    assert result["best"]["duration_s"] == 900


@pytest.mark.asyncio
async def test_initial_access_starts_at_requested_time_and_can_catch_earlier_departure():
    provider = Stub(
        lambda origin, *_: (
            [TransitRoute((walk(A, B, 600, 400), transit(B, D, 1200, 1500)))]
            if origin == A
            else [TransitRoute((transit(B, D, 300, 600),))]
        )
    )
    result = await plan_trip(A, D, NOW, provider=provider)
    assert result["best"]["duration_s"] == 600
    assert result["best"]["steps"][0]["start_time"] == NOW.isoformat()
    assert result["best"]["steps"][0]["start"] == A
    assert result["best"]["steps"][0]["mode"] == "RUN"
    assert provider.calls[1][2] < NOW + dt.timedelta(seconds=300)


@pytest.mark.asyncio
async def test_missed_connection_returned_by_provider_is_rejected_with_buffer():
    provider = Stub(
        lambda origin, *_: (
            [TransitRoute((walk(A, B, 600, 400), transit(B, D, 1200, 1500)))]
            if origin == A
            else [TransitRoute((transit(B, D, 200, 500),))]
        )
    )
    result = await plan_trip(A, D, NOW, provider=provider)
    assert result["savings_s"] == 0
    assert result["best"]["duration_s"] == 1500


@pytest.mark.asyncio
async def test_final_running_leg_can_save_time_without_a_further_transit_query():
    provider = Stub(lambda *_: [TransitRoute((transit(A, B, 120, 600), walk(B, D, 500, 400)))])
    result = await plan_trip(A, D, NOW, provider=provider)
    assert result["best"]["steps"][-1]["mode"] == "RUN"
    assert result["best"]["duration_s"] < 800
    assert result["search"]["queries"] == 1


@pytest.mark.asyncio
async def test_requery_preserves_transit_prefix_not_just_suffix():
    provider = Stub(
        lambda origin, *_: (
            [
                TransitRoute(
                    (transit(A, B, 120, 500), walk(B, C, 600, 400), transit(C, D, 1400, 1800))
                )
            ]
            if origin == A
            else [TransitRoute((transit(C, D, 800, 1100),))]
        )
    )
    result = await plan_trip(A, D, NOW, provider=provider)
    assert result["best"]["transit_count"] == 2
    assert result["best"]["duration_s"] == 1100
    assert result["best"]["steps"][0]["start"] == A
    assert result["best"]["run_duration_s"] > 0


@pytest.mark.asyncio
async def test_search_limit_is_explicit_and_enforced():
    result = await plan_trip("ETH Zürich", "Zürich Tiefenbrunnen", NOW, max_queries=1)
    assert result["search"]["queries"] == 1
    assert result["search"]["limit_reached"]
    assert any("search limit" in item.lower() for item in result["warnings"])


@pytest.mark.asyncio
async def test_secondary_service_error_keeps_a_complete_usable_route():
    class Failing(Stub):
        async def routes(self, origin, destination, departure):
            if self.calls:
                raise ProviderError("unavailable")
            return await super().routes(origin, destination, departure)

    provider = Failing(lambda *_: [TransitRoute((walk(A, B, 600, 400), transit(B, D, 1200, 1500)))])
    result = await plan_trip(A, D, NOW, provider=provider)
    assert result["best"]["steps"][-1]["end"] == D
    assert any("could not finish" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_demo_does_not_silently_substitute_unknown_addresses():
    with pytest.raises(ValueError, match="listed Zürich"):
        await plan_trip("Paris", "Zürich HB", NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_run_minutes": -1},
        {"transfer_buffer_s": float("nan")},
        {"vma_kmh": float("inf")},
        {"direct_pace_kmh": 0},
        {"effort": 1.1},
        {"profile_id": "unknown"},
        {"max_run_minutes": True},
    ],
)
async def test_invalid_inputs_fail_before_provider_call(kwargs):
    with pytest.raises(ValueError):
        await plan_trip("ETH Zürich", "Zürich Tiefenbrunnen", NOW, **kwargs)


@pytest.mark.asyncio
async def test_departure_requires_timezone():
    with pytest.raises(ValueError, match="timezone"):
        await plan_trip(A, D, NOW.replace(tzinfo=None))


def google_response():
    def location(p):
        return {"latLng": {"latitude": p["lat"], "longitude": p["lng"]}}

    return {
        "routes": [
            {
                "description": "Fixture",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "WALK",
                                "staticDuration": "300s",
                                "distanceMeters": 400,
                                "startLocation": location(A),
                                "endLocation": location(B),
                                "navigationInstruction": {"instructions": "Go to First stop"},
                            },
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "300s",
                                "distanceMeters": 1000,
                                "startLocation": location(B),
                                "endLocation": location(D),
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureTime": "2026-10-26T08:10:00Z",
                                        "arrivalTime": "2026-10-26T08:15:00Z",
                                        "departureStop": {
                                            "name": "First stop",
                                            "location": location(B),
                                        },
                                        "arrivalStop": {
                                            "name": "Destination",
                                            "location": location(D),
                                        },
                                    },
                                    "transitLine": {
                                        "name": "Tram 4",
                                        "nameShort": "4",
                                        "vehicle": {"type": "TRAM"},
                                    },
                                    "headsign": "Tiefenbrunnen",
                                    "stopCount": 3,
                                },
                            },
                        ]
                    }
                ],
            }
        ]
    }


def test_google_v2_parser_preserves_schedule_and_stops():
    routes = parse_google_routes(google_response(), "Origin", "Destination")
    assert len(routes) == 1
    assert routes[0].steps[0].duration_s == 300
    assert routes[0].steps[0].end["name"] == "First stop"
    assert routes[0].steps[1].departure == NOW + dt.timedelta(minutes=10)
    assert routes[0].steps[1].line["short_name"] == "4"


def test_google_v2_missing_schedule_is_not_invented():
    response = google_response()
    del response["routes"][0]["legs"][0]["steps"][1]["transitDetails"]["stopDetails"][
        "departureTime"
    ]
    assert parse_google_routes(response, "Origin", "Destination") == []


@pytest.mark.asyncio
async def test_google_v2_http_contract_keeps_key_in_header():
    def handle(request):
        assert request.url.path == "/directions/v2:computeRoutes"
        assert request.headers["x-goog-api-key"] == "test-private-key"
        body = json.loads(request.content)
        assert body["travelMode"] == "TRANSIT"
        assert body["computeAlternativeRoutes"] is True
        assert body["departureTime"] == "2026-10-26T08:00:00Z"
        assert "test-private-key" not in str(request.url)
        return httpx.Response(200, json=google_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = GoogleRoutesProvider("test-private-key", client=client)
        routes = await provider.routes(A, D, NOW)
        assert routes[0].steps[1].arrival == NOW + dt.timedelta(minutes=15)


def test_profile_assumptions_and_custom_speed_are_explicit():
    profile = resolve_profile("young_athletic")
    assert profile["run_speed_kmh"] == 10.4
    assert "not measured population averages" in profile["note"]
    assert resolve_profile("older", direct_pace_kmh=8)["run_speed_kmh"] == 8


@pytest.mark.asyncio
async def test_tight_baseline_transfer_is_requeried_with_margin_and_full_prefix():
    provider = Stub(
        lambda origin, *_: (
            [
                TransitRoute(
                    (transit(A, B, 120, 500), walk(B, C, 300, 200), transit(C, D, 830, 1100))
                )
            ]
            if origin == A
            else [TransitRoute((transit(C, D, 1200, 1500),))]
        )
    )
    result = await plan_trip(A, D, NOW, provider=provider, max_run_minutes=0, transfer_buffer_s=60)
    assert result["baseline"]["duration_s"] == 1500
    assert result["baseline"]["transit_count"] == 2
    assert result["baseline"]["steps"][0]["start"] == A
    assert result["baseline"]["steps"][-1]["end"] == D
    assert result["search"]["queries"] == 2


@pytest.mark.asyncio
async def test_running_does_not_exceed_per_leg_distance_cap():
    provider = Stub(lambda *_: [TransitRoute((transit(A, B, 120, 500), walk(B, D, 1500, 2000)))])
    result = await plan_trip(A, D, NOW, provider=provider, max_run_minutes=30)
    assert result["best"]["run_duration_s"] == 0


@pytest.mark.asyncio
async def test_disconnected_suffix_is_rejected_instead_of_teleporting():
    faraway = point(48, 9, "Unrelated station")
    provider = Stub(
        lambda origin, *_: (
            [TransitRoute((walk(A, B, 600, 400), transit(B, D, 1200, 1500)))]
            if origin == A
            else [TransitRoute((transit(faraway, D, 300, 600),))]
        )
    )
    result = await plan_trip(A, D, NOW, provider=provider)
    assert result["savings_s"] == 0


@pytest.mark.asyncio
async def test_last_train_running_route_survives_when_no_walking_baseline_exists():
    provider = Stub(
        lambda origin, *_: (
            [
                TransitRoute(
                    (transit(A, B, 120, 500), walk(B, C, 300, 200), transit(C, D, 830, 1100))
                )
            ]
            if origin == A
            else []
        )
    )
    result = await plan_trip(A, D, NOW, provider=provider, transfer_buffer_s=60)
    assert result["best"]["duration_s"] == 1100
    assert result["best"]["run_duration_s"] > 0
    assert result["best"]["transit_count"] == 2
    assert result["baseline"] is None
    assert result["savings_s"] is None
    assert any("No feasible walking comparison" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_timezone_dst_transition_uses_elapsed_time_not_wall_clock_arithmetic():
    from zoneinfo import ZoneInfo

    departure = dt.datetime(2026, 10, 25, 2, 59, tzinfo=ZoneInfo("Europe/Zurich"))
    provider = Stub(lambda *_: [TransitRoute((walk(A, D, 120, 100),))])
    result = await plan_trip(A, D, departure, provider=provider, max_run_minutes=0)
    route = result["best"]
    elapsed = dt.datetime.fromisoformat(route["arrival"]).timestamp() - departure.timestamp()
    assert elapsed == route["duration_s"] == 120


@pytest.mark.asyncio
async def test_short_but_nontrivial_unconnected_suffix_is_rejected():
    nearby_but_separate = point(B["lat"] + 0.0008, B["lng"], "Across the road")
    provider = Stub(
        lambda origin, *_: (
            [TransitRoute((walk(A, B, 600, 400), transit(B, D, 1200, 1500)))]
            if origin == A
            else [TransitRoute((transit(nearby_but_separate, D, 300, 600),))]
        )
    )
    result = await plan_trip(A, D, NOW, provider=provider)
    assert result["savings_s"] == 0


@pytest.mark.asyncio
async def test_provider_warnings_and_approximate_geometry_are_preserved():
    response = google_response()
    response["routes"][0]["warnings"] = ["A pedestrian crossing is temporarily closed."]
    routes = parse_google_routes(response, "Origin", "Destination")
    provider = Stub(lambda *_: routes)
    result = await plan_trip(A, D, NOW, provider=provider, max_run_minutes=0)
    assert "A pedestrian crossing is temporarily closed." in result["warnings"]
    assert any("lack detailed geometry" in warning for warning in result["warnings"])
    assert "routes.warnings" in GoogleRoutesProvider.field_mask
