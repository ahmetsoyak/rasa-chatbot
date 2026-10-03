"""External data services used by the Eco-Travel Advisor custom actions.

Every module here follows the same contract:

* live calls have short timeouts (the brief caps critical replies at ~3 s);
* every public function returns ``None`` (or a documented fallback) instead of
  raising, so actions can degrade gracefully with an honest message;

Modules
-------
http      shared requests session, User-Agent and timeouts
geo       Nominatim geocoding / reverse geocoding, local gazetteer, haversine
carbon    Climatiq estimates + DESNZ-based local factor table, colour bands
weather   Open-Meteo forecast
currency  Frankfurter (ECB reference rates) conversion
wiki      Wikipedia REST summaries
osm       Overpass queries
accommodation  accommodation estimates and observable sustainability proxies
"""

from dotenv import load_dotenv

# Must run before the submodules are imported: http.py and geo.py read their
# settings at import time.
load_dotenv()
