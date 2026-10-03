"""Carbon estimation: Climatiq API first, DESNZ-based local table as fallback.

Design decisions (documented for the report):
* Colour bands for transport use emission INTENSITY (g CO2e per passenger-km),
  not the absolute total, so a long rail journey is not flagged red merely for
  being long while a short flight still is.
* Results are rounded to two significant figures before being shown; the
  underlying factors are averages, and printing "156.25 kg" would imply a
  precision the data does not have.
* Climatiq calls for several modes run in parallel with a short timeout so a
  mode comparison still fits the 3-second latency budget.
"""

import json
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor, wait
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import http
from .geo import PROJECT_ROOT

logger = logging.getLogger(__name__)

FACTORS_PATH = os.path.join(PROJECT_ROOT, "mock_data", "carbon_factors.json")
CLIMATIQ_ESTIMATE_URL = "https://api.climatiq.io/data/v1/estimate"

_DEFAULT_FACTORS = {
    # DESNZ 2026 (see mock_data/carbon_factors.json for the exact rows).
    "factors_kg_co2e_per_km": {"walk": 0.0, "bike": 0.0, "train": 0.03092, "bus": 0.03948,
                               "electric_car": 0.02951, "car": 0.16152, "ferry": 0.1127,
                               "flight_short": 0.12576, "flight_long": 0.11704},
    "short_haul_max_km": 3700,
    "intensity_bands_g_per_pkm": {"green_max": 60, "amber_max": 149},
    "accommodation_bands_kg_per_night": {"green_max": 10.0, "amber_max": 20.0},
    "relative_bands_ratio_to_best": {"green_max": 1.5, "amber_max": 3.0},
    "mode_labels": {},
    "climatiq": {"data_version": "^37", "selector": {}, "activity_ids": {}},
}

MODE_ALIASES = {
    "plane": "flight", "fly": "flight", "flying": "flight", "air": "flight", "airplane": "flight",
    "rail": "train", "railway": "train", "trains": "train",
    "coach": "bus", "buses": "bus",
    "driving": "car", "drive": "car", "petrol car": "car", "diesel car": "car",
    "ev": "electric_car", "electric car": "electric_car", "electric vehicle": "electric_car",
    "bicycle": "bike", "cycling": "bike", "cycle": "bike",
    "boat": "ferry",
}

COMPARISON_MODES = ["train", "bus", "electric_car", "car", "flight"]


@lru_cache(maxsize=1)
def factors() -> Dict[str, Any]:
    try:
        with open(FACTORS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        merged = dict(_DEFAULT_FACTORS)
        merged.update(data)
        return merged
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("carbon_factors.json unavailable (%s); using built-in defaults", exc)
        return _DEFAULT_FACTORS


def normalise_mode(mode: Optional[str], distance_km: Optional[float] = None) -> str:
    """Map free text ('plane', 'EV', 'flight') onto a factor-table key."""
    m = (mode or "flight").strip().lower().replace("-", " ")
    m = MODE_ALIASES.get(m, m).replace(" ", "_")
    if m == "flight":
        limit = factors().get("short_haul_max_km", 3700)
        m = "flight_short" if (distance_km or 0) <= limit else "flight_long"
    if m not in factors()["factors_kg_co2e_per_km"]:
        logger.info("Unknown mode '%s', treating as petrol car", mode)
        m = "car"
    return m


def mode_label(mode_key: str) -> str:
    return factors().get("mode_labels", {}).get(mode_key, mode_key.replace("_", " ").title())


def round_sig(x: float, sig: int = 2) -> float:
    if x == 0:
        return 0.0
    digits = sig - int(math.floor(math.log10(abs(x)))) - 1
    return round(x, max(digits, 0)) if digits >= 0 else float(round(x, digits))


def transport_band(intensity_g_per_pkm: float) -> str:
    b = factors()["intensity_bands_g_per_pkm"]
    if intensity_g_per_pkm <= b["green_max"]:
        return "green"
    if intensity_g_per_pkm <= b["amber_max"]:
        return "amber"
    return "red"


_BAND_ORDER = {"green": 0, "amber": 1, "red": 2}
NON_MOTORISED = ("walk", "bike")


def worse_band(a: str, b: str) -> str:
    return a if _BAND_ORDER[a] >= _BAND_ORDER[b] else b


def relative_bands(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Raise each band to its relative band where that is worse.

    The relative band compares each option's trip total with the
    lowest-carbon motorised option for the same trip: <= 1.5x green,
    <= 3x amber, above that red. The absolute intensity band is a floor, so
    an option is never shown greener than its intensity alone would make it.
    Needs at least two motorised options; otherwise results are unchanged.
    """
    motorised = [r for r in results if r["mode"] not in NON_MOTORISED and r["kg_co2e"] > 0]
    if len(motorised) < 2:
        return results
    best = min(r["kg_co2e"] for r in motorised)
    cfg = factors().get("relative_bands_ratio_to_best", {"green_max": 1.5, "amber_max": 3.0})
    for r in motorised:
        ratio = r["kg_co2e"] / best
        rel = "green" if ratio <= cfg["green_max"] else "amber" if ratio <= cfg["amber_max"] else "red"
        r["ratio_to_best"] = round(ratio, 1)
        r["band"] = worse_band(r["band"], rel)
    return results


def accommodation_band(kg_per_night: float) -> str:
    b = factors()["accommodation_bands_kg_per_night"]
    if kg_per_night <= b["green_max"]:
        return "green"
    if kg_per_night <= b["amber_max"]:
        return "amber"
    return "red"


def _local_estimate(mode_key: str, distance_km: float) -> float:
    return factors()["factors_kg_co2e_per_km"][mode_key] * distance_km


def climatiq_request(mode_key: str, distance_km: float) -> Dict[str, Any]:
    """Estimate request pinned to the same DESNZ/BEIS rows as the local table.

    Car factors are per vehicle-km (one occupant), so they take no
    `passengers` parameter; Climatiq rejects it for those factors.
    """
    cfg = factors().get("climatiq", {})
    emission_factor = {
        "activity_id": cfg.get("activity_ids", {}).get(mode_key),
        "data_version": http.env("CLIMATIQ_DATA_VERSION", cfg.get("data_version", "^37")),
        **cfg.get("selector", {}),
        **cfg.get("selector_overrides", {}).get(mode_key, {}),
    }
    parameters: Dict[str, Any] = {"distance": distance_km, "distance_unit": "km"}
    if mode_key not in cfg.get("per_vehicle_modes", []):
        parameters["passengers"] = 1
    return {"emission_factor": emission_factor, "parameters": parameters}


def _climatiq_estimate(mode_key: str, distance_km: float, api_key: str) -> Optional[float]:
    cfg = factors().get("climatiq", {})
    activity_id = cfg.get("activity_ids", {}).get(mode_key)
    if not activity_id:
        return None
    body = http.post_json(CLIMATIQ_ESTIMATE_URL, json_body=climatiq_request(mode_key, distance_km),
                          extra_headers={"Authorization": f"Bearer {api_key}"})
    try:
        return float(body["co2e"]) if body else None
    except (KeyError, TypeError, ValueError):
        logger.warning("Unexpected Climatiq response shape for %s", mode_key)
        return None


def estimate(mode: Optional[str], distance_km: float) -> Dict[str, Any]:
    """Estimate one mode. Always returns a result (falls back locally)."""
    return compare([mode or "flight"], distance_km)[0]


def compare(modes: Iterable[str], distance_km: float) -> List[Dict[str, Any]]:
    """Estimate several modes over the same distance, best (lowest) first."""
    return compare_routes([(m, distance_km) for m in modes])


def compare_routes(routes: Iterable[Tuple[str, float]]) -> List[Dict[str, Any]]:
    """Estimate (mode, distance_km) pairs, best (lowest) first.

    Modes can have different distances: surface modes use a road/rail detour
    while flights use the great-circle distance (see geo.travel_distance_km).
    Climatiq calls run in parallel in one pool so the whole comparison stays
    inside a single LIVE_TIMEOUT. Each result: {mode, label, distance_km,
    kg_co2e, kg_display, intensity_g_per_pkm, band, source}.
    """
    pairs: List[Tuple[str, float]] = []
    for m, km in routes:
        k = normalise_mode(m, km)
        if k not in [p[0] for p in pairs]:
            pairs.append((k, km))

    api_key = http.env("CLIMATIQ_API_KEY", "")
    live: Dict[str, Optional[float]] = {}
    if api_key and pairs:
        pool = ThreadPoolExecutor(max_workers=len(pairs))
        futures = {k: pool.submit(_climatiq_estimate, k, km, api_key) for k, km in pairs if km > 0}
        wait(futures.values(), timeout=http.LIVE_TIMEOUT + 0.3)
        for k, fut in futures.items():
            live[k] = fut.result() if fut.done() and not fut.exception() else None
        pool.shutdown(wait=False, cancel_futures=True)

    results = []
    for k, km in pairs:
        kg = live.get(k)
        source = "climatiq_api"
        if kg is None:
            kg = _local_estimate(k, km)
            source = "local_factor_table"
        intensity = (kg * 1000.0 / km) if km else 0.0
        results.append({
            "mode": k,
            "label": mode_label(k),
            "distance_km": round(km),
            "kg_co2e": round(kg, 2),
            "kg_display": round_sig(kg, 2),
            "intensity_g_per_pkm": round(intensity),
            "band": transport_band(intensity),
            "source": source,
        })
    results.sort(key=lambda r: r["kg_co2e"])
    return relative_bands(results)


def offset_needed_tonnes(kg_co2e: float) -> float:
    return round(kg_co2e / 1000.0, 3)
