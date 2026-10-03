"""Open-Meteo forecast (no key, free for non-commercial use)."""

from typing import Any, Dict, Optional

from . import http

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> short text
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


def describe(code: Optional[int]) -> str:
    return _WMO.get(int(code), "mixed conditions") if code is not None else "unknown"


def forecast(lat: float, lon: float, days: int = 3) -> Optional[Dict[str, Any]]:
    body = http.get_json(FORECAST_URL, params={
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": days, "timezone": "auto",
    })
    if not body or "daily" not in body:
        return None
    d = body["daily"]
    out_days = []
    for i, date in enumerate(d.get("time", [])):
        out_days.append({
            "date": date,
            "summary": describe(d["weather_code"][i]),
            "t_max": d["temperature_2m_max"][i],
            "t_min": d["temperature_2m_min"][i],
            "rain_chance": (d.get("precipitation_probability_max") or [None] * (i + 1))[i],
        })
    cur = body.get("current", {})
    return {
        "current": {"temp": cur.get("temperature_2m"),
                    "summary": describe(cur.get("weather_code")),
                    "wind_kmh": cur.get("wind_speed_10m")},
        "days": out_days,
    }


def active_travel_advice(fc: Dict[str, Any]) -> str:
    """Turn a forecast into a sustainability-relevant tip (walk/cycle or not)."""
    days = fc.get("days") or []
    if not days:
        return ""
    wet = sum(1 for d in days if (d.get("rain_chance") or 0) >= 60)
    hot = any((d.get("t_max") or 0) >= 33 for d in days)
    cold = all((d.get("t_max") or 0) <= 3 for d in days)
    if wet >= 2:
        return "Rain is likely on most days, so public transport will be more comfortable than cycling."
    if hot:
        return "It will be hot, so walk or cycle in the morning and use trams or metro at midday."
    if cold:
        return "It will be cold. Walking is fine with layers, but bike-share may be limited."
    return "Mild conditions: walking and cycling are realistic ways to get around."
