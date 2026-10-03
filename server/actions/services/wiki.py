"""Wikipedia REST summaries for cultural recommendations."""

from typing import Optional
from urllib.parse import quote

from . import http

SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"


def summary(title: str, lang: str = "en", timeout: float = http.LONG_TIMEOUT) -> Optional[str]:
    if not title:
        return None
    if ":" in title and len(title.split(":", 1)[0]) <= 3:
        lang, title = title.split(":", 1)  # OSM wikipedia tags look like "pt:Torre de Belém"
    body = http.get_json(SUMMARY_URL.format(lang=lang, title=quote(title.replace(" ", "_"))),
                         timeout=timeout)
    if not body or body.get("type") == "disambiguation":
        return None
    text = (body.get("extract") or "").strip()
    if not text:
        return None
    # Keep it short: first two sentences.
    parts = text.split(". ")
    return ". ".join(parts[:2]).rstrip(".") + "."
