"""Local RunMap web app. Run with ``python -m runorwalk.server``."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import mimetypes
import os
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

STATIC = Path(__file__).parent / "static"
load_dotenv(Path(__file__).parent.parent / ".env")


def public_config() -> dict:
    from .demo import DEMO_PLACES
    from .profiles import PROFILES

    return {
        "google_available": bool(os.getenv("GOOGLE_MAPS_API_KEY")),
        "google_browser_key": os.getenv("GOOGLE_MAPS_BROWSER_KEY", ""),
        "profiles": PROFILES,
        "demo_places": DEMO_PLACES,
        "default_origin": "ETH Zürich",
        "default_destination": "Zürich Tiefenbrunnen",
    }


def number(body: dict, key: str, default: float, minimum: float, maximum: float) -> float:
    raw = body.get(key, default)
    if isinstance(raw, bool):
        raise ValueError(f"{key} must be a number.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number.") from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}.")
    return value


async def create_plan(body: dict) -> dict:
    from .planner import plan_trip
    from .providers import GoogleRoutesProvider, normalize_location

    if not isinstance(body, dict):
        raise ValueError("Send a journey object.")
    locations = {}
    for field in ("origin", "destination"):
        value = body.get(field)
        if isinstance(value, str):
            if not value.strip():
                raise ValueError(f"Choose a {field}.")
            if len(value) > 300:
                raise ValueError(f"The {field} is too long.")
        elif isinstance(value, dict):
            if any(
                isinstance(value.get(coordinate), bool)
                or not isinstance(value.get(coordinate), (int, float))
                for coordinate in ("lat", "lng")
            ):
                raise ValueError(f"The {field} must have numeric latitude and longitude.")
            if "name" in value and (not isinstance(value["name"], str) or len(value["name"]) > 200):
                raise ValueError(f"The {field} name must be text up to 200 characters.")
        else:
            raise ValueError(f"Choose a {field}.")
        try:
            locations[field] = normalize_location(value)
        except ValueError:
            raise ValueError(
                f"Choose a valid {field} with latitude from -90 to 90 and longitude from -180 to 180."
            ) from None
    mode = body.get("mode", "demo")
    if mode not in ("demo", "google"):
        raise ValueError("Choose demo or Google Maps mode.")
    if mode == "demo" and any(isinstance(body[field], dict) for field in ("origin", "destination")):
        raise ValueError(
            "Current location and map coordinates require Google Maps mode. Switch to Google Maps, or choose a named Zürich demo place."
        )
    departure_text = body.get("departure")
    if departure_text:
        if not isinstance(departure_text, str):
            raise ValueError("Choose a valid departure time.")
        try:
            departure = dt.datetime.fromisoformat(departure_text.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Choose a valid departure time.") from None
        if departure.tzinfo is None:
            raise ValueError("Departure time must include its time zone.")
    else:
        departure = dt.datetime.now(dt.UTC)
    provider = None
    if mode == "google":
        key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not key:
            raise ValueError(
                "Google Maps is not connected yet. Open Setup for instructions, or try the Zürich demo."
            )
        if departure < dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1):
            raise ValueError("For Google Maps, choose a departure time in the future.")
        provider = GoogleRoutesProvider(key)
    kwargs = {
        "profile_id": body.get("profile_id", "young_athletic"),
        "effort": number(body, "effort", 0.65, 0.4, 0.9),
        "max_run_minutes": number(body, "max_run_minutes", 10, 0, 30),
        "transfer_buffer_s": number(body, "transfer_buffer_s", 60, 0, 300),
        "provider": provider,
        "max_queries": 12,
    }
    if not isinstance(kwargs["profile_id"], str):
        raise ValueError("Choose a valid running profile.")
    if body.get("vma_kmh") is not None:
        kwargs["vma_kmh"] = number(body, "vma_kmh", 16, 5, 30)
    if body.get("direct_pace_kmh") is not None:
        kwargs["direct_pace_kmh"] = number(body, "direct_pace_kmh", 10, 3, 25)
    return await plan_trip(locations["origin"], locations["destination"], departure, **kwargs)


class Handler(BaseHTTPRequestHandler):
    server_version = "RunMap/1.0"

    def send_data(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(payload)

    def json(self, status: int, value: dict) -> None:
        self.send_data(
            status,
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode(),
            "application/json; charset=utf-8",
        )

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/config":
            self.json(200, public_config())
            return
        if path == "/api/health":
            self.json(200, {"status": "ok", "app": "RunMap"})
            return
        if path == "/":
            path = "/index.html"
        from urllib.parse import unquote

        target = (STATIC / unquote(path).lstrip("/")).resolve()
        if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
            self.json(404, {"error": "Page not found."})
            return
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_data(200, target.read_bytes(), mime)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/plan":
            self.json(404, {"error": "Endpoint not found."})
            return
        # The extension navigates here; cross-site pages cannot spend the server API key.
        host = self.headers.get("Host", "")
        if host not in (
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        ):
            self.json(403, {"error": "Use the local RunMap address."})
            return
        origin = self.headers.get("Origin")
        if origin and origin not in (
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        ):
            self.json(403, {"error": "This request must come from RunMap."})
            return
        if self.headers.get_content_type() != "application/json":
            self.json(415, {"error": "Send application/json."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16384:
                raise ValueError("The request body is missing or too large.")
            body = json.loads(self.rfile.read(length))
            result = asyncio.run(asyncio.wait_for(create_plan(body), timeout=90))
            self.json(200, result)
        except (ValueError, TypeError) as error:
            self.json(400, {"error": str(error)})
        except TimeoutError:
            self.json(504, {"error": "The route search took too long. Please try again."})
        except Exception:
            # Never echo provider exceptions: URLs/headers may contain a server key.
            self.json(
                502,
                {
                    "error": "The route service is unavailable. Check your Google Routes API access and try again, or use demo mode."
                },
            )

    def log_message(self, format: str, *args) -> None:
        # Avoid saving addresses or query strings to logs.
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="RunMap local route planner")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--open", action="store_true", help="Open the planner in your browser")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"RunMap is ready at http://127.0.0.1:{args.port}", flush=True)
    if args.open:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
