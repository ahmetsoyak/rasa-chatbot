"""Location services: geocoding, reverse geocoding and distances.

Lookup order for ``geocode(name)``:
  1. local gazetteer (mock_data/gazetteer.json)      - instant, offline
  2. Nominatim live search (short timeout, 1 req/s)

Nominatim usage policy: identifying User-Agent and max 1 request/second.
"""

import json
import logging
import math
import os
import threading
import time
from difflib import get_close_matches
from typing import Any, Dict, Optional

from . import http

logger = logging.getLogger(__name__)

_SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(_SERVICES_DIR))
GAZETTEER_PATH = os.path.join(PROJECT_ROOT, "mock_data", "gazetteer.json")

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"

# Road/rail routes are longer than the great-circle distance; ~1.2 is a common
# rule of thumb for surface transport. Flights use the great-circle distance
# unchanged: DESNZ flight factors (and Climatiq's copies of them) already
# include the 8% uplift for indirect routing and stacking, so adding it here
# would count it twice.
SURFACE_DETOUR_FACTOR = 1.2
FLIGHT_UPLIFT_FACTOR = 1.0

_lock = threading.Lock()
_last_nominatim_call = 0.0
_gazetteer: Optional[Dict[str, Any]] = None


def _norm(name: str) -> str:
    return " ".join(name.strip().lower().replace(",", " ").split())


def _load_gazetteer() -> Dict[str, Any]:
    global _gazetteer
    if _gazetteer is None:
        try:
            with open(GAZETTEER_PATH, "r", encoding="utf-8") as fh:
                _gazetteer = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Gazetteer unavailable: %s", exc)
            _gazetteer = {"places": {}, "aliases": {}}
    return _gazetteer


def _respect_rate_limit() -> None:
    """Nominatim allows at most one request per second."""
    global _last_nominatim_call
    with _lock:
        wait = 1.0 - (time.monotonic() - _last_nominatim_call)
        if wait > 0:
            time.sleep(wait)
        _last_nominatim_call = time.monotonic()


def lookup_local(name: str) -> Optional[Dict[str, Any]]:
    """Look up a place in the bundled gazetteer without using the network."""
    if not name:
        return None
    key = _norm(name)
    gaz = _load_gazetteer()
    key = gaz.get("aliases", {}).get(key, key)
    place = gaz.get("places", {}).get(key)
    if place:
        return dict(place, source="gazetteer")
    if len(key) >= 4:
        matches = get_close_matches(key, gaz.get("places", {}).keys(), n=1, cutoff=0.8)
        if matches:
            return dict(gaz["places"][matches[0]], source="gazetteer_fuzzy", matched_input=name)
    return None


def geocode(name: str, live: bool = True, timeout: float = http.LIVE_TIMEOUT) -> Optional[Dict[str, Any]]:
    """Resolve a place name to {name, country, lat, lon, ...} or None."""
    local = lookup_local(name)
    if local or not live or not name:
        return local

    _respect_rate_limit()
    results = http.get_json(
        NOMINATIM_SEARCH,
        params={"q": name, "format": "jsonv2", "limit": 1, "addressdetails": 1,
                "accept-language": "en"},
        timeout=timeout,
    )
    if not results:
        return None
    top = results[0]
    address = top.get("address", {})
    place = {
        "name": (address.get("city") or address.get("town") or address.get("village")
                 or top.get("name") or name.title()),
        "country": address.get("country"),
        "country_code": address.get("country_code"),
        "lat": round(float(top["lat"]), 5),
        "lon": round(float(top["lon"]), 5),
        "display_name": top.get("display_name"),
    }
    return dict(place, source="nominatim")


def reverse_geocode(lat: float, lon: float, timeout: float = http.LIVE_TIMEOUT) -> Optional[Dict[str, Any]]:
    """Turn browser GPS coordinates into a town/city name.

    Falls back to the nearest gazetteer city (within 60 km) when Nominatim is
    unreachable, so the GPS feature still degrades gracefully.
    """
    _respect_rate_limit()
    body = http.get_json(
        NOMINATIM_REVERSE,
        params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10,
                "accept-language": "en"},
        timeout=timeout,
    )
    if body and body.get("address"):
        address = body["address"]
        name = (address.get("city") or address.get("town") or address.get("village")
                or address.get("county") or body.get("name"))
        if name:
            return {"name": name, "country": address.get("country"),
                    "country_code": address.get("country_code"),
                    "lat": lat, "lon": lon, "source": "nominatim"}

    nearest, best = None, None
    for place in _load_gazetteer().get("places", {}).values():
        d = haversine_km(lat, lon, place["lat"], place["lon"])
        if best is None or d < best:
            nearest, best = place, d
    if nearest and best is not None and best <= 60:
        return dict(nearest, lat=lat, lon=lon, source="gazetteer_nearest")
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def travel_distance_km(origin: Dict[str, Any], destination: Dict[str, Any], mode: str) -> float:
    """Approximate door-to-door distance for a mode (rounded to 10 km)."""
    gc = haversine_km(origin["lat"], origin["lon"], destination["lat"], destination["lon"])
    factor = FLIGHT_UPLIFT_FACTOR if mode.startswith("flight") else SURFACE_DETOUR_FACTOR
    return max(10.0, round(gc * factor / 10.0) * 10.0)


def known_destinations() -> list:
    """Names available to the offline place matcher."""
    gaz = _load_gazetteer().get("places", {})
    return sorted(place.get("name", key.title()) for key, place in gaz.items())
