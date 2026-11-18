"""Tests from the fourth independent review (18 Nov 2026). Each asserts the
contract's behaviour: the money tests (refunds and the upfront top-up, the
6,000-sequence fuzz) and the limits the README states (a second sale shown
straight away, a buyer's affiliate, separator lines, currency names in
words). Every name is fictional."""

import copy
import json
import random

import pytest

from tests.direct.test_claim_escrow import (  # noqa: F401
    env, mod, iso, offer, read, accept, ready, money, claim, transfer, state, page, answer,
    T0, C, G, PRICE, UP, URL, GRACE, TRANSFER_BY, ALLOWANCE_BY, SELLER_NAME, BUYER_NAME, BUY_H, DEBTOR, FACE, RATE, UPG,
)
from tests.direct.test_claim_escrow_review3 import body, interp, demo, AMBIG, TERMS  # noqa: F401

SELLERS_NEW_BUYER = f"Brightwater Claims Fund LP as transferee of {SELLER_NAME}"
BUYERS_AFFILIATE = f"Harrowfield Credit Opportunities LLC as transferee of {SELLER_NAME}"


# ---------------------------------------------- 1. holder after the transfer


def test_p1_sellers_new_buyer_shown_directly_settles_the_decision_for_the_seller(env):
    """SHOULD-FIX: S-1's fix needs the seller to be SEEN twice first. If the
    register goes straight from 'Harrowfield as transferee of Quenby' to
    'Brightwater as transferee of Quenby' (the seller's second sale), OTHER
    seen twice becomes held_by and the decision pays the seller in full."""
    ready(env)
    transfer(env)  # PENDING: UP released
    read(env, state(SELLERS_NEW_BUYER, "Allowed", "$1,250,000.00"), T0 + 4000)
    r = read(env, state(SELLERS_NEW_BUYER, "Allowed", "$1,250,000.00"), T0 + 4000 + C)
    m = money(env)
    assert r["deal"]["held_by"] == "OTHER" and r["deal"]["state"] == "SETTLED"
    assert m["released"] == PRICE and m["refunded"] == 0


def test_p1b_sellers_new_buyer_withdraws_and_the_seller_takes_everything(env):
    ready(env)
    transfer(env)  # held_alive: the buyer was shown live
    read(env, state(SELLERS_NEW_BUYER, "Withdrawn by claimant"), T0 + 4000)
    read(env, state(SELLERS_NEW_BUYER, "Withdrawn by claimant"), T0 + 4000 + C)
    assert money(env)["released"] == PRICE  # "withdrawn after the transfer": attributed to the buyer


def test_p2_buyer_round_trip_through_an_affiliate_keeps_the_claim_and_gets_the_refund(env):
    """SHOULD-FIX (new with the SELLER-hold rule): the buyer withdraws its
    notice (the seller is seen twice), then its affiliate files a transfer from
    the seller. The affiliate holds the claim, allowed in full, yet nothing
    settles and the long stop refunds the buyer everything but the upfront.
    Before the fix (mutant 128) the seller would have been paid the price."""
    ready(env)
    transfer(env)
    read(env, state(SELLER_NAME, "Pending"), T0 + 2500)
    read(env, state(SELLER_NAME, "Pending"), T0 + 2500 + C)
    for k in range(3):
        read(env, state(BUYERS_AFFILIATE, "Allowed", "$1,250,000.00"), T0 + 5000 + k * C)
    d = env.c.get_deal("1")
    assert d["held_by"] == "SELLER" and d["state"] == "ACTIVE"
    env.vm.warp(iso(ALLOWANCE_BY + GRACE))
    env.c.settle("1")
    m = money(env)
    assert m["released"] == UP and m["refunded"] == PRICE - UP


# ------------------------------------------------- 2. the cut sentinel


def _cut_after(mod, kept_tail, lost_tail, head):
    pre = "\n".join(head) + "\nNotes: "
    filler = "x" * (mod.PAGE_CHARS - len(pre) - len("\n" + kept_tail) - 1)
    return pre + filler + "\n" + kept_tail + "\n" + lost_tail + "\nLast updated: 2026-11-18"


def test_p3_sentinel_can_be_anchored_as_a_value_on_the_next_line(env, mod):
    """NIT: when the last kept line is a bare label ('Status:'), a model that
    copies the next line copies the sentinel. Code anchors it (a value may
    start the next line) and reads UNCLEAR, a READ, not a NO_READING; the
    same for the holder (OTHER)."""
    head = [f"Claims Register {DEBTOR}", "Claim No.: 1042", f"Creditor: {BUY_H}", "Allowed amount: $1,250,000.00"]
    pg = mod._clean_page(_cut_after(mod, "Status:", "Allowed", head))
    assert pg.endswith("Status:\n(cut)")
    b = body(BUY_H, "Allowed", "$1,250,000.00")
    b["status"] = {"label": "Status", "value": "(cut)"}
    assert interp(mod, pg, b) == {"kind": "READ", "holder": "BUYER", "status": "UNCLEAR", "amount": 0}
    head2 = [f"Claims Register {DEBTOR}", "Claim No.: 1042", "Status: Pending", "Allowed amount: -"]
    pg2 = mod._clean_page(_cut_after(mod, "Creditor:", BUY_H, head2))
    b2 = body("(cut)", "Pending")
    assert interp(mod, pg2, b2) == {"kind": "READ", "holder": "OTHER", "status": "PENDING", "amount": 0}


def test_p3b_a_sentinel_read_restarts_the_decision_count(env, mod):
    # consequence of p3: an UNCLEAR READ (unlike a NO_READING) restarts the decision count
    ready(env)
    transfer(env)
    read(env, state(BUY_H, "Allowed", "$1,250,000.00"), T0 + 5000)
    head = [f"Claims Register {DEBTOR}", "Claim No.: 1042", f"Creditor: {BUY_H}", "Allowed amount: $1,250,000.00"]
    pg = mod._clean_page(_cut_after(mod, "Status:", "Allowed", head))
    b = body(BUY_H, "Allowed", "$1,250,000.00")
    b["status"] = {"label": "Status", "value": "(cut)"}
    read(env, (pg, "```json\n" + json.dumps(b) + "\n```"), T0 + 5100)  # fenced: genlayer-test 0.30 auto-parses a bare JSON mock into a dict
    assert env.c.get_deal("1")["decision"]["first_seen"] is None


def test_p4_a_long_single_line_page_now_reaches_the_model(env, mod):
    # NIT: before the sentinel, a page with no line break in its first 12,000 characters was N1_PAGE_DARK;
    # now it is '\n(cut)', not blank, so the model is asked; code still gives a NO_READING (N1_WRONG_PAGE).
    assert mod._clean_page("x" * 13000) == "\n(cut)"
    ready(env)
    r = read(env, ("x" * 13000, answer(BUY_H, page_kind="other")), T0 + 1000)
    assert r["reading"] == {"kind": "NO_READING", "reason": "N1_WRONG_PAGE"}


def test_p5_a_long_page_with_the_entry_on_top_still_reads(env, mod):
    # ok: the sentinel refuses only a field on the last kept line
    hist = "\n".join(f"2026-09-{(i % 28) + 1:02d} Docket entry {i}: notice filed" for i in range(600))
    pg = demo(BUY_H, "Allowed", "$1,250,000.00") + "\nClaim history\n" + hist
    assert len(pg) > mod.PAGE_CHARS
    cut = mod._clean_page(pg)
    assert cut.endswith("\n(cut)")
    assert interp(mod, cut, body(BUY_H, "Allowed", "$1,250,000.00")) == {"kind": "READ", "holder": "BUYER", "status": "ALLOWED", "amount": 1250000}


# ------------------------------------------- 3. next-line qualifier: separator lines


@pytest.mark.parametrize("sep", ["---", "—", "* * *", "-", "_____"])
def test_p6_a_separator_line_hides_the_next_line_qualifier(env, mod, sep):
    """NIT: only blank (and '|') lines are skipped. A rule line between the
    field and its qualifier hides the qualifier."""
    pg = demo(BUY_H, "Allowed", "$1,250,000.00").replace("Status: Allowed\n", f"Status: Allowed\n{sep}\n(for voting purposes only)\n")
    r = interp(mod, pg, body(BUY_H, "Allowed", "$1,250,000.00"))
    assert r == {"kind": "READ", "holder": "BUYER", "status": "ALLOWED", "amount": 1250000}


def test_p6b_wrapped_holder_without_as_is_read_as_the_buyer(env, mod):
    # NIT (README "a holder name that wraps on to the next line"): only a next line that starts with
    # "as transferee of"/"as assignee of" or a bracket is caught; "Transferee of ..." or "Transferor: ..." is not.
    for nxt in ("Transferee of Someone Else Ltd", "Transferor: Someone Else Ltd"):
        pg = demo(BUYER_NAME, "Pending").replace(f"Creditor: {BUYER_NAME}\n", f"Creditor: {BUYER_NAME}\n{nxt}\n")
        assert interp(mod, pg, body(BUYER_NAME, "Pending"))["holder"] == "BUYER"


# ------------------------------------------------- 4. what the model still judges


@pytest.mark.parametrize("cur,want", [("$", "READ"), ("USD", "READ"), ("", "READ"), ("US$", "READ"),
                                      ("US dollars", "N2_CURRENCY"), ("dollars", "N2_CURRENCY"), ("United States Dollar", "N2_CURRENCY")])
def test_p7_currency_written_in_words_refuses_an_allowed_reading(env, mod, cur, want):
    """NIT (consensus): the currency answer is a model output; a model that
    names the currency in words refuses the reading and disagrees with the
    others. The demo page prints '$'."""
    r = interp(mod, demo(BUY_H, "Allowed", "$1,250,000.00"), body(BUY_H, "Allowed", "$1,250,000.00", currency_on_page=cur))
    assert (r["kind"] if r["kind"] == "READ" else r["reason"]) == want


def test_p8_two_yes_no_judgments_still_refuse_the_page(env, mod):
    # residual of B-1: 'other_claims_shown' and 'more_than_one_holder' are judgments; "yes" refuses.
    # Measured: no validator disagreed on them in s2, s3, s5 (and grok-4.3 agreed on 'as transferee' pages in s2).
    pg = demo(BUY_H, "Pending")
    assert interp(mod, pg, body(BUY_H, "Pending", more_than_one_holder="yes")) == AMBIG
    assert interp(mod, pg, body(BUY_H, "Pending", other_claims_shown="yes")) == AMBIG


# ------------------------------------------------- 5. money: extended fuzz


def test_p9_random_sequences_with_the_top_up_rule(env, mod, monkeypatch):
    """6,000 random sequences of readings (all holders/statuses, stamps that
    run back or precede accept), buyer releases, seller refunds and deadlines.
    Checked at every step:
      - escrow == left + released + refunded, left >= 0, the _commit identity;
      - at most one upfront event (transfer-time or late);
      - without a decision, split or seller-withdrawal: released <= max(UP, gifts before the upfront) + gifts after;
      - held_by never goes straight from SELLER to OTHER; no decision confirms while held_by is SELLER;
      - each decision pays exactly: ALLOWED -> seller max(0, price(A) - R0) capped by L0, buyer the rest;
        DISALLOWED -> buyer L0; WITHDRAWN -> L0 to the seller iff held_alive; split -> seller L0*bp//BP;
        seller-held long stop -> buyer L0."""
    rnd = random.Random(4004)
    t = {"buyer_name": BUYER_NAME, "seller_name": SELLER_NAME, "face_amount": FACE, "rate_bp": RATE, "units_per_gen": UPG,
         "upfront_bp": 5000, "no_decision_seller_bp": 7000, "confirm_seconds": C, "accept_by": T0 + 3600,
         "transfer_by": TRANSFER_BY, "allowance_by": ALLOWANCE_BY, "currency": "USD"}
    holders, statuses = ("BUYER", "SELLER", "OTHER"), ("PENDING", "ALLOWED", "DISALLOWED", "WITHDRAWN", "UNCLEAR")
    seen = []
    real_settle = mod._settle_decision

    def spy(tt, s, now, pays):
        r0, l0, alive = s["released"], s["left"], s["held_alive"]
        assert s["held_by"] != "SELLER"
        real_settle(tt, s, now, pays)
        seen.append((dict(s["decision"]), r0, l0, alive, s["released"], s["refunded"]))
    monkeypatch.setattr(mod, "_settle_decision", spy)
    bad, n_dec, n_split, n_up = [], 0, 0, 0
    for n in range(6000):
        t["upfront_bp"] = rnd.choice((0, 2500, 5000, 6000, 10000))
        t["no_decision_seller_bp"] = rnd.choice((0, 3000, 7000, 10000))
        price, up_full = mod._price(t), mod._upfront(t)
        s = mod._new_state(T0)
        s.update(state="ACTIVE", accepted_at=T0 + 300, escrow=price, left=price, t=T0 + 300)
        g_before, g_after, now, last = 0, 0, T0 + 300, None
        for _ in range(rnd.randint(1, 24)):
            if s["state"] != "ACTIVE":
                break
            before = copy.deepcopy(s)
            now += rnd.choice((30, 60, 300, C - 1, C, C + 1, 2 * C, 3600, 4 * 3600, 6 * 3600))
            at = now - rnd.choice((0, 0, 0, 5, C, 4000))
            pays = []
            s["t"] = max(s["t"], now)
            seen.clear()
            mod._apply_deadlines(t, s, s["t"], pays)
            if s["state"] != "ACTIVE" and before["state"] == "ACTIVE" and before["transfer_at"]:
                l0 = before["left"]
                if before["held_by"] == "SELLER":
                    ok = s["refunded"] - before["refunded"] == l0 and s["released"] == before["released"]
                else:
                    n_split += 1
                    ok = s["released"] - before["released"] == l0 * t["no_decision_seller_bp"] // 10000
                if not ok:
                    bad.append(("long stop", n, before["held_by"], l0, s["released"], s["refunded"]))
            kind = rnd.random()
            upfront_events_before = sum(1 for e in s["log"] if e["what"] in ("UPFRONT_LATE", "TRANSFER_CONFIRMED"))
            if s["state"] == "ACTIVE" and kind < 0.08 and s["left"] > 0:
                amt = rnd.randint(1, s["left"])
                mod._pay(s, pays, "seller", amt, "release")
                if any(e["what"] in ("UPFRONT_LATE",) for e in s["log"]) or s["upfront_paid"]:
                    g_after += amt
                else:
                    g_before += amt
                if s["left"] == 0:
                    mod._close(s, now, "nothing left in escrow")
            elif s["state"] == "ACTIVE" and kind < 0.14 and s["left"] > 0:
                mod._pay(s, pays, "buyer", rnd.randint(1, s["left"]), "refund")
                if s["left"] == 0:
                    mod._close(s, now, "nothing left in escrow")
            elif s["state"] == "ACTIVE":
                if last is None or rnd.random() < 0.45:
                    st = rnd.choice(statuses)
                    amt = rnd.choice((100_000, 400_000, 1_000_000, 1_250_000, 2_000_000)) if st == "ALLOWED" else 0
                    last = {"kind": "READ", "holder": rnd.choice(holders), "status": st, "amount": amt}
                mod._apply_reading(t, s, dict(last), at, pays)  # often the same state again, so counts confirm
            out = sum(v for _w, v, _n in pays)
            if before["left"] != s["left"] + out or any(v < 0 for _w, v, _n in pays):
                bad.append(("commit identity", n))
            if s["escrow"] != s["left"] + s["released"] + s["refunded"] or s["left"] < 0:
                bad.append(("reconcile", n))
            ups = [e for e in s["log"] if e["what"] == "UPFRONT_LATE"]
            tc = [e for e in s["log"] if e["what"] == "TRANSFER_CONFIRMED"]
            paid_at_transfer = s["transfer_status"] in ("PENDING", "ALLOWED")
            if len(ups) + (1 if paid_at_transfer else 0) > 1 or len(tc) > 1:
                bad.append(("upfront twice", n))
            n_up += upfront_events_before == 0 and (len(ups) + len(tc)) > 0
            if before["held_by"] == "SELLER" and s["held_by"] == "OTHER":
                bad.append(("SELLER hold cleared by OTHER", n, s["log"][-4:]))
            for dec, r0, l0, alive, r1, f1 in seen:
                n_dec += 1
                if dec["status"] == "ALLOWED":
                    want = min(l0, max(0, mod._price_for(t, dec["amount"]) - r0))
                    if r1 - r0 != want or s["left"] != 0:
                        bad.append(("allowed pay", n, dec, r0, l0, r1))
                elif dec["status"] == "DISALLOWED":
                    if r1 != r0 or s["left"] != 0:
                        bad.append(("disallowed pay", n))
                else:
                    if (r1 - r0) != (l0 if alive else 0):
                        bad.append(("withdrawn pay", n, alive, r0, l0, r1))
            decided = s["decision"] is not None or "split" in s["settled_reason"]
            if not decided and s["released"] > max(up_full, g_before) + g_after:
                bad.append(("seller above the upfront level", n, s["released"], up_full, g_before, g_after, s["log"][-5:]))
    assert bad == [], bad[:5]
    assert n_dec > 300 and n_split > 100 and n_up > 500, (n_dec, n_split, n_up)
    print("decisions", n_dec, "splits", n_split, "upfront events", n_up)


# ------------------------------------------- 6. test gaps found by hand mutants


def test_p10_a_seller_refund_before_the_transfer_does_not_cut_the_upfront(env):
    # kills hand mutant "transfer upfront also deducts refunds" (survives the 271 tests)
    ready(env)
    env.vm.sender = env.buyer
    env.c.release("1", PRICE // 10)
    env.vm.sender = env.seller
    env.c.refund("1", PRICE // 10)
    transfer(env)  # PENDING
    m = money(env)
    assert m["released"] == UP and m["refunded"] == PRICE // 10  # the live 'one_sided' case: 2.5 GEN at the transfer


def test_p10b_a_seller_refund_does_not_cut_the_late_upfront(env):
    # kills hand mutant "late upfront also deducts refunds"
    ready(env)
    read(env, state(BUY_H, "Transferred"), T0 + 1000)
    read(env, state(BUY_H, "Transferred"), T0 + 1000 + C)
    env.vm.sender = env.seller
    env.c.refund("1", PRICE // 10)
    read(env, state(BUY_H, "Pending"), T0 + 3000)
    read(env, state(BUY_H, "Pending"), T0 + 3000 + C)
    assert money(env)["released"] == UP


def test_p11_a_live_look_with_another_holder_does_not_make_a_withdrawal_the_buyers(env):
    # kills hand mutant "held_alive set by any live look after the transfer"
    ready(env)
    read(env, state(BUY_H, "Transferred"), T0 + 1000)
    read(env, state(BUY_H, "Transferred"), T0 + 1000 + C)  # confirmed UNCLEAR, never live
    assert env.c.get_deal("1")["held_alive"] is False
    read(env, state("Brightwater Claims Fund LP", "Pending"), T0 + 3000)  # someone else, live
    for k in range(2):
        read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 4000 + k * C)
    assert env.c.get_deal("1")["decision"]["confirmed"] is None  # unattributable: the long stop splits
    assert money(env)["released"] == 0
