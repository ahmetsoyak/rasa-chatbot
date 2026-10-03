# Browser and conversation check scripts

Helper scripts used on 1 Oct 2026 to test the running bot. They need Rasa on :5005
(started with `--cors "*"`), the action server on :5055 and, for the browser
scripts, Vite on :5173 (`cd frontend && npx vite --port 5173`).

Setup (once, from the project root):
```bash
.venv-test/bin/pip install -r server/requirements/dev.txt
.venv-test/bin/playwright install chromium
```

| Script | What it does | Run |
|---|---|---|
| `ui_test.py` | Browser regression suite: origin/GPS, typo correction, live trip cards, handover details, scroll, voice state, dark/mobile, named controls. Saves screenshots and JSON report. | `.venv-test/bin/python tests/ui/ui_test.py` |
| `hotel_shot.py` | Screenshots of the hotel carousel and the things-to-do card | `W/pw/bin/python tests/ui/hotel_shot.py W` (imports helpers from `W/ui_test.py`: copy it there first) |
| `aria.py` | Dumps the Chrome accessibility tree of card replies (what a screen reader gets) | same as above |
| `smoke.py` | REST conversations; prints replies, cards, timing, slots. Conversations separated by `\|\|`, turns by `\|` | `python tests/ui/smoke.py "hi\|plan a trip to Lisbon\|\|hmm"` |
| `events.py` | Dumps tracker events (intents, actions, slots) for one conversation | `python tests/ui/events.py "hi\|Lisbon"` |
