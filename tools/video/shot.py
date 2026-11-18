#!/usr/bin/env python3
"""A screenshot of the live site for the video: python3 shot.py data.json (writes shot_site.jpg and its ratio into data.json)."""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

data_path = Path(sys.argv[1])
proxy = {"server": os.environ["HTTPS_PROXY"]} if os.environ.get("HTTPS_PROXY") else None
with sync_playwright() as p:
    b = p.chromium.launch(proxy=proxy) if proxy else p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 1400}, device_scale_factor=1.5, ignore_https_errors=True)
    pg.goto("https://claims.brilliantnodes.com/", wait_until="domcontentloaded", timeout=90000)
    pg.locator("#deals .card").first.wait_for(timeout=120000)
    pg.wait_for_timeout(2500)
    pg.screenshot(path="shot_site.jpg", type="jpeg", quality=92, full_page=True)
    w, h = pg.evaluate("[document.body.scrollWidth, document.body.scrollHeight]")
    b.close()
d = json.loads(data_path.read_text())
d["shot"], d["shot_ratio"] = "shot_site.jpg", round(h / w, 4)
data_path.write_text(json.dumps(d, indent=1))
print("shot_site.jpg", w, h)
