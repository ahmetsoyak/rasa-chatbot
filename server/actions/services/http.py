"""Shared HTTP helpers.

Nominatim and Overpass are volunteer-run services whose usage policies require
an identifying User-Agent with a contact address. Set ``CONTACT_EMAIL`` in
``.env`` before running anything that calls them.
"""

import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

APP_NAME = "EcoTravelAdvisor-BSBI-Coursework/2.0"

# Live calls made during a conversation turn must stay well under the 3 s
# latency budget. Longer requests are reserved for bounded Overpass queries.
def env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Environment variable, treating an empty or blank value as unset.

    `.env.example` leaves optional keys as `KEY=`, which os.environ.get()
    returns as "" rather than the default.
    """
    value = os.environ.get(name, "").strip()
    return value or default


def _float_env(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        logger.warning("%s is not a number; using %s", name, default)
        return default


LIVE_TIMEOUT = _float_env("LIVE_API_TIMEOUT", 2.5)
LONG_TIMEOUT = 60.0


def user_agent() -> str:
    contact = env("CONTACT_EMAIL", "contact-not-set")
    return f"{APP_NAME} ({contact})"


def headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    h = {"User-Agent": user_agent(), "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


def get_json(url: str, params: Optional[Dict[str, Any]] = None,
             timeout: float = LIVE_TIMEOUT,
             extra_headers: Optional[Dict[str, str]] = None) -> Optional[Any]:
    """GET a JSON resource. Returns None on any network / HTTP / parse error."""
    try:
        resp = requests.get(url, params=params, headers=headers(extra_headers),
                            timeout=timeout)
        if resp.status_code != 200:
            logger.warning("GET %s -> HTTP %s", url, resp.status_code)
            return None
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("GET %s failed: %s", url, type(exc).__name__)
        return None


def post_json(url: str, json_body: Optional[Dict[str, Any]] = None,
              data: Optional[Dict[str, Any]] = None,
              timeout: float = LIVE_TIMEOUT,
              extra_headers: Optional[Dict[str, str]] = None) -> Optional[Any]:
    """POST and parse JSON. Returns None on any error."""
    try:
        resp = requests.post(url, json=json_body, data=data,
                             headers=headers(extra_headers), timeout=timeout)
        if resp.status_code != 200:
            logger.warning("POST %s -> HTTP %s", url, resp.status_code)
            return None
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("POST %s failed: %s", url, type(exc).__name__)
        return None
