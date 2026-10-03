"""Fallback clarification and human-advisor handover actions."""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Text

import requests
from rasa_sdk import Action, Tracker
from rasa_sdk.events import EventType, SlotSet, UserUtteranceReverted
from rasa_sdk.executor import CollectingDispatcher

from actions.services import http

logger = logging.getLogger(__name__)

_ACTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_ACTIONS_DIR)
_DATA_DIR = os.path.join(_PROJECT_ROOT, "rasa", "data")
HANDOVER_LOG_PATH = http.env("HANDOVER_LOG_PATH", os.path.join(_DATA_DIR, "handover_log.jsonl"))

_INTENT_LABELS = {
    "request_trip_planning": "Plan a trip",
    "ask_carbon_footprint": "Compare travel emissions",
    "ask_accommodation_options": "Find somewhere to stay",
    "ask_transport_options": "Public transport",
    "ask_cultural_experiences": "Things to do",
    "ask_carbon_offset": "Carbon offsets",
    "ask_weather": "Weather",
    "request_human_advisor": "Talk to a human advisor",
    "inform_origin": "Set where I'm travelling from",
}


def _consecutive_fallbacks(tracker: Tracker) -> int:
    """Count consecutive low-confidence user turns, including this turn."""
    count = 0
    for event in reversed(list(tracker.events or [])):
        if event.get("event") != "user":
            continue
        intent = ((event.get("parse_data") or {}).get("intent") or {}).get("name")
        if intent == "nlu_fallback":
            count += 1
        else:
            break
    return max(count, 1)


def build_handover_package(tracker: Tracker, reason: Text) -> Dict[str, Any]:
    """Build the privacy-preserving context package sent to an advisor."""
    slots = dict(tracker.slots or {})
    slots.pop("last_results", None)
    transcript = []
    for event in list(tracker.events or [])[-30:]:
        if event.get("event") in ("user", "bot") and event.get("text"):
            text = event["text"]
            if event["event"] == "user" and text.startswith("/share_location"):
                text = "[shared their location]"
            transcript.append({"from": event["event"], "text": text, "timestamp": event.get("timestamp")})
    last = tracker.get_slot("last_results") or {}
    summary_bits = [f"{key.replace('_', ' ')}: {value}" for key, value in (
        ("destination", slots.get("destination")), ("origin", slots.get("origin")),
        ("dates", slots.get("travel_dates")), ("budget", slots.get("budget")),
        ("sustainability", slots.get("sustainability_level"))) if value]
    return {
        "ticket_id": f"ECO-{uuid.uuid4().hex[:8].upper()}",
        "sender_id": tracker.sender_id,
        "reason": reason,
        "summary": "; ".join(summary_bits) or "No trip details collected yet.",
        "trip": {key: slots.get(key) for key in ("destination", "origin", "travel_dates", "budget",
                                                   "budget_tier", "sustainability_level", "carbon_score")},
        "recommendations_shown": last,
        "transcript": transcript,
        "created_at": time.time(),
        "privacy": "GPS coordinates are excluded; delete after the advisor closes the ticket.",
    }


class ActionHumanHandover(Action):
    """Package full context locally and optionally send it to a webhook."""

    def name(self) -> Text:
        return "action_human_handover"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any],
            reason: Text = "user_requested") -> List[EventType]:
        package = build_handover_package(tracker, reason)
        try:
            os.makedirs(os.path.dirname(HANDOVER_LOG_PATH), exist_ok=True)
            with open(HANDOVER_LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(package) + "\n")
        except OSError as exc:
            logger.warning("Failed to write handover log: %s", type(exc).__name__)

        webhook = http.env("HANDOVER_WEBHOOK_URL")
        if webhook:
            try:
                requests.post(webhook, json=package, timeout=3).raise_for_status()
            except requests.RequestException as exc:
                logger.warning("Handover webhook failed: %s", type(exc).__name__)

        dispatcher.utter_message(
            text=f"I've prepared a handover package for a human travel advisor (reference {package['ticket_id']}). "
                 "It includes your trip details and what I suggested, so you won't need to repeat yourself."
        )
        dispatcher.utter_message(json_message={
            "type": "handover_notice", "reason": reason, "ticket_id": package["ticket_id"],
            "summary": package["summary"],
            "message": "Your trip details are ready for a human travel advisor.",
            "context": {
                "trip": package["trip"], "transcript_turns": len(package["transcript"]),
                "privacy": package["privacy"],
            },
        })
        return [SlotSet("handover_requested", True)]


class ActionDefaultFallback(Action):
    """Offer two clarification stages, then hand the conversation to an advisor."""

    def name(self) -> Text:
        return "action_default_fallback"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[EventType]:
        attempts = _consecutive_fallbacks(tracker)
        if attempts >= 3:
            dispatcher.utter_message(text="I'm still not getting it. Let me bring in a human travel advisor.")
            events = ActionHumanHandover().run(dispatcher, tracker, domain, reason="repeated_misunderstanding")
            return [SlotSet("clarification_attempts", 0)] + events

        if attempts == 1:
            ranking = (tracker.latest_message or {}).get("intent_ranking") or []
            guesses = [item["name"] for item in ranking if item.get("name") in _INTENT_LABELS][:2]
            buttons = [{"title": _INTENT_LABELS[guess], "payload": f"/{guess}"} for guess in guesses]
            buttons.append({"title": "Something else", "payload": "/out_of_scope"})
            dispatcher.utter_message(text="Sorry, I'm not sure what you meant. Did you mean one of these?", buttons=buttons)
        else:
            dispatcher.utter_message(response="utter_ask_rephrase")
        return [SlotSet("clarification_attempts", attempts), UserUtteranceReverted()]
