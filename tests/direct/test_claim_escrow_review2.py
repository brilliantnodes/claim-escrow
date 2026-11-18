"""Regression tests for the weak points found by the second independent
review of 18 Nov 2026 (blocker X1, should-fix S-1 to S-4, the ordering and
dash nits). Every case, debtor, creditor and agent here is fictional.
"""

import json

import pytest

from tests.direct.test_claim_escrow import (  # noqa: F401
    env, mod, iso, offer, read, accept, ready, money, claim, transfer, decide, state, page, answer,
    T0, C, G, PRICE, UP, URL, PROMPT, GRACE, TRANSFER_BY, ALLOWANCE_BY, SELLER_NAME, BUYER_NAME, BUY_H, DEBTOR,
)

TERMS = {"buyer_name": BUYER_NAME, "seller_name": SELLER_NAME, "debtor_name": DEBTOR, "claim_number": "1042", "currency": "USD"}


def interp(mod, pg, body):
    return mod._interpret(TERMS, body, pg)


def body(holder=SELLER_NAME, status="Pending", allowed="", **over):
    return json.loads(answer(holder, status, allowed, wrap=False, **over))


AMBIG = {"kind": "NO_READING", "reason": "N2_AMBIGUOUS"}


# ------------------------------------------- X1: the first live sighting counts


def test_buyer_shown_live_at_the_first_sighting_then_withdrawn_pays_the_seller(env):
    ready(env)
    read(env, state(BUY_H, "Pending"), T0 + 1000)  # the buyer shown holding it live
    assert env.c.get_deal("1")["held_alive"] is True
    read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 1000 + C)  # transfer confirmed, status WITHDRAWN
    read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 1000 + 2 * C)
    d = env.c.get_deal("1")
    assert d["state"] == "SETTLED" and d["settled_reason"] == "claim withdrawn after the transfer"
    assert money(env)["released"] == PRICE and claim(env, env.seller) == PRICE


def test_a_live_sighting_that_is_not_sustained_does_not_count(env):
    ready(env)
    read(env, state(BUY_H, "Pending"), T0 + 1000)
    read(env, state(SELLER_NAME, "Pending"), T0 + 1300)  # the transfer sighting restarts
    assert env.c.get_deal("1")["held_alive"] is False
    for k in range(3):
        read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 2000 + k * C)
    assert money(env)["refunded"] == PRICE  # withdrawn before the buyer was shown holding it live, as in B1


@pytest.mark.parametrize("live_status", ["Transferred", "Pending (transferred)", "Active"])
def test_withdrawal_after_an_unclear_transfer_decides_nothing(env, live_status):
    ready(env)
    transfer(env, status=live_status)
    d = env.c.get_deal("1")
    assert d["transfer"]["status"] == "UNCLEAR" and d["held_alive"] is False and money(env)["released"] == 0
    decide(env, "Withdrawn by claimant", t1=T0 + 9000)
    d = env.c.get_deal("1")
    assert d["state"] == "ACTIVE" and d["decision"]["first_seen"] is None  # nobody can tell who withdrew it
    env.vm.warp(iso(ALLOWANCE_BY + GRACE))
    env.c.settle("1")
    m = money(env)
    assert m["released"] == PRICE * 7000 // 10000 and m["refunded"] == PRICE - PRICE * 7000 // 10000  # the agreed split


def test_em_dash_status_is_pending(env, mod):
    assert interp(mod, page(BUY_H, "Filed — Pending"), body(BUY_H, "Filed — Pending"))["status"] == "PENDING"


# ------------------------------------------ S-4: an upfront released later


def test_upfront_released_late_once_the_buyer_is_seen_live_twice(env):
    ready(env)
    read(env, state(BUY_H, "Pending"), T0 + 1000)
    read(env, state(BUY_H, "Transferred"), T0 + 1000 + C)  # confirmed while unclear: no upfront yet
    assert money(env)["released"] == 0
    read(env, state(BUY_H, "Pending"), T0 + 3000)
    assert money(env)["released"] == 0  # one look
    read(env, state(BUY_H, "Pending"), T0 + 3000 + C)
    assert money(env)["released"] == UP
    read(env, state(BUY_H, "Pending"), T0 + 3000 + 2 * C)
    assert money(env)["released"] == UP  # once only


def test_no_late_upfront_on_two_looks_closer_than_confirm_seconds(env):
    ready(env)
    read(env, state(BUY_H, "Pending"), T0 + 1000)
    read(env, state(BUY_H, "Transferred"), T0 + 1000 + C)
    read(env, state(BUY_H, "Pending"), T0 + 3000)
    read(env, state(BUY_H, "Pending"), T0 + 3000 + C - 1)
    assert money(env)["released"] == 0


def test_no_late_upfront_after_allowance_by(env):
    ready(env)
    read(env, state(BUY_H, "Pending"), T0 + 1000)
    read(env, state(BUY_H, "Transferred"), T0 + 1000 + C)
    read(env, state(BUY_H, "Pending"), ALLOWANCE_BY - 10)
    read(env, state(BUY_H, "Pending"), ALLOWANCE_BY - 10 + C)
    assert money(env)["released"] == 0


# ---------------------------------------------------- S-1: whole lines only


def test_a_cut_status_phrase_is_never_read(env, mod):
    head = page(BUY_H, "Pending", "$1,250,000.00").replace("Status: Pending\n", "")
    pre = head + "\nNotes: "
    full = pre + "x" * (mod.PAGE_CHARS - len(pre) - len("\nStatus: Allowed")) + "\nStatus: Allowed for voting purposes only"
    cut = mod._clean_page(full)
    assert "Status: Allowed" not in cut
    assert interp(mod, cut, body(BUY_H, "Allowed", "$1,250,000.00"))["kind"] == "NO_READING"


def test_a_cut_holder_note_is_never_read(env, mod):
    pre = f"Claims Register {DEBTOR}\nClaim No. 1042\nStatus: Pending\nAllowed amount: -\nNotes: "
    line = f"\nCreditor: {BUY_H}"
    full = pre + "x" * (mod.PAGE_CHARS - len(pre) - len(line)) + line + " (partial: $125,000.00)"
    assert "Creditor" not in mod._clean_page(full)


# --------------------------------------- S-2: one line per field, and only one


def test_a_second_status_line_is_ambiguous(env, mod):
    pg = page(BUY_H, "Pending", "", "Objection (Docket No. 812)\nStatus: Withdrawn")
    assert interp(mod, pg, body(BUY_H, "Withdrawn")) == AMBIG
    assert interp(mod, pg, body(BUY_H, "Pending")) == AMBIG


def test_a_second_creditor_line_is_ambiguous(env, mod):
    pg = page(SELLER_NAME, "Pending", "", f"Notice address:\nc/o Treasury Dept\nCreditor: {BUYER_NAME}\n100 Main St")
    assert interp(mod, pg, body(BUYER_NAME, "Pending")) == AMBIG
    assert interp(mod, pg, body(SELLER_NAME, "Pending")) == AMBIG


def test_a_filter_sidebar_label_alone_on_its_line_is_ambiguous(env, mod):
    pg = "Filter by\nStatus\nAllowed\nDisallowed\n" + page(BUY_H, "Pending")
    assert interp(mod, pg, body(BUY_H, "Pending")) == AMBIG


def test_a_second_allowed_amount_line_is_ambiguous(env, mod):
    pg = page(BUY_H, "Allowed", "$1,250,000.00", "Allowed amount: $900,000.00")
    assert interp(mod, pg, body(BUY_H, "Allowed", "$1,250,000.00")) == AMBIG


def test_longer_labels_that_only_start_alike_are_not_counted(env, mod):
    pg = page(BUY_H, "Pending", "", "Claim status history: Filed 2026-09-14")
    assert interp(mod, pg, body(BUY_H, "Pending"))["kind"] == "READ"


# --------------------------------------------- S-3: qualifiers next to a field


@pytest.mark.parametrize("extra_after,field", [
    ("(for voting purposes only)", "Status"),
    ("Subject to objection (Docket No. 812)", "Status"),
    ("as transferee of Someone Else Ltd", "Creditor"),
    ("(partial: $125,000.00)", "Creditor"),
])
def test_a_qualifier_on_the_next_line_is_ambiguous(env, mod, extra_after, field):
    holder = BUYER_NAME if field == "Creditor" else BUY_H
    pg = page(holder, "Allowed", "$1,250,000.00")
    line = f"{field}: {holder}" if field == "Creditor" else "Status: Allowed"
    pg = pg.replace(line + "\n", line + "\n" + extra_after + "\n")
    assert interp(mod, pg, body(holder, "Allowed", "$1,250,000.00")) == AMBIG


def test_a_partial_transfer_anywhere_on_the_page_is_ambiguous(env, mod):
    pg = page(BUY_H, "Pending", "", "Transfer note: partial transfer of $125,000.00 of $1,250,000.00 (Docket No. 977)")
    assert interp(mod, pg, body(BUY_H, "Pending")) == AMBIG


def test_the_model_does_not_judge_qualifications(env, mod):
    # review 3, B-1: the model's own "qualified" judgment made a validator disagree live; code decides alone
    assert interp(mod, page(BUY_H, "Pending"), body(BUY_H, "Pending", qualified="yes"))["kind"] == "READ"


def test_a_numbered_prefix_does_not_start_a_label(env, mod):
    assert mod._line_anchored(mod._page_lines("1. Status: Pending"), "status", "pending") is None


# -------------------------------------------- ordering: stamps never run back


def test_a_reading_stamped_before_accept_is_ignored(env):
    ready(env)  # accepted at T0 + 300
    read(env, state(BUY_H), T0 + 200)
    r = read(env, state(BUY_H), T0 + 200 + C)
    assert r["deal"]["transfer"]["first_seen"] == T0 + 200 + C and r["deal"]["transfer"]["confirmed_at"] == 0


def test_an_older_stamp_processed_later_is_ignored(env):
    ready(env)
    x = T0 + 1000 + C
    read(env, state(BUY_H, "Pending"), T0 + 1000)
    read(env, state(BUY_H, "Pending"), x)  # transfer confirmed at x
    read(env, state(BUY_H, "Allowed", "$1,250,000.00"), x - C)  # older stamp, processed later: ignored
    r = read(env, state(BUY_H, "Allowed", "$1,250,000.00"), x)
    assert r["deal"]["state"] == "ACTIVE" and r["deal"]["decision"]["first_seen"]["at"] == x
    assert any(e["what"] == "IGNORED" for e in r["deal"]["log"])
