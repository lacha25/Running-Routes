"""Bounded, schedule-aware search over transit alternatives and running transfers.

This searches routes a provider exposes. It is deliberately not an assertion of
network-wide optimality: Google does not expose its transit timetable graph.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import heapq
import itertools
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from .profiles import finite_number, resolve_profile
from .providers import (
    Location,
    ProviderError,
    RouteStep,
    TransitProvider,
    TransitRoute,
    distance_between,
    normalize_location,
)


@dataclass(frozen=True)
class _State:
    steps: tuple[dict[str, Any], ...]
    cursor: dt.datetime
    run_s: float = 0
    run_m: float = 0
    depth: int = 0


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat()


def _step_json(step: RouteStep, mode: str, start: dt.datetime, duration: float) -> dict[str, Any]:
    return {
        "mode": mode,
        "start_time": _iso(start),
        "end_time": _iso(start + dt.timedelta(seconds=duration)),
        "duration_s": round(duration, 2),
        "distance_m": round(step.distance_m, 1),
        "start": step.start,
        "end": step.end,
        "instruction": step.instruction,
        "line": step.line,
        "path": step.path or [step.start, step.end],
        "walking_duration_s": step.duration_s if step.mode == "WALK" else 0,
        "directions": step.directions,
        "geometry_approximate": step.geometry_approximate,
    }


def _run_duration(step: RouteStep, speed_kmh: float) -> float:
    # Twenty seconds is retained for slowing, crossings, and getting oriented.
    # This is a planning estimate, not terrain-aware running navigation.
    return min(step.duration_s, 20 + step.distance_m / (speed_kmh / 3.6))


def _evaluate(
    route: TransitRoute,
    seed: _State,
    *,
    allow_running: bool,
    speed_kmh: float,
    budget_s: float,
    max_leg_m: float,
    buffer_s: float,
) -> tuple[list[_State], list[_State], bool]:
    states = [seed]
    opportunities: list[_State] = []
    truncated = False
    for index, step in enumerate(route.steps):
        following: list[_State] = []
        for state in states:
            if len(state.steps) >= 60:
                truncated = True
                continue
            if index == 0 and state.steps and distance_between(state.steps[-1]["end"], step.start) > 20:
                # Only validate the seam between two separately queried routes.
                # Consecutive steps in one provider itinerary can use different
                # station/platform representations; their scheduled connection
                # and supplied walking duration remain authoritative.
                continue
            if step.mode == "WALK":
                if (
                    step.duration_s < 0
                    or step.distance_m < 0
                    or (step.distance_m > 0 and step.duration_s <= 0)
                ):
                    continue
                choices = [("WALK", step.duration_s)]
                running = _run_duration(step, speed_kmh)
                if (
                    allow_running
                    and 20 <= step.distance_m <= max_leg_m
                    and running + 1 < step.duration_s
                    and state.run_s + running <= budget_s + 1e-6
                ):
                    choices.append(("RUN", running))
                for mode, duration in choices:
                    current = _step_json(step, mode, state.cursor, duration)
                    if mode == "RUN":
                        current["instruction"] = f"Run to {step.end.get('name') or 'the next stop'}"
                    updated = _State(
                        (*state.steps, current),
                        state.cursor + dt.timedelta(seconds=duration),
                        state.run_s + (duration if mode == "RUN" else 0),
                        state.run_m + (step.distance_m if mode == "RUN" else 0),
                        state.depth,
                    )
                    following.append(updated)
                    if mode == "RUN" and index + 1 < len(route.steps) and state.depth < 5:
                        opportunities.append(updated)
            elif step.mode == "TRANSIT":
                if step.departure is None or step.arrival is None or step.arrival < step.departure:
                    continue
                if state.cursor + dt.timedelta(seconds=buffer_s) > step.departure:
                    # A provider may allow a tighter transfer than our buffer.
                    # Re-query from the reached stop instead of discarding an
                    # otherwise useful prefix or pretending the bus waits.
                    if state.steps and state.depth < 5:
                        opportunities.append(state)
                    continue
                prefix = state.steps
                waiting = (step.departure - state.cursor).total_seconds()
                if waiting > 0:
                    wait_step = RouteStep(
                        "WAIT",
                        step.start,
                        step.start,
                        waiting,
                        0,
                        f"Wait at {step.start.get('name') or 'the stop'}",
                        path=[step.start],
                    )
                    wait_json = _step_json(wait_step, "WAIT", state.cursor, waiting)
                    wait_json["transfer_buffer_s"] = buffer_s
                    prefix += (wait_json,)
                transit = _step_json(
                    step, "TRANSIT", step.departure, (step.arrival - step.departure).total_seconds()
                )
                following.append(
                    _State((*prefix, transit), step.arrival, state.run_s, state.run_m, state.depth)
                )
        # Keep different running-budget choices alive across shared departures.
        following.sort(key=lambda item: (item.cursor, item.run_s))
        kept: list[_State] = []
        for candidate in following:
            if any(
                old.cursor <= candidate.cursor
                and old.run_s <= candidate.run_s
                and old.run_m <= candidate.run_m
                for old in kept
            ):
                continue
            kept.append(candidate)
        if len(kept) > 64:
            truncated = True
        states = kept[:64]
        if not states:
            break
    return states, opportunities, truncated


def _route_json(state: _State, departure: dt.datetime, label: str) -> dict[str, Any]:
    identity = "|".join(
        f"{s['mode']}:{s['start_time']}:{s['end']['lat']}:{s['end']['lng']}:{s.get('line')}"
        for s in state.steps
    )
    return {
        "id": hashlib.sha256(identity.encode()).hexdigest()[:12],
        "label": label,
        "departure": _iso(departure),
        "arrival": _iso(state.cursor),
        "duration_s": round((state.cursor - departure).total_seconds(), 2),
        "distance_m": round(sum(s["distance_m"] for s in state.steps), 1),
        "run_duration_s": round(state.run_s, 2),
        "run_distance_m": round(state.run_m, 1),
        "walk_duration_s": round(
            sum(s["duration_s"] for s in state.steps if s["mode"] == "WALK"), 2
        ),
        "wait_duration_s": round(
            sum(s["duration_s"] for s in state.steps if s["mode"] == "WAIT"), 2
        ),
        "transit_count": sum(s["mode"] == "TRANSIT" for s in state.steps),
        "steps": list(state.steps),
    }


def _maps_link(origin: Location, destination: Location) -> str:
    def fmt(value: Location) -> str:
        return value if isinstance(value, str) else f"{value['lat']},{value['lng']}"

    return "https://www.google.com/maps/dir/?" + urlencode(
        {"api": 1, "origin": fmt(origin), "destination": fmt(destination), "travelmode": "transit"}
    )


async def plan_trip(
    origin: Location,
    destination: Location,
    departure: dt.datetime,
    profile_id: str = "young_athletic",
    vma_kmh: float | None = None,
    effort: float = 0.65,
    direct_pace_kmh: float | None = None,
    max_run_minutes: float = 10,
    transfer_buffer_s: float = 60,
    provider: TransitProvider | None = None,
    max_queries: int = 12,
    max_run_distance_m: float = 1500,
) -> dict[str, Any]:
    origin, destination = normalize_location(origin), normalize_location(destination)
    if (
        not isinstance(departure, dt.datetime)
        or departure.tzinfo is None
        or departure.utcoffset() is None
    ):
        raise ValueError("Departure must include its timezone.")
    # Work on absolute instants: ZoneInfo wall-clock arithmetic can jump an
    # hour across a daylight-saving transition.
    departure = departure.astimezone(dt.UTC)
    if origin == destination:
        raise ValueError("Choose different origin and destination places.")
    profile = resolve_profile(profile_id, vma_kmh, effort, direct_pace_kmh)
    budget = finite_number(max_run_minutes, "Running budget", 0, 60) * 60
    buffer = finite_number(transfer_buffer_s, "Connection buffer", 0, 600)
    max_leg = finite_number(max_run_distance_m, "Maximum run distance", 20, 10000)
    queries_limit = int(finite_number(max_queries, "Search query limit", 1, 30))
    if provider is None:
        from .demo import DemoProvider

        provider = DemoProvider()
    if hasattr(provider, "set_reference_time"):
        provider.set_reference_time(departure)
    start = _State((), departure)
    # Asking at this time ensures the normal-pace baseline also has boarding margin.
    initial = await provider.routes(origin, destination, departure + dt.timedelta(seconds=buffer))
    if not initial:
        raise ValueError("No transit routes found for these places and this departure time.")
    baseline_states: list[_State] = []
    candidates: list[_State] = []
    queue: list[tuple[float, int, _State]] = []
    serial = itertools.count()
    query_count = 1
    truncated = False
    warnings = []
    kwargs = {
        "speed_kmh": profile["run_speed_kmh"],
        "budget_s": budget,
        "max_leg_m": max_leg,
        "buffer_s": buffer,
    }

    def process(route: TransitRoute, seed: _State, baseline: bool = False) -> None:
        nonlocal truncated
        warnings.extend(route.warnings)
        finished, opportunities, was_truncated = _evaluate(
            route, seed, allow_running=not baseline and budget > 0, **kwargs
        )
        truncated |= was_truncated
        if baseline:
            baseline_states.extend(finished)
        else:
            candidates.extend(finished)
        for state in opportunities:
            if len(queue) < 256:
                heapq.heappush(queue, (state.cursor.timestamp(), next(serial), state))
            else:
                truncated = True

    for route in initial:
        process(route, start, baseline=True)
        process(route, start)
    cache: dict[tuple[float, float, str], list[TransitRoute]] = {}
    visited: set[tuple[Any, ...]] = set()
    processed = 0
    while queue and processed < 256:
        _, _, seed = heapq.heappop(queue)
        location = seed.steps[-1]["end"]
        ready = seed.cursor + dt.timedelta(seconds=buffer)
        query_key = (round(location["lat"], 6), round(location["lng"], 6), _iso(ready))
        state_key = (*query_key, round(seed.run_s, 3), round(seed.run_m, 1))
        if state_key in visited:
            continue
        if baseline_states and seed.cursor >= min(state.cursor for state in baseline_states):
            continue
        visited.add(state_key)
        if query_key not in cache:
            if query_count >= queries_limit:
                truncated = True
                continue
            query_count += 1
            try:
                cache[query_key] = await provider.routes(location, destination, ready)
            except ProviderError:
                warnings.append(
                    "Some connection searches could not finish. The displayed routes use the schedules that were available."
                )
                cache[query_key] = []
        processed += 1
        deeper = _State(seed.steps, seed.cursor, seed.run_s, seed.run_m, seed.depth + 1)
        for route in cache[query_key]:
            if not seed.run_s:
                process(route, deeper, baseline=True)
            process(route, deeper)
    truncated |= bool(queue)
    if not baseline_states and not candidates:
        raise ValueError(
            "No complete itinerary was found within the search limit with these settings. "
            "Try a later departure or a smaller boarding buffer."
        )
    baseline = min(baseline_states, key=lambda item: (item.cursor, item.run_s), default=None)
    if baseline is not None:
        candidates.append(baseline)
    else:
        warnings.append(
            "No feasible walking comparison was found with this connection buffer. A running itinerary is available, but its time saving cannot be calculated."
        )
    candidates.sort(key=lambda state: (state.cursor, state.run_s))
    best_state = candidates[0]
    base_json = _route_json(baseline, departure, "Walk + transit") if baseline is not None else None
    best_json = _route_json(
        best_state, departure, "Run + transit" if best_state.run_s else "Walk + transit"
    )
    alternatives = []
    seen = set()
    for state in candidates:
        item = _route_json(state, departure, "Run + transit" if state.run_s else "Walk + transit")
        if item["id"] not in seen:
            seen.add(item["id"])
            alternatives.append(item)
        if len(alternatives) >= 4:
            break
    if provider.mode == "demo":
        warnings.append(
            "Illustrative Zürich demo: times, services, and paths are synthetic, not live travel directions."
        )
    warnings.extend(
        [
            "Best route found in a bounded search of provider alternatives; this does not guarantee the fastest route across the entire transit network.",
            "Running estimates include 20 seconds per leg for slowing and orientation. Hills, stairs, crossings, crowding, and delays can change the time.",
        ]
    )
    if any(step.get("geometry_approximate") for route in alternatives for step in route["steps"]):
        warnings.append(
            "Some paths lack detailed geometry and are approximate. Follow posted signs and pedestrian access routes."
        )
    if truncated:
        warnings.append("The search limit was reached; other connections may be faster.")
    return {
        "mode": provider.mode,
        "origin": best_state.steps[0]["start"],
        "destination": best_state.steps[-1]["end"],
        "requested_departure": _iso(departure),
        "profile": profile,
        "baseline": base_json,
        "best": best_json,
        "alternatives": alternatives,
        "savings_s": round(max(0, (baseline.cursor - best_state.cursor).total_seconds()), 2)
        if baseline is not None
        else None,
        "warnings": list(dict.fromkeys(warnings)),
        "search": {
            "queries": query_count,
            "limit": queries_limit,
            "complete": False,
            "limit_reached": truncated,
            "method": "Scheduled transit alternatives with bounded running-transfer re-queries",
        },
        "settings": {
            "max_run_minutes": budget / 60,
            "transfer_buffer_s": buffer,
            "max_run_distance_m": max_leg,
        },
        "google_maps_url": _maps_link(origin, destination),
        "disclaimer": "Schedules and running times are estimates. Check departure boards and allow enough time to board.",
    }
