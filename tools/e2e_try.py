#!/usr/bin/env python3
"""Click through the "Try it yourself" app in a headless browser, as a
visitor does, against the visitor contract on GenLayer Studio.

    python tools/e2e_try.py <page url> <story: full|partial|disallowed> <out dir>

Sets up the two temporary accounts, offers the claim for the next slot, reads
the baseline, pays the price as the buyer, then turns on "Keep reading for me"
and waits until the deal is settled, and withdraws every credit. Screenshots
and a JSON log of every step go to <out dir>. Fictional data; test GEN only.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

url, story, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
LOG = []


def log(what, **kw):
    LOG.append({"t": int(time.time()), "what": what, **kw})
    (out / "log.json").write_text(json.dumps(LOG, indent=1))
    print(time.strftime("%H:%M:%S"), what, json.dumps(kw)[:300], flush=True)


def wait_tx(pg, limit=900):
    """Wait until the lifecycle panel shows a final note."""
    t0 = time.time()
    while time.time() - t0 < limit:
        note = pg.inner_text("#life-note")
        if note and not note.startswith("Sent ") and not note.startswith("Signing"):
            return note
        time.sleep(3)
    return "timeout"


def press(pg, name):
    pg.get_by_role("button", name=name).first.click()
    return wait_tx(pg)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1200, "height": 1600})
    pg.on("pageerror", lambda e: log("page error", error=str(e)))
    pg.goto(url)
    pg.wait_for_timeout(3000)
    pg.click("#btn-setup")
    pg.wait_for_function("document.getElementById('buyer-bal').textContent.includes('Wallet')", timeout=120000)
    log("accounts", seller=pg.inner_text("#seller-addr"), buyer=pg.inner_text("#buyer-addr"))
    pg.check(f"input[name=story][value={story}]")
    log("slot", note=pg.inner_text("#slot-note"))
    pg.screenshot(path=str(out / "01-start.png"), full_page=True)
    pg.click("#btn-offer")
    log("offer", note=wait_tx(pg))
    pg.wait_for_selector("#deal:not([hidden])", timeout=60000)
    log("deal", title=pg.inner_text("#d-title"), next=pg.inner_text("#d-next"))
    # baseline, then pay (read again if a reading found nothing usable)
    for _ in range(4):
        nxt = pg.inner_text("#d-next")
        if "Buyer, pay" in nxt:
            break
        log("baseline read", note=press(pg, "Read the register"), next=pg.inner_text("#d-next"))
    pg.screenshot(path=str(out / "02-baseline.png"), full_page=True)
    log("pay", note=press(pg, "Buyer: pay the price into escrow"), state=pg.inner_text("#d-state"))
    pg.screenshot(path=str(out / "03-paid.png"), full_page=True)
    t0 = time.time()
    shots = 4
    seen = set()
    while time.time() - t0 < 70 * 60:
        state = pg.inner_text("#d-state")
        if state in ("SETTLED", "CANCELLED", "EXPIRED"):
            break
        box = pg.locator(".auto input[type=checkbox]")
        if box.count() and not box.first.is_checked():
            box.first.check()
            log("keep reading for me: on")
        note = pg.inner_text("#life-note") if pg.locator("#life:not([hidden])").count() else ""
        what = pg.inner_text("#life-what") if note else ""
        key = (what, note[:80])
        if note and not note.startswith(("Sent ", "Signing")) and key not in seen:
            seen.add(key)
            log("tx", step=what, note=note, state=state)
            pg.screenshot(path=str(out / f"{shots:02d}-step.png"), full_page=True)
            shots += 1
        if int(time.time() - t0) % 120 < 15:
            log("waiting", next=pg.inner_text("#d-next"))
        time.sleep(15)
    log("final", state=pg.inner_text("#d-state"), next=pg.inner_text("#d-next"), money=pg.inner_text("#d-money"), seen=pg.inner_text("#d-seen"))
    pg.screenshot(path=str(out / f"{shots:02d}-final.png"), full_page=True)
    for role in ("seller", "buyer"):
        w = pg.locator(f"#{role}-bal button")
        if w.count():
            w.first.click()
            log(f"withdraw {role}", note=wait_tx(pg))
    pg.click("#d-reload")
    time.sleep(3)
    log("balances", seller=pg.inner_text("#seller-bal"), buyer=pg.inner_text("#buyer-bal"))
    pg.screenshot(path=str(out / "99-done.png"), full_page=True)
    b.close()
