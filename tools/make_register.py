#!/usr/bin/env python3
"""Write the fictional claims agent's register pages for one live run.

    python tools/make_register.py <tag> <E_unix> <out_dir>

E is the offers' accept_by time. Each page is one claim's entry in the
register of the fictional Pellmoor Freight Lines, Inc. case, kept by the
fictional Marrowgate Restructuring Agents. A page carries its own schedule
and shows the entry as it stands at the reader's clock, so validators reading
at different moments see the register change the way a real one does:

  until E + 3 min    the seller holds the claim, status Pending
  from  E + 3 min    the buyer is shown as holder ("... as transferee of ...")
  from  E + 40 min   the court's decision (allowed, disallowed, withdrawn...),
                     after the reading that confirms the transfer
  (case withdrawn_early: the withdrawal shows from E + 3 min, with the transfer)

The live script reads well away from those change times. Pages go to
<out_dir>/register/<tag>/claim-<number>.html, served from
https://claims.brilliantnodes.com/register/<tag>/claim-<number>.html.
Every name, case and figure is fictional.
"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "examples" / "cases.json").read_text())
FLIP, DECIDE = 3 * 60, 40 * 60  # s1 used 16 min, s2 20 min, s3-s7 22 min; in s7 a busy Studio processed the E + 16 readings after E + 22

STYLE = """body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:780px;margin:32px auto;padding:0 18px;color:#1c2430;background:#f7f8fa}
.bar{background:#22334d;color:#fff;padding:14px 18px;border-radius:6px}.bar b{font-size:19px}.bar span{display:block;font-size:13px;opacity:.8}
h1{font-size:22px;margin:22px 0 6px}.case{color:#555;margin:0 0 18px}.row{padding:9px 0;border-bottom:1px solid #dde2ea}.k{display:inline-block;min-width:170px;color:#556}
.v{font-weight:600}.note{font-size:13px;color:#667;margin-top:18px}footer{margin-top:34px;font-size:12px;color:#889}"""


def page(debtor, case_no, claim, filed, amount, schedule):
    sched = json.dumps(schedule)
    rows = [("Claim No.", str(claim["number"])), ("Creditor", "<span id=holder></span>"), ("Date filed", filed),
            ("Claim amount", amount), ("Status", "<span id=status></span>"), ("Allowed amount", "<span id=allowed></span>")]
    body = "\n".join(f'<div class="row"><span class="k">{k}:</span> <span class="v">{v}</span></div>' for k, v in rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Claim {claim["number"]} - {html.escape(debtor)} - Claims Register</title>
<style>{STYLE}</style>
</head>
<body>
<div class="bar"><b>Marrowgate Restructuring Agents</b><span>Claims and noticing agent (fictional)</span></div>
<h1>Claims Register: {html.escape(debtor)}</h1>
<p class="case">Case No. {case_no}, United States Bankruptcy Court for the District of Example (fictional)</p>
<div id="entry" hidden>
{body}
<div class="row"><span class="k">Last updated:</span> <span class="v" id="updated"></span></div>
</div>
<noscript><p>This register needs JavaScript to show the current entry.</p></noscript>
<p class="note">Transfers of claim are shown as filed under Rule 3001(e). The current holder appears as "transferee of" the original creditor.</p>
<footer>Fictional case, names and figures, published for a GenLayer ClaimEscrow demonstration by Brilliant Nodes. Not a real register.</footer>
<script>
(function () {{
  var s = {sched};
  var now = Date.now() / 1000, cur = s[0];
  for (var i = 0; i < s.length; i++) if (s[i].from <= now) cur = s[i];
  document.getElementById("holder").textContent = cur.holder;
  document.getElementById("status").textContent = cur.status;
  document.getElementById("allowed").textContent = cur.allowed || "-";
  document.getElementById("updated").textContent = new Date(cur.from * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
  document.getElementById("entry").hidden = false;
}})();
</script>
</body>
</html>
"""


def schedule(case, e):
    seller, buyer = case["seller_name"], CASES["buyer_name"]
    trans = f"{buyer} as transferee of {seller}"
    s = [{"from": e - 6 * 3600, "holder": seller, "status": "Pending", "allowed": ""}]
    after_flip = trans if case.get("transfer", True) else seller
    d = case.get("decision")
    if d and case.get("decision_from_flip"):
        # the decision is already on the register when the transfer first shows (a withdrawal filed before the transfer)
        s.append({"from": e + FLIP, "holder": after_flip, "status": d["status"], "allowed": d.get("allowed", "")})
        return s
    s.append({"from": e + FLIP, "holder": after_flip, "status": "Pending", "allowed": ""})
    if d:
        s.append({"from": e + DECIDE, "holder": after_flip, "status": d["status"], "allowed": d.get("allowed", "")})
    return s


def main():
    tag, e, out = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
    n = 0
    for case in CASES["cases"]:
        claim = {"number": case["claim_number"]}
        body = page(CASES["debtor_name"], CASES["case_number"], claim, case["filed"], case["claim_amount_text"], schedule(case, e))
        p = out / "register" / tag / f"claim-{case['claim_number']}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        n += 1
    print(json.dumps({"tag": tag, "e": e, "pages": n, "dir": str(out / "register" / tag)}))


if __name__ == "__main__":
    main()
