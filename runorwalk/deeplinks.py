"""Build Google Maps deeplink URLs for inline buttons.

Deeplink times won't match the bot's calculated times (Google still uses a
walking pace for display) but the route geometry is correct, which is what
the user needs visually. The bot's text gives the timing.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlencode

from .google_directions import LatLng

Location = str | tuple[float, float] | LatLng


def _format_location(loc: Location) -> str:
    if isinstance(loc, LatLng):
        return f"{loc.lat},{loc.lng}"
    if isinstance(loc, tuple):
        lat, lng = loc
        return f"{lat},{lng}"
    return loc


def _build(
    travelmode: str, origin: Location, destination: Location, departure_time: dt.datetime | None
) -> str:
    params: list[tuple[str, str]] = [
        ("api", "1"),
        ("origin", _format_location(origin)),
        ("destination", _format_location(destination)),
        ("travelmode", travelmode),
    ]
    if departure_time is not None:
        params.append(("departure_time", str(int(departure_time.timestamp()))))
    return "https://www.google.com/maps/dir/?" + urlencode(params)


def transit_deeplink(
    origin: Location,
    destination: Location,
    departure_time: dt.datetime | None = None,
) -> str:
    return _build("transit", origin, destination, departure_time)


def walking_deeplink(
    origin: Location,
    destination: Location,
    departure_time: dt.datetime | None = None,
) -> str:
    return _build("walking", origin, destination, departure_time)
