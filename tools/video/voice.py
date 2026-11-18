#!/usr/bin/env python3
"""Voice-over for the ClaimEscrow demo video, made offline with Kokoro-82M (Apache-2.0).

    pip install kokoro-onnx soundfile
    KOKORO_DIR=/path python3 voice.py data.json      # kokoro-v1.0.fp16.onnx and voices-v1.0.bin in KOKORO_DIR
    python3 render.py data.json --durations build/durations.json --audio build/narration.wav

One clip per scene; each scene lasts as long as its line needs; one narration
track starts each line just after its scene fades in.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
OUT = HERE / "build"
LEAD, TAIL = 0.45, 0.6
BASE = [("title", 4.5), ("problem", 6.0), ("register", 6.5), ("validators", 7.0), ("twice", 7.0), ("escrow", 7.5),
        ("cases", 8.0), ("deadlines", 6.0), ("site", 6.0), ("end", 4.0)]
WORDS = {8: "Eight", 9: "Nine", 10: "Ten"}


def lines(d):
    n = len(d["cases"])
    return {
        "title": "Claim Escrow. The safer way to buy and sell bankruptcy claims: the whole price waits in escrow until the claims register decides.",
        "problem": "When a company goes bankrupt, its suppliers can sell their claims for cash now. But what a claim is worth is decided later, so today one side has to trust the other.",
        "register": "The facts that decide the money are public, on the claims register: who holds the claim, its status, and its allowed amount.",
        "validators": "Gen Layer validators each read the claim's entry and copy those lines. Plain code checks every copy against its own page, and the money moves only when they agree exactly.",
        "twice": "Nothing moves on one look. A transfer, a decision, even the seller holding the claim again, counts only when it is seen twice, a set time apart.",
        "escrow": "The whole price sits in escrow. When the transfer is confirmed, the seller gets its upfront. At the decision, code pays the price for the allowed amount, and the rest goes back to the buyer.",
        "cases": f"{WORDS.get(n, n)} fictional cases ran live on Gen Layer Studio, with {d['n_tx']} transactions: allowed in full, cut, disallowed, withdrawn, never transferred, and unclear until the long stop.",
        "deadlines": "Deadlines need no model. No transfer in time refunds the buyer, and no decision by the long stop splits what is left by the agreed share.",
        "site": "Every case and every transaction is on the site, with links to the explorer.",
        "end": "Claim Escrow. On Gen Layer, by Brilliant Nodes.",
    }


def main():
    from kokoro_onnx import Kokoro
    d = json.loads(Path(sys.argv[1]).read_text())
    kdir = Path(os.environ["KOKORO_DIR"])
    k = Kokoro(str(kdir / "kokoro-v1.0.fp16.onnx"), str(kdir / "voices-v1.0.bin"))
    (OUT / "voice").mkdir(parents=True, exist_ok=True)
    L = lines(d)
    clips, durs, sr = {}, {}, 24000
    for name, base in BASE:
        samples, sr = k.create(L[name], voice="af_heart", speed=1.0, lang="en-us")
        samples = np.asarray(samples, dtype=np.float32)
        clips[name] = samples
        durs[name] = round(max(base, LEAD + len(samples) / sr + TAIL), 2)
        print(f"{name:11s} line {len(samples) / sr:5.2f} s  scene {durs[name]:5.2f} s")
    total = sum(durs.values())
    track = np.zeros(int(total * sr) + sr, dtype=np.float32)
    t = 0.0
    for name, _ in BASE:
        i = int((t + LEAD) * sr)
        track[i:i + len(clips[name])] += clips[name]
        t += durs[name]
    track = track * (0.89 / (float(np.max(np.abs(track))) or 1.0))
    sf.write(OUT / "narration.wav", track[: int(total * sr)], sr)
    (OUT / "durations.json").write_text(json.dumps(durs, indent=1))
    (OUT / "lines.json").write_text(json.dumps(L, indent=1))
    print(f"total {total:.2f} s")


if __name__ == "__main__":
    main()
