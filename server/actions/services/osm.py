"""Overpass (OpenStreetMap) queries.

Overpass is a shared, volunteer-run service and can return 504 when busy.
Each query has a bounded timeout and the actions show an honest unavailable
message instead of returning fabricated recommendations.

Query design notes:
* ``nwr`` (node + way + relation) with ``out center`` - large hotels and
  museums are usually mapped as building outlines (ways), so node-only
  queries silently miss most of them.
* ``historic`` is constrained to values a visitor would plan around; a bare
  ``historic`` matches sally ports and street memorials.
* Bus stops are deliberately excluded from the transport query: they are
  dense and low-value, and including them caused 504 timeouts.
"""

import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Dict, List, Optional

from . import http

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

ECO_TAGS = ("green_key", "ecolabel", "eco_label", "certification", "sustainability")

# Successful responses are reused for a while: hotel search and the follow-up
# local-transport card ask Overpass the same question seconds apart, and a
# mirror that answered once may time out on the repeat.
CACHE_TTL_S = 3600.0
_cache: Dict[str, Any] = {}


def run_query(query: str) -> Optional[List[Dict[str, Any]]]:
    """Try independent public mirrors concurrently within the turn budget.

    Overpass is a best-effort enrichment, not a reason to leave a traveller
    staring at a typing indicator for several minutes. A 504 or timeout now
    gives an honest unavailable response promptly; it is not retried during
    the same conversation turn.
    """
    cached = _cache.get(query)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
        return cached[1]
    with ThreadPoolExecutor(max_workers=len(OVERPASS_URLS)) as pool:
        futures = [pool.submit(http.post_json, url, data={"data": query}, timeout=http.LIVE_TIMEOUT)
                   for url in OVERPASS_URLS]
        done, pending = wait(futures, timeout=http.LIVE_TIMEOUT + 0.2)
        for future in done:
            try:
                body = future.result()
            except Exception:  # Defensive: a public mirror must not break a reply.
                body = None
            if body is not None:
                elements = body.get("elements", [])
                _cache[query] = (time.monotonic(), elements)
                return elements
        for future in pending:
            future.cancel()
    return None


def _coords(el: Dict[str, Any]):
    if "lat" in el:
        return el["lat"], el["lon"]
    c = el.get("center") or {}
    return c.get("lat"), c.get("lon")


def hotels(lat: float, lon: float, radius_m: int = 2500, limit: int = 40) -> Optional[List[Dict[str, Any]]]:
    q = f"""
    [out:json][timeout:45];
    nwr["tourism"~"^(hotel|hostel|guest_house|apartment)$"]["name"](around:{radius_m},{lat},{lon});
    out center tags {limit};
    """
    els = run_query(q)
    if els is None:
        return None
    out = []
    for el in els:
        tags = el.get("tags", {})
        la, lo = _coords(el)
        if not tags.get("name") or la is None:
            continue
        eco_tag = next((f"{k}={tags[k]}" for k in ECO_TAGS if k in tags), None)
        out.append({
            "osm_id": f"{el['type']}/{el['id']}",
            "name": tags["name"],
            "type": tags.get("tourism"),
            "stars": tags.get("stars"),
            "rooms": tags.get("rooms"),
            "wheelchair": tags.get("wheelchair"),
            "website": tags.get("website") or tags.get("contact:website"),
            "eco_tag": eco_tag,
            "has_parking": tags.get("parking") not in (None, "no"),
            "lat": la, "lon": lo,
        })
    return out


def transport(lat: float, lon: float, radius_m: int = 1500) -> Optional[List[Dict[str, Any]]]:
    q = f"""
    [out:json][timeout:45];
    (
      nwr["railway"="station"](around:{radius_m},{lat},{lon});
      nwr["station"="subway"](around:{radius_m},{lat},{lon});
      node["railway"="tram_stop"](around:{radius_m},{lat},{lon});
      node["amenity"="bicycle_rental"](around:{radius_m},{lat},{lon});
      node["amenity"="ferry_terminal"](around:{radius_m},{lat},{lon});
    );
    out center tags 150;
    """
    els = run_query(q)
    if els is None:
        return None
    out = []
    for el in els:
        tags = el.get("tags", {})
        la, lo = _coords(el)
        if la is None:
            continue
        if tags.get("station") == "subway":
            kind = "metro"
        elif tags.get("railway") == "station":
            kind = "rail"
        elif tags.get("railway") == "tram_stop":
            kind = "tram"
        elif tags.get("amenity") == "bicycle_rental":
            kind = "bike_share"
        else:
            kind = "ferry"
        out.append({"name": tags.get("name"), "kind": kind, "lat": la, "lon": lo})
    return out


def attractions(lat: float, lon: float, radius_m: int = 3000, limit: int = 40) -> Optional[List[Dict[str, Any]]]:
    q = f"""
    [out:json][timeout:45];
    (
      nwr["tourism"~"^(museum|gallery)$"]["name"](around:{radius_m},{lat},{lon});
      nwr["historic"~"^(castle|monument|archaeological_site|monastery|fort|ruins)$"]["name"](around:{radius_m},{lat},{lon});
      nwr["amenity"~"^(theatre|arts_centre|marketplace)$"]["name"](around:{radius_m},{lat},{lon});
    );
    out center tags {limit};
    """
    els = run_query(q)
    if els is None:
        return None
    out = []
    for el in els:
        tags = el.get("tags", {})
        la, lo = _coords(el)
        if la is None:
            continue
        kind = tags.get("tourism") or tags.get("historic") or tags.get("amenity")
        out.append({
            "name": tags["name"],
            "kind": kind,
            "wikipedia": tags.get("wikipedia"),
            "wheelchair": tags.get("wheelchair"),
            "fee": tags.get("fee"),
            "lat": la, "lon": lo,
        })
    # Prefer entries with a Wikipedia article (more notable, describable).
    out.sort(key=lambda a: (a["wikipedia"] is None, a["name"]))
    return out
