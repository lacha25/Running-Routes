"""Transit provider contract and server-side Google Routes API v2 adapter."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

import httpx

Point = dict[str, Any]
Location = str | Point


class ProviderError(RuntimeError):
    """A presentable routing service failure."""


@dataclass(frozen=True)
class RouteStep:
    mode: str
    start: Point
    end: Point
    duration_s: float
    distance_m: float
    instruction: str = ""
    departure: dt.datetime | None = None
    arrival: dt.datetime | None = None
    line: dict[str, Any] | None = None
    path: list[Point] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    geometry_approximate: bool = False


@dataclass(frozen=True)
class TransitRoute:
    steps: tuple[RouteStep, ...]
    label: str = "Transit route"
    warnings: tuple[str, ...] = ()


class TransitProvider(Protocol):
    mode: str

    async def routes(
        self, origin: Location, destination: Location, departure: dt.datetime
    ) -> list[TransitRoute]: ...


def point(lat: float, lng: float, name: str = "") -> Point:
    lat, lng = float(lat), float(lng)
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("Coordinates must be valid latitude and longitude.")
    return {"lat": lat, "lng": lng, "name": name}


def normalize_location(value: Location) -> Location:
    if isinstance(value, dict):
        try:
            return point(value["lat"], value["lng"], str(value.get("name", ""))[:200])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Use a place name or valid latitude and longitude.") from exc
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("Enter an origin and destination (up to 500 characters each).")
    parts = value.split(",")
    if len(parts) == 2:
        try:
            lat, lng = float(parts[0]), float(parts[1])
        except ValueError:
            pass
        else:
            return point(lat, lng, value.strip())
    return value.strip()


def distance_between(a: Point, b: Point) -> float:
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dl = math.radians(b["lng"] - a["lng"])
    term = (
        math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dl / 2) ** 2
    )
    return 6371000 * 2 * math.asin(min(1, math.sqrt(term)))


def merge_walks(steps: list[RouteStep]) -> tuple[RouteStep, ...]:
    """Group street instructions into one access/transfer/egress leg."""
    merged: list[RouteStep] = []
    for step in steps:
        if step.mode == "WALK" and merged and merged[-1].mode == "WALK":
            previous = merged.pop()
            merged.append(
                replace(
                    previous,
                    end=step.end,
                    duration_s=previous.duration_s + step.duration_s,
                    distance_m=previous.distance_m + step.distance_m,
                    path=previous.path + step.path,
                    directions=previous.directions + step.directions,
                    instruction=f"Walk to {step.end.get('name') or 'the next stop'}",
                    geometry_approximate=previous.geometry_approximate or step.geometry_approximate,
                )
            )
        else:
            merged.append(step)
    return tuple(merged)


def decode_polyline(encoded: str) -> list[Point]:
    points: list[Point] = []
    cursor = lat = lng = 0
    try:
        while cursor < len(encoded):
            coords = []
            for _ in range(2):
                result = shift = 0
                while True:
                    value = ord(encoded[cursor]) - 63
                    cursor += 1
                    if not 0 <= value <= 63 or shift > 35:
                        raise ValueError("Invalid route geometry")
                    result |= (value & 31) << shift
                    shift += 5
                    if value < 32:
                        break
                coords.append(~(result >> 1) if result & 1 else result >> 1)
            lat += coords[0]
            lng += coords[1]
            points.append(point(lat / 1e5, lng / 1e5))
    except (IndexError, ValueError):
        return []
    return points


def _google_point(location: dict[str, Any], name: str = "") -> Point:
    coords = location["latLng"]
    # Protobuf JSON can omit scalar fields whose value is zero.
    return point(coords.get("latitude", 0.0), coords.get("longitude", 0.0), name)


def _timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Transit schedule has no timezone")
    return parsed


def _duration(value: str | None) -> float:
    duration = float((value or "0s").removesuffix("s"))
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("Invalid transit duration")
    return duration


def parse_google_routes(
    data: dict[str, Any], origin: Location, destination: Location
) -> list[TransitRoute]:
    if not isinstance(data, dict) or not isinstance(data.get("routes", []), list):
        raise ValueError("Invalid routing response")
    results = []
    for route in data.get("routes", []):
        if not isinstance(route, dict):
            continue
        steps = []
        try:
            for leg in route.get("legs", []):
                for raw in leg.get("steps", []):
                    mode = raw.get("travelMode")
                    if mode not in {"WALK", "TRANSIT"}:
                        raise ValueError("Unsupported route segment")
                    start, end = (
                        _google_point(raw["startLocation"]),
                        _google_point(raw["endLocation"]),
                    )
                    instruction = raw.get("navigationInstruction", {}).get("instructions", "")
                    duration = _duration(raw.get("staticDuration"))
                    departure = arrival = line = None
                    if mode == "TRANSIT":
                        transit = raw["transitDetails"]
                        stops = transit["stopDetails"]
                        departure, arrival = (
                            _timestamp(stops["departureTime"]),
                            _timestamp(stops["arrivalTime"]),
                        )
                        if arrival < departure:
                            raise ValueError("Invalid schedule")
                        # Route-step endpoints describe the travelled path. A
                        # transit stop's map marker can be tens of metres away
                        # (e.g. a station centroid instead of a platform exit).
                        # Keep routing geometry; copy only the display names.
                        start = {**start, "name": stops["departureStop"].get("name", "")}
                        end = {**end, "name": stops["arrivalStop"].get("name", "")}
                        duration = (arrival - departure).total_seconds()
                        service = transit.get("transitLine", {})
                        line = {
                            "name": service.get("name", "Transit"),
                            "short_name": service.get("nameShort", ""),
                            "color": service.get("color", "#167c80"),
                            "vehicle": service.get("vehicle", {}).get("type", "TRANSIT"),
                            "headsign": transit.get("headsign", ""),
                            "stop_count": transit.get("stopCount", 0),
                            "agencies": service.get("agencies", []),
                        }
                        instruction = f"Take {line['short_name'] or line['name']} towards {line['headsign'] or end['name']}"
                    path = decode_polyline(raw.get("polyline", {}).get("encodedPolyline", ""))
                    distance = float(raw.get("distanceMeters", 0))
                    if not math.isfinite(distance) or distance < 0:
                        raise ValueError("Invalid route distance")
                    steps.append(
                        RouteStep(
                            mode,
                            start,
                            end,
                            duration,
                            distance,
                            instruction,
                            departure,
                            arrival,
                            line,
                            path or [start, end],
                            [instruction] if instruction else [],
                            not path,
                        )
                    )
            if not steps:
                continue
            origin_name = origin if isinstance(origin, str) else origin.get("name", "")
            destination_name = (
                destination if isinstance(destination, str) else destination.get("name", "")
            )
            if not steps[0].start.get("name"):
                steps[0] = replace(steps[0], start={**steps[0].start, "name": origin_name})
            if not steps[-1].end.get("name"):
                steps[-1] = replace(steps[-1], end={**steps[-1].end, "name": destination_name})
            # Label street legs using adjacent stops without replacing their
            # coordinates or changing their distance / duration.
            for index, step in enumerate(steps):
                if step.mode != "WALK":
                    continue
                if index and steps[index - 1].mode == "TRANSIT":
                    step = replace(step, start={**step.start, "name": steps[index - 1].end["name"]})
                if index + 1 < len(steps) and steps[index + 1].mode == "TRANSIT":
                    step = replace(step, end={**step.end, "name": steps[index + 1].start["name"]})
                steps[index] = step
            results.append(
                TransitRoute(
                    merge_walks(steps),
                    route.get("description", "Google transit route"),
                    tuple(value for value in route.get("warnings", []) if isinstance(value, str)),
                )
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            # An incomplete transit schedule must never become a catchable connection.
            continue
    return results


class GoogleRoutesProvider:
    mode = "google"
    endpoint = "https://routes.googleapis.com/directions/v2:computeRoutes"
    field_mask = "routes.description,routes.warnings,routes.legs.steps.travelMode,routes.legs.steps.staticDuration,routes.legs.steps.distanceMeters,routes.legs.steps.startLocation,routes.legs.steps.endLocation,routes.legs.steps.navigationInstruction,routes.legs.steps.polyline,routes.legs.steps.transitDetails"

    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None):
        if not api_key or not api_key.strip():
            raise ValueError("Configure GOOGLE_MAPS_API_KEY to use Google transit routes.")
        self._api_key = api_key
        self._client = client

    @staticmethod
    def _waypoint(location: Location) -> dict[str, Any]:
        location = normalize_location(location)
        if isinstance(location, str):
            return {"address": location}
        return {"location": {"latLng": {"latitude": location["lat"], "longitude": location["lng"]}}}

    async def routes(
        self, origin: Location, destination: Location, departure: dt.datetime
    ) -> list[TransitRoute]:
        body = {
            "origin": self._waypoint(origin),
            "destination": self._waypoint(destination),
            "travelMode": "TRANSIT",
            "departureTime": departure.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
            "computeAlternativeRoutes": True,
            "languageCode": "en",
            "units": "METRIC",
        }
        headers = {"X-Goog-Api-Key": self._api_key, "X-Goog-FieldMask": self.field_mask}
        try:
            if self._client:
                response = await self._client.post(self.endpoint, json=body, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(self.endpoint, json=body, headers=headers)
            if response.status_code >= 400:
                if response.status_code in {401, 403}:
                    raise ProviderError(
                        "Google routing is not authorized. Check the server key, billing, API restrictions, and that Routes API is enabled."
                    )
                if response.status_code == 429:
                    raise ProviderError(
                        "Google routing quota was reached. Try again later or check the project quota."
                    )
                if response.status_code == 400:
                    raise ProviderError(
                        "Google could not route this request. Check the places and use a departure within its supported transit date range."
                    )
                raise ProviderError("Google routing is temporarily unavailable. Please try again.")
            return parse_google_routes(response.json(), origin, destination)
        except httpx.TimeoutException as exc:
            raise ProviderError("Google routing timed out. Please try again.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "Could not connect to Google routing. Check the connection and try again."
            ) from exc
        except (ValueError, TypeError) as exc:
            raise ProviderError("Google returned an unreadable route response.") from exc
