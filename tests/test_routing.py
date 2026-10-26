"""Routing tests with synthetic Directions API responses."""

from __future__ import annotations

import datetime as dt

import pytest

from runorwalk.routing import find_best_route
from runorwalk.running_model import RunningModel

from .conftest import FakeBackend, make_leg, make_route, make_step

# Anchor times: 14:00 UTC on 2026-05-05.
T0 = int(dt.datetime(2026, 5, 5, 14, 0, tzinfo=dt.UTC).timestamp())


def _walk(duration_s: int, distance_m: int, end: tuple[float, float] = (47.42, 8.55)) -> dict:
    return make_step(travel_mode="WALKING", duration_s=duration_s, distance_m=distance_m, end=end)


def _transit(
    *, board_unix: int, arrive_unix: int, line: str = "11", end: tuple[float, float] = (47.43, 8.56)
) -> dict:
    return make_step(
        travel_mode="TRANSIT",
        duration_s=arrive_unix - board_unix,
        distance_m=2000,
        end=end,
        transit_line=line,
        transit_departure_unix=board_unix,
        transit_arrival_unix=arrive_unix,
        departure_stop="Stop A",
        arrival_stop="Stop B",
    )


@pytest.mark.asyncio
async def test_no_walk_before_transit_returns_baseline_only() -> None:
    """Trip is just one transit step — no walking step → no run option."""
    route = make_route(
        [
            make_leg(
                steps=[_transit(board_unix=T0, arrive_unix=T0 + 600)],
                departure_unix=T0,
                arrival_unix=T0 + 600,
            )
        ]
    )
    backend = FakeBackend([[route]])
    result = await find_best_route("A", "B", None, RunningModel(), backend)
    assert result.run_option is None
    assert result.baseline.total_duration_s == 600


@pytest.mark.asyncio
async def test_walking_only_to_destination_no_candidate() -> None:
    """Final-leg walk to destination is not a run candidate (no transit follows)."""
    route = make_route(
        [
            make_leg(
                steps=[
                    _transit(board_unix=T0, arrive_unix=T0 + 600),
                    _walk(duration_s=300, distance_m=400),
                ],
                departure_unix=T0,
                arrival_unix=T0 + 900,
            )
        ]
    )
    backend = FakeBackend([[route]])
    result = await find_best_route("A", "B", None, RunningModel(), backend)
    assert result.run_option is None
    # Only one API call made — no candidate to query alts for.
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_run_candidate_below_savings_threshold_rejected() -> None:
    """Run unlocks a connection only ~2 min earlier — below MIN_SAVINGS, ignored."""
    walk = _walk(duration_s=360, distance_m=500)
    baseline_route = make_route(
        [
            make_leg(
                steps=[walk, _transit(board_unix=T0 + 360, arrive_unix=T0 + 960)],
                departure_unix=T0,
                arrival_unix=T0 + 960,
            )
        ]
    )
    # Earlier connection at T0+260 → arrives T0+860 → savings = 100s
    alt_route = make_route(
        [
            make_leg(
                steps=[_transit(board_unix=T0 + 260, arrive_unix=T0 + 860)],
                departure_unix=T0 + 260,
                arrival_unix=T0 + 860,
            )
        ]
    )
    backend = FakeBackend([[baseline_route], [alt_route]])
    result = await find_best_route("A", "B", None, RunningModel(), backend)
    assert result.run_option is None


@pytest.mark.asyncio
async def test_run_candidate_with_big_savings_recommended() -> None:
    """Run saves ~10 min → recommended."""
    walk = _walk(duration_s=360, distance_m=500)  # ~3.4 min run
    baseline_route = make_route(
        [
            make_leg(
                steps=[walk, _transit(board_unix=T0 + 360, arrive_unix=T0 + 360 + 600)],
                departure_unix=T0,
                arrival_unix=T0 + 360 + 600,  # 14:16
            )
        ]
    )
    # Run-time ~204s; new query at T0+204; alt route boards earlier and arrives much sooner
    alt_route = make_route(
        [
            make_leg(
                steps=[_transit(board_unix=T0 + 210, arrive_unix=T0 + 360)],
                departure_unix=T0 + 210,
                arrival_unix=T0 + 360,  # 14:06 — saves 10 min
            )
        ]
    )
    backend = FakeBackend([[baseline_route], [alt_route]])
    result = await find_best_route("A", "B", None, RunningModel(), backend)
    assert result.run_option is not None
    assert result.run_option.savings_s == pytest.approx(600.0)
    assert result.run_option.run_time_s == pytest.approx(203.68, abs=1.0)


@pytest.mark.asyncio
async def test_walk_too_short_skipped() -> None:
    """A 90s walking step is below MIN_RUN_DURATION_S — never a candidate."""
    short_walk = _walk(duration_s=90, distance_m=100)
    baseline_route = make_route(
        [
            make_leg(
                steps=[short_walk, _transit(board_unix=T0 + 90, arrive_unix=T0 + 690)],
                departure_unix=T0,
                arrival_unix=T0 + 690,
            )
        ]
    )
    backend = FakeBackend([[baseline_route]])
    result = await find_best_route("A", "B", None, RunningModel(), backend)
    assert result.run_option is None
    # Only one API call — short walk wasn't a candidate.
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_walk_too_long_skipped() -> None:
    """Walk distance > 800m: not a candidate."""
    long_walk = _walk(duration_s=900, distance_m=1200)
    baseline_route = make_route(
        [
            make_leg(
                steps=[long_walk, _transit(board_unix=T0 + 900, arrive_unix=T0 + 1500)],
                departure_unix=T0,
                arrival_unix=T0 + 1500,
            )
        ]
    )
    backend = FakeBackend([[baseline_route]])
    result = await find_best_route("A", "B", None, RunningModel(), backend)
    assert result.run_option is None
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_multiple_candidates_picks_best_savings() -> None:
    """Two run-candidates → return the one with the bigger savings."""
    walk_a = _walk(duration_s=360, distance_m=500, end=(47.42, 8.55))
    transit_1 = _transit(board_unix=T0 + 360, arrive_unix=T0 + 660, end=(47.43, 8.56))
    walk_b = make_step(
        travel_mode="WALKING",
        duration_s=300,
        distance_m=400,
        start=(47.43, 8.56),
        end=(47.44, 8.57),
    )
    transit_2 = _transit(board_unix=T0 + 960, arrive_unix=T0 + 1500, end=(47.45, 8.58))
    baseline_route = make_route(
        [
            make_leg(
                steps=[walk_a, transit_1, walk_b, transit_2],
                departure_unix=T0,
                arrival_unix=T0 + 1500,  # 25 min total
            )
        ]
    )
    # First candidate (walk_a) → small savings (~3 min)
    alt_for_a = make_route(
        [
            make_leg(
                steps=[_transit(board_unix=T0 + 210, arrive_unix=T0 + 1320)],
                departure_unix=T0 + 210,
                arrival_unix=T0 + 1320,  # saves 180s — below threshold
            )
        ]
    )
    # Second candidate (walk_b) → big savings (~12 min)
    alt_for_b = make_route(
        [
            make_leg(
                steps=[_transit(board_unix=T0 + 850, arrive_unix=T0 + 780)],
                departure_unix=T0 + 850,
                arrival_unix=T0 + 780,  # saves 720s
            )
        ]
    )
    backend = FakeBackend([[baseline_route], [alt_for_a], [alt_for_b]])
    result = await find_best_route("A", "B", None, RunningModel(), backend)
    assert result.run_option is not None
    # Big savings wins
    assert result.run_option.savings_s == pytest.approx(720.0)
    assert result.run_option.step.distance_m == 400  # walk_b


@pytest.mark.asyncio
async def test_no_baseline_routes_raises() -> None:
    backend = FakeBackend([[]])
    with pytest.raises(ValueError):
        await find_best_route("A", "B", None, RunningModel(), backend)
