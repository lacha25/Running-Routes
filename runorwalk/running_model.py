"""Convert Google's walking durations into expected running durations.

Google's walking duration is *not* just distance / walking_speed — it bakes in
traffic-light waits, orientation overhead, and a conservative ~5 km/h pace.
Running doesn't make red lights turn green, so naive distance / running_speed
overstates the speedup. We split the walking duration into a fixed overhead
(unaffected by speed) and a moving portion (scaled by the speed ratio).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunningModel:
    vma_kmh: float | None = None
    effort: float = 0.65
    direct_pace_kmh: float | None = None
    fixed_overhead_s: float = 30.0
    max_run_distance_m: float = 800.0
    max_run_total_s: float = 5 * 60

    @property
    def run_speed_kmh(self) -> float:
        if self.direct_pace_kmh is not None:
            return self.direct_pace_kmh
        if self.vma_kmh is not None:
            return self.vma_kmh * self.effort
        return 9.5

    @property
    def run_speed_mps(self) -> float:
        return self.run_speed_kmh / 3.6

    def walk_to_run_time(self, walk_duration_s: float, distance_m: float) -> float:
        """Convert a Google walking duration to expected running duration.

        Preserves the fixed overhead (lights, orientation) and scales the
        remaining moving portion by the walking-speed-to-running-speed ratio.
        ``distance_m`` is currently unused but kept in the signature so future
        tuning (e.g. distance-dependent slowdown) doesn't change callers.
        """
        del distance_m  # reserved for future tuning
        walk_speed_mps = 5.0 / 3.6  # Google's walking-pace assumption
        moving_walk_s = max(0.0, walk_duration_s - self.fixed_overhead_s)
        moving_run_s = moving_walk_s * (walk_speed_mps / self.run_speed_mps)
        return moving_run_s + self.fixed_overhead_s
