#!/usr/bin/env python3
"""Run the nine fictional ClaimEscrow cases live on GenLayer Studio or Testnet
Bradbury Phase 2, side by side, and record every transaction.

    python tools/live.py <tag> <E_unix> [--net studio|bradbury] [--contract 0x..]

E is every offer's accept_by. The register pages must already be live at
https://claims.brilliantnodes.com/register/<tag>/claim-<number>.html
(tools/make_register.py <tag> <E> docs). They change at E + 3 min (the buyer
appears as holder) and E + 40 min (the decision). Validators render a page
when the transaction is processed, which on a busy Studio has been 35
minutes after it was sent, so the script reads well away from those moments:

  E - 30 .. E     offer, baseline reading, accept (and one refused accept)
  E + 1 .. 2      the one-sided case: the buyer releases, the seller refunds
  E + 5           first reading after the transfer (transfer seen)
  E + 16          second reading (transfer confirmed: the upfront is released)
  E + 42          third reading (the decision, shown from E + 40, seen)
  E + 53          fourth reading (decision confirmed: settled)
  E + 60          settle: no transfer by transfer_by (E + 30) + 30 min
  E + 95          settle: no decision by allowance_by (E + 65) + 30 min
  then            withdrawals; totals reconciled with the contract's balance

Studio: throwaway accounts funded from Studio's faucet. Bradbury: two test
wallets whose key files are in BRADBURY_KEY_DIR (never printed). Every name,
case and figure is fictional; only test GEN moves.
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReceiptTimeout(RuntimeError):
    """The transaction was sent but no receipt came back: never send it again."""
G = 10**18
SITE = os.environ.get("CE_SITE", "https://claims.brilliantnodes.com")
HOST = SITE.split("://", 1)[1].split("/", 1)[0]
CASES = json.loads((ROOT / "examples" / "cases.json").read_text())
C = CASES["confirm_seconds"]
args = sys.argv[1:]
TAG, E = args[0], int(args[1])


def opt(name, default=""):
    return args[args.index(name) + 1] if name in args else default


NET = opt("--net", "studio")
BB = NET == "bradbury"
UPG = CASES["units_per_gen"][NET]
TRANSFER_BY, ALLOWANCE_BY = E + 30 * 60, E + 65 * 60
REC_PATH = ROOT / "examples" / f"live-{NET}-{TAG}.json"
REC = {"net": NET, "tag": TAG, "accept_by": E, "transfer_by": TRANSFER_BY, "allowance_by": ALLOWANCE_BY, "site": SITE,
       "contract": {}, "accounts": {}, "deals": {}, "steps": []}
LOCK = threading.Lock()


def utc(ts=None):
    return datetime.fromtimestamp(ts if ts is not None else time.time(), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    with LOCK:
        print(f"{utc()} {msg}", flush=True)


def save():
    with LOCK:
        REC_PATH.write_text(json.dumps(REC, indent=1, default=str))


def until(ts):
    while time.time() < ts:
        time.sleep(min(5, max(0.5, ts - time.time())))


# ------------------------------------------------------------------ backends

if not BB:
    from genlayer_py import create_account, create_client
    from genlayer_py.chains import studionet
    from genlayer_py.types import TransactionStatus

    ACCTS, ROLE_LOCKS = {}, {}

    def _keep_key(role, a):
        """Keep this throwaway Studio key outside the repo (never printed or
        committed), so a run cut short by a restart can still be finished by
        hand: withdrawals need the parties' own keys."""
        d = Path(os.environ.get("LIVE_KEY_DIR", "/home/claude/keys"))
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"studio-{Path(REC_PATH).stem}.json"
        keys = json.loads(f.read_text()) if f.exists() else {}
        keys[role] = a.key.hex() if hasattr(a.key, "hex") else str(a.key)
        f.write_text(json.dumps(keys))
        os.chmod(f, 0o600)

    def make_accounts():
        for role in ("seller", "buyer") + tuple(f"reader{i}" for i in range(len(CASES["cases"]))):
            a = create_account()
            c = create_client(chain=studionet, account=a)
            for k in range(8):  # Studio's gateway sometimes answers 502 for a few seconds
                try:
                    c.provider.make_request(method="sim_fundAccount", params=[a.address, 200 * G])
                    break
                except Exception:
                    time.sleep(10)
            ACCTS[role] = (c, a)
            _keep_key(role, a)
            ROLE_LOCKS[role] = threading.Lock()
            REC["accounts"][role] = a.address

    def _wait(c, tx):
        deadline, last = time.time() + 3600, None  # a busy Studio has taken 35 minutes to process a reading
        while time.time() < deadline:
            try:
                return c.wait_for_transaction_receipt(transaction_hash=tx, status=TransactionStatus.ACCEPTED, interval=3000, retries=20)
            except Exception as e:  # Studio's gateway sometimes answers 502/520 for a few seconds
                last = e
                time.sleep(5)
        raise ReceiptTimeout(f"no receipt for {tx}: {last}")

    def _result(r):
        cd = r.get("consensus_data") or {}
        lr = cd.get("leader_receipt")
        lr = lr[0] if isinstance(lr, list) and lr else lr
        lr = lr if isinstance(lr, dict) else {}
        res = lr.get("result") or {}
        payload = res.get("payload") if isinstance(res, dict) else None
        if isinstance(payload, dict) and "readable" in payload:
            try:
                payload = json.loads(payload["readable"])
            except Exception:
                payload = payload["readable"]
        return {"status": r.get("status_name"), "execution": lr.get("execution_result"), "result": payload, "votes": cd.get("votes") or {}}

    def deploy(role, path, cargs):
        c, a = ACCTS[role]
        tx = c.deploy_contract(code=Path(path).read_text(), args=cargs)
        r = _wait(c, tx)
        return tx, r.get("to_address") or r.get("recipient")

    def send(role, addr, fn, fargs, value=0, payees=""):
        """One send only: a retry after the node got it would be a second transaction."""
        c, a = ACCTS[role]
        with ROLE_LOCKS[role]:
            tx = c.write_contract(address=addr, function_name=fn, args=fargs, value=value)
        return tx, _result(_wait(c, tx))

    def view(addr, fn, fargs):
        c, a = ACCTS["reader0"]
        for k in range(8):  # a view has no side effect, so a retry after a gateway error is safe
            try:
                return c.read_contract(address=addr, function_name=fn, args=fargs)
            except Exception:
                if k == 7:
                    raise
                time.sleep(10)

    def balance(addr):
        c, a = ACCTS["reader0"]
        return int(c.provider.make_request(method="eth_getBalance", params=[addr, "latest"])["result"], 16)
else:
    JS = ROOT / "tools" / "bradbury"
    KEY_DIR = os.environ.get("BRADBURY_KEY_DIR", "/home/claude/keys")
    KEYS = {"seller": f"{KEY_DIR}/bradbury_rr2.key", "buyer": f"{KEY_DIR}/bradbury_rr.key"}
    ROLE_LOCKS = {r: threading.Lock() for r in KEYS}
    NOTHING = ("UNDETERMINED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT", "CANCELED")

    def _node(role, *a, timeout=1800):
        p = subprocess.run(["node", "gl.mjs", *a], cwd=JS, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "BRADBURY_KEY_FILE": KEYS[role]})
        return [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]

    def make_accounts():
        from eth_account import Account
        for role in KEYS:
            REC["accounts"][role] = Account.from_key(Path(KEYS[role]).read_text().strip()).address
        for i in range(8):
            REC["accounts"][f"reader{i}"] = REC["accounts"]["seller" if i % 2 else "buyer"]

    def _role(role):
        return role if role in KEYS else ("seller" if int(role[-1]) % 2 else "buyer")

    def _tx(h):
        o = _node("buyer", "tx", h, timeout=300)
        return (o[-1].get("raw") if o else None) or {}

    def _decided(raw):
        st = str(raw.get("statusName", ""))
        return st in NOTHING or (st in ("ACCEPTED", "FINALIZED") and raw.get("resultName") not in (None, "", "IDLE"))

    def _wait_h(h, final=False):
        for _ in range(240):
            raw = _tx(h)
            if (str(raw.get("statusName")) == "FINALIZED") if final else _decided(raw):
                return raw
            time.sleep(10)
        return _tx(h)

    def deploy(role, path, cargs):
        o = _node(_role(role), "deploy", str(path), json.dumps(cargs))
        d = next((x for x in reversed(o) if "ok" in x), {})
        raw = d.get("raw") or {}
        return d.get("hash"), raw.get("recipient") or raw.get("toAddress") or (raw.get("txDataDecoded") or {}).get("contractAddress")

    def send(role, addr, fn, fargs, value=0, payees=""):
        r = _role(role)
        with ROLE_LOCKS[r]:
            o = _node(r, "write", addr, fn, json.dumps(fargs), str(value), payees)
        sent = next((x["sent"] for x in o if "sent" in x), None)
        d = next((x for x in reversed(o) if "ok" in x), {})
        h = d.get("hash") or sent
        raw = d.get("raw") or {}
        if h and not _decided(raw):
            raw = _wait_h(h)
        if str(raw.get("statusName")) in ("LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"):
            raw = _wait_h(h, final=True)
        st = str(raw.get("statusName", ""))
        return h, {"status": st if st in NOTHING else raw.get("resultName"), "execution": raw.get("txExecutionResultName"),
                   "created": raw.get("createdTimestamp"), "result": None}

    def view(addr, fn, fargs):
        d = {}
        for _ in range(3):
            o = _node("buyer", "read", addr, fn, json.dumps(fargs), timeout=300)
            d = o[-1] if o else {}
            if d.get("ok"):
                return d["result"]
            time.sleep(10)
        raise RuntimeError(f"read {fn} failed: {d}")

    def balance(addr):
        return int(_node("buyer", "balance", addr, timeout=120)[-1]["result"])


def step(case, role, addr, fn, fargs, value=0, expect=None, payees=""):
    log(f"[{case}] {fn} from {role}" + (f" value {value}" if value else ""))
    for attempt in range(3 if fn == "read_register" else 1):
        # a reading is an observation: sending it again after a failed send cannot move money twice
        try:
            tx, r = send(role, addr, fn, fargs, value, payees)
            break
        except ReceiptTimeout as e:
            tx, r = None, {"status": "NO_RECEIPT", "error": str(e)[:300]}
            log(f"[{case}]   sent, but no receipt: {str(e)[:120]} (not sent again)")
            break
        except Exception as e:
            tx, r = None, {"status": "SEND_FAILED", "error": str(e)[:300]}
            log(f"[{case}]   send failed ({str(e)[:80]}); " + ("retrying in 15 s" if fn == "read_register" and attempt < 2 else "not retried"))
            time.sleep(15 if fn == "read_register" else 0)
    entry = {"case": case, "at": utc(), "from": REC["accounts"][role], "fn": fn, "args": fargs, "value": str(value), "tx": tx,
             **{k: v for k, v in r.items() if k != "votes"}}
    if r.get("votes"):
        entry["votes"] = r["votes"]
    if expect:
        entry["expect"] = expect
    with LOCK:
        REC["steps"].append(entry)
    save()
    res = r.get("result")
    brief = res.get("reading") if isinstance(res, dict) and "reading" in res else (res.get("error") if isinstance(res, dict) and "error" in res else "")
    log(f"[{case}]   -> {r.get('status')} / {r.get('execution')} {json.dumps(brief, default=str)[:160]}")
    return tx, r


def run_case(i, case, addr, did):
    key, reader = case["key"], f"reader{i}"
    deal = REC["deals"][key]
    price = int(deal["price"])
    if case.get("release_tenths"):
        until(E + 60 + i * 5)
        step(key, "buyer", addr, "release", [did, price * case["release_tenths"] // 10], expect="buyer releases part of the escrow to the seller")
        step(key, "seller", addr, "refund", [did, price * case["refund_tenths"] // 10], expect="seller refunds part of the escrow to the buyer")
    if case.get("transfer", True):
        until(E + 5 * 60 + i * 8)
        t1 = time.time()
        step(key, reader, addr, "read_register", [did], expect="transfer seen")
        until(max(E + 16 * 60 + i * 8, t1 + C + 30))
        t2 = time.time()
        step(key, reader, addr, "read_register", [did], expect="transfer confirmed: upfront released")
        until(max(E + 42 * 60 + i * 8, t2 + 60))
        t3 = time.time()
        step(key, reader, addr, "read_register", [did], expect="decision seen")
        until(max(E + 53 * 60 + i * 8, t3 + C + 30))
        if key != "unclear":
            step(key, reader, addr, "read_register", [did], expect=case["expect"])
        else:
            step(key, reader, addr, "read_register", [did], expect="status unclear: no decision")
            until(ALLOWANCE_BY + 1800 + 30)
            step(key, reader, addr, "settle", [did], expect=case["expect"])
    else:
        until(E + 5 * 60 + i * 8)
        step(key, reader, addr, "read_register", [did], expect="the seller still holds the claim")
        until(TRANSFER_BY + 1800 + 30)
        step(key, reader, addr, "settle", [did], expect=case["expect"])


def main():
    make_accounts()
    save()
    addr = opt("--contract")
    if not addr:
        path = ROOT / ("bradbury/build/claim_escrow.py" if BB else "contracts/claim_escrow.py")
        tx, addr = deploy("seller", path, [json.dumps([HOST]), C])
        REC["contract"] = {"address": addr, "deploy_tx": tx}
        log(f"ClaimEscrow deployed at {addr} ({tx})")
    else:
        REC["contract"] = {"address": addr}
    save()
    acc = REC["accounts"]
    step("refused offer", "seller", addr, "offer", [acc["buyer"], CASES["buyer_name"], "Quenby Tool & Die LLC", CASES["debtor_name"], "1042",
         "https://register.example.com/claim-1042.html", "USD", 1000, 5000, UPG, 5000, C, E, TRANSFER_BY, ALLOWANCE_BY, 7000], expect="error: host not on the frozen list")
    for case in CASES["cases"]:
        url = f"{SITE}/register/{TAG}/claim-{case['claim_number']}.html"
        step(case["key"], "seller", addr, "offer", [acc["buyer"], CASES["buyer_name"], case["seller_name"], CASES["debtor_name"], case["claim_number"], url, "USD",
             case["face_amount"], case["rate_bp"], UPG, case["upfront_bp"], C, E, TRANSFER_BY, ALLOWANCE_BY, case["no_decision_seller_bp"]], expect="offer stored")
        did = str(view(addr, "totals", [])["deals"])
        d = view(addr, "get_deal", [did])
        if d["terms"]["claim_number"] != case["claim_number"]:
            did = next(x for x in view(addr, "get_deals_of", [acc["seller"]]) if view(addr, "get_deal", [x])["terms"]["claim_number"] == case["claim_number"])
            d = view(addr, "get_deal", [did])
        REC["deals"][case["key"]] = {"id": did, "digest": d["digest"], "price": d["price"], "upfront": d["upfront"], "url": url, "title": case["title"]}
        save()
    for i, case in enumerate(CASES["cases"]):
        did = REC["deals"][case["key"]]["id"]
        step(case["key"], f"reader{i}", addr, "read_register", [did], expect="baseline: the seller holds the claim, Pending")
        if i == 0:
            step(case["key"], "buyer", addr, "accept", [did, REC["deals"][case["key"]]["digest"]], value=int(REC["deals"][case["key"]]["price"]) - 1,
                 expect="refused: not exactly the price (credited back)")
        step(case["key"], "buyer", addr, "accept", [did, REC["deals"][case["key"]]["digest"]], value=int(REC["deals"][case["key"]]["price"]), expect="accepted")
    if time.time() > E:
        log("WARNING: setup ran past accept_by")
    threads = [threading.Thread(target=run_case, args=(i, case, addr, REC["deals"][case["key"]]["id"])) for i, case in enumerate(CASES["cases"])]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for role in ("seller", "buyer"):
        step("withdraw", role, addr, "withdraw", [0], payees=acc[role] if BB else "")
    final = {"totals": view(addr, "totals", []), "balance": str(balance(addr)), "deals": {}}
    for key, d in REC["deals"].items():
        final["deals"][key] = view(addr, "get_deal", [d["id"]])
    final["claimable"] = {r: view(addr, "get_claimable", [a]) for r, a in acc.items() if r in ("seller", "buyer")}
    REC["final"] = final
    save()
    log(f"balance {final['balance']} vs locked {final['totals']['locked']} + credited {final['totals']['credited']}")
    log(f"record written to {REC_PATH}")


if __name__ == "__main__":
    main()
