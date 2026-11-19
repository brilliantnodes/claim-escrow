#!/usr/bin/env python3
"""Check a Bradbury live-run record against the chain, after every
transaction has finalized, and write the result next to it as
<record>-check.json. The Studio twin is tools/verify.py.

    BRADBURY_KEY_FILE=/home/claude/keys/bradbury_rr.key \\
        python tools/verify_bradbury.py examples/live-bradbury-b1.json

The key file is only used to open a client for reads (nothing is sent, the key
is never printed). For every recorded transaction it re-reads the transaction
from Bradbury and compares its result and execution with the record, and
requires FINALIZED. Then it reads the contract's views and balance again: the
balance must equal locked + credited.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "tools" / "bradbury"
NOTHING = ("UNDETERMINED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT", "CANCELED")


def node(*a, timeout=300):
    p = subprocess.run(["node", "gl.mjs", *a], cwd=JS, capture_output=True, text=True, timeout=timeout, env=os.environ.copy())
    out = [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]
    if not out or not out[-1].get("ok"):
        raise RuntimeError(f"{a[0]} failed: {out[-1] if out else p.stderr[-300:]}")
    return out[-1]


def main():
    if not os.environ.get("BRADBURY_KEY_FILE"):
        sys.exit("set BRADBURY_KEY_FILE (used for reads only)")
    path = Path(sys.argv[1])
    rec = json.loads(path.read_text())
    rows, ok = [], True
    for s in rec["steps"]:
        if not s.get("tx"):
            continue
        raw = node("tx", s["tx"])["raw"]
        st, res, ex = str(raw.get("statusName")), raw.get("resultName"), raw.get("txExecutionResultName")
        recorded = s.get("status")
        chain_result = st if st in NOTHING else res
        match = st == "FINALIZED" and chain_result == recorded and ex == s.get("execution")
        ok &= match
        rows.append({"case": s["case"], "fn": s["fn"], "tx": s["tx"], "status": st, "result": res, "execution": ex,
                     "recorded_result": recorded, "recorded_execution": s.get("execution"), "match": match})
    addr = rec["contract"]["address"]
    totals = node("read", addr, "totals", "[]")["result"]
    bal = int(node("balance", addr)["result"])
    out = {"record": path.name, "net": "bradbury", "contract": addr, "transactions": len(rows), "all_finalized_and_match": ok,
           "totals": totals, "balance": str(bal), "balance_reconciles": bal == int(totals["locked"]) + int(totals["credited"]),
           "rows": rows}
    check = path.with_name(path.stem + "-check.json")
    check.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1, default=str))
    bad = [r for r in rows if not r["match"]]
    if bad:
        print("MISMATCH:", json.dumps(bad, indent=1)[:2000])


if __name__ == "__main__":
    main()
