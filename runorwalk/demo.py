"""A deterministic, explicitly fictional Zürich transit timetable for local demos."""

from __future__ import annotations

import datetime as dt
import math
import unicodedata
from dataclasses import dataclass
from typing import Any

from .providers import (
    Location,
    RouteStep,
    TransitRoute,
    distance_between,
    merge_walks,
    normalize_location,
    point,
)

_PLACES = {
    "eth": point(47.37640, 8.54810, "ETH Zürich"),
    "hb": point(47.37820, 8.54020, "Zürich HB"),
    "central": point(47.37645, 8.54420, "Central"),
    "bellevue": point(47.36672, 8.54590, "Bellevue"),
    "stadelhofen": point(47.36653, 8.54855, "Zürich Stadelhofen"),
    "tiefenbrunnen": point(47.35050, 8.56145, "Zürich Tiefenbrunnen"),
    "kunsthaus": point(47.37015, 8.54805, "Kunsthaus Zürich"),
    "paradeplatz": point(47.36955, 8.53884, "Paradeplatz"),
}
DEMO_PLACES: list[dict[str, Any]] = [{"id": key, **value} for key, value in _PLACES.items()]


def _slug(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if c.isalnum())


_ALIASES = {
    "eth": "eth",
    "ethzurich": "eth",
    "ethzuerich": "eth",
    "ethzurichhauptgebaude": "eth",
    "hb": "hb",
    "zurichhb": "hb",
    "zurichhauptbahnhof": "hb",
    "zurichmainstation": "hb",
    "stadelhofen": "stadelhofen",
    "tiefenbrunnen": "tiefenbrunnen",
    "kunsthaus": "kunsthaus",
}
for _key, _value in _PLACES.items():
    _ALIASES[_slug(_value["name"])] = _key


@dataclass(frozen=True)
class _Edge:
    start: str
    end: str
    mode: str
    duration_s: float
    distance_m: float
    line: str = ""
    phase_s: float = 0
    interval_s: float = 600
    path: tuple[tuple[float, float], ...] = ()


def _edges() -> list[_Edge]:
    walks = [
        _Edge(
            "eth",
            "central",
            "WALK",
            540,
            650,
            path=(
                (47.3764, 8.5481),
                (47.3766, 8.5474),
                (47.3768, 8.5468),
                (47.3767, 8.5456),
                (47.37645, 8.5442),
            ),
        ),
        _Edge(
            "hb",
            "central",
            "WALK",
            360,
            450,
            path=((47.3782, 8.5402), (47.3775, 8.5405), (47.3772, 8.5425), (47.37645, 8.5442)),
        ),
        _Edge(
            "bellevue",
            "stadelhofen",
            "WALK",
            330,
            420,
            path=((47.36672, 8.5459), (47.36645, 8.5463), (47.36635, 8.5472), (47.36653, 8.54855)),
        ),
        _Edge(
            "kunsthaus",
            "bellevue",
            "WALK",
            420,
            510,
            path=(
                (47.37015, 8.54805),
                (47.3694, 8.5479),
                (47.3683, 8.5472),
                (47.3672, 8.5468),
                (47.36672, 8.5459),
            ),
        ),
    ]
    transits = [
        _Edge(
            "central",
            "bellevue",
            "TRANSIT",
            420,
            1300,
            "4",
            360,
            600,
            (
                (47.37645, 8.5442),
                (47.3745, 8.5432),
                (47.3722, 8.5422),
                (47.3701, 8.5433),
                (47.3682, 8.5448),
                (47.36672, 8.5459),
            ),
        ),
        _Edge(
            "stadelhofen",
            "tiefenbrunnen",
            "TRANSIT",
            240,
            2200,
            "S16",
            1020,
            600,
            (
                (47.36653, 8.54855),
                (47.3637, 8.5509),
                (47.3606, 8.5530),
                (47.3572, 8.5561),
                (47.3536, 8.5590),
                (47.3505, 8.56145),
            ),
        ),
        _Edge(
            "central",
            "paradeplatz",
            "TRANSIT",
            420,
            1400,
            "7",
            660,
            600,
            (
                (47.37645, 8.5442),
                (47.3770, 8.5422),
                (47.3762, 8.5403),
                (47.3731, 8.5391),
                (47.36955, 8.53884),
            ),
        ),
        _Edge(
            "paradeplatz",
            "bellevue",
            "TRANSIT",
            300,
            750,
            "2",
            180,
            600,
            ((47.36955, 8.53884), (47.3680, 8.5381), (47.3661, 8.5407), (47.36672, 8.5459)),
        ),
    ]
    forward = walks + transits
    return forward + [
        _Edge(
            edge.end,
            edge.start,
            edge.mode,
            edge.duration_s,
            edge.distance_m,
            edge.line,
            edge.phase_s + (180 if edge.mode == "TRANSIT" else 0),
            edge.interval_s,
            tuple(reversed(edge.path)),
        )
        for edge in forward
    ]


class DemoProvider:
    mode = "demo"

    def __init__(self) -> None:
        self._anchor: dt.datetime | None = None
        self._edges = _edges()

    def set_reference_time(self, departure: dt.datetime) -> None:
        self._anchor = departure

    @staticmethod
    def _resolve(value: Location) -> str:
        value = normalize_location(value)
        if isinstance(value, str):
            known = _ALIASES.get(_slug(value))
            if known:
                return known
        else:
            closest = min(_PLACES, key=lambda name: distance_between(value, _PLACES[name]))
            if distance_between(value, _PLACES[closest]) <= 100:
                return closest
        raise ValueError(
            "Demo mode supports the listed Zürich places only. Choose a suggested place, or enable Google routing for other addresses."
        )

    def _paths(
        self, origin: str, destination: str, visited: tuple[str, ...] = ()
    ) -> list[list[_Edge]]:
        if origin == destination:
            return [[]]
        if len(visited) >= 7:
            return []
        paths = []
        for edge in self._edges:
            if edge.start == origin and edge.end not in visited:
                for tail in self._paths(edge.end, destination, (*visited, origin)):
                    paths.append([edge, *tail])
        return paths

    async def routes(
        self, origin: Location, destination: Location, departure: dt.datetime
    ) -> list[TransitRoute]:
        start, end = self._resolve(origin), self._resolve(destination)
        if start == end:
            return []
        if self._anchor is None:
            self._anchor = departure
        results: list[tuple[dt.datetime, TransitRoute]] = []
        for path in self._paths(start, end):
            cursor = departure
            steps = []
            for edge in path:
                a, b = _PLACES[edge.start], _PLACES[edge.end]
                geometry = [point(lat, lng) for lat, lng in edge.path] or [a, b]
                if edge.mode == "WALK":
                    steps.append(
                        RouteStep(
                            "WALK",
                            a,
                            b,
                            edge.duration_s,
                            edge.distance_m,
                            f"Walk to {b['name']}",
                            path=geometry,
                            directions=[f"Follow the pedestrian route to {b['name']}"],
                            geometry_approximate=True,
                        )
                    )
                    cursor += dt.timedelta(seconds=edge.duration_s)
                else:
                    elapsed = (cursor - self._anchor).total_seconds()
                    cycle = max(0, math.ceil((elapsed - edge.phase_s) / edge.interval_s))
                    leaving = self._anchor + dt.timedelta(
                        seconds=edge.phase_s + cycle * edge.interval_s
                    )
                    arrival = leaving + dt.timedelta(seconds=edge.duration_s)
                    is_train = edge.line.startswith("S")
                    line = {
                        "name": f"{'Train' if is_train else 'Tram'} {edge.line}",
                        "short_name": edge.line,
                        "color": "#167c80" if is_train else "#6e75d1",
                        "vehicle": "COMMUTER_TRAIN" if is_train else "TRAM",
                        "headsign": b["name"],
                        "stop_count": 2 if is_train else 5,
                    }
                    steps.append(
                        RouteStep(
                            "TRANSIT",
                            a,
                            b,
                            edge.duration_s,
                            edge.distance_m,
                            f"Take {line['name']} towards {b['name']}",
                            leaving,
                            arrival,
                            line,
                            geometry,
                            geometry_approximate=True,
                        )
                    )
                    cursor = arrival
            results.append(
                (cursor, TransitRoute(merge_walks(steps), "Illustrative Zürich connection"))
            )
        results.sort(key=lambda value: value[0])
        return [route for _, route in results[:4]]
