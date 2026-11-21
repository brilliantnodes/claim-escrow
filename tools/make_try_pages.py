#!/usr/bin/env python3
"""Write the register pages for the site's "Try it yourself" app.

    python tools/make_try_pages.py <out_dir> [--days 14] [--from <unix>]

A visitor runs one fictional claim sale on GenLayer Studio. The offer must be
accepted by a slot D (every 15 minutes, UTC), and the claim's register page
changes on its own clock, the way the live runs' pages do:

  until D + 3     the seller holds the claim, status Pending
  from  D + 3     the buyer is shown as holder ("... as transferee of ...")
  from  D + 12    the court's decision: allowed in full, allowed at 80%, or
                  disallowed (one story each)

Pages go to <out_dir>/register/try/<story>/claim-<claim number, lower case>.html,
one per story and slot, from the next slot for --days days, served from
https://claims.brilliantnodes.com. The visitor contract confirms a state seen
twice at least 120 s apart. Every name, case and figure is fictional.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_register as mr  # noqa: E402

SLOT = 15 * 60
FLIP, DECIDE = 3 * 60, 12 * 60
BUYER = "Harrowfield Credit Partners LP"
FILED = "2026-09-14"
FACE_TEXT = "$1,000,000.00"
STORIES = {
    "full": {"letter": "F", "seller": "Quenby Tool & Die LLC", "decision": {"status": "Allowed", "allowed": "$1,000,000.00"}},
    "partial": {"letter": "P", "seller": "Brasswick Conveyor Parts LLC", "decision": {"status": "Allowed", "allowed": "$800,000.00"}},
    "disallowed": {"letter": "D", "seller": "Tamsford Cold Storage Inc.", "decision": {"status": "Disallowed by court order", "allowed": ""}},
}


def claim_number(story: str, d: int) -> str:
    return f"T{STORIES[story]['letter']}-" + datetime.fromtimestamp(d, timezone.utc).strftime("%y%m%d%H%M")


def schedule(story: str, d: int) -> list:
    s = STORIES[story]
    trans = f"{BUYER} as transferee of {s['seller']}"
    return [{"from": d - 6 * 3600, "holder": s["seller"], "status": "Pending", "allowed": ""},
            {"from": d + FLIP, "holder": trans, "status": "Pending", "allowed": ""},
            {"from": d + DECIDE, "holder": trans, "status": s["decision"]["status"], "allowed": s["decision"]["allowed"]}]


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    out = Path(a[0])
    days = int(a[a.index("--days") + 1]) if "--days" in a else 14
    start = int(a[a.index("--from") + 1]) if "--from" in a else int(datetime.now(timezone.utc).timestamp())
    first = (start // SLOT + 1) * SLOT
    n = 0
    for d in range(first, first + days * 86400, SLOT):
        for story in STORIES:
            num = claim_number(story, d)
            body = mr.page(mr.CASES["debtor_name"], mr.CASES["case_number"], {"number": num}, FILED, FACE_TEXT, schedule(story, d))
            p = out / "register" / "try" / story / f"claim-{num.lower()}.html"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
            n += 1
    print(json.dumps({"pages": n, "first_slot": first, "last_slot": first + days * 86400 - SLOT}))


if __name__ == "__main__":
    main()
