"""Tests for Google Maps deeplink URL builders."""

from __future__ import annotations

import datetime as dt
from urllib.parse import parse_qs, urlparse

from runorwalk.deeplinks import transit_deeplink, walking_deeplink
from runorwalk.google_directions import LatLng


def _parse(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_transit_deeplink_with_addresses() -> None:
    url = transit_deeplink("ETH Zürich", "Bahnhof Stadelhofen")
    assert url.startswith("https://www.google.com/maps/dir/?")
    q = _parse(url)
    assert q["api"] == ["1"]
    assert q["origin"] == ["ETH Zürich"]
    assert q["destination"] == ["Bahnhof Stadelhofen"]
    assert q["travelmode"] == ["transit"]
    assert "departure_time" not in q


def test_transit_deeplink_with_departure_time() -> None:
    when = dt.datetime(2026, 5, 5, 14, 0, tzinfo=dt.UTC)
    url = transit_deeplink("A", "B", departure_time=when)
    q = _parse(url)
    assert q["departure_time"] == [str(int(when.timestamp()))]


def test_walking_deeplink_with_latlng_tuple() -> None:
    url = walking_deeplink((47.4131, 8.5448), (47.3667, 8.5500))
    q = _parse(url)
    assert q["origin"] == ["47.4131,8.5448"]
    assert q["destination"] == ["47.3667,8.55"]
    assert q["travelmode"] == ["walking"]


def test_walking_deeplink_with_latlng_object() -> None:
    url = walking_deeplink(LatLng(lat=47.41, lng=8.54), "Zürich HB")
    q = _parse(url)
    assert q["origin"] == ["47.41,8.54"]
    assert q["destination"] == ["Zürich HB"]
    assert q["travelmode"] == ["walking"]


def test_url_encoding_handles_unicode_and_spaces() -> None:
    url = transit_deeplink("ETH Zürich", "Bahnhof Stadelhofen")
    # URL must be safely encodable — parse_qs round-trips it cleanly.
    q = _parse(url)
    assert q["origin"] == ["ETH Zürich"]
