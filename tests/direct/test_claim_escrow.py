"""Direct-mode tests for ClaimEscrow. Web pages and the LLM are mocked.

Every case, debtor, creditor and agent here is fictional.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

import pytest

from tests.direct.conftest import to_hex

CONTRACT = os.environ.get("CE_CONTRACT", "contracts/claim_escrow.py")  # mutation runs point elsewhere
HOST = "claims.example.org"
URL = f"https://{HOST}/case/26-10432/claim/1042"
PROMPT = r"(?s).*claims register.*"
G = 10**18
C = 600  # confirm_seconds

T0 = int(datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc).timestamp())
ACCEPT_BY = T0 + 3600
TRANSFER_BY = ACCEPT_BY + 4 * 3600
ALLOWANCE_BY = TRANSFER_BY + 8 * 3600
GRACE = 1800

SELLER_NAME = "Quenby Tool & Die LLC"
BUYER_NAME = "Harrowfield Credit Partners LP"
DEBTOR = "Pellmoor Freight Lines, Inc."

# face 1,250,000 USD at 60% = 750,000 USD; 100,000 USD per GEN -> 7.5 GEN; upfront 50% = 3.75 GEN
FACE, RATE, UPG, UPFRONT = 1_250_000, 6000, 100_000, 5000
PRICE = FACE * RATE * G // (10000 * UPG)
UP = PRICE * UPFRONT // 10000


def iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def page(holder=SELLER_NAME, status="Pending", allowed="", extra=""):
    return f"""Marrowgate Restructuring Agents - Claims Register
Case: {DEBTOR} (Case No. 26-10432)
Claim No. 1042
Creditor: {holder}
Date filed: 2026-09-14
Claim amount: $1,250,000.00
Status: {status}
Allowed amount: {allowed or "-"}
{extra}"""


def answer(holder=SELLER_NAME, status="Pending", allowed="", wrap=True, **over):
    body = {
        "page_kind": "claim_entry",
        "debtor_name_on_page": DEBTOR,
        "claim_number_on_page": "1042",
        "other_claims_shown": "no",
        "more_than_one_holder": "no",
        "holder": {"label": "Creditor", "value": holder},
        "status": {"label": "Status", "value": status},
        "allowed_amount": {"label": "Allowed amount", "value": allowed} if allowed else {"label": "", "value": ""},
        "currency_on_page": "$" if allowed else "",
    }
    body.update(over)
    s = json.dumps(body)
    return "```json\n" + s + "\n```" if wrap else s


def state(holder=SELLER_NAME, status="Pending", allowed="", **over):
    """A matching (page, answer) pair."""
    return page(holder, status, allowed), answer(holder, status, allowed, **over)


@pytest.fixture
def env(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    direct_vm.warp(iso(T0))
    c = direct_deploy(CONTRACT, json.dumps([HOST, "register.example.net"]), C)

    class E:
        pass

    e = E()
    e.vm, e.c = direct_vm, c
    e.seller, e.buyer, e.anyone = direct_alice, direct_bob, direct_charlie
    return e


@pytest.fixture
def mod(env):
    for m in list(sys.modules.values()):
        if getattr(m, "ClaimEscrow", None) is not None and hasattr(m, "_interpret"):
            return m
    raise RuntimeError("contract module not found")


def terms(e, **over):
    t = dict(buyer=to_hex(e.buyer), buyer_name=BUYER_NAME, seller_name=SELLER_NAME, debtor_name=DEBTOR, claim_number="1042",
             register_url=URL, currency="USD", face_amount=FACE, rate_bp=RATE, units_per_gen=UPG, upfront_bp=UPFRONT,
             confirm_seconds=C, accept_by=ACCEPT_BY, transfer_by=TRANSFER_BY, allowance_by=ALLOWANCE_BY, no_decision_seller_bp=7000)
    t.update(over)
    return t


ORDER = ["buyer", "buyer_name", "seller_name", "debtor_name", "claim_number", "register_url", "currency", "face_amount", "rate_bp",
         "units_per_gen", "upfront_bp", "confirm_seconds", "accept_by", "transfer_by", "allowance_by", "no_decision_seller_bp"]


def offer(e, at=T0, **over):
    e.vm.warp(iso(at))
    e.vm.sender = e.seller
    t = terms(e, **over)
    return e.c.offer(*[t[k] for k in ORDER])


def read(e, st, at, did="1"):
    pg, ans = st
    e.vm.clear_mocks()
    e.vm.warp(iso(at))
    e.vm.sender = e.anyone
    e.vm.mock_web(re.escape(URL), {"status": 200, "body": pg})
    e.vm.mock_llm(PROMPT, ans)
    return e.c.read_register(did)


def accept(e, at=T0 + 300, value=None, digest=None, did="1", who=None):
    e.vm.warp(iso(at))
    e.vm.sender = who or e.buyer
    e.vm.value = PRICE if value is None else value
    try:
        return e.c.accept(did, digest if digest is not None else e.c.get_deal(did)["digest"])
    finally:
        e.vm.value = 0


def ready(e):
    """An offer with a good baseline, accepted."""
    offer(e)
    read(e, state(), T0 + 120)
    r = accept(e)
    assert r["ok"], r
    return r


def money(e, did="1"):
    m = e.c.get_deal(did)["money"]
    return {k: int(v) for k, v in m.items()}


def claim(e, who):
    return int(e.c.get_claimable(to_hex(who)))


def transfer(e, status="Pending", allowed="", t1=T0 + 1000):
    """Two readings C apart showing the buyer as holder."""
    h = f"{BUYER_NAME} as transferee of {SELLER_NAME}"
    read(e, state(h, status, allowed), t1)
    return read(e, state(h, status, allowed), t1 + C)


BUY_H = f"{BUYER_NAME} as transferee of {SELLER_NAME}"


# ------------------------------------------------------------- deployment


def test_rules(env):
    r = env.c.get_rules()
    assert r["register_hosts"] == ["claims.example.org", "register.example.net"] and r["min_confirm_seconds"] == C
    assert r["status_table"]["allowed"] == "ALLOWED" and "not allowed" not in r["status_table"]
    assert env.c.totals() == {"deals": 0, "locked": "0", "credited": "0"}


@pytest.mark.parametrize(
    "hosts,minc,needle",
    [
        ("claims.example.org", C, "JSON list"),
        ("[]", C, "1 to 8"),
        (json.dumps(["a.example.org"] * 2), C, "1 to 8 different"),
        (json.dumps(["Claims.Example.org"]), C, "lower-case"),
        (json.dumps(["localhost"]), C, "two labels"),
        (json.dumps(["claims.local"]), C, "public"),
        (json.dumps(["10.0.0.1"]), C, "public"),
        (json.dumps(["claims_example.org"]), C, "letters, digits"),
        (json.dumps(["claims.example.org"]), 59, "min_confirm_seconds"),
    ],
)
def test_constructor_refuses(direct_vm, direct_deploy, hosts, minc, needle):
    direct_vm.warp(iso(T0))
    with pytest.raises(Exception, match=re.escape(needle)):
        direct_deploy(CONTRACT, hosts, minc)


# ------------------------------------------------------------------ offer


def test_offer_freezes_terms(env):
    d = offer(env)
    assert d["id"] == "1" and d["state"] == "OFFERED" and d["seller"] == to_hex(env.seller) and d["buyer"] == to_hex(env.buyer)
    assert d["price"] == str(PRICE) and d["upfront"] == str(UP) and PRICE == 75 * G // 10
    t = d["terms"]
    canon = json.dumps(t, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert d["digest"] == hashlib.sha256(canon.encode()).hexdigest()
    assert env.c.get_deals_of(to_hex(env.seller)) == ["1"]
    assert env.c.get_deals_of(to_hex(env.buyer)) == []  # the buyer is indexed when it accepts: nobody can flood its list
    read(env, state(), T0 + 120)
    accept(env)
    assert env.c.get_deals_of(to_hex(env.buyer)) == ["1"]


@pytest.mark.parametrize(
    "over,needle",
    [
        (dict(buyer="nope"), "buyer must be an address"),
        (dict(buyer_name=""), "buyer_name is required"),
        (dict(seller_name="x" * 81), "at most 80"),
        (dict(debtor_name="---"), "letters or digits"),
        (dict(buyer_name=SELLER_NAME), "must differ"),
        (dict(buyer_name="Quenby Tool"), "neither may contain the other"),
        (dict(seller_name="Harrowfield Credit Partners LP Fund II"), "neither may contain the other"),
        (dict(claim_number=""), "claim_number"),
        (dict(claim_number="ABC"), "with a digit"),
        (dict(claim_number="10 42"), "claim_number"),
        (dict(claim_number="-1042"), "claim_number"),
        (dict(register_url="http://claims.example.org/c/1042"), "https://"),
        (dict(register_url="https://evil.example.com/c/1042"), "register hosts"),
        (dict(register_url="https://claims.example.org.evil.com/c/1042"), "register hosts"),
        (dict(register_url="https://user@claims.example.org/c/1042"), "user name"),
        (dict(register_url="https://claims.example.org:8443/c/1042"), "port"),
        (dict(register_url="https://claims.example.org/c/1042#x"), "#"),
        (dict(register_url="https://claims.example.org"), "claim's own page"),
        (dict(currency="XYZ"), "currency must be"),
        (dict(face_amount=0), "face_amount"),
        (dict(face_amount=10**15 + 1), "face_amount"),
        (dict(rate_bp=0), "rate_bp"),
        (dict(rate_bp=10001), "rate_bp"),
        (dict(units_per_gen=0), "units_per_gen"),
        (dict(upfront_bp=10001), "upfront_bp"),
        (dict(no_decision_seller_bp=-1), "no_decision_seller_bp"),
        (dict(confirm_seconds=C - 1), "confirm_seconds"),
        (dict(confirm_seconds=True), "confirm_seconds"),
        (dict(accept_by=T0), "accept_by must be in the future"),
        (dict(transfer_by=ACCEPT_BY + 2 * C - 1), "two confirmation periods after accept_by"),
        (dict(allowance_by=TRANSFER_BY + 2 * C - 1), "two confirmation periods after transfer_by"),
        (dict(allowance_by=T0 + 6 * 366 * 86400), "within five years"),
    ],
)
def test_offer_refuses_bad_terms(env, over, needle):
    with pytest.raises(Exception, match=re.escape(needle)):
        offer(env, **over)


def test_offer_to_self_refused(env):
    with pytest.raises(Exception, match="different addresses"):
        offer(env, buyer=to_hex(env.seller))


def test_cancel(env):
    offer(env)
    env.vm.sender = env.buyer
    with pytest.raises(Exception, match="only the seller"):
        env.c.cancel("1")
    env.vm.sender = env.seller
    assert env.c.cancel("1")["state"] == "CANCELLED"
    with pytest.raises(Exception, match="only an open offer"):
        env.c.cancel("1")


# ---------------------------------------------------------- baseline/accept


def test_accept_needs_a_good_baseline(env):
    offer(env)
    r = accept(env)
    assert r["ok"] is False and "baseline" in r["error"] and r["refunded"] == str(PRICE)
    assert claim(env, env.buyer) == PRICE
    read(env, state(), T0 + 120)
    assert env.c.get_deal("1")["baseline"]["status"] == "PENDING"
    r = accept(env, at=T0 + 200)
    assert r["ok"] and r["deal"]["state"] == "ACTIVE" and money(env)["left"] == PRICE
    assert env.c.totals() == {"deals": 1, "locked": str(PRICE), "credited": str(PRICE)}


@pytest.mark.parametrize(
    "st",
    [
        state(holder="Somebody Else Ltd"),
        state(holder=BUY_H),
        state(status="Disallowed"),
        state(status="Withdrawn"),
        state(status="Objection withdrawn"),
    ],
)
def test_bad_baselines(env, st):
    offer(env)
    read(env, st, T0 + 120)
    assert env.c.get_deal("1")["baseline"] is None
    assert accept(env)["ok"] is False


def test_allowed_baseline_is_good_and_a_later_bad_one_clears_it(env):
    offer(env)
    read(env, state(status="Allowed", allowed="$1,000,000.00"), T0 + 100)
    assert env.c.get_deal("1")["baseline"]["amount"] == 1_000_000
    read(env, state(holder="Somebody Else Ltd"), T0 + 200)
    assert env.c.get_deal("1")["baseline"] is None
    read(env, state(), T0 + 250)
    nr = read(env, (page(), "garbage"), T0 + 260)
    assert nr["reading"]["kind"] == "NO_READING" and env.c.get_deal("1")["baseline"] is not None  # a no-reading changes nothing


@pytest.mark.parametrize(
    "kw,needle",
    [
        (dict(value=PRICE - 1), "exactly the price"),
        (dict(value=PRICE + 1), "exactly the price"),
        (dict(digest="00" * 32), "terms_digest"),
        (dict(at=ACCEPT_BY), "EXPIRED"),
    ],
)
def test_accept_refusals_credit_back(env, kw, needle):
    offer(env)
    read(env, state(), T0 + 120)
    r = accept(env, **kw)
    assert r["ok"] is False and needle in r["error"]
    v = kw.get("value", PRICE)
    assert r["refunded"] == str(v) and claim(env, env.buyer) == v
    assert env.c.totals()["locked"] == "0"


def test_only_the_buyer_accepts(env):
    offer(env)
    read(env, state(), T0 + 120)
    r = accept(env, who=env.anyone)
    assert r["ok"] is False and "only the named buyer" in r["error"] and claim(env, env.anyone) == PRICE


def test_unknown_deal_accept_credits_back(env):
    r = accept(env, did="9", digest="x")
    assert r == {"ok": False, "error": "no such deal", "refunded": str(PRICE)}


def test_offer_expires(env):
    offer(env)
    r = read(env, state(), ACCEPT_BY + 1)
    assert r["read"] is False and r["deal"]["state"] == "EXPIRED"
    with pytest.raises(Exception, match="the deal is EXPIRED"):
        read(env, state(), ACCEPT_BY + 2)


# ---------------------------------------------------------------- transfer


def test_transfer_confirmed_after_two_readings_releases_the_upfront(env):
    ready(env)
    r1 = read(env, state(BUY_H), T0 + 1000)
    assert r1["deal"]["transfer"]["first_seen"] == T0 + 1000 and money(env)["released"] == 0
    r2 = read(env, state(BUY_H), T0 + 1000 + C - 1)
    assert r2["deal"]["transfer"]["confirmed_at"] == 0  # not yet confirm_seconds apart
    r3 = read(env, state(BUY_H), T0 + 1000 + C)
    assert r3["deal"]["transfer"]["confirmed_at"] == T0 + 1000 + C and r3["deal"]["transfer"]["status"] == "PENDING"
    assert money(env)["released"] == UP and claim(env, env.seller) == UP and money(env)["left"] == PRICE - UP


def test_another_holder_restarts_the_transfer_count(env):
    ready(env)
    read(env, state(BUY_H), T0 + 1000)
    read(env, state("Corvane Affiliate Holdings LLC"), T0 + 1200)
    r = read(env, state(BUY_H), T0 + 1000 + C)
    assert r["deal"]["transfer"]["first_seen"] == T0 + 1000 + C and r["deal"]["transfer"]["confirmed_at"] == 0


def test_a_no_reading_does_not_restart(env):
    ready(env)
    read(env, state(BUY_H), T0 + 1000)
    read(env, (page(BUY_H), answer(BUY_H, page_kind="other")), T0 + 1200)
    assert read(env, state(BUY_H), T0 + 1000 + C)["deal"]["transfer"]["confirmed_at"] == T0 + 1000 + C


def test_transfer_with_allowed_status_releases_the_smaller(env):
    ready(env)
    # allowed at 400,000: price for it 2.4 GEN, smaller than the 3.75 GEN upfront
    transfer(env, "Allowed", "$400,000.00")
    assert money(env)["released"] == 400_000 * RATE * G // (10000 * UPG)


@pytest.mark.parametrize("status", ["Disallowed", "Withdrawn", "Disallowed in part"])
def test_transfer_on_a_dead_or_unclear_claim_releases_nothing(env, status):
    ready(env)
    transfer(env, status)
    d = env.c.get_deal("1")
    assert d["transfer"]["confirmed_at"] and money(env)["released"] == 0


def test_transfer_must_be_confirmed_before_transfer_by(env):
    ready(env)
    read(env, state(BUY_H), TRANSFER_BY - C)
    r = read(env, state(BUY_H), TRANSFER_BY)
    assert r["deal"]["transfer"]["confirmed_at"] == 0


def test_no_transfer_refunds_the_buyer_at_the_deadline(env):
    ready(env)
    env.vm.warp(iso(TRANSFER_BY + GRACE - 1))
    assert env.c.settle("1")["state"] == "ACTIVE"
    env.vm.warp(iso(TRANSFER_BY + GRACE))
    d = env.c.settle("1")
    assert d["state"] == "SETTLED" and "no confirmed transfer" in d["settled_reason"]
    assert money(env)["refunded"] == PRICE and claim(env, env.buyer) == PRICE and env.c.totals()["locked"] == "0"


def test_settle_needs_no_page(env):
    ready(env)
    env.vm.clear_mocks()  # the page is dark: settle reads nothing
    env.vm.warp(iso(TRANSFER_BY + GRACE))
    assert env.c.settle("1")["state"] == "SETTLED"


def test_a_reading_after_a_deadline_applies_it_without_reading(env):
    ready(env)
    r = read(env, state(BUY_H), TRANSFER_BY + GRACE + 5)
    assert r["read"] is False and r["deal"]["state"] == "SETTLED"
    with pytest.raises(Exception, match="the deal is SETTLED"):
        read(env, state(BUY_H), TRANSFER_BY + GRACE + 10)


# ---------------------------------------------------------------- decision


def decide(e, status, allowed="", holder=BUY_H, t1=T0 + 3000):
    read(e, state(holder, status, allowed), t1)
    return read(e, state(holder, status, allowed), t1 + C)


def test_allowed_in_full(env):
    ready(env)
    transfer(env)
    d = decide(env, "Allowed", "$1,250,000.00")["deal"]
    assert d["state"] == "SETTLED" and d["decision"]["confirmed"] == {"status": "ALLOWED", "amount": 1_250_000}
    m = money(env)
    assert m["released"] == PRICE and m["refunded"] == 0 and m["left"] == 0
    assert claim(env, env.seller) == PRICE and env.c.totals()["locked"] == "0"


def test_allowed_at_80_percent(env):
    ready(env)
    transfer(env)
    decide(env, "Allowed", "$1,000,000.00")
    m = money(env)
    seller = 1_000_000 * RATE * G // (10000 * UPG)
    assert m["released"] == seller and m["refunded"] == PRICE - seller and m["shortfall"] == 0


def test_allowed_above_face_is_capped(env):
    ready(env)
    transfer(env)
    decide(env, "Allowed", "$2,000,000.00")
    assert money(env)["released"] == PRICE and money(env)["final_due"] == PRICE - UP


def test_price_is_rounded_down(env):
    d = offer(env, units_per_gen=7)
    assert int(d["price"]) == FACE * RATE * G // (10000 * 7) and (FACE * RATE * G) % (10000 * 7) != 0


def test_decision_needs_confirm_seconds_between_looks(env):
    ready(env)
    transfer(env)
    read(env, state(BUY_H, "Allowed", "$1,000,000.00"), T0 + 3000)
    r = read(env, state(BUY_H, "Allowed", "$1,000,000.00"), T0 + 3000 + C - 1)
    assert r["deal"]["state"] == "ACTIVE" and r["deal"]["decision"]["confirmed_at"] == 0


def test_allowed_below_the_upfront_records_a_shortfall(env):
    offer(env, upfront_bp=6000)
    read(env, state(), T0 + 120)
    accept(env)
    transfer(env)
    up = PRICE * 6000 // 10000
    assert money(env)["released"] == up
    decide(env, "Allowed", "$625,000.00")  # 50%
    m = money(env)
    due = 625_000 * RATE * G // (10000 * UPG)
    assert m["released"] == up and m["refunded"] == PRICE - up and m["shortfall"] == up - due


def test_disallowed_after_transfer(env):
    ready(env)
    transfer(env)
    decide(env, "Disallowed")
    m = money(env)
    assert m["released"] == UP and m["refunded"] == PRICE - UP and env.c.get_deal("1")["settled_reason"] == "claim disallowed after the transfer"


def test_withdrawn_after_transfer_pays_the_seller(env):
    ready(env)
    transfer(env)
    decide(env, "Withdrawn by claimant")
    m = money(env)
    assert m["released"] == PRICE and m["refunded"] == 0


@pytest.mark.parametrize("status", ["Expunged", "Amended", "Superseded", "Duplicate", "Not allowed", "Allowed for voting purposes only",
                                    "Objection withdrawn", "Expunged, amended by claim 1234", "Disallowed in part", "Allowed?"])
def test_unclear_statuses_never_decide(env, status):
    ready(env)
    transfer(env)
    decide(env, status)
    d = env.c.get_deal("1")
    assert d["state"] == "ACTIVE" and d["decision"]["first_seen"] is None and money(env)["left"] == PRICE - UP


def test_decision_needs_the_same_status_and_amount(env):
    ready(env)
    transfer(env)
    read(env, state(BUY_H, "Allowed", "$1,000,000.00"), T0 + 3000)
    r = read(env, state(BUY_H, "Allowed", "$900,000.00"), T0 + 3000 + C)
    assert r["deal"]["state"] == "ACTIVE" and r["deal"]["decision"]["first_seen"]["amount"] == 900_000
    r = read(env, state(BUY_H, "Pending"), T0 + 3000 + 2 * C)
    assert r["deal"]["decision"]["first_seen"] is None


def test_holder_change_does_not_restart_the_decision(env):
    ready(env)
    transfer(env)
    read(env, state(BUY_H, "Allowed", "$1,000,000.00"), T0 + 3000)
    r = read(env, state("Corvane Affiliate Holdings LLC", "Allowed", "$1,000,000.00"), T0 + 3000 + C)
    assert r["deal"]["state"] == "SETTLED"


def test_no_settlement_while_the_seller_holds_the_claim_again(env):
    ready(env)
    transfer(env)
    decide(env, "Allowed", "$1,250,000.00", holder=SELLER_NAME)
    assert env.c.get_deal("1")["state"] == "ACTIVE"


def test_decision_must_be_confirmed_before_allowance_by(env):
    ready(env)
    transfer(env)
    read(env, state(BUY_H, "Allowed", "$1,000,000.00"), ALLOWANCE_BY - C)
    r = read(env, state(BUY_H, "Allowed", "$1,000,000.00"), ALLOWANCE_BY)
    assert r["deal"]["state"] == "ACTIVE"


def test_no_decision_splits_at_the_long_stop(env):
    ready(env)
    transfer(env)
    env.vm.warp(iso(ALLOWANCE_BY + GRACE))
    d = env.c.settle("1")
    left = PRICE - UP
    seller = left * 7000 // 10000
    m = money(env)
    assert d["state"] == "SETTLED" and m["released"] == UP + seller and m["refunded"] == left - seller


def test_no_decision_with_the_seller_confirmed_as_holder_goes_to_the_buyer(env):
    ready(env)
    transfer(env)
    read(env, state(SELLER_NAME), T0 + 5000)
    read(env, state(SELLER_NAME), T0 + 5000 + C)
    assert env.c.get_deal("1")["held_by"] == "SELLER"
    env.vm.warp(iso(ALLOWANCE_BY + GRACE))
    env.c.settle("1")
    m = money(env)
    assert m["released"] == UP and m["refunded"] == PRICE - UP


def test_seller_seen_once_as_holder_changes_nothing(env):
    ready(env)
    transfer(env)
    read(env, state(SELLER_NAME), T0 + 5000)
    assert env.c.get_deal("1")["held_by"] == "BUYER"
    env.vm.warp(iso(ALLOWANCE_BY + GRACE))
    env.c.settle("1")
    m = money(env)
    left = PRICE - UP
    assert m["released"] == UP + left * 7000 // 10000 and m["refunded"] == left - left * 7000 // 10000


def test_seller_seen_once_does_not_block_a_decision_for_good(env):
    ready(env)
    transfer(env)
    read(env, state(BUY_H, "Allowed", "$1,250,000.00"), T0 + 5000)
    read(env, state(SELLER_NAME, "Allowed", "$1,250,000.00"), T0 + 5000 + C)  # blocked at this reading only
    assert env.c.get_deal("1")["state"] == "ACTIVE"
    r = read(env, state(BUY_H, "Allowed", "$1,250,000.00"), T0 + 5000 + 2 * C)
    assert r["deal"]["state"] == "SETTLED" and money(env)["released"] == PRICE


def test_holder_changes_after_allowance_by_are_not_counted(env):
    ready(env)
    transfer(env)
    read(env, state(SELLER_NAME), ALLOWANCE_BY + 10)
    read(env, state(SELLER_NAME), ALLOWANCE_BY + 10 + C)
    assert env.c.get_deal("1")["held_by"] == "BUYER"


def test_transfer_confirmation_starts_the_decision_count(env):
    ready(env)
    transfer(env, "Allowed", "$1,250,000.00")
    d = env.c.get_deal("1")
    assert d["transfer"]["confirmed_at"] and d["decision"]["first_seen"]["status"] == "ALLOWED" and d["state"] == "ACTIVE"
    r = read(env, state(BUY_H, "Allowed", "$1,250,000.00"), T0 + 1000 + 2 * C)
    assert r["deal"]["state"] == "SETTLED" and money(env)["released"] == PRICE


def test_clock_never_runs_backwards(env):
    ready(env)
    read(env, state(BUY_H), T0 + 2000)
    # A reading stamped earlier but processed later is handled at the later time.
    r = read(env, state(BUY_H), T0 + 2000 - C)
    assert r["deal"]["clock"] == T0 + 2000 and r["deal"]["transfer"]["confirmed_at"] == 0
    assert read(env, state(BUY_H), T0 + 2000 + C)["deal"]["transfer"]["confirmed_at"] == T0 + 2000 + C


# ------------------------------------------------------- release and refund


def test_release_and_refund(env):
    ready(env)
    env.vm.sender = env.buyer
    env.c.release("1", G)
    env.vm.sender = env.seller
    env.c.refund("1", 2 * G)
    m = money(env)
    assert m["released"] == G and m["refunded"] == 2 * G and m["left"] == PRICE - 3 * G
    env.vm.sender = env.anyone
    with pytest.raises(Exception, match="only the buyer"):
        env.c.release("1", 1)
    env.vm.sender = env.buyer
    with pytest.raises(Exception, match="amount must be 1 to"):
        env.c.release("1", PRICE)
    env.c.release("1", PRICE - 3 * G)
    d = env.c.get_deal("1")
    assert d["state"] == "SETTLED" and d["settled_reason"] == "nothing left in escrow"


def test_releases_count_against_the_final_price(env):
    ready(env)
    env.vm.sender = env.buyer
    env.c.release("1", G)
    transfer(env)
    decide(env, "Allowed", "$1,000,000.00")
    seller = 1_000_000 * RATE * G // (10000 * UPG)
    assert money(env)["released"] == seller


def test_release_refused_outside_active(env):
    offer(env)
    env.vm.sender = env.buyer
    r = env.c.release("1", 1)
    assert r["ok"] is False and "OFFERED" in r["error"]


def test_withdraw(env):
    ready(env)
    env.vm.warp(iso(TRANSFER_BY + GRACE))
    env.c.settle("1")
    env.vm.sender = env.buyer
    assert env.c.withdraw(0)["amount"] == str(PRICE)
    with pytest.raises(Exception, match="nothing to withdraw"):
        env.c.withdraw(0)
    assert env.c.totals() == {"deals": 1, "locked": "0", "credited": "0"}


# ------------------------------------------------------ reading the page


def nr(r, reason):
    assert r["reading"]["kind"] == "NO_READING", r["reading"]
    assert r["reading"]["reason"] == reason, r["reading"]


def test_holder_classes(env, mod):
    t = {"buyer_name": BUYER_NAME, "seller_name": SELLER_NAME}
    assert mod._holder_class(BUY_H, t) == "BUYER"
    assert mod._holder_class("HARROWFIELD CREDIT PARTNERS, L.P.", t) == "OTHER"  # 'l p' is not 'lp'
    assert mod._holder_class("Harrowfield Credit Partners LP.", t) == "BUYER"
    assert mod._holder_class("Quenby Tool and Die LLC", t) == "OTHER"
    assert mod._holder_class("Quenby Tool & Die LLC", t) == "SELLER"
    assert mod._holder_class("Harrowfield Credit Partners LP Fund II", t) == "OTHER"
    assert mod._holder_class(f"{SELLER_NAME} as assignee of {BUYER_NAME}", t) == "SELLER"


@pytest.mark.parametrize(
    "over,reason",
    [
        (dict(page_kind="other"), "N1_WRONG_PAGE"),
        (dict(debtor_name_on_page="Pellmoor Freight"), "N1_WRONG_PAGE"),
        (dict(claim_number_on_page="1043"), "N1_WRONG_PAGE"),
        (dict(other_claims_shown="yes"), "N2_AMBIGUOUS"),
        (dict(more_than_one_holder="yes"), "N2_AMBIGUOUS"),
        (dict(holder={"label": "Original creditor", "value": SELLER_NAME}), "N2_LABEL"),
        (dict(holder={"label": "Filed by", "value": SELLER_NAME}), "N2_LABEL"),
        (dict(status={"label": "Objection", "value": "Pending"}), "N2_LABEL"),
        (dict(holder={"label": "Creditor", "value": "Someone Else Ltd"}), "N2_NOT_ANCHORED"),
        (dict(status={"label": "Status", "value": "Allowed"}), "N2_NOT_ANCHORED"),
    ],
)
def test_page_refusals(env, over, reason):
    offer(env)
    body = json.loads(answer(wrap=False))
    body.update(over)
    nr(read(env, (page(), "```json\n" + json.dumps(body) + "\n```"), T0 + 100), reason)


def test_claim_number_must_be_a_whole_token(env):
    offer(env)
    pg = page().replace("Claim No. 1042", "Claim No. 21042")
    nr(read(env, (pg, answer()), T0 + 100), "N1_WRONG_PAGE")  # '1042' inside '10432' and '21042' only
    pg = page().replace("Claim No. 1042", "Claim No. 1042-1")
    nr(read(env, (pg, answer()), T0 + 110), "N1_WRONG_PAGE")


def test_debtor_must_be_on_the_page(env):
    offer(env)
    pg = page().replace(DEBTOR, "Pellmoor Freight Holdings")
    nr(read(env, (pg, answer()), T0 + 100), "N1_WRONG_PAGE")


@pytest.mark.parametrize(
    "allowed,expected",
    [
        ("$1,000,000.00", 1_000_000),
        ("$1,000,000", 1_000_000),
        ("USD 1,000,000.50", 1_000_000),
        ("1,000,000 USD", 1_000_000),
        ("$999.99", 999),
    ],
)
def test_allowed_amounts(env, allowed, expected):
    ready(env)
    r = read(env, state(SELLER_NAME, "Allowed", allowed), T0 + 1000)
    assert r["reading"] == {"kind": "READ", "holder": "SELLER", "status": "ALLOWED", "amount": expected}


@pytest.mark.parametrize(
    "allowed,reason",
    [
        ("$1.25 million", "N2_FORMAT"),
        ("$1,000k", "N2_FORMAT"),
        ("€1,000,000.00", "N2_FORMAT"),
        ("$0.00", "N2_FORMAT"),
        ("$1,000,000.000", "N2_FORMAT"),
        ("$1.000.000", "N2_FORMAT"),
        ("$1 000 000", "N2_FORMAT"),
        ("($1,000,000.00)", "N2_FORMAT"),
        ("$01,000", "N2_FORMAT"),
    ],
)
def test_bad_allowed_amounts(env, allowed, reason):
    ready(env)
    nr(read(env, state(SELLER_NAME, "Allowed", allowed), T0 + 1000), reason)


def test_allowed_amount_must_be_anchored_and_labelled(env):
    ready(env)
    pg = page(SELLER_NAME, "Allowed", "$1,000,000.00")
    nr(read(env, (pg, answer(SELLER_NAME, "Allowed", "$1,250,000.00")), T0 + 1000), "N2_NOT_ANCHORED")  # the claim amount, not the allowed one
    ans = answer(SELLER_NAME, "Allowed", "$1,000,000.00")
    ans = ans.replace('"label": "Allowed amount"', '"label": "Claim amount"')
    nr(read(env, (pg, ans), T0 + 1010), "N2_LABEL")
    pg2 = page(SELLER_NAME, "Allowed", "$21,000,000.00")
    nr(read(env, (pg2, answer(SELLER_NAME, "Allowed", "$1,000,000.00")), T0 + 1020), "N2_NOT_ANCHORED")


def test_currency_on_page_must_not_name_another(env):
    ready(env)
    nr(read(env, state(SELLER_NAME, "Allowed", "$1,000,000.00", currency_on_page="CAD"), T0 + 1000), "N2_CURRENCY")


def test_amount_ignored_unless_allowed(env):
    ready(env)
    r = read(env, (page(SELLER_NAME, "Pending", "$5"), answer(SELLER_NAME, "Pending", "$5")), T0 + 1000)
    assert r["reading"] == {"kind": "READ", "holder": "SELLER", "status": "PENDING", "amount": 0}


def test_status_table_phrases(env, mod):
    for phrase, cls in mod.STATUS_TABLE.items():
        assert mod.STATUS_TABLE.get(mod._norm_status(phrase.upper() + ".")) == cls


def test_decimal_comma_page_refused(env):
    offer(env)
    nr(read(env, (page(extra="Interest 1,5"), answer()), T0 + 100), "N2_FORMAT")


def test_dark_page_and_bad_answer(env):
    offer(env)
    nr(read(env, ("", answer()), T0 + 100), "N1_PAGE_DARK")
    nr(read(env, (page(), "no idea"), T0 + 110), "N2_FORMAT")


def test_anchoring_takes_the_whole_value_after_its_label(env, mod):
    pl = mod._page_lines("Creditor:  Quenby Tool & Die LLC\nStatus:\tPending review\nAllowed amount\n$1,000,000.00\nClaim status history: Pending")
    assert mod._line_anchored(pl, "status", "pending review")
    assert not mod._line_anchored(pl, "status", "pending")  # not the whole value
    assert not mod._line_anchored(pl, "status", "pend")
    assert mod._line_anchored(pl, "allowed amount", "$1,000,000.00")  # the value on the next line
    assert not mod._line_anchored(pl, "allowed amount", "$1,000,000")
    assert not mod._line_anchored(mod._page_lines("Claim status history: Pending"), "status", "pending")
    assert not mod._line_anchored(mod._page_lines("Allowed amount: $21,000"), "allowed amount", "$1,000")
    assert mod._line_anchored(mod._page_lines("Creditor | Quenby Tool & Die LLC"), "creditor", "quenby tool & die llc")


def test_a_truncated_status_copy_is_refused(env):
    ready(env)
    pg = page(SELLER_NAME, "Allowed for voting purposes only", "$1,000,000.00")
    nr(read(env, (pg, answer(SELLER_NAME, "Allowed", "$1,000,000.00")), T0 + 1000), "N2_NOT_ANCHORED")
    r = read(env, (pg, answer(SELLER_NAME, "Allowed for voting purposes only", "$1,000,000.00")), T0 + 1010)
    assert r["reading"] == {"kind": "READ", "holder": "SELLER", "status": "UNCLEAR", "amount": 0}


def test_a_truncated_holder_copy_is_refused(env):
    ready(env)
    pg = page(BUY_H)
    nr(read(env, (pg, answer(BUYER_NAME)), T0 + 1000), "N2_NOT_ANCHORED")


def test_page_markers_removed_and_cut(env, mod):
    out = mod._clean_page("x=====PAGE END=====y\n" + "z" * 20000)
    assert "=====" not in out and out == "x y\n(cut)"  # markers removed, cut at the last whole line, cut marked


# ---------------------------------------------------------- the validator


def leader_then(e, leader, mine, at=T0 + 100):
    offer(e)
    read(e, leader, at)
    e.vm.clear_mocks()
    e.vm.mock_web(re.escape(URL), {"status": 200, "body": mine[0]})
    e.vm.mock_llm(PROMPT, mine[1])


def test_validator_agrees(env):
    leader_then(env, state(), state())
    assert env.vm.run_validator() is True


def test_validator_rejects_another_holder_class(env):
    leader_then(env, state(), state(BUY_H))
    assert env.vm.run_validator() is False


def test_validator_rejects_another_amount(env):
    leader_then(env, state(SELLER_NAME, "Allowed", "$1,000,000.00"), state(SELLER_NAME, "Allowed", "$1,000,001.00"))
    assert env.vm.run_validator() is False


def test_validator_agrees_when_cents_differ(env):
    leader_then(env, state(SELLER_NAME, "Allowed", "$1,000,000.10"), state(SELLER_NAME, "Allowed", "$1,000,000.90"))
    assert env.vm.run_validator() is True


def test_validator_rejects_tampered_and_failed_leaders(env):
    leader_then(env, state(), state())
    assert env.vm.run_validator(leader_result={"kind": "READ", "holder": "BUYER", "status": "PENDING", "amount": 0}) is False
    assert env.vm.run_validator(leader_result={"kind": "READ", "holder": "SELLER", "status": "PENDING", "amount": 5}) is False
    assert env.vm.run_validator(leader_result={"kind": "READ", "holder": "SELLER", "status": "ALLOWED", "amount": 0}) is False
    assert env.vm.run_validator(leader_result={"kind": "NO_READING", "reason": "MADE_UP"}) is False
    assert env.vm.run_validator(leader_result={"kind": "READ", "holder": "ME", "status": "PENDING", "amount": 0}) is False
    assert env.vm.run_validator(leader_error=Exception("boom")) is False


def test_check_and_same_outcome(env, mod):
    a = {"kind": "READ", "holder": "SELLER", "status": "ALLOWED", "amount": 10}
    assert mod._check_outcome(a) == a and mod._same_outcome(a, dict(a))
    assert not mod._same_outcome(a, {**a, "amount": 11}) and not mod._same_outcome(a, {**a, "holder": "OTHER"})
    assert not mod._same_outcome(a, {"kind": "NO_READING", "reason": "N2_FORMAT"})
    assert mod._same_outcome({"kind": "NO_READING", "reason": "N2_LABEL"}, {"kind": "NO_READING", "reason": "N2_LABEL"})
    for bad in (None, {"kind": "X"}, {**a, "amount": True}, {**a, "amount": -1}, {**a, "status": "MAYBE"}):
        with pytest.raises(Exception):
            mod._check_outcome(bad)


def test_money_always_reconciles(env):
    ready(env)
    env.vm.sender = env.buyer
    env.c.release("1", 123)
    transfer(env)
    decide(env, "Allowed", "$777,777.77")
    m = money(env)
    assert m["escrow"] == m["left"] + m["released"] + m["refunded"] == PRICE
    assert claim(env, env.seller) + claim(env, env.buyer) == PRICE
    assert env.c.totals() == {"deals": 1, "locked": "0", "credited": str(PRICE)}
