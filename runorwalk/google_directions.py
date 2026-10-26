"""Async wrapper + Pydantic models for the Google Directions API.

The googlemaps SDK is synchronous; we wrap calls in asyncio.to_thread() to
keep the bot's event loop responsive. Raw dict responses are parsed into
typed Route/Leg/Step models so the rest of the codebase never touches dicts.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Literal, cast

import googlemaps
from pydantic import BaseModel, ConfigDict, Field

TravelMode = Literal["WALKING", "TRANSIT", "DRIVING", "BICYCLING", "OTHER"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class LatLng(_Base):
    lat: float
    lng: float

    def as_tuple(self) -> tuple[float, float]:
        return (self.lat, self.lng)


class _DurationField(_Base):
    """A {"value": <seconds>, "text": "..."} block."""

    value: int  # seconds
    text: str = ""


class _DistanceField(_Base):
    """A {"value": <meters>, "text": "..."} block."""

    value: int  # meters
    text: str = ""


class _TimeField(_Base):
    """A {"value": <unix>, "text": "...", "time_zone": "..."} block."""

    value: int  # unix seconds
    text: str = ""
    time_zone: str = ""

    def to_datetime(self) -> dt.datetime:
        tz = dt.UTC
        return dt.datetime.fromtimestamp(self.value, tz=tz)


class TransitStop(_Base):
    name: str = ""
    location: LatLng


class TransitLineVehicle(_Base):
    type: str = ""
    name: str = ""


class TransitLine(_Base):
    name: str = ""
    short_name: str = ""
    vehicle: TransitLineVehicle = Field(default_factory=TransitLineVehicle)


class TransitDetails(_Base):
    departure_stop: TransitStop
    arrival_stop: TransitStop
    departure_time: _TimeField
    arrival_time: _TimeField
    headsign: str = ""
    line: TransitLine = Field(default_factory=TransitLine)
    num_stops: int = 0


class Step(_Base):
    travel_mode: TravelMode
    duration: _DurationField
    distance: _DistanceField
    start_location: LatLng
    end_location: LatLng
    html_instructions: str = ""
    polyline_points: str = ""
    transit_details: TransitDetails | None = None
    # Computed during parsing — unix seconds at which this step starts.
    start_time_unix: int = 0

    @property
    def duration_s(self) -> int:
        return self.duration.value

    @property
    def distance_m(self) -> int:
        return self.distance.value

    @property
    def start_time(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.start_time_unix, tz=dt.UTC)

    @property
    def end_time(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.start_time_unix + self.duration_s, tz=dt.UTC)


class Leg(_Base):
    duration: _DurationField
    distance: _DistanceField
    start_location: LatLng
    end_location: LatLng
    start_address: str = ""
    end_address: str = ""
    departure_time: _TimeField | None = None
    arrival_time: _TimeField | None = None
    steps: list[Step] = Field(default_factory=list)


class Route(_Base):
    summary: str = ""
    legs: list[Leg]
    overview_polyline_points: str = ""

    @property
    def total_duration_s(self) -> int:
        return sum(leg.duration.value for leg in self.legs)

    @property
    def arrival_time(self) -> dt.datetime | None:
        last = self.legs[-1] if self.legs else None
        if last is None or last.arrival_time is None:
            return None
        return last.arrival_time.to_datetime()

    @property
    def departure_time(self) -> dt.datetime | None:
        first = self.legs[0] if self.legs else None
        if first is None or first.departure_time is None:
            return None
        return first.departure_time.to_datetime()


def parse_routes(raw: list[dict[str, Any]]) -> list[Route]:
    """Convert a raw Directions API response (list of route dicts) into typed
    Route objects. Computes per-step start_time_unix by accumulating durations
    from each leg's departure_time.
    """
    routes: list[Route] = []
    for raw_route in raw:
        legs_in: list[dict[str, Any]] = raw_route.get("legs", [])
        legs_out: list[Leg] = []
        for raw_leg in legs_in:
            steps_in: list[dict[str, Any]] = raw_leg.get("steps", [])
            cursor: int | None = None
            dep = raw_leg.get("departure_time")
            if dep is not None:
                cursor = int(dep["value"])
            normalized_steps: list[dict[str, Any]] = []
            for raw_step in steps_in:
                rs = dict(raw_step)
                # Flatten polyline.points → polyline_points so Pydantic can read it.
                pl = rs.get("polyline")
                if isinstance(pl, dict) and "points" in pl:
                    rs["polyline_points"] = pl["points"]
                # Step start time: prefer transit_details.departure_time if present;
                # otherwise use the running cursor inherited from the leg.
                td = rs.get("transit_details")
                if isinstance(td, dict) and "departure_time" in td:
                    cursor = int(td["departure_time"]["value"])
                rs["start_time_unix"] = cursor or 0
                if cursor is not None:
                    cursor += int(rs["duration"]["value"])
                normalized_steps.append(rs)
            leg_dict = dict(raw_leg)
            leg_dict["steps"] = normalized_steps
            legs_out.append(Leg.model_validate(leg_dict))
        overview = raw_route.get("overview_polyline", {})
        routes.append(
            Route(
                summary=raw_route.get("summary", ""),
                legs=legs_out,
                overview_polyline_points=overview.get("points", "")
                if isinstance(overview, dict)
                else "",
            )
        )
    return routes


def _format_location(loc: str | tuple[float, float] | LatLng) -> str | tuple[float, float]:
    """Convert any of our location types into something googlemaps accepts."""
    if isinstance(loc, LatLng):
        return loc.as_tuple()
    return loc


class DirectionsClient:
    """Thin async wrapper around googlemaps.Client.directions."""

    def __init__(self, api_key: str) -> None:
        self._client = googlemaps.Client(key=api_key)

    async def directions(
        self,
        origin: str | tuple[float, float] | LatLng,
        destination: str | tuple[float, float] | LatLng,
        *,
        mode: str = "transit",
        departure_time: dt.datetime | None = None,
        alternatives: bool = True,
    ) -> list[Route]:
        kwargs: dict[str, Any] = {
            "origin": _format_location(origin),
            "destination": _format_location(destination),
            "mode": mode,
            "alternatives": alternatives,
        }
        if departure_time is not None:
            kwargs["departure_time"] = departure_time

        raw = await asyncio.to_thread(self._client.directions, **kwargs)
        return parse_routes(cast(list[dict[str, Any]], raw))
