#!/usr/bin/env python3
"""The video's figures, read from a live-run record.

    python3 make_data.py ../../examples/live-studio-s4.json > data.json
"""
import json
import sys

G = 10**18
rec = json.load(open(sys.argv[1]))
fin = rec["final"]["deals"]
cases = []
for key, d in rec["deals"].items():
    m = fin[key]["money"]
    cases.append({"key": key, "title": d["title"], "claim": fin[key]["terms"]["claim_number"], "escrow": int(m["escrow"]) / G,
                  "seller": int(m["released"]) / G, "buyer": int(m["refunded"]) / G, "state": fin[key]["state"], "reason": fin[key]["settled_reason"]})
out = {"source": f"{rec['net']} run {rec['tag']}, contract {rec['contract']['address']}; every name and case is fictional",
       "net": "GenLayer Studio" if rec["net"] == "studio" else "Testnet Bradbury", "contract": rec["contract"]["address"],
       "n_tx": len([s for s in rec["steps"] if s.get("tx")]), "cases": cases, "shot": "shot_site.jpg", "shot_ratio": 1.0}
print(json.dumps(out, indent=1))
