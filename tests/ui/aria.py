import sys
from playwright.sync_api import sync_playwright
exec(open(f"{sys.argv[1]}/ui_test.py").read().split("with sync_playwright")[0])
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    page = b.new_context(geolocation={"latitude": 52.52, "longitude": 13.405}, permissions=["geolocation"]).new_page()
    page.goto("http://localhost:5173"); page.wait_for_timeout(800)
    click(page, "Use my location")
    say(page, "plan a trip to Lisbon"); say(page, "next week"); say(page, "cheap"); say(page, "balanced")
    say(page, "what if I fly")
    say(page, "how do I offset it")
    snap = page.locator("[role=log]").aria_snapshot()
    i = snap.find("You said: balanced")
    print(snap[i:])
    b.close()
