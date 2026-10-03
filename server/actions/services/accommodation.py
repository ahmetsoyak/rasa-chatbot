"""Derive honest accommodation indicators from OpenStreetMap records.

Greenwashing safeguard
----------------------
OpenStreetMap almost never records eco-certification. The bot therefore
NEVER calls an OSM hotel "eco-certified". Instead it reports:

* ``eco_tag``   - only when OSM itself carries a tag (shown as "unverified
                  OSM tag"), because tags are user-edited;
* ``proxies``   - observable indicators (near rail/metro/tram, small scale,
                  no car park) that are explicitly labelled as proxies;
* estimates     - price band and per-night footprint inferred from the
                  accommodation type, labelled "estimate".
"""

import os
from typing import Any, Dict, List, Optional

from .carbon import accommodation_band, factors
from .geo import haversine_km

# Indicative nightly prices (EUR) per type, used only to rank OSM results that
# carry no price. Shown to the user as a band (EUR / EUR EUR / EUR EUR EUR), never as a quote.
_PRICE_BY_TYPE = {
    "hostel": 35, "guest_house": 70, "apartment": 90,
    "hotel_1_2_star": 70, "hotel_3_star": 110, "hotel_4_5_star": 200, "hotel_unknown": 110,
}


def _type_key(hotel: Dict[str, Any]) -> str:
    t = hotel.get("type") or "hotel"
    if t != "hotel":
        return t if t in _PRICE_BY_TYPE else "hotel_unknown"
    try:
        stars = float(str(hotel.get("stars") or "").replace("S", "").strip())
    except ValueError:
        return "hotel_unknown"
    if stars <= 2:
        return "hotel_1_2_star"
    if stars < 4:
        return "hotel_3_star"
    return "hotel_4_5_star"


def nearest_stop(lat: float, lon: float, stops: List[Dict[str, Any]],
                 kinds=("rail", "metro", "tram")) -> Optional[Dict[str, Any]]:
    best = None
    for s in stops:
        if s.get("kind") not in kinds:
            continue
        d = haversine_km(lat, lon, s["lat"], s["lon"]) * 1000
        if best is None or d < best["distance_m"]:
            best = {"name": s.get("name") or s["kind"], "kind": s["kind"], "distance_m": round(d)}
    return best


def enrich_hotel(hotel: Dict[str, Any], stops: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach proxy indicators and labelled estimates to one OSM hotel."""
    h = dict(hotel)
    tkey = _type_key(h)
    kg = factors().get("accommodation_kg_per_night_by_type", {}).get(tkey, 16.0)
    price = _PRICE_BY_TYPE[tkey]
    proxies = []
    stop = nearest_stop(h["lat"], h["lon"], stops)
    if stop and stop["distance_m"] <= 500:
        proxies.append(f"{stop['distance_m']} m from {stop['kind']} ({stop['name']})")
    try:
        if h.get("rooms") and int(h["rooms"]) <= 30:
            proxies.append(f"small scale ({h['rooms']} rooms)")
    except ValueError:
        pass
    if h.get("type") in ("hostel", "guest_house"):
        proxies.append(f"{h['type'].replace('_', ' ')} (typically lower energy use per guest)")
    h.update({
        "nearest_transit": stop,
        "proxies": proxies,
        "type_key": tkey,
        "est_kg_co2e_per_night": kg,
        "est_price_eur": price,
        "price_band": "€" if price < 60 else "€€" if price < 150 else "€€€",
        "band": accommodation_band(kg),
    })
    return h


def proxy_score(hotel: Dict[str, Any]) -> int:
    """Number of sustainability proxies a hotel shows (for tie-breaking)."""
    return len(hotel.get("proxies") or []) + (1 if hotel.get("eco_tag") else 0)


def transit_summary(stops: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for s in stops:
        out[s["kind"]] = out.get(s["kind"], 0) + 1
    return out
