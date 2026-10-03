"""Currency conversion via Frankfurter (European Central Bank reference rates).

ECB rates are published once per working day (~16:00 CET). They are
reference rates, not what a card or exchange bureau will charge; the bot says
"about" for converted figures for that reason.
"""

import re
import time
from typing import Dict, Optional, Tuple

from . import http

BASE_URL = "https://api.frankfurter.dev/v1"
_CACHE_TTL = 6 * 3600
_cache: Dict[str, Tuple[float, Dict[str, float]]] = {}

SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₺": "TRY", "chf": "CHF"}
WORDS = {
    "dollar": "USD", "dollars": "USD", "usd": "USD", "bucks": "USD",
    "euro": "EUR", "euros": "EUR", "eur": "EUR",
    "pound": "GBP", "pounds": "GBP", "gbp": "GBP", "quid": "GBP",
    "yen": "JPY", "jpy": "JPY", "lira": "TRY", "try": "TRY",
    "franc": "CHF", "francs": "CHF", "chf": "CHF",
    "krona": "ISK", "kronur": "ISK", "isk": "ISK",
}

# Qualitative budgets map to a nightly accommodation ceiling in EUR.
QUALITATIVE = {
    "low": ("low", None), "cheap": ("low", None), "tight": ("low", None),
    "shoestring": ("low", None), "small": ("low", None), "budget-friendly": ("low", None),
    "medium": ("medium", None), "moderate": ("medium", None), "mid": ("medium", None),
    "mid-range": ("medium", None), "average": ("medium", None),
    "high": ("high", None), "luxury": ("high", None), "generous": ("high", None),
    "big": ("high", None), "unlimited": ("high", None),
}


def parse_budget(text: Optional[str]) -> Dict[str, Optional[object]]:
    """Parse '£1,500', '2000 euros', '2k', 'medium budget' into parts.

    Returns {amount: float|None, currency: str|None, tier: 'low'|'medium'|'high'|None}.
    """
    out: Dict[str, Optional[object]] = {"amount": None, "currency": None, "tier": None}
    if not text:
        return out
    t = text.strip().lower()
    for sym, code in SYMBOLS.items():
        if sym in t:
            out["currency"] = code
    for word, code in WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", t):
            out["currency"] = code
    m = re.search(r"(\d[\d,\.]*)\s*(k|thousand)?", t)
    if m:
        num = m.group(1).replace(",", "")
        try:
            amount = float(num)
            if m.group(2):
                amount *= 1000
            out["amount"] = amount
        except ValueError:
            pass
    for word, (tier, _) in QUALITATIVE.items():
        if re.search(rf"\b{re.escape(word)}\b", t):
            out["tier"] = tier
            break
    if out["tier"] is None and out["amount"] is not None:
        eur = out["amount"]
        out["tier"] = "low" if eur < 800 else "medium" if eur < 2500 else "high"
    return out


def rates(base: str) -> Optional[Dict[str, float]]:
    base = base.upper()
    hit = _cache.get(base)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    body = http.get_json(f"{BASE_URL}/latest", params={"base": base})
    if not body or "rates" not in body:
        return None
    table = {k.upper(): float(v) for k, v in body["rates"].items()}
    table[base] = 1.0
    _cache[base] = (time.time(), table)
    return table


def convert(amount: float, from_cur: str, to_cur: str) -> Optional[float]:
    if from_cur.upper() == to_cur.upper():
        return amount
    table = rates(from_cur)
    if not table or to_cur.upper() not in table:
        return None
    return amount * table[to_cur.upper()]
