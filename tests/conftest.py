"""Shared test helpers — synthetic Directions API response builders + fake backend."""

from __future__ import annotations

import datetime as dt
from collections import deque
from typing import Any

from runorwalk.google_directions import LatLng, Route, parse_routes


def make_step(
    *,
    travel_mode: str,
    duration_s: int,
    distance_m: int,
    start: tuple[float, float] = (47.41, 8.54),
    end: tuple[float, float] = (47.42, 8.55),
    transit_line: str | None = None,
    transit_departure_unix: int | None = None,
    transit_arrival_unix: int | None = None,
    departure_stop: str = "",
    arrival_stop: str = "",
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "travel_mode": travel_mode,
        "duration": {"value": duration_s, "text": f"{duration_s}s"},
        "distance": {"value": distance_m, "text": f"{distance_m}m"},
        "start_location": {"lat": start[0], "lng": start[1]},
        "end_location": {"lat": end[0], "lng": end[1]},
        "polyline": {"points": ""},
    }
    if travel_mode == "TRANSIT":
        assert transit_departure_unix is not None and transit_arrival_unix is not None
        step["transit_details"] = {
            "departure_stop": {
                "name": departure_stop,
                "location": {"lat": start[0], "lng": start[1]},
            },
            "arrival_stop": {
                "name": arrival_stop,
                "location": {"lat": end[0], "lng": end[1]},
            },
            "departure_time": {"value": transit_departure_unix, "text": "", "time_zone": "UTC"},
            "arrival_time": {"value": transit_arrival_unix, "text": "", "time_zone": "UTC"},
            "headsign": "",
            "line": {
                "name": transit_line or "",
                "short_name": transit_line or "",
                "vehicle": {"type": "TRAM", "name": "Tram"},
            },
            "num_stops": 1,
        }
    return step


def make_leg(
    *,
    steps: list[dict[str, Any]],
    departure_unix: int,
    arrival_unix: int,
) -> dict[str, Any]:
    return {
        "duration": {"value": arrival_unix - departure_unix, "text": ""},
        "distance": {"value": 1000, "text": ""},
        "start_location": steps[0]["start_location"],
        "end_location": steps[-1]["end_location"],
        "start_address": "Origin",
        "end_address": "Destination",
        "departure_time": {"value": departure_unix, "text": "", "time_zone": "UTC"},
        "arrival_time": {"value": arrival_unix, "text": "", "time_zone": "UTC"},
        "steps": steps,
    }


def make_route(legs: list[dict[str, Any]], summary: str = "") -> dict[str, Any]:
    return {"summary": summary, "legs": legs, "overview_polyline": {"points": ""}}


class FakeBackend:
    """Pops a pre-canned response off the queue for each .directions() call."""

    def __init__(self, responses: list[list[dict[str, Any]]]):
        self._queue: deque[list[dict[str, Any]]] = deque(responses)
        self.calls: list[dict[str, Any]] = []

    async def directions(
        self,
        origin: str | tuple[float, float] | LatLng,
        destination: str | tuple[float, float] | LatLng,
        *,
        mode: str = "transit",
        departure_time: dt.datetime | None = None,
        alternatives: bool = True,
    ) -> list[Route]:
        self.calls.append(
            {
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "departure_time": departure_time,
                "alternatives": alternatives,
            }
        )
        if not self._queue:
            return []
        return parse_routes(self._queue.popleft())
