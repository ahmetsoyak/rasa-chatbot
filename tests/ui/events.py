import json, sys, uuid, urllib.request
sender = "dbg-" + uuid.uuid4().hex[:6]
for msg in sys.argv[1].split("|"):
    req = urllib.request.Request("http://localhost:5005/webhooks/rest/webhook", data=json.dumps({"sender": sender, "message": msg}).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()
t = json.load(urllib.request.urlopen(f"http://localhost:5005/conversations/{sender}/tracker?include_events=ALL"))
for e in t["events"]:
    ev = e["event"]
    if ev == "user": print(f"USER {e['text']!r} intent={e['parse_data']['intent']['name']} {e['parse_data']['intent'].get('confidence',0):.2f} ents={[(x['entity'],x['value']) for x in e['parse_data']['entities']]}")
    elif ev == "action": print("  action", e["name"], e.get("policy"), round(e.get("confidence") or 0, 2))
    elif ev == "slot": print("    slot", e["name"], "=", repr(e["value"])[:60])
    elif ev in ("active_loop", "rewind", "undo", "action_execution_rejected"): print("   ", ev, e.get("name"))
