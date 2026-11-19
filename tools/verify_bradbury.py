#!/usr/bin/env python3
"""Check a Bradbury live-run record against the chain, after every
transaction has finalized, and write the result next to it as
<record>-check.json. The Studio twin is tools/verify.py.

    (cd tools/bradbury && npm install)
    python tools/verify_bradbury.py examples/live-bradbury-b1-merged.json

It only reads. Without BRADBURY_KEY_FILE it makes a throwaway key in a
temporary file just to open the client, sends nothing and deletes the file. For every recorded transaction it re-reads the transaction
from Bradbury and compares its result and execution with the record, and
requires FINALIZED. Then it reads the contract's views and balance again: the
balance must equal locked + credited.
"""
import atexit
import json
import os
import secrets
import subprocess
import sys
import tempfile
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
        fd, tmp = tempfile.mkstemp(suffix=".key")  # mode 0600; read-only use
        os.write(fd, secrets.token_hex(32).encode())
        os.close(fd)
        os.environ["BRADBURY_KEY_FILE"] = tmp
        atexit.register(os.remove, tmp)
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
    if rec["contract"].get("deploy_tx"):
        raw = node("tx", rec["contract"]["deploy_tx"])["raw"]
        dep = {"case": "deploy", "fn": "deploy", "tx": rec["contract"]["deploy_tx"], "status": str(raw.get("statusName")), "result": raw.get("resultName"),
               "execution": raw.get("txExecutionResultName"), "recipient": raw.get("recipient")}
        dep["match"] = dep["status"] == "FINALIZED" and dep["execution"] == "FINISHED_WITH_RETURN" and str(dep["recipient"]).lower() == addr.lower()
        ok &= dep["match"]
        rows.insert(0, dep)
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
