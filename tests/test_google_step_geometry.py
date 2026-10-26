"""Google stop labels must not replace its authoritative route-step geometry."""

from __future__ import annotations

import pytest

from runorwalk.planner import plan_trip
from runorwalk.providers import parse_google_routes, point
from tests.test_planner import NOW, A, B, D, Stub, google_response


def _location(value):
    return {"latLng": {"latitude": value["lat"], "longitude": value["lng"]}}


def _route_with_offset_stop_metadata(*, native_egress_gap_m: float = 0):
    response = google_response()
    steps = response["routes"][0]["legs"][0]["steps"]
    transit_stops = steps[1]["transitDetails"]["stopDetails"]
    # Station/platform metadata can be some distance from a routed street point.
    transit_stops["departureStop"]["location"] = _location(
        point(B["lat"] + 0.0008, B["lng"], "First stop")
    )
    transit_stops["arrivalStop"]["location"] = _location(
        point(D["lat"] + 0.0008, D["lng"], "Destination stop")
    )
    destination = point(D["lat"] + 0.0015, D["lng"], "Final destination")
    egress_start = point(D["lat"] + native_egress_gap_m / 111_000, D["lng"])
    steps.append(
        {
            "travelMode": "WALK",
            "staticDuration": "120s",
            "distanceMeters": 150,
            "startLocation": _location(egress_start),
            "endLocation": _location(destination),
            "navigationInstruction": {"instructions": "Walk to Final destination"},
        }
    )
    return response, destination


def test_stop_metadata_offset_preserves_actual_transit_and_walking_endpoints():
    response, destination = _route_with_offset_stop_metadata()
    route = parse_google_routes(response, A, destination)[0]
    access, ride, egress = route.steps
    assert (access.end["lat"], access.end["lng"]) == (B["lat"], B["lng"])
    assert (ride.start["lat"], ride.start["lng"]) == (B["lat"], B["lng"])
    assert (ride.end["lat"], ride.end["lng"]) == (D["lat"], D["lng"])
    assert (egress.start["lat"], egress.start["lng"]) == (D["lat"], D["lng"])
    assert ride.start["name"] == "First stop"
    assert ride.end["name"] == "Destination"


@pytest.mark.asyncio
async def test_offset_station_metadata_does_not_discard_valid_walking_baseline():
    response, destination = _route_with_offset_stop_metadata()
    routes = parse_google_routes(response, A, destination)
    provider = Stub(lambda *_: routes)
    result = await plan_trip(A, destination, NOW, provider=provider, max_run_minutes=0)
    assert result["baseline"] is not None
    assert result["baseline"]["duration_s"] == 1020
    assert result["baseline"]["steps"][-1]["mode"] == "WALK"
    assert result["baseline"]["steps"][-1]["end"] == destination
    assert result["search"]["queries"] == 1


@pytest.mark.asyncio
async def test_native_provider_step_offset_does_not_trigger_cross_response_seam_guard():
    response, destination = _route_with_offset_stop_metadata(native_egress_gap_m=35)
    routes = parse_google_routes(response, A, destination)
    provider = Stub(lambda *_: routes)
    result = await plan_trip(A, destination, NOW, provider=provider, max_run_minutes=0)
    assert result["baseline"] is not None
    assert result["baseline"]["duration_s"] == 1020
    assert result["best"]["steps"][-1]["end"] == destination
    assert result["search"]["queries"] == 1
