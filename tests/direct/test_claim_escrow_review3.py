"""Regression tests from the third independent review (18 Nov 2026). The
reviewer's probes, kept; where the review found a weak point the test now
asserts the fixed behaviour. Every case, debtor, creditor and agent is
fictional.
"""

import json
import random

import pytest

from tests.direct.test_claim_escrow import (  # noqa: F401
    env, mod, iso, offer, read, accept, ready, money, claim, transfer, decide, state, page, answer,
    T0, C, G, PRICE, UP, URL, PROMPT, GRACE, TRANSFER_BY, ALLOWANCE_BY, SELLER_NAME, BUYER_NAME, BUY_H, DEBTOR, FACE, RATE, UPG,
)

TERMS = {"buyer_name": BUYER_NAME, "seller_name": SELLER_NAME, "debtor_name": DEBTOR, "claim_number": "1042", "currency": "USD"}
AMBIG = {"kind": "NO_READING", "reason": "N2_AMBIGUOUS"}
OTHER_H = f"Brightwater Claims Fund LP as transferee of {SELLER_NAME}"


def body(holder=SELLER_NAME, status="Pending", allowed="", **over):
    return json.loads(answer(holder, status, allowed, wrap=False, **over))


def interp(mod, pg, b):
    return mod._interpret(TERMS, b, pg)


def demo(holder=SELLER_NAME, status="Pending", allowed="", claim_amount="$1,250,000.00", after_entry=None):
    """The demo register page as Studio renders it (make_register.py; measured
    line shapes: 'Claim No.: 1042', 'Creditor: ...', 'Status: ...',
    'Allowed amount: ...', 'Last updated: ...')."""
    tail = after_entry if after_entry is not None else [
        'Transfers of claim are shown as filed under Rule 3001(e). The current holder appears as "transferee of" the original creditor.',
        "Fictional case, names and figures, published for a GenLayer ClaimEscrow demonstration by Brilliant Nodes. Not a real register.",
    ]
    return "\n".join([
        "Marrowgate Restructuring Agents",
        "Claims and noticing agent (fictional)",
        f"Claims Register: {DEBTOR}",
        "Case No. 26-10432, United States Bankruptcy Court for the District of Example (fictional)",
        "Claim No.: 1042",
        f"Creditor: {holder}",
        "Date filed: 2026-09-14",
        f"Claim amount: {claim_amount}",
        f"Status: {status}",
        f"Allowed amount: {allowed or '-'}",
        "Last updated: 2026-11-18 12:42 UTC",
    ] + tail)


# ---------------------------------------------- 1. the real demo page reads


@pytest.mark.parametrize("holder,status,allowed,want", [
    (SELLER_NAME, "Pending", "", ("SELLER", "PENDING", 0)),
    (BUY_H, "Pending", "", ("BUYER", "PENDING", 0)),
    (BUY_H, "Allowed", "$1,250,000.00", ("BUYER", "ALLOWED", 1250000)),
    (BUY_H, "Allowed", "$1,000,000.00", ("BUYER", "ALLOWED", 1000000)),
    (BUY_H, "Disallowed by court order", "", ("BUYER", "DISALLOWED", 0)),
    (BUY_H, "Withdrawn by claimant", "", ("BUYER", "WITHDRAWN", 0)),
    (BUY_H, "Allowed for voting purposes only", "$900,000.00", ("BUYER", "UNCLEAR", 0)),
])
def test_r1_demo_page_as_rendered_reads_every_case(env, mod, holder, status, allowed, want):
    r = interp(mod, demo(holder, status, allowed), body(holder, status, allowed if status == "Allowed" else ""))
    assert r["kind"] == "READ" and (r["holder"], r["status"], r["amount"]) == want


def test_r1b_an_extra_qualified_answer_from_the_model_is_ignored(env, mod):
    # B-1: the model no longer judges qualifications (a validator disagreed live on its own judgment)
    assert interp(mod, demo(), body(qualified="yes")) == {"kind": "READ", "holder": "SELLER", "status": "PENDING", "amount": 0}


def test_r1c_a_reduced_allowance_is_decided_at_the_price_for_the_allowed_amount(env):
    ready(env)
    transfer(env)  # PENDING: upfront 3.75 GEN released
    for k in range(2):
        pg = demo(BUY_H, "Allowed", "$1,000,000.00")
        read(env, (pg, answer(BUY_H, "Allowed", "$1,000,000.00", qualified="yes")), T0 + 5000 + k * C)
    m = money(env)
    due = 1_000_000 * RATE * G // (10000 * UPG)  # 6.0 GEN: the price for the allowed amount
    assert env.c.get_deal("1")["state"] == "SETTLED" and m["released"] == due and m["refunded"] == PRICE - due


@pytest.mark.parametrize("footer", [
    "(fictional)",
    "Copyright 2026 Marrowgate Restructuring Agents. All rights reserved.",
    "Amounts subject to change without notice.",
    "Claim type: General unsecured, non-contingent",
])
def test_r2_ordinary_footer_right_after_the_last_field_line_refuses_the_page(env, mod, footer):
    pg = demo(BUY_H, "Allowed", "$1,250,000.00").replace("Last updated: 2026-11-18 12:42 UTC\n", "")
    pg = pg.replace("Allowed amount: $1,250,000.00\n", "Allowed amount: $1,250,000.00\n" + footer + "\n")
    assert interp(mod, pg, body(BUY_H, "Allowed", "$1,250,000.00")) == AMBIG


def test_r2b_status_history_original_creditor_and_case_status_lines_do_not_count(env, mod):
    extra = ["Original creditor: " + SELLER_NAME, "Creditor address: 100 Main St", "Case status: Open",
             "Claim status history", "2026-09-14 Filed", "Status history: Filed 2026-09-14"]
    pg = demo(BUY_H, "Pending", after_entry=extra)
    assert interp(mod, pg, body(BUY_H, "Pending"))["kind"] == "READ"


def test_r2c_a_bare_status_line_for_the_case_refuses_the_page(env, mod):
    pg = demo(BUY_H, "Pending").replace("Claim No.: 1042", "Status: Open\nClaim No.: 1042")
    assert interp(mod, pg, body(BUY_H, "Pending")) == AMBIG


def test_r2d_on_a_space_joined_table_the_one_line_rule_does_not_apply(env, mod):
    # Other sites' tables render one line per row, cells joined by one space. A second
    # 'Status ...' row (an objection sub-table) is not 'written as a label', so it is not
    # counted; only the model's choice of line protects the money (S-2 at the table level).
    pg = "\n".join([f"Claims Register {DEBTOR}", "Claim Number 1042", f"Creditor Name {BUY_H}", "Claim Status Pending",
                    "Objection Docket No. 812", "Status Withdrawn"])
    b = body(BUY_H, "Withdrawn")
    b["holder"] = {"label": "Creditor Name", "value": BUY_H}
    assert interp(mod, pg, b) == {"kind": "READ", "holder": "BUYER", "status": "WITHDRAWN", "amount": 0}
    b["status"] = {"label": "Claim Status", "value": "Pending"}
    assert interp(mod, pg, b)["status"] == "PENDING"  # same page, the other line: the model's choice decides
    pg2 = pg.replace("Claim Status Pending", f"Claim Status Pending\nCreditor Name {BUYER_NAME}")
    b["holder"] = {"label": "Creditor Name", "value": BUYER_NAME}
    assert interp(mod, pg2, b)["holder"] == "BUYER"  # a second 'Creditor Name' row is not counted either


# ------------------------------------- 3. the cut can drop the next-line qualifier


def _cut_page(mod, last_line, next_line, before):
    pre = "\n".join(before) + "\nNotes: "
    filler = "x" * (mod.PAGE_CHARS - len(pre) - len("\n" + last_line) - 1)
    return pre + filler + "\n" + last_line + "\n" + next_line + "\nLast updated: 2026-11-18"


def test_r3_a_field_on_the_last_line_of_a_cut_page_is_refused(env, mod):
    before = [f"Claims Register {DEBTOR}", "Claim No.: 1042", f"Creditor: {BUY_H}", "Allowed amount: $1,250,000.00"]
    full = _cut_page(mod, "Status: Allowed", "(for voting purposes only)", before)
    assert len(full) > mod.PAGE_CHARS
    assert interp(mod, full, body(BUY_H, "Allowed", "$1,250,000.00")) == AMBIG  # whole page: refused
    cut = mod._clean_page(full)
    assert cut.endswith("Status: Allowed\n(cut)")
    assert interp(mod, cut, body(BUY_H, "Allowed", "$1,250,000.00")) == AMBIG  # what followed is unknown


def test_r3b_a_holder_on_the_last_line_of_a_cut_page_is_refused(env, mod):
    before = [f"Claims Register {DEBTOR}", "Claim No.: 1042", "Status: Pending", "Allowed amount: -"]
    full = _cut_page(mod, f"Creditor: {BUYER_NAME}", "as transferee of Someone Else Ltd", before)
    assert interp(mod, full, body(BUYER_NAME, "Pending")) == AMBIG
    assert interp(mod, mod._clean_page(full), body(BUYER_NAME, "Pending")) == AMBIG


# --------------------------------------- 4. holder after the transfer: SELLER then OTHER


def test_r4_once_the_seller_holds_the_claim_again_a_third_party_does_not_clear_it(env):
    ready(env)
    transfer(env)  # PENDING, upfront to the seller
    read(env, state(SELLER_NAME, "Pending"), T0 + 2500)
    read(env, state(SELLER_NAME, "Pending"), T0 + 2500 + C)
    assert env.c.get_deal("1")["held_by"] == "SELLER"  # the seller holds the claim again (seen twice)
    read(env, state(OTHER_H, "Allowed", "$1,250,000.00"), T0 + 4000)
    read(env, state(OTHER_H, "Allowed", "$1,250,000.00"), T0 + 4000 + C)  # the seller's new buyer
    d = env.c.get_deal("1")
    assert d["held_by"] == "SELLER" and d["state"] == "ACTIVE" and money(env)["released"] == UP
    env.vm.warp(iso(ALLOWANCE_BY + GRACE))
    env.c.settle("1")
    m = money(env)
    assert m["released"] == UP and m["refunded"] == PRICE - UP  # the long stop gives the buyer everything left


def test_r4b_seller_again_then_a_third_party_withdraws_does_not_pay_the_seller(env):
    ready(env)
    transfer(env)
    read(env, state(SELLER_NAME, "Pending"), T0 + 2500)
    read(env, state(SELLER_NAME, "Pending"), T0 + 2500 + C)
    read(env, state(OTHER_H, "Withdrawn by claimant"), T0 + 4000)
    read(env, state(OTHER_H, "Withdrawn by claimant"), T0 + 4000 + C)
    assert money(env)["released"] == UP
    env.vm.warp(iso(ALLOWANCE_BY + GRACE))
    env.c.settle("1")
    assert money(env)["refunded"] == PRICE - UP


# ------------------------------------------------------- 5. late upfront


def _unclear_transfer(env):
    ready(env)
    read(env, state(BUY_H, "Pending"), T0 + 1000)
    read(env, state(BUY_H, "Transferred"), T0 + 1000 + C)  # confirmed while unclear: no upfront
    assert money(env)["released"] == 0


def test_r5_a_release_made_by_hand_counts_toward_the_late_upfront(env):
    _unclear_transfer(env)
    env.vm.sender = env.buyer
    env.c.release("1", UP)  # the parties settle the upfront by hand
    read(env, state(BUY_H, "Pending"), T0 + 3000)
    read(env, state(BUY_H, "Pending"), T0 + 3000 + C)  # the late upfront tops up to its level: nothing more
    d = env.c.get_deal("1")
    assert money(env)["released"] == UP and d["state"] == "ACTIVE"


def test_r5d_a_partial_release_is_topped_up_to_the_upfront(env):
    _unclear_transfer(env)
    env.vm.sender = env.buyer
    env.c.release("1", UP // 4)
    read(env, state(BUY_H, "Pending"), T0 + 3000)
    read(env, state(BUY_H, "Pending"), T0 + 3000 + C)
    assert money(env)["released"] == UP


def test_r5e_an_earlier_release_counts_toward_the_transfer_upfront(env):
    ready(env)
    env.vm.sender = env.buyer
    env.c.release("1", UP // 5)
    transfer(env)  # PENDING
    assert money(env)["released"] == UP


def test_r5b_late_upfront_after_a_transfer_confirmed_disallowed(env):
    ready(env)
    for k in range(2):
        read(env, state(BUY_H, "Disallowed"), T0 + 1000 + k * C)
    assert env.c.get_deal("1")["transfer"]["status"] == "DISALLOWED"
    read(env, state(BUY_H, "Pending"), T0 + 1000 + 2 * C + 100)  # the disallowance was vacated
    read(env, state(BUY_H, "Pending"), T0 + 1000 + 3 * C + 100)
    assert money(env)["released"] == UP  # README says this happens after an "unclear" transfer; it also does here


def test_r5c_late_upfront_and_the_decision_on_the_same_reading_add_up(env):
    _unclear_transfer(env)
    a = "$1,000,000.00"
    read(env, state(BUY_H, "Allowed", a), T0 + 3000)
    r = read(env, state(BUY_H, "Allowed", a), T0 + 3000 + C)
    due = 1_000_000 * RATE * G // (10000 * UPG)
    m = money(env)
    assert r["deal"]["state"] == "SETTLED" and m["released"] == due and m["refunded"] == PRICE - due


# ---------------------------------------- 6. withdrawal attribution corners


def test_r6_one_live_look_after_an_unclear_transfer_turns_the_split_into_seller_takes_all(env):
    _unclear_transfer(env)
    read(env, state(BUY_H, "Pending"), T0 + 3000)  # one look
    assert env.c.get_deal("1")["held_alive"] is True
    for k in range(2):
        read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 4000 + k * C)
    assert money(env)["released"] == PRICE


def test_r6b_buyer_shown_live_then_seller_once_then_withdrawn_refunds_the_buyer(env):
    # README table: "the register showed the buyer holding the claim live ... at any reading from the
    # first sighting on" -> seller. The reading at T0+1000 did show that; one seller look resets it.
    ready(env)
    read(env, state(BUY_H, "Pending"), T0 + 1000)
    read(env, state(SELLER_NAME, "Pending"), T0 + 1300)
    for k in range(3):
        read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 2000 + k * C)
    assert money(env)["refunded"] == PRICE and claim(env, env.seller) == 0


def test_r6c_withdrawn_shown_first_then_unclear_at_the_confirming_reading_goes_to_the_split(env):
    ready(env)
    read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 1000)
    read(env, state(BUY_H, "Transferred"), T0 + 1000 + C)  # transfer_status UNCLEAR
    for k in range(2):
        read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 3000 + k * C)
    assert env.c.get_deal("1")["decision"]["confirmed"] is None
    env.vm.warp(iso(ALLOWANCE_BY + GRACE))
    env.c.settle("1")
    assert money(env)["released"] == PRICE * 7000 // 10000  # vs a full refund when the order is the other way round


# ------------------------------------------------ 7. the ordering guard


def test_r7_a_later_stamped_reading_processed_first_voids_the_grace_for_an_earlier_one(env):
    ready(env)
    read(env, state(BUY_H), TRANSFER_BY - C - 10)  # first sighting
    read(env, state(BUY_H), TRANSFER_BY + 5)  # stamped after the cut-off, processed first
    r = read(env, state(BUY_H), TRANSFER_BY - 5)  # stamped before the cut-off: IGNORED
    assert r["deal"]["transfer"]["confirmed_at"] == 0 and r["deal"]["log"][-1]["what"] == "IGNORED"
    env.vm.warp(iso(TRANSFER_BY + GRACE))
    env.c.settle("1")
    assert money(env)["refunded"] == PRICE


def test_r7b_a_settle_in_between_does_not_void_the_grace(env):
    ready(env)
    read(env, state(BUY_H), TRANSFER_BY - C - 10)
    env.vm.warp(iso(TRANSFER_BY + 5))
    env.c.settle("1")
    r = read(env, state(BUY_H), TRANSFER_BY - 5)
    assert r["deal"]["transfer"]["confirmed_at"] == TRANSFER_BY - 5


def test_r7c_no_reading_does_not_move_last_read(env):
    ready(env)
    read(env, state(BUY_H), T0 + 1000)
    read(env, (page(BUY_H), answer(BUY_H, page_kind="other")), T0 + 9000)  # NO_READING, later stamp
    r = read(env, state(BUY_H), T0 + 1000 + C)
    assert r["deal"]["transfer"]["confirmed_at"] == T0 + 1000 + C


# ------------------------------------------------ 8. money: random sequences


def test_r8_random_sequences_reconcile_and_bound_the_seller(env, mod):
    rnd = random.Random(20261118)
    t = {"buyer_name": BUYER_NAME, "seller_name": SELLER_NAME, "face_amount": FACE, "rate_bp": RATE, "units_per_gen": UPG,
         "upfront_bp": 5000, "no_decision_seller_bp": 7000, "confirm_seconds": C, "accept_by": T0 + 3600,
         "transfer_by": TRANSFER_BY, "allowance_by": ALLOWANCE_BY, "currency": "USD"}
    holders, statuses = ("BUYER", "SELLER", "OTHER"), ("PENDING", "ALLOWED", "DISALLOWED", "WITHDRAWN", "UNCLEAR")
    bad = []
    for n in range(4000):
        t["upfront_bp"] = rnd.choice((0, 2500, 5000, 6000, 10000))
        price = mod._price(t)
        s = mod._new_state(T0)
        s.update(state="ACTIVE", accepted_at=T0 + 300, escrow=price, left=price, t=T0 + 300)
        gifts, now, ups, buyer_gift = 0, T0 + 300, 0, False
        for _ in range(rnd.randint(1, 14)):
            if s["state"] != "ACTIVE":
                break
            now += rnd.choice((60, 300, C, C + 1, 2 * C, 3600, 4 * 3600))
            at = now - rnd.choice((0, 0, 0, 5, C))  # some stamps run back
            pays = []
            s["t"] = max(s["t"], now)
            mod._apply_deadlines(t, s, s["t"], pays)
            kind = rnd.random()
            if s["state"] == "ACTIVE" and kind < 0.08 and s["left"] > 0:
                amt = rnd.randint(1, s["left"])
                mod._pay(s, pays, "seller", amt, "gift")
                gifts += amt
            elif s["state"] == "ACTIVE" and kind < 0.14 and s["left"] > 0:
                mod._pay(s, pays, "buyer", rnd.randint(1, s["left"]), "gift")
                buyer_gift = True
            elif s["state"] == "ACTIVE":
                st = rnd.choice(statuses)
                amt = rnd.choice((400_000, 1_000_000, 1_250_000, 2_000_000)) if st == "ALLOWED" else 0
                mod._apply_reading(t, s, {"kind": "READ", "holder": rnd.choice(holders), "status": st, "amount": amt}, at, pays)
            if s["state"] == "ACTIVE" and s["left"] == 0:
                s["state"] = "SETTLED"
            ups = sum(1 for e in s["log"] if e["what"] in ("UPFRONT_LATE",)) + (1 if s["upfront_paid"] and s["transfer_status"] in ("PENDING", "ALLOWED") else 0)
            if s["escrow"] != s["left"] + s["released"] + s["refunded"] or s["left"] < 0 or ups > 1:
                bad.append(("reconcile", n, s["log"][-3:]))
            decided = s["decision"] is not None or "split" in s["settled_reason"]
            if not decided and s["released"] > mod._upfront(t) + gifts:
                bad.append(("seller over upfront+gifts", n, s["released"], s["log"][-4:]))
            if s["decision"] and s["decision"]["status"] == "ALLOWED":
                due = mod._price_for(t, s["decision"]["amount"])
                before = s["released"] - s["paid_at_decision"]
                want = max(0, due - before)
                if s["paid_at_decision"] > want or (not buyer_gift and s["paid_at_decision"] != want):
                    bad.append(("allowed short", n, due, before, s["paid_at_decision"], s["log"][-8:]))
    assert bad == []


# ------------------------------------------- 9. next-line qualifier: blank lines


def test_r9_a_qualifier_after_one_blank_line_is_seen(env, mod):
    pg = demo(BUY_H, "Allowed", "$1,250,000.00").replace("Status: Allowed\n", "Status: Allowed\n\n(for voting purposes only)\n")
    assert interp(mod, pg, body(BUY_H, "Allowed", "$1,250,000.00")) == AMBIG


def test_r9b_a_qualifier_after_two_blank_lines_is_seen(env, mod):
    pg = demo(BUY_H, "Allowed", "$1,250,000.00").replace("Status: Allowed\n", "Status: Allowed\n\n\n(for voting purposes only)\n")
    assert interp(mod, pg, body(BUY_H, "Allowed", "$1,250,000.00")) == AMBIG


def test_r9c_whitespace_only_lines_count_as_blank(env, mod):
    pg = demo(BUY_H, "Allowed", "$1,250,000.00").replace("Status: Allowed\n", "Status: Allowed\n \n\u00a0\n\t\n(for voting purposes only)\n")
    assert interp(mod, pg, body(BUY_H, "Allowed", "$1,250,000.00")) == AMBIG


# --------------------------------------- 10. late upfront at an ALLOWED reading


def test_r10_late_upfront_at_a_small_allowed_amount_is_capped(env):
    _unclear_transfer(env)
    a = "$200,000.00"  # price for $200,000 = 1.2 GEN < upfront 3.75 GEN
    read(env, state(BUY_H, "Allowed", a), T0 + 3000)
    read(env, state(BUY_H, "Pending"), T0 + 3000 + C)  # live, but a different status: the decision restarts
    small = 200_000 * RATE * G // (10000 * UPG)
    assert money(env)["released"] == UP  # the late upfront is computed from the LAST reading (Pending): full UP
    assert UP > small


def test_r10b_late_upfront_run_survives_nothing_but_live_readings(env):
    _unclear_transfer(env)
    read(env, state(BUY_H, "Pending"), T0 + 3000)
    read(env, state(BUY_H, "Transferred"), T0 + 3300)  # not live: the run restarts
    read(env, state(BUY_H, "Pending"), T0 + 3000 + C)
    assert money(env)["released"] == 0


# --------------------------------- gaps the review's hand mutants found (S-6)


def test_s6_a_second_label_line_written_with_equals_refuses_the_page(env, mod):
    pg = demo(BUY_H, "Pending").replace("Last updated", "Status = Withdrawn\nLast updated")
    assert interp(mod, pg, body(BUY_H, "Pending")) == AMBIG


def test_s6_a_bracket_line_after_a_field_qualifies_it(env, mod):
    pg = demo(BUY_H, "Pending").replace("Status: Pending\n", "Status: Pending\n(see Docket No. 812)\n")
    assert interp(mod, pg, body(BUY_H, "Pending")) == AMBIG


def test_s6_the_line_after_the_amount_can_qualify_it(env, mod):
    pg = demo(BUY_H, "Allowed", "$1,250,000.00").replace("Allowed amount: $1,250,000.00\n", "Allowed amount: $1,250,000.00\nreserved pending appeal\n")
    assert interp(mod, pg, body(BUY_H, "Allowed", "$1,250,000.00")) == AMBIG


def test_s6_reserved_is_a_qualifier(env, mod):
    pg = demo(BUY_H, "Pending").replace("Status: Pending\n", "Status: Pending\nRights reserved by the debtor\n")
    assert interp(mod, pg, body(BUY_H, "Pending")) == AMBIG


def test_s6_a_late_upfront_that_empties_the_escrow_settles_the_deal(env):
    offer(env, upfront_bp=10000)
    read(env, state(), T0 + 120)
    assert accept(env)["ok"]
    read(env, state(BUY_H, "Pending"), T0 + 1000)
    read(env, state(BUY_H, "Transferred"), T0 + 1000 + C)  # confirmed while unclear: nothing released
    read(env, state(BUY_H, "Pending"), T0 + 3000)
    r = read(env, state(BUY_H, "Pending"), T0 + 3000 + C)
    assert r["deal"]["state"] == "SETTLED" and money(env)["released"] == PRICE


def test_s6_a_late_upfront_at_an_allowed_reading_is_capped_at_the_price_for_it(env):
    _unclear_transfer(env)
    a = "$200,000.00"  # price 1.2 GEN, below the 3.75 GEN upfront
    small = 200_000 * RATE * G // (10000 * UPG)
    read(env, state(BUY_H, "Allowed", a), T0 + 3000)
    read(env, state(BUY_H, "Allowed", a), T0 + 3000 + C)
    assert money(env)["released"] == small
