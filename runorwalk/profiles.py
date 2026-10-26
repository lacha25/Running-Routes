"""Editable running scenarios; these are not measured population averages."""

from __future__ import annotations

import math
from typing import Any

PROFILES: list[dict[str, Any]] = [
    {
        "id": "young_athletic",
        "label": "Young · athletic",
        "vma_kmh": 16.0,
        "description": "An illustrative fit young adult.",
    },
    {
        "id": "young_casual",
        "label": "Young · less active",
        "vma_kmh": 11.0,
        "description": "An illustrative less active young adult.",
    },
    {
        "id": "forties",
        "label": "In your 40s",
        "vma_kmh": 12.0,
        "description": "An illustrative adult in their 40s.",
    },
    {
        "id": "older",
        "label": "Older adult (65+)",
        "vma_kmh": 9.0,
        "description": "An illustrative older adult.",
    },
]
PROFILE_NOTE = (
    "Age and activity presets are editable examples, not measured population averages. "
    "VMA is maximal aerobic speed; estimated running speed is VMA multiplied by effort. "
    "Use a measured VMA or a pace you can sustain for a better estimate."
)


def finite_number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}.")
    return number


def resolve_profile(
    profile_id: str = "young_athletic",
    vma_kmh: float | None = None,
    effort: float = 0.65,
    direct_pace_kmh: float | None = None,
) -> dict[str, Any]:
    preset = next((item for item in PROFILES if item["id"] == profile_id), None)
    if preset is None:
        raise ValueError("Choose a valid running profile.")
    vma = finite_number(vma_kmh if vma_kmh is not None else preset["vma_kmh"], "VMA", 5, 30)
    fraction = finite_number(effort, "Effort", 0.3, 1.0)
    speed = (
        finite_number(direct_pace_kmh, "Running speed", 3, 30)
        if direct_pace_kmh is not None
        else vma * fraction
    )
    return {
        **preset,
        "vma_kmh": vma,
        "effort": fraction,
        "run_speed_kmh": round(speed, 3),
        "pace_min_km": round(60 / speed, 3),
        "custom": vma_kmh is not None or direct_pace_kmh is not None,
        "direct_pace_kmh": direct_pace_kmh,
        "note": PROFILE_NOTE,
    }
