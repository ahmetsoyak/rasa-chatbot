import sys
from playwright.sync_api import sync_playwright
exec(open(f"{sys.argv[1]}/ui_test.py").read().split("with sync_playwright")[0])
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    page = b.new_context(viewport={"width": 900, "height": 900}, device_scale_factor=2).new_page()
    page.goto("http://localhost:5173"); page.wait_for_timeout(800)
    say(page, "plan a trip to Lisbon"); say(page, "next week"); say(page, "cheap"); say(page, "balanced")
    page.locator("[aria-label^='Advisor: places to stay']").last.screenshot(path=f"{SP}/shots/7_hotels.png")
    say(page, "things to do in Lisbon")
    page.locator("text=Things to do in Lisbon").last.locator("xpath=ancestor::div[@data-slot='card']").screenshot(path=f"{SP}/shots/8_experiences.png")
    b.close()
