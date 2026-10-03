"""Browser regression checks for the local Eco-Travel Advisor.

Start the Rasa server (:5005), action server (:5055), and Vite (:5173), then:
    .venv-test/bin/python tests/ui/ui_test.py

Against the single-container build (see Dockerfile) or a deployed Space:
    .venv-test/bin/python tests/ui/ui_test.py --url http://127.0.0.1:7860
"""

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


APP_URL = "http://127.0.0.1:5173"


def wait_idle(page: Page) -> None:
    page.wait_for_timeout(150)
    page.wait_for_function(
        """() => ![...document.querySelectorAll('[role=status]')]
        .some((node) => node.textContent?.includes('typing'))""",
        timeout=45_000,
    )
    page.wait_for_timeout(250)


def say(page: Page, text: str) -> None:
    page.get_by_label("Message the Eco-Travel Advisor").fill(text)
    page.keyboard.press("Enter")
    wait_idle(page)


def click(page: Page, name: str) -> None:
    page.get_by_role("button", name=name, exact=True).last.click()
    wait_idle(page)


def run_case(results: list[dict], name: str, check) -> None:
    try:
        check()
        results.append({"case": name, "status": "passed"})
        print(f"PASS  {name}")
    except Exception as exc:
        status = "skipped" if str(exc).startswith("SKIP:") else "failed"
        results.append({"case": name, "status": status, "error": str(exc)})
        print(f"{status.upper():<5} {name}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="results/ui", help="Directory for screenshots and report.json")
    parser.add_argument("--url", default=APP_URL, help="Chat UI to test (default: local Vite dev server)")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 900, "height": 1000},
            geolocation={"latitude": 52.52, "longitude": 13.405},
            permissions=["geolocation"],
            device_scale_factor=1,
        )
        page = context.new_page()
        console_errors: list[str] = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        page.goto(args.url, wait_until="domcontentloaded")

        def origin_and_typo() -> None:
            click(page, "Use my departure location")
            expect(page.get_by_text("Where would you like to go from there?")).to_be_visible()
            say(page, "I would like to go Cophanagen")
            expect(page.get_by_text("I'll use Copenhagen for 'Cophanagen'.")).to_be_visible()
            expect(page.get_by_text("What dates are you planning to travel?")).to_be_visible()

        run_case(results, "GPS is origin and destination typo is corrected", origin_and_typo)

        def date_chips() -> None:
            expect(page.get_by_role("group", name="Suggested dates")).to_be_visible()
            expect(page.get_by_role("button", name="Not sure yet")).to_be_visible()
            click(page, "In X days, for Y nights")
            page.get_by_label("Start in (days from today)").fill("4")
            click(page, "5 nights")
            preview = page.get_by_role("group", name="Choose travel dates").get_by_role("status")
            expect(preview).to_contain_text("· 5 nights")
            summary = preview.inner_text()
            click(page, "Use these dates")
            expect(page.get_by_text(summary).last).to_be_visible()
            expect(page.get_by_role("group", name="Choose travel dates")).to_have_count(0)

        run_case(results, "Date chips turn 'in 4 days for 5 nights' into a date range", date_chips)

        def complete_trip() -> None:
            expect(page.get_by_role("group", name="Budget levels")).to_be_visible()
            page.get_by_label("Currency").select_option("GBP")
            page.get_by_label("Total amount").fill("1200")
            expect(page.get_by_role("group", name="Choose a budget").get_by_role("status")).to_have_text("£1,200 for the whole trip")
            click(page, "Use this budget")
            expect(page.get_by_text("£1,200 in total").last).to_be_visible()
            click(page, "Lowest carbon (80% carbon)")
            expect(page.get_by_role("group", name="Advisor: places to stay in Copenhagen")).to_be_visible(timeout=45_000)
            expect(page.get_by_text("All options, lowest first")).to_be_visible()
            expect(page.get_by_text(re.compile(r"Getting around Copenhagen|couldn't get live local transit data for Copenhagen")).first).to_be_visible()

        run_case(results, "Complete trip returns live recommendation cards", complete_trip)
        page.screenshot(path=str(output / "01_trip-results.png"), full_page=False)

        def flight_alert() -> None:
            say(page, "what if I fly")
            expect(page.get_by_text("High-emission option")).to_be_visible()
            page.get_by_role("button", name="What do these numbers mean?").last.click()
            expect(page.get_by_text("kg CO2e = kilograms of carbon-dioxide equivalent").last).to_be_visible()

        run_case(results, "Flight alert and carbon explanation", flight_alert)

        def handover_card() -> None:
            click(page, "Talk to a human advisor")
            expect(page.get_by_text("Before I share a handover")).to_be_visible()
            click(page, "Yes, share my trip details")
            expect(page.get_by_text("Handover package prepared")).to_be_visible()
            expect(page.get_by_text("Reference:")).to_be_visible()
            page.get_by_text("View advisor handover details").click()
            expect(page.get_by_text("GPS coordinates, email addresses and phone numbers are excluded").last).to_be_visible()
            expect(page.get_by_text("Destination")).to_be_visible()

        run_case(results, "Expandable handover package", handover_card)
        page.screenshot(path=str(output / "02_handover-expanded.png"), full_page=False)

        def composer_scroll_and_keyboard() -> None:
            page.locator("[role=log]").evaluate("node => node.parentElement.scrollTop = node.parentElement.scrollHeight")
            footer_bottom = page.locator("footer").bounding_box()["y"] + page.locator("footer").bounding_box()["height"]
            assert footer_bottom <= page.viewport_size["height"] + 1, f"composer bottom {footer_bottom} is below the viewport"
            sizes = page.evaluate("[document.scrollingElement.scrollHeight, document.scrollingElement.clientHeight]")
            assert sizes[0] == sizes[1], f"page itself scrolls (scrollHeight, clientHeight) = {sizes}"
            page.get_by_label("Message the Eco-Travel Advisor").focus()
            assert page.evaluate("document.activeElement.id"), "message field did not take keyboard focus"

        run_case(results, "Composer stays visible while conversation scrolls", composer_scroll_and_keyboard)

        def listening_waveform() -> None:
            mic = page.get_by_role("button", name="Speak your message")
            if mic.count() == 0:
                raise RuntimeError("SKIP: Web Speech API is unavailable in this test browser")
            mic.click()
            expect(page.get_by_text("Listening…")).to_be_visible()
            page.get_by_role("button", name="Stop voice input").click()

        run_case(results, "Voice listening waveform", listening_waveform)

        def theme_and_mobile() -> None:
            click(page, "Toggle dark mode")
            assert page.evaluate("document.documentElement.classList.contains('dark')")
            page.screenshot(path=str(output / "03_dark.png"), full_page=False)
            page.set_viewport_size({"width": 400, "height": 850})
            page.screenshot(path=str(output / "04_mobile.png"), full_page=False)
            assert page.locator("footer").bounding_box()["x"] >= 0

        run_case(results, "Dark mode and 400px mobile layout", theme_and_mobile)

        def accessible_controls() -> None:
            expect(page.get_by_label("Message the Eco-Travel Advisor")).to_be_visible()
            expect(page.get_by_role("button", name="Share my location to calculate journeys from here")).to_be_visible()
            expect(page.get_by_role("button", name="Send message")).to_be_visible()

        run_case(results, "Named controls remain accessible", accessible_controls)
        results.append({"case": "Console errors", "status": "passed" if not console_errors else "failed", "error": console_errors})
        browser.close()

    (output / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
