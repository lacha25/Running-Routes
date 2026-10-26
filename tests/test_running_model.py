"""Tests for the walk-time → run-time conversion."""

from __future__ import annotations

import math

import pytest

from runorwalk.running_model import RunningModel


def test_default_speed_is_95_kmh() -> None:
    assert RunningModel().run_speed_kmh == pytest.approx(9.5)


def test_vma_and_effort_combine() -> None:
    m = RunningModel(vma_kmh=18.0, effort=0.5)
    assert m.run_speed_kmh == pytest.approx(9.0)


def test_direct_pace_overrides_vma() -> None:
    m = RunningModel(vma_kmh=18.0, effort=0.5, direct_pace_kmh=12.0)
    assert m.run_speed_kmh == pytest.approx(12.0)


def test_sanity_case_six_minute_walk() -> None:
    """Spec sanity check: 6-min walk over 500m, default config → ~3.4 min run."""
    m = RunningModel()  # 9.5 km/h, 30s overhead
    run_s = m.walk_to_run_time(walk_duration_s=360, distance_m=500)
    # moving_walk = 360 - 30 = 330; moving_run = 330 * (5/9.5) ~= 173.7; +30 = 203.7s
    assert run_s == pytest.approx(203.68, abs=0.5)
    assert math.isclose(run_s / 60, 3.4, abs_tol=0.05)


def test_overhead_larger_than_walk_duration() -> None:
    """Tiny walk → run-time floors at the fixed overhead."""
    m = RunningModel(fixed_overhead_s=30.0)
    assert m.walk_to_run_time(walk_duration_s=10, distance_m=20) == pytest.approx(30.0)


def test_zero_overhead_pure_speed_ratio() -> None:
    m = RunningModel(direct_pace_kmh=10.0, fixed_overhead_s=0.0)
    # walking 5 km/h vs running 10 km/h → run takes half the time
    assert m.walk_to_run_time(600, 500) == pytest.approx(300.0)


def test_run_speed_mps_is_kmh_over_36() -> None:
    m = RunningModel(direct_pace_kmh=18.0)
    assert m.run_speed_mps == pytest.approx(5.0)
