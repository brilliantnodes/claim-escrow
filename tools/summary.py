#!/usr/bin/env python3
"""Print a ClaimEscrow live run as Markdown for the README: one table of the
eight deals' outcomes and one of every transaction.

    python tools/summary.py examples/live-studio-s2.json
"""
import json
import sys

EXPL = {"studio": "https://explorer-studio.genlayer.com", "bradbury": "https://scan.bradbury.genlayer.com"}
G = 10**18


def gen(w):
    return f"{int(w) / G:g}"


def outcome(s):
    r = s.get("result")
    base = f"{s.get('status')} / {s.get('execution')}"
    if isinstance(r, dict):
        if isinstance(r.get("reading"), dict):
            x = r["reading"]
            return base + (f" · {x['holder']} {x['status']}" + (f" {x['amount']:,}" if x.get("amount") else "") if x["kind"] == "READ" else f" · NO_READING {x['reason']}")
        if r.get("read") is False:
            return base + " · " + r.get("note", "")
        if "error" in r:
            return base + " · refused: " + r["error"] + (f" (refunded {gen(r['refunded'])} GEN)" if r.get("refunded") not in (None, "0") else "")
        if "amount" in r and "left" in r:
            return base + f" · withdrew {gen(r['amount'])} GEN"
        if r.get("state"):
            return base + f" · {r['state']}" + (f": {r['settled_reason']}" if r.get("settled_reason") else "")
        if isinstance(r.get("deal"), dict):
            return base + f" · {r['deal']['state']}"
    elif isinstance(r, str) and r:
        return base + " · " + r
    return base


def main():
    rec = json.loads(open(sys.argv[1]).read())
    ex = EXPL[rec["net"]]
    fin = (rec.get("final") or {}).get("deals") or {}
    print("| Case | Claim | Price | Seller got | Buyer got | Shortfall | Ended |")
    print("|---|---|---|---|---|---|---|")
    for key, d in rec["deals"].items():
        f = fin.get(key)
        if not f:
            continue
        m = f["money"]
        print(f"| {d['title']} | {f['terms']['claim_number']} | {gen(d['price'])} | {gen(m['released'])} | {gen(m['refunded'])} | {gen(m['shortfall'])} | {f['settled_reason']} |")
    print()
    print("| # | Case | Call | Outcome | Tx |")
    print("|---|---|---|---|---|")
    for i, s in enumerate(rec["steps"], 1):
        tx = f"[`{s['tx'][:10]}…`]({ex}/tx/{s['tx']})" if s.get("tx") else ""
        print(f"| {i} | {s['case']} | `{s['fn']}` | {outcome(s)} | {tx} |")


if __name__ == "__main__":
    main()
