import json, sys, time, uuid, urllib.request
def send(sender, text):
    req = urllib.request.Request("http://localhost:5005/webhooks/rest/webhook",
        data=json.dumps({"sender": sender, "message": text}).encode(), headers={"Content-Type": "application/json"})
    t = time.monotonic(); out = json.load(urllib.request.urlopen(req, timeout=30)); dt = time.monotonic() - t
    return out, dt
def show(out):
    for m in out:
        if "text" in m: print("   BOT:", m["text"].replace("\n", " | ")[:260])
        if "buttons" in m: print("   BTN:", [b["title"] for b in m["buttons"]])
        if "custom" in m:
            c = m["custom"]; keys = {k: c[k] for k in ("type","band","mode","kg_co2e","data_source","ticket_id","alert","is_example") if k in c}
            print("   JSON:", keys)
def tracker(sender):
    t = json.load(urllib.request.urlopen(f"http://localhost:5005/conversations/{sender}/tracker?include_events=ALL"))
    user = [e for e in t["events"] if e["event"] == "user"][-1]
    return {k: v for k, v in t["slots"].items() if v not in (None, False, 0, 0.0) and k != "last_results"}, user["parse_data"]["intent"]
for convo in sys.argv[1].split("||"):
    sender = "smoke-" + uuid.uuid4().hex[:6]; print("=" * 70)
    for msg in convo.split("|"):
        out, dt = send(sender, msg); slots, intent = tracker(sender)
        print(f"USER: {msg}   [{dt:.2f}s, intent={intent.get('name')} {intent.get('confidence', 0):.2f}]"); show(out)
    print("   SLOTS:", slots)
