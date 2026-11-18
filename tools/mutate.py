#!/usr/bin/env python3
"""Mutation check: break the contract on purpose, one change at a time, and
confirm that the direct-mode tests catch every break.

    PYTHONPATH=. venv/bin/python tools/mutate.py

Each mutant is written to a temporary file and the tests are pointed at it
with CE_CONTRACT; contracts/claim_escrow.py itself is never modified.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "contracts" / "claim_escrow.py").read_text()

MUTANTS = [
    # terms
    ("names may contain each other", "if b == s or _contains_words(b, s) or _contains_words(s, b):", "if b == s:"),
    ("any host accepted", "if _host_of(url) not in hosts:", "if False:"),
    ("http accepted", 'if not url.startswith("https://"):', 'if not url.startswith("http"):'),
    ("port accepted", 'if "@" in authority or ":" in authority:', 'if "@" in authority:'),
    ("claim number without digit", " or not any(c in DIGITS for c in cn)", ""),
    ("confirm below the deployment minimum", '_int_in(t["confirm_seconds"], min_confirm, MAX_CONFIRM_SECONDS)', '_int_in(t["confirm_seconds"], 1, MAX_CONFIRM_SECONDS)'),
    ("transfer_by too early", 'if t["transfer_by"] < t["accept_by"] + 2 * c:', 'if t["transfer_by"] < t["accept_by"]:'),
    ("allowance_by too early", 'if t["allowance_by"] < t["transfer_by"] + 2 * c:', 'if t["allowance_by"] < t["transfer_by"]:'),
    ("rate above 100%", '_int_in(t["rate_bp"], 1, BP)', '_int_in(t["rate_bp"], 1, 2 * BP)'),
    ("price rounded up", "return a * t[\"rate_bp\"] * WEI // (BP * t[\"units_per_gen\"])", "return _ceil_div(a * t[\"rate_bp\"] * WEI, BP * t[\"units_per_gen\"])"),
    ("allowed amount not capped", "a = min(units, t[\"face_amount\"])", "a = units"),
    # constructor
    ("upper-case hosts allowed", "or host != host.lower():", ":"),
    ("internal hosts allowed", "if host.endswith(PRIVATE_SUFFIXES) or all(c in DIGITS for c in labels[-1]):", "if False:"),
    # baseline and accept
    ("any baseline is good", 'good = r["holder"] == "SELLER" and r["status"] in ("PENDING", "ALLOWED")', "good = True"),
    ("withdrawn baseline good", 'r["status"] in ("PENDING", "ALLOWED")', 'r["status"] in ("PENDING", "ALLOWED", "WITHDRAWN")'),
    ("accept without baseline", 'elif s["baseline"] is None:', "elif False:"),
    ("accept without digest", "elif terms_digest != d.digest:", "elif False:"),
    ("accept any value", 'elif value != _price(t):', "elif value < _price(t):"),
    ("anyone accepts", 'if gl.message.sender_address.as_hex.lower() != d.buyer.lower():\n            problem', 'if False:\n            problem'),
    ("refused accept keeps the value", "        self._credit(gl.message.sender_address.as_hex, v)\n        return {\"ok\": False, \"error\": error", "        return {\"ok\": False, \"error\": error"),
    ("offers never expire", 'if s["state"] == "OFFERED" and now >= t["accept_by"]:', "if False:"),
    # transfer
    ("other holder does not restart", 'if r["holder"] != "BUYER":\n            s["transfer_first"] = 0', 'if False:\n            s["transfer_first"] = 0'),
    ("transfer on one look", 'elif now - s["transfer_first"] >= t["confirm_seconds"] and now < t["transfer_by"]:', 'elif now < t["transfer_by"]:'),
    ("transfer after transfer_by", 'elif now - s["transfer_first"] >= t["confirm_seconds"] and now < t["transfer_by"]:', 'elif now - s["transfer_first"] >= t["confirm_seconds"]:'),
    ("upfront on a dead claim", "            else:\n                up = 0", "            else:\n                up = _upfront(t)"),
    ("allowed upfront not capped", 'up = min(_upfront(t), _price_for(t, r["amount"]))', "up = _upfront(t)"),
    # decision
    ("decision before transfer", 'if not s["transfer_at"] or s["state"] != "ACTIVE":\n        return', 'if s["state"] != "ACTIVE":\n        return'),
    ("unclear does not restart", 'if r["status"] not in DECISIONS:\n        s["decision_first"] = None', 'if r["status"] not in DECISIONS:\n        pass'),
    ("amount change does not restart", 'if first is None or first["status"] != key["status"] or first["amount"] != key["amount"]:', 'if first is None or first["status"] != key["status"]:'),
    ("decision on one look", 'if now - first["at"] >= t["confirm_seconds"] and now < t["allowance_by"] and r["holder"] != "SELLER":', 'if now < t["allowance_by"] and r["holder"] != "SELLER":'),
    ("decision after allowance_by", 'if now - first["at"] >= t["confirm_seconds"] and now < t["allowance_by"] and r["holder"] != "SELLER":', 'if now - first["at"] >= t["confirm_seconds"] and r["holder"] != "SELLER":'),
    ("settles while the seller holds it", 'if now - first["at"] >= t["confirm_seconds"] and now < t["allowance_by"] and r["holder"] != "SELLER":', 'if now - first["at"] >= t["confirm_seconds"] and now < t["allowance_by"]:'),
    ("released not deducted", 'due = max(0, _price_for(t, d["amount"]) - s["released"])', 'due = _price_for(t, d["amount"])'),
    ("withdrawn refunds the buyer", '_pay(s, pays, "seller", s["left"], "claim withdrawn', '_pay(s, pays, "buyer", s["left"], "claim withdrawn'),
    ("disallowed pays the seller", '_pay(s, pays, "buyer", s["left"], "claim disallowed', '_pay(s, pays, "seller", s["left"], "claim disallowed'),
    ("no shortfall recorded", 's["shortfall"] = max(0, s["released"] - _price_for(t, d["amount"]))', "pass"),
    # deadlines
    ("no transfer deadline", 'if not s["transfer_at"] and now >= t["transfer_by"] + GRACE_SECONDS:', "if False:"),
    ("transfer deadline without grace", 'if not s["transfer_at"] and now >= t["transfer_by"] + GRACE_SECONDS:', 'if not s["transfer_at"] and now >= t["transfer_by"]:'),
    ("long stop ignores the seller as holder", 'if s["last_holder"] == "SELLER":', "if False:"),
    ("long stop split reversed", 'seller = s["left"] * t["no_decision_seller_bp"] // BP', 'seller = s["left"] * (BP - t["no_decision_seller_bp"]) // BP'),
    ("long stop without grace", 'if s["transfer_at"] and now >= t["allowance_by"] + GRACE_SECONDS:', 'if s["transfer_at"] and now >= t["allowance_by"]:'),
    ("clock runs backwards", 'now = max(self._tx_time(), s["t"])', "now = self._tx_time()"),
    # one-sided money
    ("release above what is left", 'not 0 < amount <= s["left"]:', "not 0 < amount:"),
    ("anyone releases", 'if me != (d.buyer if who == "buyer" else d.seller).lower():', "if False:"),
    ("empty escrow stays open", 'if s["left"] == 0:\n            _close(s, now, "nothing left in escrow")', 'if False:\n            _close(s, now, "nothing left in escrow")'),
    # reading
    ("wrong page kind accepted", 'if str(ans.get("page_kind", "")).strip().lower() != "claim_entry":', "if False:"),
    ("debtor not on the page", "if not _contains_words(_name_words(page), debtor) or ", "if "),
    ("claim number not a whole token", 'after = b >= len(page_n) or not (page_n[b].isalnum() or (page_n[b] == "-" and b + 1 < len(page_n) and page_n[b + 1].isalnum()))', "after = True"),
    ("claim number prefix allowed", 'before = a == 0 or not (page_n[a - 1].isalnum() or page_n[a - 1] == "-")', "before = True"),
    ("other claims ignored", 'if _yes(ans.get("other_claims_shown")) or _yes(ans.get("more_than_one_holder")):', 'if _yes(ans.get("more_than_one_holder")):'),
    ("holder label not checked", 'if _norm_label(h.get("label")) not in HOLDER_LABELS or _norm_label(st.get("label")) not in STATUS_LABELS:', 'if _norm_label(st.get("label")) not in STATUS_LABELS:'),
    ("amount label not checked", 'if _norm_label(am.get("label")) not in AMOUNT_LABELS:', "if False:"),
    ("holder not anchored", 'if not _line_anchored(pl, _norm_label(h.get("label")), _norm(h.get("value"))):', "if False:"),
    ("status not anchored", 'if not _line_anchored(pl, _norm_label(st.get("label")), _norm(st.get("value"))):', "if False:"),
    ("amount not anchored", 'if not _line_anchored(pl, _norm_label(am.get("label")), _norm(am.get("value"))):', "if False:"),
    ("partial value anchored", 'if e == len(pl) or pl[e] == "\\n":', "if True:"),
    ("label anchored inside a word run", "if (a == 0 or not pl[a - 1].isalnum()) and (b == len(pl) or pl[b] in SEPARATORS):", "if True:"),
    ("words between label and value", "while j < len(pl) and j - b <= ANCHOR_CHARS and pl[j] in SEPARATORS:", "while j < len(pl) and j - b <= ANCHOR_CHARS and not pl.startswith(value_n, j):"),
    ("status by word not phrase", 'status = STATUS_TABLE.get(_norm_status(st.get("value")), "UNCLEAR")', 'status = next((v for k, v in STATUS_TABLE.items() if k in _norm_status(st.get("value"))), "UNCLEAR")'),
    ("not allowed counted as allowed", '"allowed": "ALLOWED", "allowed in full"', '"allowed": "ALLOWED", "not allowed": "ALLOWED", "allowed in full"'),
    ("bare expunged disallows", '"expunged and disallowed": "DISALLOWED",', '"expunged and disallowed": "DISALLOWED", "expunged": "DISALLOWED",'),
    ("transferee mark ignored", "        if k >= 0:\n            s = s[:k]", "        if False:\n            s = s[:k]"),
    ("holder by containment", 'if words == _name_words(t["buyer_name"]):', 'if _contains_words(words, _name_words(t["buyer_name"])):'),
    ("scale word accepted", "        if w != currency.lower():\n            return None", "        if w not in (currency.lower(), \"million\", \"k\"):\n            return None"),
    ("other currency symbol accepted", "    if any(sym in s and sym != own_sym for sym in SYMBOLS):\n        return None", "    if False:\n        return None"),
    ("three decimals accepted", "if \".\" in frac or len(frac) not in (1, 2) or not all(c in DIGITS for c in frac):", "if \".\" in frac or not all(c in DIGITS for c in frac):"),
    ("zero amount accepted", "return n if n > 0 else None", "return n"),
    ("currency on page ignored", 'if not _currency_ok(ans.get("currency_on_page"), t["currency"]):', "if False:"),
    ("decimal-comma page accepted", 'if _decimal_comma_page(page):\n        return {"kind": "NO_READING", "reason": "N2_FORMAT"}', 'if False:\n        return {"kind": "NO_READING", "reason": "N2_FORMAT"}'),
    ("page not cut", "return text[:PAGE_CHARS]", "return text"),
    ("markers not removed", 'text = text.replace(PAGE_BEGIN, " ").replace(PAGE_END, " ").replace("=====", " ")', "text = text"),
    # leader result and agreement
    ("amount with a non-allowed status", 'if (st == "ALLOWED") != (am > 0):', "if False:"),
    ("unknown holder accepted", "if h not in HOLDERS or st not in STATUSES", "if st not in STATUSES"),
    ("unknown reason accepted", 'if r.get("reason") not in NO_READING_REASONS:', "if False:"),
    ("leader error accepted", "if not isinstance(leader_result, gl.vm.Return):\n                return False", "if not isinstance(leader_result, gl.vm.Return):\n                return True"),
    ("holder not compared", 'return (a["holder"], a["status"], a["amount"]) == (b["holder"], b["status"], b["amount"])', 'return (a["status"], a["amount"]) == (b["status"], b["amount"])'),
    ("amount not compared", 'return (a["holder"], a["status"], a["amount"]) == (b["holder"], b["status"], b["amount"])', 'return (a["holder"], a["status"]) == (b["holder"], b["status"])'),
    ("reason not compared", 'return a["reason"] == b["reason"]', "return True"),
    # money checks
    ("refused value not credited on refund path", "if any(v < 0 for _w, v, _n in pays) or held_before + value_in != s[\"left\"] + out or s[\"left\"] < 0:", "if False:"),
]


def main() -> int:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    caught = 0
    tmp = Path(tempfile.mkdtemp(prefix="ce-mutants-"))
    for i, (name, old, new) in enumerate(MUTANTS, 1):
        n = SRC.count(old)
        if n != 1:
            print(f"SETUP ERROR  {name}: pattern found {n} times")
            return 2
        path = tmp / f"mutant_{i:02d}.py"
        path.write_text(SRC.replace(old, new))
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/direct", "-q", "-x", "-p", "no:cacheprovider"],
                           cwd=ROOT, env={**env, "CE_CONTRACT": str(path)}, capture_output=True, text=True)
        ok = r.returncode != 0
        caught += ok
        print(f"{'caught ' if ok else 'MISSED '} {i:2d} {name}", flush=True)
    print(f"\n{caught} of {len(MUTANTS)} mutants caught")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
