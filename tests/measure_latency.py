#!/usr/bin/env python3
"""Measure reply latency through the Rasa REST channel (non-functional
requirement: under 3 s for critical interactions).

Runs N scripted conversations against a running bot (Rasa on :5005, action
server on :5055) and reports median / p95 / max per turn type. The form
submit turn is the heaviest: it runs the accommodation search, the carbon
comparison (live Climatiq calls when CLIMATIQ_API_KEY is set), transport and
ranking in one reply.

Usage:
    python tests/measure_latency.py [--runs 10] [--url http://localhost:5005]
Writes a Markdown table to stdout and results/<label>.json.
"""

import argparse
import json
import os
import statistics
import time
import urllib.request
import uuid

SCRIPT = [
    ("greeting", "hi"),
    ("set origin (geocode)", "I'm travelling from Berlin"),
    ("start form + destination", "plan a trip to Porto"),
    ("form: dates", "10 to 15 May"),
    ("form: budget", "around 1200 euros"),
    ("form submit: hotels + carbon + transport + ranking", "balanced"),
    ("carbon comparison, flight", "what if I fly instead?"),
    ("weather (Open-Meteo, live)", "what's the weather like there"),
    ("things to do", "what is there to do"),
    ("offset guidance", "how do I offset my trip"),
    ("human handover", "I want to talk to a human"),
]


def send(url: str, sender: str, text: str) -> float:
    req = urllib.request.Request(
        f"{url}/webhooks/rest/webhook",
        data=json.dumps({"sender": sender, "message": text}).encode(),
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    return time.perf_counter() - start


def p95(values):
    ordered = sorted(values)
    return ordered[max(0, round(0.95 * len(ordered)) - 1)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--url", default="http://localhost:5005")
    ap.add_argument("--label", default="latency", help="output name: results/<label>.json")
    args = ap.parse_args()

    timings = {label: [] for label, _ in SCRIPT}
    for _ in range(args.runs):
        sender = f"latency-{uuid.uuid4().hex[:8]}"
        for label, text in SCRIPT:
            timings[label].append(send(args.url, sender, text))

    rows = []
    print(f"| Turn ({args.runs} runs) | Median (s) | p95 (s) | Max (s) | < 3 s |")
    print("|---|---|---|---|---|")
    for label, values in timings.items():
        row = {"turn": label, "median": statistics.median(values), "p95": p95(values), "max": max(values)}
        rows.append(row)
        ok = "yes" if row["max"] < 3 else "NO"
        print(f"| {label} | {row['median']:.2f} | {row['p95']:.2f} | {row['max']:.2f} | {ok} |")

    os.makedirs("results", exist_ok=True)
    with open(os.path.join("results", f"{args.label}.json"), "w") as fh:
        json.dump({"runs": args.runs, "measured_at": time.strftime("%Y-%m-%d %H:%M"), "rows": rows}, fh, indent=1)


if __name__ == "__main__":
    main()
