"""Browser regression checks for the local Eco-Travel Advisor.

Start the Rasa server (:5005), action server (:5055), and Vite (:5173), then:
    .venv-test/bin/python tests/ui/ui_test.py
"""

import argparse
import json
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
        page.goto(APP_URL, wait_until="domcontentloaded")

        def origin_and_typo() -> None:
            click(page, "Use my departure location")
            expect(page.get_by_text("Where would you like to go from there?")).to_be_visible()
            say(page, "I would like to go Cophanagen")
            expect(page.get_by_text("I'll use Copenhagen for 'Cophanagen'.")).to_be_visible()
            expect(page.get_by_text("What dates are you planning to travel?")).to_be_visible()

        run_case(results, "GPS is origin and destination typo is corrected", origin_and_typo)

        def complete_trip() -> None:
            say(page, "2026-10-10 to 2026-10-14")
            say(page, "£1200")
            click(page, "Lowest carbon (80% carbon)")
            expect(page.get_by_role("group", name="Advisor: places to stay in Copenhagen")).to_be_visible(timeout=45_000)
            expect(page.get_by_text("All options, lowest first")).to_be_visible()
            expect(page.get_by_text("Getting around Copenhagen:")).to_be_visible()

        run_case(results, "Complete trip returns live recommendation cards", complete_trip)
        page.screenshot(path=str(output / "01_trip-results.png"), full_page=False)

        def flight_alert() -> None:
            say(page, "what if I fly")
            expect(page.get_by_text("High-emission option")).to_be_visible()
            page.get_by_role("button", name="What do these numbers mean?").last.click()
            expect(page.get_by_text("kg CO2e = kilograms of carbon-dioxide equivalent")).to_be_visible()

        run_case(results, "Flight alert and carbon explanation", flight_alert)

        def handover_card() -> None:
            click(page, "Talk to a human advisor")
            expect(page.get_by_text("Handover package prepared")).to_be_visible()
            expect(page.get_by_text("Reference:")).to_be_visible()
            page.get_by_text("View advisor handover details").click()
            expect(page.get_by_text("GPS coordinates are excluded")).to_be_visible()
            expect(page.get_by_text("Destination")).to_be_visible()

        run_case(results, "Expandable handover package", handover_card)
        page.screenshot(path=str(output / "02_handover-expanded.png"), full_page=False)

        def composer_scroll_and_keyboard() -> None:
            page.locator("[role=log]").evaluate("node => node.parentElement.scrollTop = node.parentElement.scrollHeight")
            footer_bottom = page.locator("footer").bounding_box()["y"] + page.locator("footer").bounding_box()["height"]
            assert footer_bottom <= page.viewport_size["height"] + 1
            assert page.evaluate("document.scrollingElement.scrollHeight === document.scrollingElement.clientHeight")
            page.get_by_label("Message the Eco-Travel Advisor").focus()
            assert page.evaluate("document.activeElement.id")

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
