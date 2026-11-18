"""Regression tests for the weak points found by the independent review of
18 Nov 2026 (blockers B1 and B2, should-fix S1 to S4 and S8, and the nits
that changed code). Every case, debtor, creditor and agent here is
fictional.
"""

import json
import re

import pytest

from tests.direct.test_claim_escrow import (  # noqa: F401
    env, mod, iso, offer, read, accept, ready, money, claim, transfer, decide, state, page, answer, leader_then,
    T0, C, G, PRICE, UP, URL, PROMPT, GRACE, TRANSFER_BY, ALLOWANCE_BY, SELLER_NAME, BUYER_NAME, BUY_H, DEBTOR,
)


def nr(r, reason):
    assert r["reading"]["kind"] == "NO_READING" and r["reading"]["reason"] == reason, r["reading"]


# ------------------------------------------- B1: withdrawn before the transfer showed


def test_withdrawn_before_the_buyer_held_it_live_refunds_the_buyer(env):
    ready(env)
    for k in range(3):
        read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 1000 + k * C)
    d = env.c.get_deal("1")
    assert d["state"] == "SETTLED" and "before the buyer was shown holding it live" in d["settled_reason"], d["settled_reason"]
    m = money(env)
    assert m["released"] == 0 and m["refunded"] == PRICE and claim(env, env.buyer) == PRICE and claim(env, env.seller) == 0
    assert d["held_alive"] is False


def test_withdrawn_after_the_buyer_held_it_live_pays_the_seller(env):
    ready(env)
    transfer(env)  # confirmed while Pending
    assert env.c.get_deal("1")["held_alive"] is True
    decide(env, "Withdrawn by claimant")
    assert money(env)["released"] == PRICE


def test_live_hold_seen_after_a_withdrawn_transfer_counts(env):
    ready(env)
    read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 1000)
    read(env, state(BUY_H, "Withdrawn by claimant"), T0 + 1000 + C)  # transfer confirmed, no upfront
    assert money(env)["released"] == 0 and env.c.get_deal("1")["held_alive"] is False
    read(env, state(BUY_H, "Pending"), T0 + 1000 + 2 * C)  # the agent shows the claim live with the buyer
    assert env.c.get_deal("1")["held_alive"] is True


# ----------------------------------------------- B2: labels inside longer labels


def interp(mod, pg, ans):
    t = {"buyer_name": BUYER_NAME, "seller_name": SELLER_NAME, "debtor_name": DEBTOR, "claim_number": "1042", "currency": "USD"}
    return mod._interpret(t, json.loads(ans.strip("`").replace("json\n", "", 1)), pg)


@pytest.mark.parametrize("extra,field,copy", [
    ("Voting status: Allowed", "status", {"label": "Status", "value": "Allowed"}),
    ("Objection status: Withdrawn", "status", {"label": "Status", "value": "Withdrawn"}),
    (f"Original creditor: {SELLER_NAME}", "holder", {"label": "Creditor", "value": SELLER_NAME}),
])
def test_label_inside_a_longer_label_is_not_anchored(env, mod, extra, field, copy):
    pg = page(BUY_H, "Allowed for voting purposes only", "", extra)
    body = json.loads(answer(BUY_H, "Allowed for voting purposes only", "", wrap=False))
    body[field] = copy
    if field == "holder":
        pg = pg.replace(f"Creditor: {BUY_H}\n", "")  # only the original creditor line names the seller
    r = interp(mod, pg, json.dumps(body))
    assert r == {"kind": "NO_READING", "reason": "N2_NOT_ANCHORED"}, r


def test_amount_inside_a_longer_label_is_not_anchored(env, mod):
    pg = page(BUY_H, "Allowed", "", "Previously allowed amount: $1,250,000.00").replace("Allowed amount: -\n", "")
    ans = answer(BUY_H, "Allowed", "$1,250,000.00")
    assert interp(mod, pg, ans) == {"kind": "NO_READING", "reason": "N2_NOT_ANCHORED"}


@pytest.mark.parametrize("line", ["Status: Pending", "  Status: Pending", "• Status: Pending", "* Status: Pending", "| Status | Pending |", "Status\nPending"])
def test_label_at_the_start_of_its_line_anchors(env, mod, line):
    pl = mod._page_lines("Claim No. 1042\n" + line + "\nEnd")
    assert mod._line_anchored(pl, "status", "pending") is not None


def test_value_two_lines_below_does_not_anchor(env, mod):
    pl = mod._page_lines("Status\n\nPending")
    assert mod._line_anchored(pl, "status", "pending") is None


# ---------------------------------------------- S1: the seller as holder again
# (the twice-seen rule and the allowance_by cut-off are in test_claim_escrow.py)


# ------------------------------------------------ S2: the reading's own stamp


def test_reading_stamped_before_transfer_by_counts_after_a_later_write(env):
    ready(env)
    h = BUY_H
    read(env, state(h), TRANSFER_BY - C - 10)
    env.vm.warp(iso(TRANSFER_BY + 5))
    env.c.settle("1")  # the deal clock moves past transfer_by
    read(env, state(h), TRANSFER_BY - 5)  # stamped before transfer_by, processed later
    d = env.c.get_deal("1")
    assert d["transfer"]["confirmed_at"] == TRANSFER_BY - 5 and money(env)["released"] == UP
    assert d["clock"] == TRANSFER_BY + 5  # the clock never ran backwards


def test_reading_stamped_after_transfer_by_does_not_confirm(env):
    ready(env)
    read(env, state(BUY_H), TRANSFER_BY - C)
    read(env, state(BUY_H), TRANSFER_BY + 1)
    assert env.c.get_deal("1")["transfer"]["confirmed_at"] == 0
    env.vm.warp(iso(TRANSFER_BY + GRACE))
    env.c.settle("1")
    assert money(env)["refunded"] == PRICE


def test_an_older_stamp_never_confirms(env):
    ready(env)
    read(env, state(BUY_H), T0 + 5000)
    read(env, state(BUY_H), T0 + 5000 - C)  # processed second, stamped earlier
    assert env.c.get_deal("1")["transfer"]["confirmed_at"] == 0


# --------------------------------------- S3: the words after "as transferee of"


@pytest.mark.parametrize("holder,cls", [
    (f"{BUYER_NAME} as transferee of {SELLER_NAME}", "BUYER"),
    (f"{BUYER_NAME} (as transferee of {SELLER_NAME})", "BUYER"),
    (f"{BUYER_NAME} as transferee of {SELLER_NAME} (partial: $125,000.00)", "OTHER"),
    (f"{BUYER_NAME} as transferee of Someone Else Ltd", "OTHER"),
    (f"{SELLER_NAME} as transferee of {BUYER_NAME}", "SELLER"),
    (f"{SELLER_NAME} as transferee of Someone Else Ltd", "OTHER"),
])
def test_transferee_names_both_parties_exactly(env, mod, holder, cls):
    assert mod._holder_class(holder, {"buyer_name": BUYER_NAME, "seller_name": SELLER_NAME}) == cls


# ----------------------------------------------------- S4: no query string


def test_register_url_with_a_query_string_is_refused(env):
    with pytest.raises(Exception, match=r"\? or #"):
        offer(env, register_url="https://claims.example.org/out?to=https://elsewhere.example.com/claim/1042")


# --------------------------------------------------------------- S8 tests


def test_validator_rejects_another_no_reading_reason(env):
    leader_then(env, state(), (page(), answer(page_kind="other")))
    assert env.vm.run_validator(leader_result={"kind": "NO_READING", "reason": "N2_LABEL"}) is False
    assert env.vm.run_validator(leader_result={"kind": "NO_READING", "reason": "N1_WRONG_PAGE"}) is True


@pytest.mark.parametrize("bad", [
    {"kind": "READ", "holder": "BUYER", "status": "PENDING", "amount": 5},  # an amount without ALLOWED
    {"kind": "READ", "holder": "BUYER", "status": "DISALLOWED", "amount": 5},
    {"kind": "READ", "holder": "NOBODY", "status": "PENDING", "amount": 0},
    {"kind": "NO_READING", "reason": "N9_MADE_UP"},
    {"kind": "READ", "holder": "BUYER", "status": "ALLOWED", "amount": 10**16 + 1},
])
def test_check_outcome_rejects(env, mod, bad):
    with pytest.raises(Exception):
        mod._check_outcome(bad)


def test_second_accept_on_an_active_deal_is_refused_and_credited_back(env):
    ready(env)
    r = accept(env, at=T0 + 400)
    assert r["ok"] is False and "ACTIVE" in r["error"] and r["refunded"] == str(PRICE)
    assert claim(env, env.buyer) == PRICE and money(env)["escrow"] == PRICE


def test_withdraw_partial_and_bad_amounts(env):
    ready(env)
    env.vm.warp(iso(TRANSFER_BY + GRACE))
    env.c.settle("1")
    env.vm.sender = env.buyer
    assert env.c.withdraw(G)["left"] == str(PRICE - G)
    for bad in (PRICE, -1, True):
        with pytest.raises(Exception):
            env.c.withdraw(bad)
    assert env.c.withdraw(0)["amount"] == str(PRICE - G)


def test_seller_refund_then_decision_records_what_was_paid(env):
    ready(env)
    transfer(env)
    env.vm.sender = env.seller
    env.c.refund("1", G)
    decide(env, "Allowed", "$1,250,000.00")
    m = money(env)
    assert m["final_due"] == PRICE - UP and m["paid_at_decision"] == PRICE - UP - G
    assert m["released"] == PRICE - G and m["refunded"] == G and m["left"] == 0


# ------------------------------------------------------------------- nits


@pytest.mark.parametrize("text", ["Claim No. 1042.1", "Claim No. 1042/2", "Claim 2/1042", "Claim 3.1042"])
def test_claim_number_inside_a_dotted_or_slashed_number_does_not_match(env, mod, text):
    assert not mod._claim_number_on_page(mod._norm(text), "1042")


@pytest.mark.parametrize("text", ["Claim No. 1042.", "Claim No. 1042, filed", "Claim (1042)", "Claim #1042"])
def test_claim_number_at_a_sentence_end_matches(env, mod, text):
    assert mod._claim_number_on_page(mod._norm(text), "1042")


@pytest.mark.parametrize("text,refused", [
    ("See Docket Nos. 12,15 and 18", False),
    ("Agent server 192.168.100.200", False),
    ("Note 4, 5 and 7", False),
    ("Allowed amount: $1.250.000,00", True),
    ("Paid 12,5 per cent", True),
])
def test_decimal_comma_scan_skips_references_and_addresses(env, mod, text, refused):
    assert mod._decimal_comma_page(text) is refused


def test_upfront_of_everything_closes_the_deal(env):
    offer(env, upfront_bp=10000)
    read(env, state(), T0 + 120)
    accept(env)
    transfer(env)
    d = env.c.get_deal("1")
    assert d["state"] == "SETTLED" and money(env)["released"] == PRICE and "nothing left" in d["settled_reason"]


def test_stale_baseline_is_refused_at_accept(env):
    offer(env)
    read(env, state(), T0 + 60)
    r = accept(env, at=T0 + 60 + 3 * C + 1)
    assert r["ok"] is False and "older than 3 confirmation periods" in r["error"] and r["refunded"] == str(PRICE)
    read(env, state(), T0 + 60 + 3 * C + 2)
    assert accept(env, at=T0 + 60 + 3 * C + 3)["ok"] is True


def test_page_cut_keeps_only_whole_lines(env, mod):
    text = "Claim No.: 1042\n" + "x" * (mod.PAGE_CHARS - 40) + "\nStatus: Allowed for voting purposes only\n"
    cut = mod._clean_page(text)
    assert cut.endswith("x\n(cut)") and "Status" not in cut  # never 'Status: Allowed' cut out of a longer phrase


# ------------------------------------------- gaps the mutation run found (v2)


def test_seller_confirmed_again_blocks_a_decision_until_the_buyer_is_confirmed_back(env):
    ready(env)
    transfer(env)
    t = T0 + 5000
    read(env, state(BUY_H, "Allowed", "$1,250,000.00"), t)  # the decision is first seen with the buyer
    read(env, state(SELLER_NAME, "Allowed", "$1,250,000.00"), t + C)
    read(env, state(SELLER_NAME, "Allowed", "$1,250,000.00"), t + 2 * C)  # the seller is confirmed as holder again
    assert env.c.get_deal("1")["held_by"] == "SELLER"
    read(env, state(BUY_H, "Allowed", "$1,250,000.00"), t + 3 * C)  # one look at the buyer does not undo it
    assert env.c.get_deal("1")["state"] == "ACTIVE"
    r = read(env, state(BUY_H, "Allowed", "$1,250,000.00"), t + 4 * C)
    assert r["deal"]["held_by"] == "BUYER" and r["deal"]["state"] == "SETTLED" and money(env)["released"] == PRICE


def test_two_looks_at_the_seller_less_than_confirm_seconds_apart_change_nothing(env):
    ready(env)
    transfer(env)
    read(env, state(SELLER_NAME), T0 + 5000)
    read(env, state(SELLER_NAME), T0 + 5000 + C - 1)
    assert env.c.get_deal("1")["held_by"] == "BUYER"


@pytest.mark.parametrize("text,label,value", [
    ("Status: Not allowed", "status", "allowed"),  # words between the label and the copy
    ("Status: see note 4: Pending", "status", "pending"),
    ("Statuses: Pending", "status", "es: pending"),  # the label runs on into another word
])
def test_more_lines_that_do_not_anchor(env, mod, text, label, value):
    assert mod._line_anchored(mod._page_lines(text), label, value) is None


def test_dot_thousands_with_a_three_digit_comma_tail_is_decimal_comma(env, mod):
    assert mod._decimal_comma_page("Total 1.234,567")


def test_commit_refuses_money_that_does_not_add_up(env):
    ready(env)
    env.vm.sender = env.anyone
    d, t, s = env.c._load("1")
    held = s["left"]
    s["left"] -= 1  # one wei lost and paid to nobody
    with pytest.raises(Exception, match="money does not add up"):
        env.c._commit(d, s, held, 0, [])
    d, t, s = env.c._load("1")
    s["escrow"] += 1  # the deal's own books do not reconcile
    with pytest.raises(Exception, match="escrow does not reconcile"):
        env.c._commit(d, s, s["left"], 0, [])
