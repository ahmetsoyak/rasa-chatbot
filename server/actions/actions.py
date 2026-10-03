"""Custom actions for the Eco-Travel Advisor Rasa chatbot."""

import json
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Text

import requests
from dotenv import load_dotenv
from rasa_sdk import Action, FormValidationAction, Tracker
from rasa_sdk.events import EventType, SlotSet
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.types import DomainDict

from actions.services import accommodation
from actions.services import carbon, currency, geo, http, osm, weather, wiki
from actions import handover as handover_module
from actions.handover import (ActionDefaultFallback, ActionHumanHandover as _ActionHumanHandover,
                              ActionRecordHandoverConsent, build_handover_package)

load_dotenv()

logger = logging.getLogger(__name__)

_ACTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_ACTIONS_DIR)
_MOCK_DATA_DIR = os.path.join(_PROJECT_ROOT, "mock_data")
_DATA_DIR = os.path.join(_PROJECT_ROOT, "rasa", "data")

OFFSET_PROGRAMS_PATH = os.path.join(_MOCK_DATA_DIR, "offset_programs.json")
ACCOMMODATION_SAMPLE_PATH = os.path.join(_MOCK_DATA_DIR, "accommodation_samples.json")
HANDOVER_LOG_PATH = http.env("HANDOVER_LOG_PATH", os.path.join(_DATA_DIR, "handover_log.jsonl"))


class ActionHumanHandover(_ActionHumanHandover):
    """Compatibility export for Rasa and tests that configure the log path here."""

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any],
            reason: Text = "user_requested") -> List[EventType]:
        handover_module.HANDOVER_LOG_PATH = HANDOVER_LOG_PATH
        return super().run(dispatcher, tracker, domain, reason)

# Nightly accommodation ceilings (EUR) per budget tier, used to flag options.
BUDGET_NIGHTLY_CAP_EUR = {"low": 80, "medium": 160, "high": None}

# Default weights used by weighted_score() before adjusting for sustainability_level.
_DEFAULT_W_CARBON = 0.5

# Wording for the sustainability tooltip shown in the UI.
CARBON_TOOLTIP = (
    "kg CO2e = kilograms of carbon-dioxide equivalent per traveller, including other "
    "greenhouse gases (flights include the extra warming from contrails and NOx). "
    "Colour compares each option with the lowest-carbon way to make this trip: green is up to "
    "1.5 times it, amber up to 3 times, red more than that. An option of 150 g per km or more "
    "is always red. Figures are rounded UK government (DESNZ 2026) averages."
)


def _load_json(path: Text) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _safe_load_json(path: Text, default: Any) -> Any:
    try:
        return _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load data file %s: %s", path, exc)
        return default


def weighted_score(carbon_impact: float, price: float, user_pref_weight: float) -> float:
    """Weighted desirability score in [0, 1] (higher is better).

        score = (1 - carbon_norm) * w_carbon + (1 - price_norm) * w_price
        w_carbon = user_pref_weight, w_price = 1 - w_carbon

    ``carbon_impact`` and ``price`` must already be min-max normalised to
    [0, 1] across the candidate set (0 = lowest/best). ``user_pref_weight``
    comes from the sustainability_level slot (low 0.25, medium 0.5, high 0.8).
    """
    w_carbon = max(0.0, min(1.0, user_pref_weight))
    w_price = 1.0 - w_carbon
    normalized_carbon = max(0.0, min(1.0, carbon_impact))
    normalized_price = max(0.0, min(1.0, price))
    score = (1 - normalized_carbon) * w_carbon + (1 - normalized_price) * w_price
    return round(score, 4)


def _sustainability_to_pref_weight(sustainability_level: Optional[Text]) -> float:
    mapping = {"low": 0.25, "medium": 0.5, "high": 0.8}
    if sustainability_level is None:
        return _DEFAULT_W_CARBON
    return mapping.get(sustainability_level.lower(), _DEFAULT_W_CARBON)


def _normalize(values: List[float]) -> List[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _rank_candidates(
    candidates: List[Dict[str, Any]],
    carbon_key: Text,
    price_key: Text,
    sustainability_level: Optional[Text],
    preference_bonus_key: Optional[Text] = None,
) -> List[Dict[str, Any]]:
    """Attach a ``score`` to each candidate and return them best first.

    ``preference_bonus_key`` (optional) names a 0-1 field that adds up to
    0.1 to the score. It is used for things the user cares about that are
    neither carbon nor price (e.g. number of sustainability proxies, or being
    within the stated budget). It is a tie-breaker, not a third weight.
    """
    if not candidates:
        return []
    carbon_values = [float(c.get(carbon_key) or 0.0) for c in candidates]
    price_values = [float(c.get(price_key) or 0.0) for c in candidates]
    norm_carbon = _normalize(carbon_values)
    norm_price = _normalize(price_values)
    pref_weight = _sustainability_to_pref_weight(sustainability_level)

    scored = []
    for candidate, nc, np_ in zip(candidates, norm_carbon, norm_price):
        enriched = dict(candidate)
        score = weighted_score(nc, np_, pref_weight)
        if preference_bonus_key:
            score += 0.1 * max(0.0, min(1.0, float(candidate.get(preference_bonus_key) or 0)))
        enriched["score"] = round(score, 4)
        scored.append(enriched)

    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored


def _entity(tracker: Tracker, name: Text) -> Optional[Any]:
    for e in (tracker.latest_message or {}).get("entities", []) or []:
        if e.get("entity") == name:
            return e.get("value")
    return None


def _message_text(tracker: Tracker) -> Text:
    """The user's latest message, or "" for button payloads like '/intent{...}'."""
    text = (tracker.latest_message or {}).get("text") or ""
    return "" if text.startswith("/") else text


def _destination_phrase(text: Text) -> Text:
    """Extract a likely place phrase from an otherwise natural sentence.

    DIET deliberately does not force every unknown word to be a location. For
    an intent that is already confidently ``inform_destination``, recover the
    phrase after common travel wording and let the geocoder/fuzzy gazetteer
    validate it. This supports inputs such as "I would like to go Cophanagen"
    without treating arbitrary hotel-request words as cities.
    """
    cleaned = text.strip().rstrip("?.!")
    match = re.search(r"\b(?:go|travel|head|fly|drive)(?:\s+to)?\s+(.+)$|\bvisit\s+(.+)$|\bdestination\s+is\s+(.+)$", cleaned, re.I)
    if match:
        return next(part.strip() for part in match.groups() if part)
    return cleaned


def _user_currency(tracker: Tracker) -> Text:
    return tracker.get_slot("user_currency") or "EUR"


def _fmt_money(amount: Optional[float], cur: Text) -> Text:
    if amount is None:
        return "price n/a"
    symbol = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥"}.get(cur, cur + " ")
    return f"{symbol}{amount:,.0f}"


def _convert_or_none(amount: float, src: Text, dst: Text) -> Optional[float]:
    try:
        return currency.convert(amount, src, dst)
    except Exception as exc:  # never let a currency glitch break a reply
        logger.warning("currency conversion failed: %s", exc)
        return None


def _origin_place(tracker: Tracker) -> Optional[Dict[str, Any]]:
    lat, lon = tracker.get_slot("origin_lat"), tracker.get_slot("origin_lon")
    name = tracker.get_slot("origin")
    if lat is not None and lon is not None:
        return {"name": name or "your location", "lat": float(lat), "lon": float(lon)}
    if name:
        return geo.geocode(name)
    return None


def _follow_up_buttons(destination: Optional[Text], extra: Optional[List[Dict[str, Text]]] = None) -> List[Dict[str, Text]]:
    """Context-dependent quick replies generated by actions (not static domain buttons)."""
    buttons: List[Dict[str, Text]] = list(extra or [])
    if destination:
        buttons += [
            {"title": f"Things to do in {destination}", "payload": "/ask_cultural_experiences"},
            {"title": f"Weather in {destination}", "payload": "/ask_weather"},
        ]
    buttons += [
        {"title": "Offset my trip", "payload": "/ask_carbon_offset"},
        {"title": "Talk to a human advisor", "payload": "/request_human_advisor"},
    ]
    return buttons



class ActionSetLocation(Action):
    """Handles both location inputs the brief asks for:

    * GPS: the frontend sends ``/share_location{"latitude":..,"longitude":..}``
      after the browser's geolocation prompt; we reverse-geocode it.
    * Manual: "I'm travelling from Berlin" (entity ``origin``); we geocode it.
    """

    def name(self) -> Text:
        return "action_set_location"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        lat, lon = _entity(tracker, "latitude"), _entity(tracker, "longitude")
        origin_text = _entity(tracker, "origin") or tracker.get_slot("origin")

        if lat is not None and lon is not None:
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                dispatcher.utter_message(text="I couldn't read your location. Please type the city you're travelling from.")
                return []
            place = geo.reverse_geocode(lat, lon)
            label = place["name"] if place else "your current location"
            dispatcher.utter_message(
                text=f"Thanks. I'll calculate journeys from {label}. "
                     "I only use your coordinates for this conversation and don't store them."
            )
            events: List[EventType] = [SlotSet("origin", label), SlotSet("origin_lat", lat), SlotSet("origin_lon", lon)]
        elif origin_text:
            place = geo.geocode(origin_text)
            if not place:
                dispatcher.utter_message(
                    text=f"I couldn't find '{origin_text}' on the map. Could you give the nearest city?",
                    buttons=[{"title": "Use my location", "payload": "/share_location"}],
                )
                return [SlotSet("origin", None)]
            dispatcher.utter_message(text=f"Got it, travelling from {place['name']}.")
            events = [SlotSet("origin", place["name"]), SlotSet("origin_lat", place["lat"]), SlotSet("origin_lon", place["lon"])]
        else:
            dispatcher.utter_message(
                text="Where will you be travelling from? Type a city, or share your location.",
                buttons=[{"title": "Use my location", "payload": "/share_location"}],
            )
            return []

        if tracker.get_slot("destination"):
            dispatcher.utter_message(
                text="Want me to compare ways of getting there?",
                buttons=[{"title": f"Compare routes to {tracker.get_slot('destination')}", "payload": "/ask_carbon_footprint"}],
            )
        else:
            dispatcher.utter_message(
                text="Where would you like to go from there?",
                buttons=[{"title": "Plan a trip", "payload": "/request_trip_planning"}],
            )
        return events



class ActionSetDestination(Action):
    """Runs before the form when the user names a place outside it.

    With an entity, the slot mapping has already stored it. Without one (a
    city the model doesn't know, or a short unclear message the model
    misreads as a place) the whole message is geocoded: a real place becomes
    the new destination; anything else clears the slot so the form asks again
    rather than silently re-running the previous trip.
    """

    def name(self) -> Text:
        return "action_set_destination"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        extracted = _entity(tracker, "destination")
        raw = extracted or _destination_phrase(_message_text(tracker))
        raw = str(raw).strip()
        place = geo.geocode(raw) if 0 < len(raw) <= 40 else None
        if place:
            if extracted and raw.lower() == place["name"].lower():
                # Rasa has already set this valid entity through the slot
                # mapping; avoid creating a redundant slot event.
                return []
            if raw.lower() != place["name"].lower():
                dispatcher.utter_message(text=f"I'll use {place['name']} for '{raw}'.")
            return [SlotSet("destination", place["name"])]
        if raw:
            dispatcher.utter_message(text=f"I couldn't match '{raw}' to a place.")
        return [SlotSet("destination", None)]


class ActionUpdateSustainabilityLevel(Action):
    """Normalises a preference change made after the form ("I care more about
    price now") so the re-ranking that follows uses low/medium/high."""

    def name(self) -> Text:
        return "action_update_sustainability_level"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        value = _entity(tracker, "sustainability_level")
        level = (str(value).lower() if str(value).lower() in ("low", "medium", "high") else None) \
            or map_sustainability_text(_message_text(tracker)) or map_sustainability_text(value)
        if level:
            return [SlotSet("sustainability_level", level)]
        return ActionAskSustainabilityLevel().run(dispatcher, tracker, domain)


class ActionAskDestination(Action):
    """Asks for the destination with quick replies built from the destinations
    that actually have data, so the buttons always reflect what the bot can
    answer well."""

    def name(self) -> Text:
        return "action_ask_destination"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        known = geo.known_destinations()
        names = list(dict.fromkeys(n for n in known if n))
        buttons = [{"title": n, "payload": f'/inform_destination{{"destination": "{n}"}}'} for n in names[:6]]
        dispatcher.utter_message(
            text="Where would you like to go? Pick one, or type any city.",
            buttons=buttons,
        )
        return []


class ActionAskSustainabilityLevel(Action):
    """Asks for the sustainability preference and explains what each choice
    changes, so the user can see the effect of their answer on ranking."""

    def name(self) -> Text:
        return "action_ask_sustainability_level"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        dest = tracker.get_slot("destination")
        prefix = f"For {dest}: " if dest else ""
        dispatcher.utter_message(
            text=prefix + "how much should low emissions count against price when I rank options?",
            buttons=[
                {"title": "Price first (25% carbon)", "payload": '/inform_sustainability_preference{"sustainability_level": "low"}'},
                {"title": "Balanced (50/50)", "payload": '/inform_sustainability_preference{"sustainability_level": "medium"}'},
                {"title": "Lowest carbon (80% carbon)", "payload": '/inform_sustainability_preference{"sustainability_level": "high"}'},
            ],
        )
        return []


# Checked in order, first match wins, on word boundaries. Negations come first
# ("not really important" is low), then phrases where "low" means low CARBON
# ("lowest carbon" is high), and only then the bare levels.
_SUSTAINABILITY_PATTERNS = [
    ("low", r"not really|not (that |very )?important|not a priority|don'?t care|doesn'?t matter|"
            r"price first|very low"),
    ("high", r"low[- ]?(carbon|emissions?)|lowest|important|top priority|very|most|max|"
             r"strict|eco|green as possible|essential|high"),
    ("medium", r"medium|moderate|balanced?|both|somewhat|fairly|some|middle|average|50"),
    ("low", r"low|cheap(er)?|minimal|little|price|money|cost"),
]


def map_sustainability_text(text: Optional[Text]) -> Optional[Text]:
    if not text:
        return None
    t = text.lower()
    for level, pattern in _SUSTAINABILITY_PATTERNS:
        if re.search(rf"\b(?:{pattern})\b", t):
            return level
    return None


_DATE_HINT = re.compile(
    r"\d|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|"
    r"\b(mon|tues|wednes|thurs|fri|satur|sun)day\b|\b(today|tomorrow|tonight|week|weekend|month|year|"
    r"spring|summer|autumn|fall|winter|christmas|easter|new year|half term|holiday|holidays|"
    r"flexible|any ?time|soon|asap|next|this|early|mid|late)\b",
    re.IGNORECASE,
)


class ValidateTripPlanningForm(FormValidationAction):
    """Validates and normalises each form slot. Invalid or ambiguous input is
    rejected with a specific clarification (the error-recovery requirement)
    instead of being stored as-is."""

    def name(self) -> Text:
        return "validate_trip_planning_form"

    def validate_destination(self, slot_value: Any, dispatcher: CollectingDispatcher,
                             tracker: Tracker, domain: DomainDict) -> Dict[Text, Any]:
        values = slot_value if isinstance(slot_value, list) else [slot_value]
        values = [v for v in values if v]
        if not values:
            return {"destination": None}
        if len(values) >= 3:
            dispatcher.utter_message(
                text=f"A multi-stop trip ({', '.join(values)}) is something our human advisors plan best. "
                     f"I'll start with {values[0]} for now.",
                buttons=[{"title": "Talk to a human advisor", "payload": "/request_human_advisor"}],
            )
        place = geo.geocode(str(values[0]))
        if not place:
            dispatcher.utter_message(
                text=f"I couldn't find '{values[0]}' on the map. Could you check the spelling or give a nearby city?"
            )
            return {"destination": None}
        if place.get("source") == "gazetteer_fuzzy":
            dispatcher.utter_message(text=f"I'll use {place['name']} for '{values[0]}'.")
        out: Dict[Text, Any] = {"destination": place["name"]}
        # A bare city name typed as the answer can be tagged as `origin` by the
        # NLU model; the same city can't be both, so drop the origin.
        origin = tracker.get_slot("origin")
        if origin and str(origin).lower() in (str(values[0]).lower(), place["name"].lower()):
            out.update({"origin": None, "origin_lat": None, "origin_lon": None})
        return out

    def validate_travel_dates(self, slot_value: Any, dispatcher: CollectingDispatcher,
                              tracker: Tracker, domain: DomainDict) -> Dict[Text, Any]:
        text = (slot_value[0] if isinstance(slot_value, list) else slot_value) or ""
        # "10 to 15 May" can come back as two entities ("10 to", "15 May") and
        # Rasa keeps only the last; use the span from the first to the last.
        msg = tracker.latest_message or {}
        spans = [e for e in msg.get("entities") or []
                 if e.get("entity") == "travel_date" and e.get("start") is not None]
        if len(spans) > 1 and msg.get("text"):
            text = msg["text"][min(e["start"] for e in spans):max(e["end"] for e in spans)]
        if len(str(text).strip()) < 3 or not _DATE_HINT.search(str(text)):
            dispatcher.utter_message(text="Sorry, I didn't get the dates. Something like 'mid-May' or '3 to 10 June' works.")
            return {"travel_dates": None}
        return {"travel_dates": str(text).strip()}

    def validate_budget(self, slot_value: Any, dispatcher: CollectingDispatcher,
                        tracker: Tracker, domain: DomainDict) -> Dict[Text, Any]:
        text = slot_value[0] if isinstance(slot_value, list) else slot_value
        parsed = currency.parse_budget(str(text) if text is not None else "")
        if not parsed["currency"]:
            parsed["currency"] = currency.parse_budget(_message_text(tracker))["currency"]
        if parsed["amount"] is None and parsed["tier"] is None:
            dispatcher.utter_message(
                text="I didn't catch a budget. You can give an amount ('£1200') or a level.",
                buttons=[
                    {"title": "Low budget", "payload": '/inform_budget{"budget": "low"}'},
                    {"title": "Medium budget", "payload": '/inform_budget{"budget": "medium"}'},
                    {"title": "High budget", "payload": '/inform_budget{"budget": "high"}'},
                ],
            )
            return {"budget": None}
        out: Dict[Text, Any] = {"budget": str(text), "budget_tier": parsed["tier"]}
        if parsed["currency"]:
            out["user_currency"] = parsed["currency"]
        return out

    def validate_sustainability_level(self, slot_value: Any, dispatcher: CollectingDispatcher,
                                      tracker: Tracker, domain: DomainDict) -> Dict[Text, Any]:
        value = str(slot_value).lower() if slot_value else ""
        if value in ("low", "medium", "high"):
            return {"sustainability_level": value}
        # The entity can be a fragment ("important" out of "not that important"),
        # so try the whole message before the extracted value.
        mapped = map_sustainability_text(_message_text(tracker)) or map_sustainability_text(value)
        if mapped:
            return {"sustainability_level": mapped}
        dispatcher.utter_message(text="Sorry, I didn't catch that. Please choose one of the options.")
        return {"sustainability_level": None}



def _osm_hotel_card(h: Dict[str, Any], user_cur: Text, cap_eur: Optional[float],
                    data_source: Text = "OpenStreetMap") -> Dict[str, Any]:
    price_user = _convert_or_none(h["est_price_eur"], "EUR", user_cur)
    within = cap_eur is None or h["est_price_eur"] <= cap_eur
    return {
        "name": h["name"],
        "eco_certification": h.get("eco_certification") if h.get("sample_data") else None,
        "eco_tag": h.get("eco_tag"),
        "verification": "sample_data" if h.get("sample_data") else ("unverified_osm_tag" if h.get("eco_tag") else "none"),
        "proxies": h.get("proxies", []),
        "type": (h.get("type") or "hotel").replace("_", " "),
        "price_band": h.get("price_band"),
        "price_per_night": round(price_user) if price_user is not None else h["est_price_eur"],
        "currency": user_cur if price_user is not None else "EUR",
        "price_is_estimate": True,
        "kg_co2e_per_night": h["est_kg_co2e_per_night"],
        "carbon_is_estimate": True,
        "band": h.get("band"),
        "within_budget": within,
        "wheelchair": h.get("wheelchair"),
        "booking_url": h.get("website"),
        "data_source": data_source,
        "score": h.get("score"),
    }


def find_accommodation(destination: Optional[Text], sustainability_level: Optional[Text],
                       budget_tier: Optional[Text]) -> Dict[str, Any]:
    """Query OpenStreetMap and return ranked accommodation results."""
    cap = BUDGET_NIGHTLY_CAP_EUR.get(budget_tier or "", None)
    place = geo.geocode(destination) if destination else None
    if not place:
        return {"source": "osm", "items": [], "unknown_destination": True}
    # Both OpenStreetMap lookups are independent. Parallel execution keeps a
    # degraded public API within one short interaction-time budget.
    with ThreadPoolExecutor(max_workers=2) as pool:
        stops_future = pool.submit(osm.transport, place["lat"], place["lon"])
        hotels_future = pool.submit(osm.hotels, place["lat"], place["lon"])
        stops, raw_hotels = stops_future.result(), hotels_future.result()
    source = "osm"
    if stops is None or raw_hotels is None:
        # Public Overpass mirrors are often unavailable. The brief permits a
        # curated mock database for exactly this case; use it transparently
        # rather than leaving the main hotel experience non-functional.
        samples = _safe_load_json(ACCOMMODATION_SAMPLE_PATH, {})
        raw_hotels = samples.get(place["name"].strip().lower(), [])
        if not raw_hotels:
            return {"source": "osm", "items": [], "unavailable": True}
        stops, source = [], "curated_demo"
    hotels = []
    for raw in raw_hotels:
        h = accommodation.enrich_hotel(raw, stops)
        if source == "curated_demo":
            h["sample_data"] = True
            h["eco_certification"] = raw.get("eco_certification")
        h["_bonus"] = min(1.0, accommodation.proxy_score(h) / 3.0) * 0.5 + (
            0.5 if cap is None or h["est_price_eur"] <= cap else 0.0)
        hotels.append(h)
    ranked = _rank_candidates(hotels, "est_kg_co2e_per_night", "est_price_eur",
                              sustainability_level, preference_bonus_key="_bonus")
    return {"source": source, "items": ranked}



class ActionSearchAccommodations(Action):
    def name(self) -> Text:
        return "action_search_accommodations"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        destination = tracker.get_slot("destination")
        if not destination:
            dispatcher.utter_message(text="Which city should I look for places to stay in?")
            return []
        level = tracker.get_slot("sustainability_level")
        tier = tracker.get_slot("budget_tier")
        user_cur = _user_currency(tracker)
        cap = BUDGET_NIGHTLY_CAP_EUR.get(tier or "", None)

        result = find_accommodation(destination, level, tier)
        if result.get("unknown_destination"):
            # NLU can occasionally mistake a word near "hotel" or
            # "recommend" for a location. Never show that token back as a
            # destination or try to query accommodation providers with it.
            dispatcher.utter_message(
                text="I need a city or destination before I can recommend a hotel. Where are you travelling to?",
                buttons=[
                    {"title": name, "payload": f'/inform_destination{{"destination": "{name}"}}'}
                    for name in geo.known_destinations()[:4]
                ],
            )
            return [SlotSet("destination", None)]
        top = result["items"][:3]
        if not top:
            reason = "I couldn't reach OpenStreetMap right now" if result.get("unavailable") else "I couldn't find named places to stay"
            dispatcher.utter_message(
                text=f"{reason} in {destination}. A human advisor can help, "
                     "or I can still compare low-carbon ways to get there.",
                buttons=[
                    {"title": "Compare ways to get there", "payload": "/ask_carbon_footprint"},
                    {"title": "Talk to a human advisor", "payload": "/request_human_advisor"},
                ],
            )
            return []

        is_sample = result.get("source") == "curated_demo"
        data_source = "Curated demo data" if is_sample else "OpenStreetMap"
        cards = [_osm_hotel_card(h, user_cur, cap, data_source=data_source) for h in top]
        note = ("The live map service is unavailable, so these are clearly-labelled illustrative entries from a curated "
                "local demo set; they are not verified listings or booking quotes. Prices and footprints are estimates."
                if is_sample else
                "Real places from OpenStreetMap. None has a verified eco-certification. OSM rarely records it, "
                "so I show observable indicators instead (e.g. distance to rail or tram). "
                "Prices and footprints are estimates by accommodation type.")

        dispatcher.utter_message(json_message={
            "type": "hotel_carousel",
            "destination": destination,
            "data_source": cards[0]["data_source"],
            "note": note,
            "hotels": cards,
        })

        lines = [f"Top places to stay in {destination}, ranked for your preferences:"]
        for c in cards:
            price = _fmt_money(c["price_per_night"], c["currency"])
            est = "about " if c["price_is_estimate"] else ""
            budget_flag = "" if c["within_budget"] else " (above your budget)"
            lines.append(f"- {c['name']}: {est}{price}/night, about {c['kg_co2e_per_night']:.0f} kg CO2e/night{budget_flag}")
        lines.append(note)
        dispatcher.utter_message(text="\n".join(lines))

        last = dict(tracker.get_slot("last_results") or {})
        last["hotel"] = cards[0]
        return [SlotSet("last_results", last)]



def _trip_distance(tracker: Tracker) -> Dict[str, Any]:
    """Distances for origin -> destination, or a clearly-labelled example.

    `km` is the surface distance (road/rail detour); `flight_km` is the
    great-circle distance, because DESNZ flight factors already include the
    routing uplift. A distance the user typed is used for every mode.
    """
    explicit = _entity(tracker, "distance_km")
    if explicit:
        try:
            km = float(str(explicit).replace(",", ""))
            return {"km": km, "flight_km": km, "basis": "you gave the distance"}
        except ValueError:
            pass
    origin = _origin_place(tracker)
    dest_name = tracker.get_slot("destination")
    dest = geo.geocode(dest_name) if dest_name else None
    if origin and dest and origin["name"].lower() != dest["name"].lower():
        return {"km": geo.travel_distance_km(origin, dest, "surface"),
                "flight_km": geo.travel_distance_km(origin, dest, "flight"),
                "basis": f"{origin['name']} to {dest['name']}",
                "origin": origin["name"], "destination": dest["name"]}
    return {"km": 500.0, "flight_km": 500.0, "basis": "an example 500 km trip", "example": True}


class ActionCalculateCarbonFootprint(Action):
    """Compares travel modes for the user's journey (Climatiq per mode, in
    parallel, with the DESNZ table as fallback) and sends the colour-coded
    carbon card. A red alert is attached when the user's chosen mode is
    high-emission and a lower-carbon alternative exists."""

    def name(self) -> Text:
        return "action_calculate_carbon_footprint"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        requested = _entity(tracker, "travel_mode")
        if not requested:
            # A short follow-up such as "what if I fly?" is reliably
            # classified as a carbon question but can miss entity extraction.
            # Recover only explicit mode words; never guess a mode otherwise.
            words = _message_text(tracker).lower()
            for pattern, mode in ((r"\b(?:fly|flying|plane|flight)\b", "flight"),
                                  (r"\b(?:train|rail)\b", "train"),
                                  (r"\b(?:bus|coach)\b", "bus"),
                                  (r"\b(?:drive|driving|car)\b", "car"),
                                  (r"\b(?:bike|cycle|cycling)\b", "bike"),
                                  (r"\b(?:ferry|boat)\b", "ferry")):
                if re.search(pattern, words):
                    requested = mode
                    break
        dist = _trip_distance(tracker)
        km, flight_km = dist["km"], dist["flight_km"]

        def route_km(mode: Text) -> float:
            return flight_km if mode == "flight" or mode.startswith("flight") else km

        try:
            options = carbon.compare_routes([(m, route_km(m)) for m in carbon.COMPARISON_MODES])
        except Exception as exc:  # defensive: carbon must never crash the turn
            logger.exception("carbon comparison failed: %s", exc)
            dispatcher.utter_message(text="Sorry, I couldn't calculate emissions just now. Please try again.")
            return []

        # Ferry only when relevant; walking/cycling only for short trips.
        if km <= 30:
            options = carbon.compare(["bike"], km) + options

        if requested:
            req_key = carbon.normalise_mode(requested, flight_km)
            req_km = route_km(req_key)
            headline = next((o for o in options if o["mode"] == req_key), None) or carbon.estimate(requested, req_km)
        else:
            headline = options[0]

        best = options[0]
        any_live = any(o["source"] == "climatiq_api" for o in options)
        source_label = "Climatiq API (DESNZ 2026 factors)" if any_live else "DESNZ 2026 factors (local table)"
        saving = None
        if headline["mode"] != best["mode"] and headline["kg_co2e"] > 0:
            saving = round(100 * (1 - best["kg_co2e"] / headline["kg_co2e"]))

        summary = (f"{headline['label']} for {dist['basis']} ({headline['distance_km']:,} km): "
                   f"about {headline['kg_display']:g} kg CO2e per person.")
        if saving:
            summary += f" {best['label']} would cut that by about {saving}%."

        alert = None
        if headline["band"] == "red":
            times = headline.get("ratio_to_best")
            why = (f"about {times:g} times the lowest-carbon option" if times and times > 1
                   else f"about {headline['intensity_g_per_pkm']} g CO2e per km")
            alert = (f"High-emission option. {headline['label']} emits {why}. "
                     f"{best['label']} is about {best['kg_display']:g} kg for the same trip.")

        dispatcher.utter_message(json_message={
            "type": "carbon_card",
            "mode": headline["label"],
            "kg_co2e": headline["kg_display"],
            "band": headline["band"],
            "distance_km": headline["distance_km"],
            "route": dist["basis"],
            "is_example": bool(dist.get("example")),
            "source": source_label,
            "summary": summary,
            "alert": alert,
            "tooltip": CARBON_TOOLTIP,
            "options": [
                {"mode": o["label"], "kg_co2e": o["kg_display"], "band": o["band"],
                 "intensity_g_per_pkm": o["intensity_g_per_pkm"]}
                for o in options
            ],
        })
        dispatcher.utter_message(text=summary + f" (Source: {source_label}; rounded averages.)")

        if dist.get("example"):
            dispatcher.utter_message(
                text="That was an example distance. Tell me where you're travelling from for your real numbers.",
                buttons=[{"title": "Use my location", "payload": "/share_location"}],
            )

        last = dict(tracker.get_slot("last_results") or {})
        last["transport"] = {"best": best["label"], "best_kg": best["kg_display"],
                             "headline": headline["label"], "headline_kg": headline["kg_display"],
                             "route": dist["basis"], "is_example": bool(dist.get("example"))}
        return [SlotSet("carbon_score", float(headline["kg_co2e"])), SlotSet("last_results", last)]



class ActionSearchTransport(Action):
    """Public transport at the destination from live OpenStreetMap data."""

    def name(self) -> Text:
        return "action_search_transport"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        destination = tracker.get_slot("destination")
        level = tracker.get_slot("sustainability_level")
        if not destination:
            dispatcher.utter_message(text="Which destination should I check public transport for?")
            return []

        payload: Dict[str, Any] = {"type": "transport_options", "destination": destination}
        lines: List[Text] = []

        place = geo.geocode(destination)
        stops = osm.transport(place["lat"], place["lon"]) if place else None
        if stops:
            ts = accommodation.transit_summary(stops)
            parts = [f"{n} {k.replace('_', ' ')} {'points' if k == 'bike_share' else 'stops'}"
                     for k, n in sorted(ts.items(), key=lambda kv: -kv[1])]
            payload["local_transit"] = {"counts": ts, "radius_km": 1.5, "source": "OpenStreetMap"}
            lines.append(f"Getting around {destination}: within 1.5 km of the centre there are " + ", ".join(parts) + ".")
            lines.append("These are stop locations from OpenStreetMap. I don't have live timetables, so check the local operator.")
        else:
            payload["unavailable"] = stops is None
            lines.append(f"I couldn't get live local transit data for {destination} right now.")

        routes: List[Dict[str, Any]] = []
        if routes:
            enriched = []
            for r in routes:
                est = carbon.estimate(r.get("mode", "car"), float(r.get("distance_km", 0)))
                enriched.append(dict(r, kg=est["kg_display"], band=est["band"], label=est["label"],
                                     intensity=est["intensity_g_per_pkm"]))
            # Bands relative to the other ways of making the same day trip.
            by_trip: Dict[Text, List[Dict[str, Any]]] = {}
            for r in enriched:
                by_trip.setdefault(r.get("destination", ""), []).append(r)
            for group in by_trip.values():
                rows = [{"mode": r["mode"], "kg_co2e": r["kg"], "band": r["band"]} for r in group]
                for r, row in zip(group, carbon.relative_bands(rows)):
                    r["band"] = row["band"]
            ranked = _rank_candidates(enriched, "kg", "base_price_usd", level)
            payload["routes"] = [
                {"mode": r["label"], "route": f"{r['origin']} → {r['destination']}", "kg_co2e": r["kg"],
                 "band": r["band"], "price": r.get("base_price_usd"), "currency": "USD",
                 "duration_hours": r.get("duration_hours"), "score": r["score"]}
                for r in ranked[:5]
            ]
            payload["routes_note"] = "Day-trip prices and durations are illustrative sample data; emissions are calculated."
            lines.append("Day trips, ranked for your preferences:")
            for r in payload["routes"]:
                lines.append(f"- {r['mode']} {r['route']}: about {r['kg_co2e']:g} kg CO2e ({r['band']})")

        dispatcher.utter_message(json_message=payload)
        dispatcher.utter_message(text="\n".join(lines))
        return []



class ActionSearchCulturalExperiences(Action):
    def name(self) -> Text:
        return "action_search_cultural_experiences"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        destination = tracker.get_slot("destination")
        items: List[Dict[str, Any]] = []

        # 1) Community-run experiences from the curated sample (OSM can't tell
        #    us who runs or benefits from an activity).
        curated: List[Dict[str, Any]] = []
        for e in curated[:3]:
            items.append({"name": e.get("name"), "kind": e.get("type"), "description": e.get("description"),
                          "supports_local_community": e.get("supports_local_community"),
                          "price": e.get("price_usd"), "currency": "USD", "data_source": "Illustrative sample data"})

        # 2) Real landmarks/museums from OpenStreetMap + Wikipedia descriptions.
        place = geo.geocode(destination) if destination else None
        attractions = osm.attractions(place["lat"], place["lon"]) if place else None
        if attractions:
            for a in attractions[:4]:
                description = wiki.summary(a["wikipedia"]) if a.get("wikipedia") else None
                items.append({"name": a["name"], "kind": (a.get("kind") or "").replace("_", " "),
                              "description": description, "wheelchair": a.get("wheelchair"),
                              "data_source": "OpenStreetMap + Wikipedia"})

        if not items:
            if not destination:
                dispatcher.utter_message(text="Which city are you interested in?")
            else:
                dispatcher.utter_message(
                    text=f"I don't have cultural data for {destination} yet. A human advisor can suggest local, community-run options.",
                    buttons=[{"title": "Talk to a human advisor", "payload": "/request_human_advisor"}],
                )
            return []

        dispatcher.utter_message(json_message={"type": "experience_list", "destination": destination, "items": items})
        lines = [f"Things to do in {destination}:"]
        for i in items:
            tag = " (community-run)" if i.get("supports_local_community") else ""
            lines.append(f"- {i['name']}{tag}: {i.get('description') or i.get('kind')}")
        if curated:
            lines.append("Community-run options are from my sample set, so check that they're current before booking.")
        dispatcher.utter_message(text="\n".join(lines))
        return []



class ActionGetWeather(Action):
    def name(self) -> Text:
        return "action_get_weather"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        destination = _entity(tracker, "destination") or tracker.get_slot("destination")
        if not destination:
            dispatcher.utter_message(text="Which destination should I check the weather for?")
            return []
        place = geo.geocode(destination)
        fc = weather.forecast(place["lat"], place["lon"]) if place else None
        if not fc:
            dispatcher.utter_message(text=f"I couldn't get a forecast for {destination} right now. Please try again shortly.")
            return []
        tip = weather.active_travel_advice(fc)
        dispatcher.utter_message(json_message={"type": "weather_card", "destination": place["name"],
                                               "current": fc["current"], "days": fc["days"], "tip": tip,
                                               "source": "Open-Meteo"})
        d0 = fc["days"][0] if fc["days"] else {}
        dispatcher.utter_message(
            text=f"{place['name']} now: {fc['current']['temp']}°C, {fc['current']['summary']}. "
                 f"Today: {d0.get('t_min')} to {d0.get('t_max')}°C. {tip} Note this is the next 3 days, not your travel dates."
        )
        return []



class ActionCarbonOffsetInfo(Action):
    """Explains offsetting for the user's estimated footprint without
    overclaiming: reduce first, then use verified standards and public registries."""

    def name(self) -> Text:
        return "action_carbon_offset_info"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        info = _safe_load_json(OFFSET_PROGRAMS_PATH, {})
        kg = tracker.get_slot("carbon_score")
        last = tracker.get_slot("last_results") or {}
        lines = []
        payload: Dict[str, Any] = {"type": "offset_info", "standards": info.get("standards", []),
                                   "principles": info.get("principles", [])}
        if kg:
            tonnes = carbon.offset_needed_tonnes(float(kg) * 2)  # return trip
            price = info.get("indicative_price_per_tonne_eur", {})
            lo, hi = price.get("low"), price.get("high")
            payload["return_trip_tonnes"] = tonnes
            # One rounding for both units, so the text never says "1200 kg (1.25 t)".
            kg_shown = carbon.round_sig(tonnes * 1000, 2)
            lines.append(f"A return trip at your last estimate is about {kg_shown:,.0f} kg CO2e "
                         f"({kg_shown / 1000:g} t).")
            if lo and hi:
                cost = {"low": max(1, round(tonnes * lo)), "high": max(1, round(tonnes * hi)),
                        "per_tonne_low": lo, "per_tonne_high": hi}
                payload["indicative_cost_eur"] = cost
                lines.append(f"Verified credits commonly cost roughly €{lo} to €{hi} per tonne, so about "
                             f"€{cost['low']} to €{cost['high']}. That's indicative only.")
            t = last.get("transport") or {}
            if t.get("best") and t.get("headline") and t["best"] != t["headline"]:
                payload["lower_carbon_alternative"] = t["best"]
                lines.append(f"Switching to {t['best']} would avoid most of this in the first place.")
        else:
            lines.append("I don't have a footprint for your trip yet. Ask me to compare routes first and I'll size the offset.")
        lines += info.get("principles", [])[:2]
        lines.append("If you offset, use a credit certified by one of these and retired in a public registry: "
                     + ", ".join(s["name"] for s in info.get("standards", [])) + ".")
        dispatcher.utter_message(json_message=payload)
        dispatcher.utter_message(text="\n".join(lines))
        return []



class ActionRankRecommendations(Action):
    """Pulls the hotel and transport results of this turn together into one
    recommendation that explains the weighting, then offers next steps as
    dynamically generated quick replies."""

    def name(self) -> Text:
        return "action_rank_recommendations"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        destination = tracker.get_slot("destination")
        level = tracker.get_slot("sustainability_level") or "medium"
        last = tracker.get_slot("last_results") or {}
        w = _sustainability_to_pref_weight(level)

        parts = []
        if (t := last.get("transport")) and not t.get("is_example"):
            parts.append(f"travel by {t['best'].lower()} (about {t['best_kg']:g} kg CO2e one way)")
        if h := last.get("hotel"):
            parts.append(f"stay at {h['name']}")

        if parts:
            text = f"My recommendation for {destination}: " + " and ".join(parts) + ". "
        else:
            text = f"Here's what I can help with next for {destination or 'your trip'}. "
        text += (f"I weighted carbon at {round(w * 100)}% and price at {round((1 - w) * 100)}% "
                 f"because you chose '{level}' sustainability. You can change this at any time.")

        extra = []
        if level != "high":
            extra.append({"title": "Prioritise lowest carbon", "payload": '/inform_sustainability_preference{"sustainability_level": "high"}'})
        if not tracker.get_slot("origin"):
            extra.append({"title": "Use my location", "payload": "/share_location"})
        dispatcher.utter_message(text=text, buttons=_follow_up_buttons(destination, extra))
        dispatcher.utter_message(json_message={"type": "recommendation_summary", "weights": {"carbon": w, "price": round(1 - w, 2)},
                                               "sustainability_level": level, "items": last})
        return []
