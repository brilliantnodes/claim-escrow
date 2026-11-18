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
    ("query string accepted", ' or "#" in url or "?" in url:', ' or "#" in url:'),
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
    ("withdrawn baseline good", 'good = r["holder"] == "SELLER" and r["status"] in ("PENDING", "ALLOWED")', 'good = r["holder"] == "SELLER" and r["status"] in ("PENDING", "ALLOWED", "WITHDRAWN")'),
    ("accept without baseline", 'elif s["baseline"] is None:', "elif False:"),
    ("baseline of any age", 'elif now - s["baseline"]["at"] > BASELINE_MAX_PERIODS * t["confirm_seconds"]:', "elif False:"),
    ("buyer indexed at offer", "        self._index(seller, did)  #", "        self._index(buyer_hex, did)\n        self._index(seller, did)  #"),
    ("accept without digest", "elif terms_digest != d.digest:", "elif False:"),
    ("accept any value", 'elif value != _price(t):', "elif value < _price(t):"),
    ("anyone accepts", 'if gl.message.sender_address.as_hex.lower() != d.buyer.lower():\n            problem', 'if False:\n            problem'),
    ("refused accept keeps the value", "        self._credit(gl.message.sender_address.as_hex, v)\n        return {\"ok\": False, \"error\": error", "        return {\"ok\": False, \"error\": error"),
    ("offers never expire", 'if s["state"] == "OFFERED" and now >= t["accept_by"]:', "if False:"),
    # transfer
    ("other holder does not restart", 'if r["holder"] != "BUYER":\n            s["transfer_first"] = 0', 'if False:\n            s["transfer_first"] = 0'),
    ("transfer on one look", 'elif at - s["transfer_first"] >= t["confirm_seconds"] and at < t["transfer_by"]:', 'elif at < t["transfer_by"]:'),
    ("transfer after transfer_by", 'elif at - s["transfer_first"] >= t["confirm_seconds"] and at < t["transfer_by"]:', 'elif at - s["transfer_first"] >= t["confirm_seconds"]:'),
    ("readings counted at the deal clock", "        _apply_reading(t, s, r, stamp, pays)", "        _apply_reading(t, s, r, now, pays)"),
    ("upfront of everything leaves the deal open", '            if s["left"] == 0:\n                _close(s, at, "nothing left in escrow after the upfront")\n                return', "            pass"),
    ("upfront on a dead claim", "            else:\n                up = 0", "            else:\n                up = _upfront(t)"),
    ("allowed upfront not capped", 'up = min(_upfront(t), _price_for(t, r["amount"]))', "up = _upfront(t)"),
    # decision
    ("decision before transfer", 'if not s["transfer_at"] or s["state"] != "ACTIVE":\n        return', 'if s["state"] != "ACTIVE":\n        return'),
    ("unclear does not restart", '    if r["status"] not in DECISIONS or unattributable:  # a withdrawal nobody can attribute decides nothing: the long stop splits\n        s["decision_first"] = None', '    if r["status"] not in DECISIONS or unattributable:  # a withdrawal nobody can attribute decides nothing: the long stop splits\n        return'),
    ("amount change does not restart", 'if first is None or first["status"] != key["status"] or first["amount"] != key["amount"]:', 'if first is None or first["status"] != key["status"]:'),
    ("decision on one look", 'if at - first["at"] >= t["confirm_seconds"] and at < t["allowance_by"] and', 'if at < t["allowance_by"] and'),
    ("decision after allowance_by", 'if at - first["at"] >= t["confirm_seconds"] and at < t["allowance_by"] and', 'if at - first["at"] >= t["confirm_seconds"] and'),
    ("settles while this reading shows the seller", ' and r["holder"] != "SELLER" and s["held_by"] != "SELLER":', ' and s["held_by"] != "SELLER":'),
    ("settles while the seller is confirmed holder", ' and r["holder"] != "SELLER" and s["held_by"] != "SELLER":', ' and r["holder"] != "SELLER":'),
    ("withdrawn pays the seller without a live hold", '    elif s["held_alive"]:\n        _pay(s, pays, "seller"', '    elif True:\n        _pay(s, pays, "seller"'),
    ("live hold never seen", '    if r["holder"] == "BUYER" and r["status"] in ("PENDING", "ALLOWED"):\n        s["held_alive"] = True', '    pass'),
    ("a withdrawn hold counts as live", 'if r["holder"] == "BUYER" and r["status"] in ("PENDING", "ALLOWED"):', 'if r["holder"] == "BUYER":'),
    ("holder changes after allowance_by counted", '    if at >= t["allowance_by"]:\n        return\n    if r["holder"] == "BUYER"', '    if r["holder"] == "BUYER"'),
    ("seller again on one look", 'elif at - run["at"] >= t["confirm_seconds"] and s["held_by"] != r["holder"] and', 'elif s["held_by"] != r["holder"] and'),
    ("another holder does not restart the run", 'if run is None or run["holder"] != r["holder"]:', "if run is None:"),
    ("no record of what was paid at the decision", '    s["paid_at_decision"] = s["released"] - before', "    pass"),
    ("released not deducted", 'due = max(0, _price_for(t, d["amount"]) - s["released"])', 'due = _price_for(t, d["amount"])'),
    ("withdrawn after a live hold refunds the buyer", '_pay(s, pays, "seller", s["left"], "claim withdrawn after', '_pay(s, pays, "buyer", s["left"], "claim withdrawn after'),
    ("disallowed pays the seller", '_pay(s, pays, "buyer", s["left"], "claim disallowed', '_pay(s, pays, "seller", s["left"], "claim disallowed'),
    ("no shortfall recorded", 's["shortfall"] = max(0, s["released"] - _price_for(t, d["amount"]))', "pass"),
    # deadlines
    ("no transfer deadline", 'if not s["transfer_at"] and now >= t["transfer_by"] + GRACE_SECONDS:', "if False:"),
    ("transfer deadline without grace", 'if not s["transfer_at"] and now >= t["transfer_by"] + GRACE_SECONDS:', 'if not s["transfer_at"] and now >= t["transfer_by"]:'),
    ("long stop ignores the seller as holder", 'if s["held_by"] == "SELLER":', "if False:"),
    ("long stop uses the last look", 'if s["held_by"] == "SELLER":', 'if s["last_holder"] == "SELLER":'),
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
    ("claim number not a whole token", 'after = b >= len(page_n) or not (page_n[b].isalnum() or (page_n[b] in "-./" and b + 1 < len(page_n) and page_n[b + 1].isalnum()))', "after = True"),
    ("claim number may continue with a dot or slash", '(page_n[b] in "-./" and b + 1', '(page_n[b] == "-" and b + 1'),
    ("claim number prefix allowed", "before = a == 0 or not (page_n[a - 1].isalnum() or page_n[a - 1] == \"-\" or (page_n[a - 1] in \"./\" and a > 1 and page_n[a - 2].isalnum()))", "before = True"),
    ("claim number may follow a dot or slash", ' or (page_n[a - 1] in "./" and a > 1 and page_n[a - 2].isalnum()))', ")"),
    ("other claims ignored", 'if _yes(ans.get("other_claims_shown")) or _yes(ans.get("more_than_one_holder")):', 'if _yes(ans.get("more_than_one_holder")):'),
    ("holder label not checked", 'if _norm_label(h.get("label")) not in HOLDER_LABELS or _norm_label(st.get("label")) not in STATUS_LABELS:', 'if _norm_label(st.get("label")) not in STATUS_LABELS:'),
    ("amount label not checked", 'if _norm_label(am.get("label")) not in AMOUNT_LABELS:', "if False:"),
    ("holder not anchored", "    if h_at < 0 or st_at < 0:", "    if st_at < 0:"),
    ("status not anchored", "    if h_at < 0 or st_at < 0:", "    if h_at < 0:"),
    ("amount not anchored", "        if am_at < 0:", "        if False:"),
    ("partial value anchored", 'if all(c in " |" for c in pl[e:eol]):', "if True:"),
    ("label anchored after other words", "if all(c in SEPARATORS or c in LEAD_MARKS for c in pl[start:a]) and", "if True and"),
    ("label anchored inside a longer word", " and (b == len(pl) or pl[b] in SEPARATORS):\n            j, breaks", ":\n            j, breaks"),
    ("words between label and value", "and pl[j] in SEPARATORS and breaks", "and not pl.startswith(value_n, j) and breaks"),
    ("value lines away", 'and breaks + (pl[j] == "\\n") <= 1:', ":"),
    ("transferee from anyone", 'if words == buyer and source in (None, seller):', "if words == buyer:"),
    ("seller transferee from anyone", 'if words == seller and source in (None, buyer):', "if words == seller:"),
    ("bracketed transferee not read", '.replace("(", " ").replace(")", " ")', ""),
    ("status by word not phrase", 'status = STATUS_TABLE.get(_norm_status(st.get("value")), "UNCLEAR")', 'status = next((v for k, v in STATUS_TABLE.items() if k in _norm_status(st.get("value"))), "UNCLEAR")'),
    ("not allowed counted as allowed", '"allowed": "ALLOWED", "allowed in full"', '"allowed": "ALLOWED", "not allowed": "ALLOWED", "allowed in full"'),
    ("bare expunged disallows", '"expunged and disallowed": "DISALLOWED",', '"expunged and disallowed": "DISALLOWED", "expunged": "DISALLOWED",'),
    ("transferee mark ignored", "        if k >= 0:\n            source", "        if False:\n            source"),
    ("holder by containment", 'if words == buyer and source', 'if _contains_words(words, buyer) and source'),
    ("three decimals accepted", "if \".\" in frac or len(frac) not in (1, 2) or not all(c in DIGITS for c in frac):", "if \".\" in frac or not all(c in DIGITS for c in frac):"),
    ("zero amount accepted", "return n if n > 0 else None", "return n"),
    ("currency on page ignored", 'if not _currency_ok(ans.get("currency_on_page"), t["currency"]):', "if False:"),
    ("decimal-comma page accepted", 'if _decimal_comma_page(page):\n        return {"kind": "NO_READING", "reason": "N2_FORMAT"}', 'if False:\n        return {"kind": "NO_READING", "reason": "N2_FORMAT"}'),
    ("page not cut", "        text = text[:PAGE_CHARS]\n", ""),
    ("page cut inside a line", '        text = text[:nl] if nl >= 0 else ""', "        pass"),
    ("references read as decimal commas", 'for ch in _drop_refs(str(page or "").lower()) + " ":', 'for ch in str(page or "").lower() + " ":'),
    ("dotted addresses read as decimal commas", "        if _dotted_address(r):\n            continue", "        pass"),
    ("1.234,56 not decimal comma", 'if "." in r and r.index(".") < r.rindex(","):\n                return True', "if False:\n                return True"),
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
    # second review
    ("first live sighting not counted", '        if r["holder"] == "BUYER" and r["status"] in ("PENDING", "ALLOWED") and at < t["transfer_by"]:\n            s["held_alive"] = True', "        pass"),
    ("unsustained sighting still live", '            s["held_alive"] = False  # the sighting was not sustained', "            pass"),
    ("unattributable withdrawal decides", ' or unattributable:  # a withdrawal nobody can attribute', ':  # a withdrawal nobody can attribute'),
    ("no late upfront", "    _late_upfront(t, s, r, at, pays)\n", ""),
    ("late upfront on one look", "    if at - s[\"live_first\"] >= t[\"confirm_seconds\"]:\n        up =", "    if True:\n        up ="),
    ("late upfront paid twice", '        s["upfront_paid"] = True\n        _log(s, at, "UPFRONT_LATE"', '        _log(s, at, "UPFRONT_LATE"'),
    ("late upfront after allowance_by", '    if s["upfront_paid"] or at >= t["allowance_by"]:', '    if s["upfront_paid"]:'),
    ("late upfront on a dead status", '    if r["holder"] != "BUYER" or r["status"] not in ("PENDING", "ALLOWED"):\n        s["live_first"] = 0', '    if r["holder"] != "BUYER":\n        s["live_first"] = 0'),
    ("a second label line accepted", "    if any(x != h_at for x in _label_form_lines(pl, HOLDER_LABELS)) or any(x != st_at for x in _label_form_lines(pl, STATUS_LABELS)):", "    if False:"),
    ("a second amount line accepted", "        if any(x != am_at for x in _label_form_lines(pl, AMOUNT_LABELS)) or _qualified_next(", "        if _qualified_next("),
    ("a longer label counted as a label line", '                if tail == "" or tail[0] in ":|=":', "                if True:"),
    ("next-line qualifier ignored", '        if n.startswith("(") or any(w in n for w in QUALIFIERS) or n.startswith(tuple(m.strip() for m in TRANSFEREE_MARKS)):', "        if False:"),
    ("wrapped holder tail ignored", ' or n.startswith(tuple(m.strip() for m in TRANSFEREE_MARKS)):', ":"),
    ("partial transfer on the page ignored", '    if any(w in pl for w in ("partial transfer", "partial assignment", "transfer of part")):', "    if False:"),
    # third review
    ("a label line written with = not counted", '                if tail == "" or tail[0] in ":|=":', '                if tail == "" or tail[0] in ":|":'),
    ("only the very next line checked", "    for nxt in lines[used:]:", "    for nxt in lines[used:used + 1]:"),
    ("a leading bracket not a qualifier", '        if n.startswith("(") or any(w in n for w in QUALIFIERS)', '        if any(w in n for w in QUALIFIERS)'),
    ("cut page not marked", '        text += "\\n(cut)"', '        pass'),
    ("amount line's next line not checked", " or _qualified_next(pl, am_at, _norm_label(am.get(\"label\")), _norm(am.get(\"value\"))):", ":"),
    ("reserved not a qualifier", '"reduced", "reserved", "disputed"', '"reduced", "disputed"'),
    ("late upfront run not reset", '        s["live_first"] = 0\n        return\n    if not s["live_first"]:', '        return\n    if not s["live_first"]:'),
    ("no close when the late upfront empties the escrow", '        _pay(s, pays, "seller", up, "upfront, after a transfer confirmed while the status was unclear")\n        if s["left"] == 0:', '        _pay(s, pays, "seller", up, "upfront, after a transfer confirmed while the status was unclear")\n        if False:'),
    ("late upfront not capped at an allowed reading", '        up = _upfront(t) if r["status"] == "PENDING" else min(_upfront(t), _price_for(t, r["amount"]))\n        up = max(0, up - s["released"])', '        up = _upfront(t)\n        up = max(0, up - s["released"])'),
    ("late upfront ignores releases", '        up = max(0, up - s["released"])  # the upfront tops the seller up to its level: a release made by hand counts', '        pass'),
    ("transfer upfront ignores releases", '            up = max(0, up - s["released"])  # the upfront tops the seller up to its level: earlier releases count', '            pass'),
    ("a third party clears the seller's hold", ' and not (s["held_by"] == "SELLER" and r["holder"] != "BUYER"):', ':'),
    # fourth review
    ('transfer upfront also deducts refunds', '            up = max(0, up - s["released"])  # the upfront tops the seller up to its level: earlier releases count', '            up = max(0, up - s["released"] - s["refunded"])'),
    ('late upfront also deducts refunds', '        up = max(0, up - s["released"])  # the upfront tops the seller up to its level: a release made by hand counts', '        up = max(0, up - s["released"] - s["refunded"])'),
    ('held_alive set by any live look after the transfer', '    if r["holder"] == "BUYER" and r["status"] in ("PENDING", "ALLOWED"):\n        s["held_alive"] = True', '    if r["status"] in ("PENDING", "ALLOWED"):\n        s["held_alive"] = True'),
    ("readings in any order", '    if at < s.get("last_read", 0) or (s["state"] == "ACTIVE" and at < s["accepted_at"]):', '    if False:'),
    ("a reading before accept counts", ' or (s["state"] == "ACTIVE" and at < s["accepted_at"]):', ":"),
    ("em dash not a dash", 'for d in ("\\u2212", "\\u2013", "\\u2014", "\\u2012", "\\u2015"):', 'for d in ("\\u2212", "\\u2013"):'),
    ("money check in _commit removed", "if any(v < 0 for _w, v, _n in pays) or held_before + value_in != s[\"left\"] + out or s[\"left\"] < 0:", "if False:"),
]


# Equivalent mutant, not counted: the page lines are already normalised (a
# no-break space or tab becomes a space) before _qualified_next strips them.
EQUIVALENT = [
    ("no-break space line not blank", '        n = nxt.strip(" |\\t\\u00a0")', '        n = nxt.strip(" |")'),
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
