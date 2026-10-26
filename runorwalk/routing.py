"""Core run-or-walk routing logic + CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from dataclasses import dataclass
from typing import Protocol

from .config import (
    DEFAULT_MAX_RUN_MINUTES,
    MAX_RUN_DISTANCE_M,
    MIN_RUN_DURATION_S,
    MIN_SAVINGS_S,
    Settings,
)
from .deeplinks import transit_deeplink, walking_deeplink
from .google_directions import DirectionsClient, LatLng, Route, Step
from .running_model import RunningModel


class _DirectionsBackend(Protocol):
    async def directions(
        self,
        origin: str | tuple[float, float] | LatLng,
        destination: str | tuple[float, float] | LatLng,
        *,
        mode: str = "transit",
        departure_time: dt.datetime | None = None,
        alternatives: bool = True,
    ) -> list[Route]: ...


@dataclass(frozen=True)
class RunOption:
    """A walking step worth running, plus the better itinerary it unlocks."""

    step: Step
    run_time_s: float
    new_route: Route
    savings_s: float

    @property
    def walk_duration_s(self) -> int:
        return self.step.duration_s

    @property
    def distance_m(self) -> int:
        return self.step.distance_m


@dataclass(frozen=True)
class RouteResult:
    baseline: Route
    run_option: RunOption | None


def _walking_steps_before_transit(route: Route) -> list[Step]:
    """Return walking steps that are immediately followed by a transit step.

    A walking step ending at the destination (no transit afterwards) isn't a
    candidate — running won't catch any earlier connection.
    """
    out: list[Step] = []
    for leg in route.legs:
        steps = leg.steps
        for i, step in enumerate(steps):
            if step.travel_mode != "WALKING":
                continue
            if i + 1 >= len(steps):
                continue
            if steps[i + 1].travel_mode != "TRANSIT":
                continue
            out.append(step)
    return out


def _is_run_candidate(step: Step, model: RunningModel, run_budget_remaining_s: float) -> bool:
    if step.duration_s < MIN_RUN_DURATION_S:
        return False
    if step.distance_m > min(MAX_RUN_DISTANCE_M, model.max_run_distance_m):
        return False
    run_time_s = model.walk_to_run_time(step.duration_s, step.distance_m)
    return run_time_s <= run_budget_remaining_s


async def find_best_route(
    origin: str | tuple[float, float] | LatLng,
    destination: str | tuple[float, float] | LatLng,
    depart_time: dt.datetime | None,
    model: RunningModel,
    backend: _DirectionsBackend,
) -> RouteResult:
    """Find the fastest baseline transit route, then test if running any
    walking step unlocks an earlier connection. Return both."""
    baseline_routes = await backend.directions(
        origin, destination, mode="transit", departure_time=depart_time, alternatives=True
    )
    if not baseline_routes:
        raise ValueError("No transit routes found from origin to destination.")
    baseline = baseline_routes[0]
    baseline_arrival = baseline.arrival_time
    if baseline_arrival is None:
        return RouteResult(baseline=baseline, run_option=None)

    candidates: list[RunOption] = []
    run_budget_remaining_s = model.max_run_total_s
    for step in _walking_steps_before_transit(baseline):
        if not _is_run_candidate(step, model, run_budget_remaining_s):
            continue
        run_time_s = model.walk_to_run_time(step.duration_s, step.distance_m)
        new_t = step.start_time + dt.timedelta(seconds=run_time_s)
        alts = await backend.directions(
            step.end_location,
            destination,
            mode="transit",
            departure_time=new_t,
            alternatives=True,
        )
        if not alts:
            continue
        timed_alts: list[tuple[dt.datetime, Route]] = [
            (r.arrival_time, r) for r in alts if r.arrival_time is not None
        ]
        if not timed_alts:
            continue
        best_arrival, best_alt = min(timed_alts, key=lambda pair: pair[0])
        savings_s = (baseline_arrival - best_arrival).total_seconds()
        if savings_s >= MIN_SAVINGS_S:
            candidates.append(
                RunOption(
                    step=step,
                    run_time_s=run_time_s,
                    new_route=best_alt,
                    savings_s=savings_s,
                )
            )

    best_run = max(candidates, key=lambda c: c.savings_s, default=None)
    return RouteResult(baseline=baseline, run_option=best_run)


# ---- CLI ----


def _fmt_clock(when: dt.datetime | None, tz: dt.tzinfo) -> str:
    if when is None:
        return "?"
    return when.astimezone(tz).strftime("%H:%M")


def _fmt_minutes(seconds: float) -> str:
    return f"{round(seconds / 60)} min"


def _print_result(
    result: RouteResult,
    origin: str,
    destination: str,
    tz: dt.tzinfo,
) -> None:
    base = result.baseline
    print(f"From: {origin}")
    print(f"To:   {destination}")
    print()
    print("🚶 Walking pace")
    print(
        f"   depart {_fmt_clock(base.departure_time, tz)} → "
        f"arrive {_fmt_clock(base.arrival_time, tz)} "
        f"({_fmt_minutes(base.total_duration_s)})"
    )
    print(f"   {transit_deeplink(origin, destination, base.departure_time)}")
    print()

    ro = result.run_option
    if ro is None:
        print("(no worthwhile run option found)")
        return

    new_arrival = ro.new_route.arrival_time
    print("🏃 Run option")
    print(
        f"   run {ro.distance_m}m to {_describe_step_end(ro.step)} "
        f"(~{_fmt_minutes(ro.run_time_s)} instead of {_fmt_minutes(ro.walk_duration_s)})"
    )
    print(f"   new arrival {_fmt_clock(new_arrival, tz)} (saves ~{_fmt_minutes(ro.savings_s)})")
    print(f"   run-leg map: {walking_deeplink(ro.step.start_location, ro.step.end_location)}")


def _describe_step_end(step: Step) -> str:
    """Best human label for where a walking step ends (the boarding stop)."""
    # The next step (transit) carries departure_stop info, but here we only
    # have the walking step itself. End coordinates are still useful.
    return f"({step.end_location.lat:.4f}, {step.end_location.lng:.4f})"


def _parse_depart(value: str | None) -> dt.datetime | None:
    if value is None:
        return None
    # Accept "YYYY-MM-DD HH:MM" or ISO format. Treat naive as local time.
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError as e:
            raise SystemExit(f"Could not parse --depart {value!r}: {e}") from e
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="runorwalk",
        description="Plan a transit trip and tell me when running a walking leg saves real time.",
    )
    p.add_argument("origin", help="Origin address or 'lat,lng'")
    p.add_argument("destination", help="Destination address or 'lat,lng'")
    p.add_argument("--depart", help="Departure time (e.g. '2026-05-05 17:30'); default = now")
    p.add_argument("--vma", type=float, help="Maximal aerobic speed in km/h")
    p.add_argument(
        "--effort", type=float, default=0.65, help="Fraction of VMA used as run pace (default 0.65)"
    )
    p.add_argument("--pace", type=float, help="Override run pace in km/h (skips VMA * effort)")
    p.add_argument(
        "--max-run",
        type=float,
        default=DEFAULT_MAX_RUN_MINUTES,
        help="Max minutes you'll run (default 5)",
    )
    return p


def _parse_origin_dest(value: str) -> str | tuple[float, float]:
    """If 'lat,lng', return tuple; otherwise return raw address string."""
    parts = value.split(",")
    if len(parts) == 2:
        try:
            return (float(parts[0].strip()), float(parts[1].strip()))
        except ValueError:
            pass
    return value


async def _run_cli(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if not settings.google_maps_api_key:
        print("ERROR: GOOGLE_MAPS_API_KEY is not set (put it in .env).", file=sys.stderr)
        return 2

    model = RunningModel(
        vma_kmh=args.vma,
        effort=args.effort,
        direct_pace_kmh=args.pace,
        max_run_total_s=args.max_run * 60,
    )
    depart = _parse_depart(args.depart)
    backend = DirectionsClient(api_key=settings.google_maps_api_key)
    origin = _parse_origin_dest(args.origin)
    destination = _parse_origin_dest(args.destination)

    result = await find_best_route(origin, destination, depart, model, backend)
    tz = depart.tzinfo if depart and depart.tzinfo else dt.datetime.now().astimezone().tzinfo
    assert tz is not None
    _print_result(result, args.origin, args.destination, tz)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run_cli(args))


if __name__ == "__main__":
    raise SystemExit(main())
