"""Pytest suite for the Eco-Travel Advisor custom actions and services.

No test touches the network: every HTTP helper is patched to fail by default
and individual tests patch in successful responses where needed.

Run in the separate test virtualenv (see tests/README.md):
    pytest tests/test_actions.py -v
"""

import json
import os
import re
import sys
import time

import pytest
from rasa_sdk import Tracker
from rasa_sdk.events import SlotSet, UserUtteranceReverted
from rasa_sdk.executor import CollectingDispatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from actions import actions as A  # noqa: E402
from actions.services import accommodation, carbon, currency, geo, http, osm, wiki  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_tracker(slots=None, latest_message=None, events=None, sender_id="test-user"):
    """Build a minimal rasa_sdk Tracker with every domain slot present."""
    default_slots = {
        "destination": None, "travel_dates": None, "budget": None,
        "sustainability_level": None, "origin": None, "origin_lat": None,
        "origin_lon": None, "budget_tier": None, "user_currency": None,
        "last_results": None, "carbon_score": None, "handover_requested": False,
        "handover_consent": False, "handover_consent_requested": False, "clarification_attempts": 0.0,
    }
    default_slots.update(slots or {})
    return Tracker(
        sender_id=sender_id,
        slots=default_slots,
        latest_message=latest_message or {"text": "", "intent": {}, "entities": []},
        events=events or [],
        paused=False,
        followup_action=None,
        active_loop={},
        latest_action_name=None,
    )


def entities(**kwargs):
    return {"text": "", "intent": {}, "entities": [{"entity": k, "value": v} for k, v in kwargs.items()]}


def json_messages(dispatcher, kind=None):
    out = [m["custom"] for m in dispatcher.messages if m.get("custom")]
    return [m for m in out if kind is None or m.get("type") == kind]


def texts(dispatcher):
    return [m["text"] for m in dispatcher.messages if m.get("text")]


def slot_events(events):
    return {e["name"]: e["value"] for e in events if e.get("event") == "slot"}


@pytest.fixture
def dispatcher():
    return CollectingDispatcher()


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """Isolate every test from the network and real handover logs."""
    monkeypatch.setattr(http, "get_json", lambda *a, **k: None)
    monkeypatch.setattr(http, "post_json", lambda *a, **k: None)
    monkeypatch.setattr(osm, "transport", lambda *a, **k: None)
    monkeypatch.setattr(osm, "hotels", lambda *a, **k: None)
    monkeypatch.setattr(osm, "attractions", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_respect_rate_limit", lambda: None)
    monkeypatch.delenv("CLIMATIQ_API_KEY", raising=False)
    monkeypatch.delenv("HANDOVER_WEBHOOK_URL", raising=False)

    monkeypatch.setattr(A, "HANDOVER_LOG_PATH", str(tmp_path / "handover_log.jsonl"))
    currency._cache.clear()
    osm._cache.clear()
    return tmp_path


@pytest.fixture
def osm_lisbon(monkeypatch):
    """Live OpenStreetMap responses, replaced with deterministic fixtures."""
    stops = [
        {"kind": "tram", "name": "Rossio", "lat": 38.7139, "lon": -9.1394},
        {"kind": "metro", "name": "Baixa-Chiado", "lat": 38.7106, "lon": -9.1420},
        {"kind": "bus", "name": "Praça", "lat": 38.7120, "lon": -9.1400},
    ]
    raw = [
        {"name": "Casa Pequena", "type": "guest_house", "lat": 38.7140, "lon": -9.1396, "rooms": "8"},
        {"name": "Grand Palace Lisboa", "type": "hotel", "stars": "5", "lat": 38.7300, "lon": -9.1600},
        {"name": "Green Tag Hostel", "type": "hostel", "lat": 38.7108, "lon": -9.1421,
         "eco_tag": "Green Key"},
    ]
    monkeypatch.setattr(osm, "transport", lambda *args, **kwargs: stops)
    monkeypatch.setattr(osm, "hotels", lambda *args, **kwargs: raw)
    monkeypatch.setattr(osm, "attractions", lambda *args, **kwargs: [
        {"name": "Belém Tower", "kind": "castle", "wikipedia": "Bel%C3%A9m_Tower"}
    ])
    monkeypatch.setattr(wiki, "summary", lambda *args, **kwargs: "A 16th-century fortification.")
    return {"stops": stops, "hotels": raw}


# ---------------------------------------------------------------------------
# Pure helpers: scoring, parsing, normalisation, bands, rounding
# ---------------------------------------------------------------------------


class TestWeightedScore:
    def test_best_and_worst_case(self):
        assert A.weighted_score(0.0, 0.0, 0.5) == 1.0
        assert A.weighted_score(1.0, 1.0, 0.5) == 0.0

    def test_high_sustainability_prefers_low_carbon(self):
        green_pricey, cheap_dirty = (0.0, 1.0), (1.0, 0.0)
        assert A.weighted_score(*green_pricey, 0.8) > A.weighted_score(*cheap_dirty, 0.8)
        assert A.weighted_score(*green_pricey, 0.25) < A.weighted_score(*cheap_dirty, 0.25)

    def test_inputs_are_clamped(self):
        assert A.weighted_score(-5, 5, 2) == 1.0

    def test_rank_candidates_orders_best_first_and_applies_bonus(self):
        cands = [{"n": "a", "c": 10, "p": 100, "b": 0}, {"n": "b", "c": 10, "p": 100, "b": 1}]
        ranked = A._rank_candidates(cands, "c", "p", "medium", preference_bonus_key="b")
        assert [c["n"] for c in ranked] == ["b", "a"]
        assert ranked[0]["score"] - ranked[1]["score"] == pytest.approx(0.1)


class TestParseBudget:
    @pytest.mark.parametrize("text, amount, cur, tier", [
        ("£1,500", 1500.0, "GBP", "medium"),
        ("2k euros", 2000.0, "EUR", "medium"),
        ("$500", 500.0, "USD", "low"),
        ("5000 dollars", 5000.0, "USD", "high"),
        ("medium budget", None, None, "medium"),
        ("something cheap", None, None, "low"),
        ("luxury", None, None, "high"),
    ])
    def test_parses_amount_currency_and_tier(self, text, amount, cur, tier):
        assert currency.parse_budget(text) == {"amount": amount, "currency": cur, "tier": tier}

    @pytest.mark.parametrize("text", ["", None, "no idea"])
    def test_unparseable_returns_all_none(self, text):
        assert currency.parse_budget(text) == {"amount": None, "currency": None, "tier": None}


class TestMapSustainabilityText:
    @pytest.mark.parametrize("text, level", [
        ("very important to me", "high"),
        ("lowest carbon please", "high"),
        ("low emissions matter most", "high"),
        ("I like slow travel", None),
        ("very low", "low"),
        ("not really important", "low"),
        ("I don't care", "low"),
        ("balanced", "medium"),
        ("balance cost and emissions", "medium"),
        ("I care about both price and planet", "medium"),
        ("I'd rather save money", "low"),
        ("somewhat", "medium"),
        ("banana", None),
        ("", None),
        (None, None),
    ])
    def test_maps_free_text(self, text, level):
        assert A.map_sustainability_text(text) == level


class TestCarbonHelpers:
    @pytest.mark.parametrize("mode, km, key", [
        ("plane", 500, "flight_short"),
        ("flight", 5000, "flight_long"),
        ("EV", 100, "electric_car"),
        ("Coach", 100, "bus"),
        ("rail", 100, "train"),
        ("spaceship", 100, "car"),
        (None, 0, "flight_short"),
    ])
    def test_normalise_mode(self, mode, km, key):
        assert carbon.normalise_mode(mode, km) == key

    @pytest.mark.parametrize("g, band", [(0, "green"), (60, "green"), (61, "amber"),
                                         (149, "amber"), (150, "red"), (250, "red")])
    def test_transport_band_by_intensity(self, g, band):
        assert carbon.transport_band(g) == band

    @pytest.mark.parametrize("kg, band", [(6, "green"), (10, "green"), (16, "amber"), (25, "red")])
    def test_accommodation_band(self, kg, band):
        assert carbon.accommodation_band(kg) == band

    @pytest.mark.parametrize("x, out", [(156.25, 160.0), (1234, 1200.0), (0.03456, 0.035),
                                        (8.0, 8.0), (0, 0.0)])
    def test_round_sig(self, x, out):
        assert carbon.round_sig(x, 2) == out

    def test_factor_table_matches_desnz_2026(self):
        f = carbon.factors()["factors_kg_co2e_per_km"]
        assert f["flight_short"] == 0.12576 and f["flight_long"] == 0.11704
        assert f["train"] == 0.03092 and f["bus"] == 0.03948 and f["car"] == 0.16152
        assert f["electric_car"] == 0.02951 and f["ferry"] == 0.1127
        assert carbon.factors()["short_haul_max_km"] == 3700
        rows = carbon.factors()["_factor_rows"]
        assert "Economy class > With RF" in rows["flight_short"] and "Economy class > With RF" in rows["flight_long"]

    def test_single_mode_uses_absolute_band_only(self):
        assert carbon.estimate("train", 2000)["band"] == "green"
        assert carbon.estimate("flight", 300)["band"] == "amber"  # 126 g/pkm, below the 150 floor
        assert carbon.estimate("car", 300)["band"] == "red"       # 162 g/pkm

    def test_relative_band_makes_flight_red_next_to_rail(self):
        by_mode = {r["mode"]: r for r in carbon.compare_routes([("train", 1200), ("flight", 1000)])}
        assert by_mode["train"]["band"] == "green"
        assert by_mode["flight_short"]["band"] == "red"
        assert by_mode["flight_short"]["ratio_to_best"] > 3

    def test_absolute_floor_is_never_softened(self):
        rows = [{"mode": "car", "kg_co2e": 160.0, "band": "red"}, {"mode": "car2", "kg_co2e": 150.0, "band": "red"}]
        assert [r["band"] for r in carbon.relative_bands(rows)] == ["red", "red"]

    def test_relative_band_thresholds(self):
        rows = [{"mode": m, "kg_co2e": kg, "band": "green"} for m, kg in
                (("a", 10.0), ("b", 15.0), ("c", 30.0), ("d", 31.0), ("bike", 0.0))]
        bands = {r["mode"]: r["band"] for r in carbon.relative_bands(rows)}
        assert bands == {"a": "green", "b": "green", "c": "amber", "d": "red", "bike": "green"}

    def test_flight_distance_has_no_extra_uplift(self):
        berlin, lisbon = geo.geocode("Berlin"), geo.geocode("Lisbon")
        gc = geo.haversine_km(berlin["lat"], berlin["lon"], lisbon["lat"], lisbon["lon"])
        assert abs(geo.travel_distance_km(berlin, lisbon, "flight") - gc) <= 5
        assert geo.travel_distance_km(berlin, lisbon, "surface") > gc * 1.15


# ---------------------------------------------------------------------------
# carbon.compare with Climatiq mocked
# ---------------------------------------------------------------------------


class TestCarbonCompare:
    def test_no_key_uses_local_table_without_calling_api(self, monkeypatch):
        calls = []
        monkeypatch.setattr(http, "post_json", lambda *a, **k: calls.append(1))
        results = carbon.compare(carbon.COMPARISON_MODES, 500)
        assert calls == []
        assert {r["source"] for r in results} == {"local_factor_table"}
        assert [r["kg_co2e"] for r in results] == sorted(r["kg_co2e"] for r in results)

    def test_climatiq_success(self, monkeypatch):
        monkeypatch.setenv("CLIMATIQ_API_KEY", "test-key")
        seen = []

        def fake_post(url, json_body=None, extra_headers=None, **kw):
            seen.append((json_body["emission_factor"]["activity_id"], extra_headers["Authorization"]))
            return {"co2e": 12.3}

        monkeypatch.setattr(http, "post_json", fake_post)
        results = carbon.compare(["train", "flight"], 500)
        assert {r["source"] for r in results} == {"climatiq_api"}
        assert all(r["kg_co2e"] == 12.3 for r in results)
        assert all(auth == "Bearer test-key" for _, auth in seen)
        assert len(seen) == 2

    def test_climatiq_failure_falls_back_per_mode(self, monkeypatch):
        monkeypatch.setenv("CLIMATIQ_API_KEY", "test-key")

        def fake_post(url, json_body=None, **kw):
            # Only train succeeds; flight returns an error (None) or a bad shape.
            return {"co2e": 17.5} if "train" in json_body["emission_factor"]["activity_id"] else {"error": "x"}

        monkeypatch.setattr(http, "post_json", fake_post)
        by_mode = {r["mode"]: r for r in carbon.compare(["train", "flight"], 500)}
        assert by_mode["train"]["source"] == "climatiq_api"
        assert by_mode["flight_short"]["source"] == "local_factor_table"
        assert by_mode["flight_short"]["kg_co2e"] == pytest.approx(carbon.factors()["factors_kg_co2e_per_km"]["flight_short"] * 500, abs=0.01)

    def test_climatiq_request_is_pinned_to_desnz_rows(self):
        req = carbon.climatiq_request("flight_short", 1000)
        ef = req["emission_factor"]
        assert (ef["source"], ef["region"], ef["year"], ef["source_lca_activity"]) == ("BEIS", "GB", 2026, "fuel_combustion")
        assert ef["data_version"] == "^37"
        assert req["parameters"] == {"distance": 1000, "distance_unit": "km", "passengers": 1}

    def test_car_requests_have_no_passengers(self):
        for mode in ("car", "electric_car"):
            assert "passengers" not in carbon.climatiq_request(mode, 100)["parameters"]
        assert carbon.climatiq_request("electric_car", 100)["emission_factor"]["source_lca_activity"].startswith("electricity")

    def test_flight_is_sent_great_circle_distance(self, monkeypatch, dispatcher):
        monkeypatch.setenv("CLIMATIQ_API_KEY", "k")
        sent = {}
        def fake_post(url, json_body=None, **kw):
            sent[json_body["emission_factor"]["activity_id"]] = json_body["parameters"]["distance"]
            return {"co2e": 1.0}
        monkeypatch.setattr(http, "post_json", fake_post)
        tracker = make_tracker(slots={"destination": "Lisbon", "origin": "Berlin"})
        A.ActionCalculateCarbonFootprint().run(dispatcher, tracker, {})
        flight = next(v for k, v in sent.items() if k.startswith("passenger_flight"))
        train = next(v for k, v in sent.items() if k.startswith("passenger_train"))
        assert train == pytest.approx(flight * 1.2, rel=0.02)

    def test_climatiq_timeout_falls_back_within_budget(self, monkeypatch):
        monkeypatch.setenv("CLIMATIQ_API_KEY", "test-key")
        monkeypatch.setattr(http, "LIVE_TIMEOUT", 0.05)

        def slow(*a, **k):
            time.sleep(1.0)
            return 1.0

        monkeypatch.setattr(carbon, "_climatiq_estimate", slow)
        start = time.monotonic()
        results = carbon.compare(["train", "bus"], 300)
        assert time.monotonic() - start < 0.9
        assert {r["source"] for r in results} == {"local_factor_table"}


# ---------------------------------------------------------------------------
# Accommodation: live OSM results; no greenwashing
# ---------------------------------------------------------------------------


class TestActionSearchAccommodations:
    def run(self, dispatcher, **slots):
        tracker = make_tracker(slots=slots)
        return A.ActionSearchAccommodations().run(dispatcher, tracker, {})

    def test_live_osm_is_used_and_never_claims_certification(self, dispatcher, osm_lisbon):
        events = self.run(dispatcher, destination="Lisbon", sustainability_level="high")
        [card] = json_messages(dispatcher, "hotel_carousel")
        assert card["data_source"] == "OpenStreetMap"
        assert len(card["hotels"]) == 3
        for h in card["hotels"]:
            assert h["eco_certification"] is None
            assert h["price_is_estimate"] is True and h["carbon_is_estimate"] is True
            assert h["verification"] in ("none", "unverified_osm_tag")
        tagged = next(h for h in card["hotels"] if h["name"] == "Green Tag Hostel")
        assert tagged["verification"] == "unverified_osm_tag"
        all_text = " ".join(texts(dispatcher)).lower() + card["note"].lower()
        assert "certified" not in all_text
        assert "estimate" in all_text
        assert slot_events(events)["last_results"]["hotel"]["name"] == card["hotels"][0]["name"]

    def test_high_sustainability_ranks_low_footprint_first(self, dispatcher, osm_lisbon):
        self.run(dispatcher, destination="Lisbon", sustainability_level="high")
        [card] = json_messages(dispatcher, "hotel_carousel")
        assert card["hotels"][-1]["name"] == "Grand Palace Lisboa"

    def test_proxies_are_observable_indicators(self, dispatcher, osm_lisbon):
        self.run(dispatcher, destination="Lisbon")
        [card] = json_messages(dispatcher, "hotel_carousel")
        casa = next(h for h in card["hotels"] if h["name"] == "Casa Pequena")
        assert any("from tram" in p for p in casa["proxies"])
        assert any("small scale" in p for p in casa["proxies"])

    def test_budget_tier_flags_expensive_options(self, dispatcher, osm_lisbon):
        self.run(dispatcher, destination="Lisbon", budget_tier="low")
        [card] = json_messages(dispatcher, "hotel_carousel")
        palace = next(h for h in card["hotels"] if h["name"] == "Grand Palace Lisboa")
        assert palace["within_budget"] is False
        assert any("above your budget" in t for t in texts(dispatcher))

    def test_missing_data_does_not_show_sample_hotels(self, dispatcher):
        self.run(dispatcher, destination="Lisbon")
        assert not json_messages(dispatcher, "hotel_carousel")
        assert any("couldn't reach openstreetmap" in t.lower() for t in texts(dispatcher))

    def test_unknown_destination_offers_alternatives(self, dispatcher):
        events = self.run(dispatcher, destination="Atlantis")
        assert events == [SlotSet("destination", None)]
        assert json_messages(dispatcher, "hotel_carousel") == []
        assert "city or destination" in texts(dispatcher)[0]
        payloads = [b["payload"] for m in dispatcher.messages for b in m.get("buttons", [])]
        assert any(payload.startswith("/inform_destination") for payload in payloads)

    def test_mistaken_word_as_destination_is_cleared_not_repeated(self, dispatcher):
        events = self.run(dispatcher, destination="recoomend")
        assert events == [SlotSet("destination", None)]
        reply = texts(dispatcher)[0].lower()
        assert "recoomend" not in reply and "where are you travelling" in reply

    def test_missing_destination_asks_for_it(self, dispatcher):
        assert self.run(dispatcher) == []
        assert "Which city" in texts(dispatcher)[0]


# ---------------------------------------------------------------------------
# Carbon footprint action (colour-coded card)
# ---------------------------------------------------------------------------


class TestOverpassQuery:
    def test_successful_response_is_reused_when_mirrors_later_time_out(self, monkeypatch):
        calls = []

        def post(url, **kwargs):
            calls.append(url)
            return {"elements": [{"id": 1}]} if len(calls) == 1 else None

        monkeypatch.setattr(http, "post_json", post)
        assert osm.run_query("q") == [{"id": 1}]
        assert osm.run_query("q") == [{"id": 1}]
        assert len(calls) == len(osm.OVERPASS_URLS)

    def test_failure_is_not_cached(self):
        assert osm.run_query("q") is None
        assert osm._cache == {}


class TestActionCalculateCarbonFootprint:
    def test_real_route_with_flight_raises_red_alert(self, dispatcher):
        tracker = make_tracker(slots={"destination": "Lisbon", "origin": "Porto"},
                               latest_message=entities(travel_mode="plane"))
        events = A.ActionCalculateCarbonFootprint().run(dispatcher, tracker, {})
        [card] = json_messages(dispatcher, "carbon_card")
        assert card["band"] == "red"
        assert card["alert"] and "High-emission" in card["alert"]
        assert card["is_example"] is False
        assert card["route"] == "Porto to Lisbon"
        assert card["source"].startswith("DESNZ")
        assert card["tooltip"] == A.CARBON_TOOLTIP
        assert {o["band"] for o in card["options"]} >= {"green", "red"}
        assert "would cut that by" in card["summary"]
        assert slot_events(events)["carbon_score"] > 0

    def test_short_flight_follow_up_is_inferred_when_entity_is_missing(self, dispatcher):
        tracker = make_tracker(slots={"destination": "Lisbon", "origin": "Porto"},
                               latest_message={"text": "what if I fly?", "intent": {}, "entities": []})
        A.ActionCalculateCarbonFootprint().run(dispatcher, tracker, {})
        [card] = json_messages(dispatcher, "carbon_card")
        assert card["mode"] == "Short-haul flight" and card["alert"]

    def test_origin_equal_to_destination_is_treated_as_unknown(self, dispatcher):
        tracker = make_tracker(slots={"destination": "Lisbon", "origin": "Lisbon"})
        A.ActionCalculateCarbonFootprint().run(dispatcher, tracker, {})
        [card] = json_messages(dispatcher, "carbon_card")
        assert card["is_example"] is True

    def test_without_origin_uses_labelled_example_and_asks_for_location(self, dispatcher):
        tracker = make_tracker(slots={"destination": "Lisbon"})
        A.ActionCalculateCarbonFootprint().run(dispatcher, tracker, {})
        [card] = json_messages(dispatcher, "carbon_card")
        assert card["is_example"] is True and card["distance_km"] == 500
        assert card["alert"] is None  # best option is the headline when no mode was named
        payloads = [b["payload"] for m in dispatcher.messages for b in m.get("buttons", [])]
        assert "/share_location" in payloads

    def test_short_trip_includes_cycling(self, dispatcher):
        tracker = make_tracker(latest_message=entities(distance_km="12"))
        A.ActionCalculateCarbonFootprint().run(dispatcher, tracker, {})
        [card] = json_messages(dispatcher, "carbon_card")
        assert card["options"][0]["kg_co2e"] == 0.0
        assert card["band"] == "green"


# ---------------------------------------------------------------------------
# Location: GPS and typed input
# ---------------------------------------------------------------------------


class TestActionSetLocation:
    def test_gps_reverse_geocodes_and_sets_slots(self, dispatcher, monkeypatch):
        monkeypatch.setattr(geo, "reverse_geocode", lambda lat, lon: {"name": "Hamburg"})
        tracker = make_tracker(latest_message=entities(latitude=53.55, longitude=9.99))
        events = A.ActionSetLocation().run(dispatcher, tracker, {})
        assert slot_events(events) == {"origin": "Hamburg", "origin_lat": 53.55, "origin_lon": 9.99}
        assert "don't store them" in texts(dispatcher)[0]
        assert texts(dispatcher)[1] == "Where would you like to go from there?"

    def test_gps_without_reverse_geocode_still_works(self, dispatcher):
        # http is offline and 0,0 is far from every gazetteer city.
        tracker = make_tracker(latest_message=entities(latitude="0", longitude="0"))
        events = A.ActionSetLocation().run(dispatcher, tracker, {})
        assert slot_events(events)["origin"] == "your current location"

    def test_gps_falls_back_to_nearest_gazetteer_city(self, dispatcher):
        tracker = make_tracker(latest_message=entities(latitude=52.51, longitude=13.39))
        events = A.ActionSetLocation().run(dispatcher, tracker, {})
        assert slot_events(events)["origin"] == "Berlin"

    def test_invalid_coordinates_ask_for_city(self, dispatcher):
        tracker = make_tracker(latest_message=entities(latitude="abc", longitude="1"))
        assert A.ActionSetLocation().run(dispatcher, tracker, {}) == []
        assert "type the city" in texts(dispatcher)[0]

    def test_typed_city_is_geocoded_offline(self, dispatcher):
        tracker = make_tracker(latest_message=entities(origin="berlin"))
        events = A.ActionSetLocation().run(dispatcher, tracker, {})
        assert slot_events(events) == {"origin": "Berlin", "origin_lat": 52.52, "origin_lon": 13.405}

    def test_unknown_city_clears_slot_and_offers_gps(self, dispatcher):
        tracker = make_tracker(latest_message=entities(origin="Xyzzyville"))
        events = A.ActionSetLocation().run(dispatcher, tracker, {})
        assert slot_events(events) == {"origin": None}
        assert dispatcher.messages[0]["buttons"][0]["payload"] == "/share_location"

    def test_no_input_prompts_for_location(self, dispatcher):
        assert A.ActionSetLocation().run(dispatcher, make_tracker(), {}) == []
        assert dispatcher.messages[0]["buttons"][0]["payload"] == "/share_location"

    def test_offers_route_comparison_when_destination_known(self, dispatcher):
        tracker = make_tracker(slots={"destination": "Lisbon"}, latest_message=entities(origin="Porto"))
        A.ActionSetLocation().run(dispatcher, tracker, {})
        assert dispatcher.messages[-1]["buttons"][0]["payload"] == "/ask_carbon_footprint"


# ---------------------------------------------------------------------------
# Form: dynamic prompts and validation
# ---------------------------------------------------------------------------


class TestTripPlanningForm:
    validator = A.ValidateTripPlanningForm()

    def test_ask_destination_buttons_come_from_available_data(self, dispatcher):
        A.ActionAskDestination().run(dispatcher, make_tracker(), {})
        titles = [b["title"] for b in dispatcher.messages[0]["buttons"]]
        assert len(titles) <= 6

    def test_ask_destination_uses_known_cities(self, dispatcher, osm_lisbon):
        A.ActionAskDestination().run(dispatcher, make_tracker(), {})
        assert all(button["title"] in geo.known_destinations()
                   for button in dispatcher.messages[0]["buttons"])

    def test_set_destination_keeps_entity_value(self, dispatcher):
        tracker = make_tracker(latest_message=entities(destination="Kyoto"))
        assert A.ActionSetDestination().run(dispatcher, tracker, {}) == []

    LONG_ROUTE = ("hi eco-lovely machine :D I want to go Milan from Berlin. Just so you know, I can not "
                  "walk or bike from here to Milan. Please give me your suggestions.")

    @pytest.mark.parametrize("found", [
        [("origin", "Milan"), ("origin", "Berlin")],                       # both tagged as origin
        [("destination", "Berlin"), ("destination", "Milan")],             # both tagged as destination
    ])
    def test_set_destination_uses_from_wording_over_entity_roles(self, dispatcher, found):
        message = {"text": "I want to go Milan from Berlin", "intent": {},
                   "entities": [{"entity": k, "value": v} for k, v in found]}
        events = slot_events(A.ActionSetDestination().run(dispatcher, make_tracker(latest_message=message), {}))
        assert events["destination"] == "Milan" and events["origin"] == "Berlin"
        assert events["origin_lat"] is not None

    def test_form_drops_the_starting_point_and_repeats_from_destinations(self, dispatcher):
        tracker = make_tracker(latest_message={"text": self.LONG_ROUTE, "intent": {}, "entities": []})
        out = self.validator.validate_destination(["Milan", "Berlin", "Milan"], dispatcher, tracker, {})
        assert out["destination"] == "Milan" and out["origin"] == "Berlin"
        assert texts(dispatcher) == []  # no multi-stop warning

    def test_from_here_is_not_a_place(self, dispatcher):
        tracker = make_tracker(latest_message={"text": "I want to go to Milan from here", "intent": {}, "entities": []})
        assert slot_events(A.ActionSetDestination().run(dispatcher, tracker, {})) == {"destination": "Milan"}

    def test_set_destination_geocodes_bare_text(self, dispatcher):
        tracker = make_tracker(slots={"destination": "Hamburg"},
                               latest_message={"text": "porto", "intent": {}, "entities": []})
        assert A.ActionSetDestination().run(dispatcher, tracker, {}) == [SlotSet("destination", "Porto")]

    def test_set_destination_recovers_city_from_natural_sentence_and_corrects_typo(self, dispatcher):
        tracker = make_tracker(latest_message={"text": "I would like to go Cophanagen", "intent": {}, "entities": []})
        assert A.ActionSetDestination().run(dispatcher, tracker, {}) == [SlotSet("destination", "Copenhagen")]
        assert "I'll use Copenhagen for 'Cophanagen'." in texts(dispatcher)

    def test_set_destination_clears_unrecognised_text(self, dispatcher):
        tracker = make_tracker(slots={"destination": "Hamburg"},
                               latest_message={"text": "fnord xyzzy", "intent": {}, "entities": []})
        assert A.ActionSetDestination().run(dispatcher, tracker, {}) == [SlotSet("destination", None)]
        assert "fnord xyzzy" in texts(dispatcher)[0]

    def test_budget_currency_taken_from_message_when_entity_drops_symbol(self, dispatcher):
        tracker = make_tracker(latest_message={"text": "£2000", "intent": {}, "entities": []})
        out = self.validator.validate_budget("2000", dispatcher, tracker, {})
        assert out == {"budget": "2000", "budget_tier": "medium", "user_currency": "GBP"}

    def test_sustainability_uses_whole_message_over_fragment(self, dispatcher):
        tracker = make_tracker(latest_message={"text": "not that important", "intent": {}, "entities": []})
        out = self.validator.validate_sustainability_level("important", dispatcher, tracker, {})
        assert out == {"sustainability_level": "low"}

    @pytest.mark.parametrize("text, ents, level", [
        ("I care more about price now", {}, "low"),
        ("", {"sustainability_level": "High"}, "high"),
        ("eco is not that important", {"sustainability_level": "important"}, "low"),
    ])
    def test_update_sustainability_level(self, dispatcher, text, ents, level):
        msg = {"text": text, "intent": {}, "entities": [{"entity": k, "value": v} for k, v in ents.items()]}
        events = A.ActionUpdateSustainabilityLevel().run(dispatcher, make_tracker(latest_message=msg), {})
        assert events == [SlotSet("sustainability_level", level)]

    def test_update_sustainability_level_unclear_asks_with_buttons(self, dispatcher):
        msg = {"text": "hmm, change it", "intent": {}, "entities": []}
        assert A.ActionUpdateSustainabilityLevel().run(dispatcher, make_tracker(latest_message=msg), {}) == []
        assert len(dispatcher.messages[0]["buttons"]) == 3

    def test_ask_sustainability_offers_three_levels(self, dispatcher):
        A.ActionAskSustainabilityLevel().run(dispatcher, make_tracker(slots={"destination": "Kyoto"}), {})
        msg = dispatcher.messages[0]
        assert msg["text"].startswith("For Kyoto")
        assert [b["payload"].split('"')[-2] for b in msg["buttons"]] == ["low", "medium", "high"]

    def test_destination_known_city(self, dispatcher):
        assert self.validator.validate_destination("lisbon", dispatcher, make_tracker(), {}) == {"destination": "Lisbon"}

    def test_destination_corrects_a_small_typo(self, dispatcher):
        out = self.validator.validate_destination("Cophanagen", dispatcher, make_tracker(), {})
        assert out == {"destination": "Copenhagen"}
        assert texts(dispatcher) == ["I'll use Copenhagen for 'Cophanagen'."]

    def test_destination_correction_is_not_repeated_in_the_same_turn(self, dispatcher):
        # action_set_destination already announced it before the form ran.
        tracker = make_tracker(events=[
            {"event": "user", "text": "I would like to go Cophanagen"},
            {"event": "bot", "text": "I'll use Copenhagen for 'Cophanagen'."},
        ])
        out = self.validator.validate_destination("Cophanagen", dispatcher, tracker, {})
        assert out == {"destination": "Copenhagen"}
        assert texts(dispatcher) == []

    def test_destination_clears_origin_mis_tagged_as_same_city(self, dispatcher):
        tracker = make_tracker(slots={"origin": "Lisbon"})
        out = self.validator.validate_destination("Lisbon", dispatcher, tracker, {})
        assert out == {"destination": "Lisbon", "origin": None, "origin_lat": None, "origin_lon": None}

    def test_destination_keeps_different_origin(self, dispatcher):
        tracker = make_tracker(slots={"origin": "Berlin"})
        assert self.validator.validate_destination("Lisbon", dispatcher, tracker, {}) == {"destination": "Lisbon"}

    def test_split_date_entities_are_joined(self, dispatcher):
        msg = {"text": "10 to 15 May", "intent": {}, "entities": [
            {"entity": "travel_date", "value": "10 to", "start": 0, "end": 5},
            {"entity": "travel_date", "value": "15 May", "start": 6, "end": 12}]}
        out = self.validator.validate_travel_dates("15 May", dispatcher, make_tracker(latest_message=msg), {})
        assert out == {"travel_dates": "10 to 15 May"}

    def test_destination_is_accepted_before_live_search(self, dispatcher):
        assert self.validator.validate_destination("Berlin", dispatcher, make_tracker(), {}) == {"destination": "Berlin"}
        assert texts(dispatcher) == []

    def test_destination_unknown_is_rejected(self, dispatcher):
        assert self.validator.validate_destination("Qwertyland", dispatcher, make_tracker(), {}) == {"destination": None}

    def test_multi_city_suggests_human_advisor(self, dispatcher):
        out = self.validator.validate_destination(["Lisbon", "Porto", "Kyoto"], dispatcher, make_tracker(), {})
        assert out == {"destination": "Lisbon"}
        assert dispatcher.messages[0]["buttons"][0]["payload"] == "/request_human_advisor"

    def test_budget_amount_sets_tier_and_currency(self, dispatcher):
        out = self.validator.validate_budget("£1200", dispatcher, make_tracker(), {})
        assert out == {"budget": "£1200", "budget_tier": "medium", "user_currency": "GBP"}

    def test_budget_unparseable_reprompts_with_buttons(self, dispatcher):
        assert self.validator.validate_budget("whatever", dispatcher, make_tracker(), {}) == {"budget": None}
        assert len(dispatcher.messages[0]["buttons"]) == 3

    @pytest.mark.parametrize("value", ["x", "cheap", "fnord xyzzy"])
    def test_dates_without_anything_date_like_are_rejected(self, dispatcher, value):
        assert self.validator.validate_travel_dates(value, dispatcher, make_tracker(), {}) == {"travel_dates": None}

    @pytest.mark.parametrize("value", [" mid May ", "tomorrow", "2026-11-12 to 2026-11-20",
                                       "next weekend", "around Christmas", "I'm flexible"])
    def test_date_like_answers_are_accepted(self, dispatcher, value):
        out = self.validator.validate_travel_dates(value, dispatcher, make_tracker(), {})
        assert out == {"travel_dates": value.strip()}

    @pytest.mark.parametrize("value, level", [("high", "high"), ("Medium", "medium"),
                                              ("really important", "high"), ("important", "high"), ("not important", "low")])
    def test_sustainability_free_text_is_mapped(self, dispatcher, value, level):
        out = self.validator.validate_sustainability_level(value, dispatcher, make_tracker(), {})
        assert out == {"sustainability_level": level}

    def test_sustainability_unknown_rejected(self, dispatcher):
        out = self.validator.validate_sustainability_level("purple", dispatcher, make_tracker(), {})
        assert out == {"sustainability_level": None}


# ---------------------------------------------------------------------------
# Transport, culture, weather, offsets, ranking
# ---------------------------------------------------------------------------


class TestInformationActions:
    def test_transport_uses_osm_counts_without_sample_routes(self, dispatcher, osm_lisbon):
        A.ActionSearchTransport().run(dispatcher, make_tracker(slots={"destination": "Lisbon",
                                                                      "sustainability_level": "high"}), {})
        [payload] = json_messages(dispatcher, "transport_options")
        assert payload["local_transit"]["counts"] == {"tram": 1, "metro": 1, "bus": 1}
        assert "routes" not in payload
        assert any("live timetables" in t for t in texts(dispatcher))

    def test_transport_marks_unreachable_map_service(self, dispatcher):
        A.ActionSearchTransport().run(dispatcher, make_tracker(slots={"destination": "Lisbon"}), {})
        [payload] = json_messages(dispatcher, "transport_options")
        assert payload["unavailable"] is True

    def test_cultural_uses_osm_data_only(self, dispatcher, osm_lisbon):
        A.ActionSearchCulturalExperiences().run(dispatcher, make_tracker(slots={"destination": "Lisbon"}), {})
        [payload] = json_messages(dispatcher, "experience_list")
        sources = {i["data_source"] for i in payload["items"]}
        assert sources == {"OpenStreetMap + Wikipedia"}

    def test_weather_card(self, dispatcher, monkeypatch):
        from actions.services import weather
        fc = {"current": {"temp": 21, "summary": "clear sky", "wind_kmh": 5},
              "days": [{"date": "2026-10-02", "summary": "clear sky", "t_max": 24, "t_min": 15, "rain_chance": 0}]}
        monkeypatch.setattr(weather, "forecast", lambda lat, lon: fc)
        A.ActionGetWeather().run(dispatcher, make_tracker(slots={"destination": "Lisbon"}), {})
        [card] = json_messages(dispatcher, "weather_card")
        assert card["destination"] == "Lisbon" and card["source"] == "Open-Meteo"
        assert "not your travel dates" in texts(dispatcher)[0]

    def test_weather_failure_is_reported(self, dispatcher):
        A.ActionGetWeather().run(dispatcher, make_tracker(slots={"destination": "Lisbon"}), {})
        assert json_messages(dispatcher) == []
        assert "couldn't get a forecast" in texts(dispatcher)[0]

    def test_offset_sizes_return_trip(self, dispatcher):
        A.ActionCarbonOffsetInfo().run(dispatcher, make_tracker(slots={"carbon_score": 50.0}), {})
        [payload] = json_messages(dispatcher, "offset_info")
        assert payload["return_trip_tonnes"] == 0.1
        assert payload["standards"]
        assert payload["indicative_cost_eur"]["low"] >= 1

    def test_offset_text_rounds_kg_and_tonnes_consistently(self, dispatcher):
        last = {"transport": {"best": "Train", "headline": "Short-haul flight"}}
        A.ActionCarbonOffsetInfo().run(dispatcher, make_tracker(slots={"carbon_score": 625.0, "last_results": last}), {})
        assert "about 1,200 kg CO2e (1.2 t)" in texts(dispatcher)[0]
        assert json_messages(dispatcher, "offset_info")[0]["lower_carbon_alternative"] == "Train"

    def test_offset_without_footprint_asks_to_compare_first(self, dispatcher):
        A.ActionCarbonOffsetInfo().run(dispatcher, make_tracker(), {})
        assert "compare routes first" in texts(dispatcher)[0]

    def test_rank_recommendations_explains_weights(self, dispatcher):
        last = {"hotel": {"name": "Casa Pequena"},
                "transport": {"best": "Train", "best_kg": 10, "is_example": False}}
        tracker = make_tracker(slots={"destination": "Lisbon", "sustainability_level": "high",
                                      "last_results": last, "origin": "Porto"})
        A.ActionRankRecommendations().run(dispatcher, tracker, {})
        text = texts(dispatcher)[0]
        assert "travel by train" in text and "Casa Pequena" in text
        assert "carbon at 80% and price at 20%" in text
        payloads = [b["payload"] for b in dispatcher.messages[0]["buttons"]]
        assert "/share_location" not in payloads  # origin already known
        assert json_messages(dispatcher, "recommendation_summary")[0]["weights"]["carbon"] == 0.8


# ---------------------------------------------------------------------------
# Fallback: clarification 1 -> clarification 2 -> handover
# ---------------------------------------------------------------------------


def user_event(intent, text="..."):
    return {"event": "user", "text": text, "parse_data": {"intent": {"name": intent}}}


class TestActionDefaultFallback:
    ranking = {"text": "hmm", "intent": {"name": "nlu_fallback"}, "entities": [],
               "intent_ranking": [{"name": "nlu_fallback"}, {"name": "ask_carbon_footprint"},
                                  {"name": "greet"}, {"name": "ask_weather"}]}

    def run(self, dispatcher, events):
        tracker = make_tracker(latest_message=self.ranking, events=events)
        return A.ActionDefaultFallback().run(dispatcher, tracker, {})

    def test_stage_one_did_you_mean_from_intent_ranking(self, dispatcher):
        events = self.run(dispatcher, [user_event("greet"), user_event("nlu_fallback")])
        titles = [b["title"] for b in dispatcher.messages[0]["buttons"]]
        assert titles == ["Compare travel emissions", "Weather", "Something else"]
        assert SlotSet("clarification_attempts", 1) in events
        assert UserUtteranceReverted() in events

    def test_stage_two_constrained_menu(self, dispatcher):
        events = self.run(dispatcher, [user_event("nlu_fallback"), {"event": "bot", "text": "?"},
                                       user_event("nlu_fallback")])
        assert dispatcher.messages[0]["response"] == "utter_ask_rephrase"
        assert SlotSet("clarification_attempts", 2) in events

    def test_stage_three_hands_over(self, dispatcher):
        events = self.run(dispatcher, [user_event("nlu_fallback")] * 3)
        assert SlotSet("handover_consent_requested", True) in events
        assert SlotSet("clarification_attempts", 0) in events
        assert any("Before I share a handover" in message for message in texts(dispatcher))

    def test_clear_turn_resets_the_count(self, dispatcher):
        events = self.run(dispatcher, [user_event("nlu_fallback"), user_event("greet"),
                                       user_event("nlu_fallback")])
        assert SlotSet("clarification_attempts", 1) in events


# ---------------------------------------------------------------------------
# Human handover package
# ---------------------------------------------------------------------------


class TestHumanHandover:
    slots = {"destination": "Kyoto", "travel_dates": "May", "budget": "£2000",
             "sustainability_level": "high", "origin": "Hamburg",
             "origin_lat": 53.5511, "origin_lon": 9.9937, "carbon_score": 900.0,
             "last_results": {"transport": {"best": "Train"}}, "handover_consent": True}

    def events(self, n=40):
        evs = [{"event": "user", "text": '/share_location{"latitude":53.5511,"longitude":9.9937}'}]
        for i in range(n):
            evs.append({"event": "user" if i % 2 == 0 else "bot", "text": f"msg {i}", "timestamp": i})
        evs.append({"event": "slot", "name": "x", "value": 1})
        return evs

    def test_package_contents(self):
        pkg = A.build_handover_package(make_tracker(slots=self.slots, events=self.events()), "user_requested")
        assert re.fullmatch(r"ECO-[0-9A-F]{8}", pkg["ticket_id"])
        assert "destination: Kyoto" in pkg["summary"] and "sustainability: high" in pkg["summary"]
        assert pkg["trip"]["destination"] == "Kyoto" and pkg["trip"]["carbon_score"] == 900.0
        assert pkg["recommendations_shown"] == {"transport": {"best": "Train"}}
        assert len(pkg["transcript"]) <= 30
        assert pkg["transcript"][-1]["text"] == "msg 39"

    def test_gps_coordinates_never_leave_the_bot(self):
        events = self.events(n=4)
        pkg = A.build_handover_package(make_tracker(slots=self.slots, events=events), "user_requested")
        dumped = json.dumps(pkg)
        assert "53.5511" not in dumped and "9.9937" not in dumped
        assert pkg["transcript"][0]["text"] == "[shared their location]"

    def test_transcript_redacts_direct_identifiers_and_sender_id(self):
        events = [{"event": "user", "text": "Email sam@example.com or call +49 151 23456789"}]
        pkg = A.build_handover_package(make_tracker(slots=self.slots, events=events, sender_id="sam-123"), "user_requested")
        dumped = json.dumps(pkg)
        assert "sam@example.com" not in dumped and "151 23456789" not in dumped and "sam-123" not in dumped
        assert "[email removed]" in dumped and "[phone number removed]" in dumped

    def test_purge_keeps_only_records_within_retention(self, offline, monkeypatch):
        monkeypatch.setenv("HANDOVER_RETENTION_DAYS", "30")
        path = offline / "handover_log.jsonl"
        path.write_text("\n".join([
            json.dumps({"created_at": 100.0, "ticket_id": "old"}),
            json.dumps({"created_at": 1000.0 + 371 * 86400, "ticket_id": "new"}),
        ]) + "\n")
        A.handover_module.purge_expired_handover_records(str(path), now=1000.0 + 400 * 86400)
        assert [json.loads(row)["ticket_id"] for row in path.read_text().splitlines()] == ["new"]

    def test_empty_conversation_summary(self):
        pkg = A.build_handover_package(make_tracker(), "user_requested")
        assert pkg["summary"] == "No trip details collected yet."

    def test_action_writes_log_and_shows_notice(self, dispatcher, offline):
        events = A.ActionHumanHandover().run(dispatcher, make_tracker(slots=self.slots, events=self.events(4)), {})
        assert events == [SlotSet("handover_requested", True)]
        logged = json.loads((offline / "handover_log.jsonl").read_text().splitlines()[0])
        [notice] = json_messages(dispatcher, "handover_notice")
        assert notice["ticket_id"] == logged["ticket_id"]
        assert notice["summary"] == logged["summary"]
        assert notice["context"]["trip"] == logged["trip"]
        assert notice["context"]["transcript_turns"] == len(logged["transcript"])
        assert logged["ticket_id"] in texts(dispatcher)[0]

    def test_webhook_receives_package_and_failure_is_tolerated(self, dispatcher, monkeypatch):
        monkeypatch.setenv("HANDOVER_WEBHOOK_URL", "https://example.invalid/hook")
        sent = []

        class Resp:
            def raise_for_status(self):
                raise A.requests.HTTPError("500")

        def fake_post(url, json=None, timeout=None):
            sent.append((url, json))
            return Resp()

        monkeypatch.setattr(A.requests, "post", fake_post)
        events = A.ActionHumanHandover().run(dispatcher, make_tracker(slots=self.slots), {})
        assert sent and sent[0][1]["trip"]["destination"] == "Kyoto"
        assert events == [SlotSet("handover_requested", True)]


# ---------------------------------------------------------------------------
# Environment variables: an empty "KEY=" line (as in .env.example) means unset
# ---------------------------------------------------------------------------


class TestEnv:
    def test_blank_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CLIMATIQ_DATA_VERSION", "  ")
        assert http.env("CLIMATIQ_DATA_VERSION", "^6") == "^6"
        monkeypatch.setenv("CLIMATIQ_DATA_VERSION", "^21")
        assert http.env("CLIMATIQ_DATA_VERSION", "^6") == "^21"

    def test_bad_timeout_does_not_crash(self, monkeypatch):
        monkeypatch.setenv("LIVE_API_TIMEOUT", "")
        assert http._float_env("LIVE_API_TIMEOUT", 2.5) == 2.5
        monkeypatch.setenv("LIVE_API_TIMEOUT", "fast")
        assert http._float_env("LIVE_API_TIMEOUT", 2.5) == 2.5

    def test_blank_data_version_is_not_sent_to_climatiq(self, monkeypatch):
        monkeypatch.setenv("CLIMATIQ_API_KEY", "k")
        monkeypatch.setenv("CLIMATIQ_DATA_VERSION", "")
        sent = []
        monkeypatch.setattr(http, "post_json", lambda url, json_body=None, **kw: sent.append(json_body) or {"co2e": 1.0})
        carbon.compare(["train"], 100)
        assert sent[0]["emission_factor"]["data_version"] == carbon.factors()["climatiq"]["data_version"]
