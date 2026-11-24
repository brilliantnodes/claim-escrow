import "./style.css";
import { createClient, createAccount, generatePrivateKey, abi } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
// Since late November 2026 GenLayer Studio refuses a transaction without a fee distribution.
// Reads stay on genlayer-js 1; every write goes through genlayer-js 2 with a fee estimate
// (about 0.1 test GEN deposited, the unused part refunded).
import { createClient as createWriter, createAccount as createAccountW } from "genlayer-js-studio";
import { studionet as studionetW } from "genlayer-js-studio/chains";
const studioFees = async (w) => { const f = await w.estimateTransactionFees(); return { distribution: f.distribution, feeValue: f.feeValue }; };

// The visitor contract on GenLayer Studio (tools/deploy_visitor.py): the same
// source as the live runs, register host claims.brilliantnodes.com, minimum
// confirmation 60 s. Register pages: tools/make_try_pages.py.
const CONTRACT = "0xF25F7144B7Aa074c376EdB55E8a96826CB47e5b2";
const EXPLORER = "https://explorer-studio.genlayer.com";
const SITE = "https://claims.brilliantnodes.com";
const SLOT = 15 * 60;
const FLIP_AT = 3 * 60; // the register shows the buyer as holder from D + 3 min
const DECIDE_AT = 12 * 60; // and the court's decision from D + 12 min
const CONFIRM = 120;
const TRANSFER_BY = 20 * 60;
const ALLOWANCE_BY = 40 * 60;
const LEAD = 8 * 60; // time to offer, read the baseline and pay before the acceptance deadline
const PAGES_FROM = 1795276800; // first and last slot with a published register page
const PAGES_TO = 1796485500;
const BASELINE_PERIODS = 3; // the contract's baseline_max_periods
const G = 10n ** 18n;
const DEBTOR = "Pellmoor Freight Lines, Inc.";
const BUYER_NAME = "Harrowfield Credit Partners LP";
const FACE = 1000000; // US dollars
const RATE_BP = 6000; // the price is 60% of the allowed amount
const UNITS_PER_GEN = 500000; // $500,000 = 1 test GEN, so the full claim's price is 1.2 GEN
const UPFRONT_BP = 5000;
const NO_DECISION_SELLER_BP = 7000;
const STORIES = {
  full: { letter: "F", title: "Allowed in full", seller: "Quenby Tool & Die LLC",
    text: "The court allows the whole $1,000,000. The seller ends with the whole price, 1.2 GEN: 0.6 at the transfer, 0.6 at the decision." },
  partial: { letter: "P", title: "Allowed at 80%", seller: "Brasswick Conveyor Parts LLC",
    text: "The court allows $800,000. The seller gets the price for that amount, 0.96 GEN in all; the buyer gets 0.24 GEN back." },
  disallowed: { letter: "D", title: "Disallowed", seller: "Tamsford Cold Storage Inc.",
    text: "The court disallows the claim. The seller keeps the 0.6 GEN upfront it received at the transfer; the buyer gets the other 0.6 GEN back." },
};

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = String(text); return n; };
const link = (href, text) => { const a = el("a", null, text); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; return a; };
const RPC = studionet.rpcUrls.default.http[0];
const reader = createClient({ chain: studionet });
function plain(v) {
  if (v instanceof Map) return Object.fromEntries([...v.entries()].map(([k, x]) => [k, plain(x)]));
  if (Array.isArray(v)) return v.map(plain);
  if (typeof v === "bigint") return Number(v) > Number.MAX_SAFE_INTEGER ? v.toString() : Number(v);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, plain(x)]));
  return v;
}
const read = async (fn, args = []) => plain(await reader.readContract({ address: CONTRACT, functionName: fn, args }));
const short = (e) => String((e && (e.shortMessage || e.message)) || e).slice(0, 300);
const nowS = () => Math.floor(Date.now() / 1000);
const pad = (n) => String(n).padStart(2, "0");
const hhmm = (t) => { const d = new Date(t * 1000); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; };
const hhmmss = (t) => { const d = new Date(t * 1000); return `${hhmm(t)}:${pad(d.getUTCSeconds())} UTC`; };
const local = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
function inWords(s) { s = Math.max(0, Math.round(s)); const m = Math.floor(s / 60); return m >= 1 ? `${m} min ${pad(s % 60)} s` : `${s} s`; }
function gen(wei) {
  const n = BigInt(wei); const w = n / G; const f = (n % G).toString().padStart(18, "0").slice(0, 4).replace(/0+$/, "");
  return `${w}${f ? "." + f : ""} GEN`;
}
const usd = (n) => `$${Number(n).toLocaleString("en-US")}`;
const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };

// ------------------------------------------------------------ accounts

const roles = { seller: null, buyer: null };
function useRole(role) {
  let key = store.get(`ce.temp.${role}`);
  if (!key) { key = generatePrivateKey(); store.set(`ce.temp.${role}`, key); }
  const account = createAccount(key);
  roles[role] = { client: createWriter({ chain: studionetW, account: createAccountW(key) }), address: account.address };
  $(`${role}-addr`).textContent = account.address;
}
async function faucet(address) {
  const body = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "sim_fundAccount", params: [address, 20000000000000000000] });
  const r = await fetch(RPC, { method: "POST", headers: { "content-type": "application/json" }, body });
  const j = await r.json();
  if (j.error) throw new Error(j.error.message || "faucet error");
}
async function refreshBalances() {
  for (const role of Object.keys(roles)) {
    const r = roles[role];
    const box = $(`${role}-bal`);
    if (!r) { box.textContent = ""; continue; }
    try {
      const [bal, claim] = await Promise.all([reader.getBalance({ address: r.address }), read("get_claimable", [r.address])]);
      box.textContent = `Wallet: ${gen(bal)}. Credited by the contract: ${gen(claim)}.`;
      if (BigInt(claim) > 0n) {
        const b = el("button", "ghost", "Withdraw");
        b.type = "button";
        b.addEventListener("click", () => send(role, "withdraw", [0], 0n, `Withdraw ${gen(claim)} (${role})`));
        box.append(" ", b);
      }
    } catch { /* keep the last figures */ }
  }
}
const acctError = (m) => { $("acct-error").textContent = m; $("acct-error").hidden = !m; };
$("btn-setup").addEventListener("click", async () => {
  acctError("");
  $("btn-setup").disabled = true;
  try {
    for (const role of Object.keys(roles)) {
      if (!roles[role]) useRole(role);
      const bal = await reader.getBalance({ address: roles[role].address });
      if (BigInt(bal) < 3n * G) await faucet(roles[role].address);
    }
    await new Promise((x) => setTimeout(x, 1500));
  } catch (e) { acctError(`Faucet: ${short(e)}. Try again in a moment.`); }
  $("btn-setup").disabled = false;
  refreshBalances();
});
for (const role of Object.keys(roles)) if (store.get(`ce.temp.${role}`)) useRole(role);

// ------------------------------------------------------------- stories

let story = store.get("ce.story") || "full";
if (!STORIES[story]) story = "full";
function drawStories() {
  const box = $("stories");
  box.replaceChildren();
  for (const [key, s] of Object.entries(STORIES)) {
    const lab = el("label", "story");
    const r = el("input"); r.type = "radio"; r.name = "story"; r.value = key; r.checked = key === story;
    r.addEventListener("change", () => { story = key; store.set("ce.story", key); drawSlot(); });
    lab.append(r, el("strong", null, ` ${s.title}. `), el("span", "small", s.text));
    box.append(lab);
  }
}
function nextSlot() { return (Math.floor((nowS() + LEAD) / SLOT) + 1) * SLOT; }
const claimNo = (st, d) => { const x = new Date(d * 1000); return `T${STORIES[st].letter}-${String(x.getUTCFullYear()).slice(2)}${pad(x.getUTCMonth() + 1)}${pad(x.getUTCDate())}${pad(x.getUTCHours())}${pad(x.getUTCMinutes())}`; };
const registerUrl = (st, no) => `${SITE}/register/try/${st}/claim-${no.toLowerCase()}.html`;
function drawSlot() {
  const d = nextSlot();
  const ok = d >= PAGES_FROM && d <= PAGES_TO;
  $("slot-note").replaceChildren();
  if (!ok) { $("slot-note").textContent = "No register page is published for the next slot. Please check back later."; $("btn-offer").disabled = true; return; }
  const no = claimNo(story, d);
  $("slot-note").append(`Claim ${no} against ${DEBTOR}, face amount ${usd(FACE)}. The buyer must accept by ${hhmm(d)} UTC (your time ${local(d)}, in ${inWords(d - nowS())}). `, link(registerUrl(story, no), "See its register page"), ".");
  $("btn-offer").disabled = false;
}
$("btn-offer").addEventListener("click", async () => {
  if (!roles.seller || !roles.buyer) return acctError("Set up both accounts first.");
  const d = nextSlot();
  const no = claimNo(story, d);
  const args = [roles.buyer.address, BUYER_NAME, STORIES[story].seller, DEBTOR, no, registerUrl(story, no), "USD", FACE, RATE_BP, UNITS_PER_GEN, UPFRONT_BP, CONFIRM, d, d + TRANSFER_BY, d + ALLOWANCE_BY, NO_DECISION_SELLER_BP];
  const res = await send("seller", "offer", args, 0n, `Offer claim ${no}`);
  let id = res && res.answer && res.answer.id;
  if (res && !id) { try { const ids = await read("get_deals_of", [roles.seller.address]); id = ids[ids.length - 1]; } catch {} }
  if (id) { store.set("ce.current", String(id)); openDeal(String(id)); }
});

// ------------------------------------------------------------- the deal

let current = null; // { id, d }
let auto = false, autoCount = 0, lastEnd = 0; // "keep reading for me": the page sends each reading when it is due
const AUTO_MAX = 8;
async function openDeal(id) {
  try { const d = await read("get_deal", [id]); current = { id, d }; render(); $("deal").hidden = false; }
  catch (e) { current = null; $("deal").hidden = true; alert(`Could not open deal ${id}: ${short(e)}`); }
}
async function reload() { if (current) { try { current.d = await read("get_deal", [current.id]); render(); } catch {} } refreshBalances(); }
$("d-reload").addEventListener("click", reload);
$("lookup").addEventListener("submit", (ev) => { ev.preventDefault(); const v = $("lookup-id").value.trim(); if (/^\d+$/.test(v)) openDeal(v); });

const DONE = ["SETTLED", "CANCELLED", "EXPIRED"];
function kv(dl, rows) { dl.replaceChildren(); for (const [k, v] of rows) { dl.append(el("dt", null, k)); const dd = el("dd"); if (v instanceof Node) dd.append(v); else dd.textContent = v; dl.append(dd); } }
const seenText = (x) => x ? `${x.holder ? x.holder.toLowerCase() + " holds it, " : ""}${String(x.status || "").toLowerCase()}${x.amount ? ", allowed " + usd(x.amount) : ""} (${hhmmss(x.at)})` : "not yet";
function render() {
  const d = current.d, t = d.terms, m = d.money;
  $("d-title").textContent = `Deal #${d.id}: claim ${t.claim_number}`;
  $("d-state").textContent = d.state;
  $("d-state").className = `badge ${DONE.includes(d.state) ? "s-closed" : d.state === "ACTIVE" ? "s-active" : "s-offered"}`;
  kv($("d-money"), [["Price (60% of the allowed amount)", gen(d.price)], ["Upfront at the transfer", gen(d.upfront)], ["Paid into escrow", gen(m.escrow)], ["Still in escrow", gen(m.left)], ["Paid to the seller", gen(m.released)], ["Paid back to the buyer", gen(m.refunded)], ["Readings so far", String(d.readings)]]);
  kv($("d-terms"), [["Debtor", t.debtor_name], ["Claim", `${t.claim_number}, face ${usd(t.face_amount)}`], ["Register page", link(t.register_url, "open the page the validators read")], ["Seller", t.seller_name], ["Buyer", t.buyer_name], ["Accept by", hhmmss(t.accept_by)], ["Transfer by", hhmmss(t.transfer_by)], ["Decision by", hhmmss(t.allowance_by)], ["Seen twice, at least", `${t.confirm_seconds} s apart`], ["No decision in time", `the seller gets ${t.no_decision_seller_bp / 100}% of what is left`]]);
  const df = d.decision.first_seen, dc = d.decision.confirmed;
  kv($("d-seen"), [["Baseline (before paying)", seenText(d.baseline)], ["Transfer first seen", d.transfer.first_seen ? hhmmss(d.transfer.first_seen) : "not yet"], ["Transfer confirmed", d.transfer.confirmed_at ? `${hhmmss(d.transfer.confirmed_at)}, status ${String(d.transfer.status).toLowerCase()}` : "not yet"], ["Decision first seen", df ? seenText(df) : "not yet"], ["Decision confirmed", dc ? `${String(dc.status || dc).toLowerCase()}${dc.amount ? ", allowed " + usd(dc.amount) : ""}${d.decision.confirmed_at ? " (" + hhmmss(d.decision.confirmed_at) + ")" : ""}` : "not yet"], ["Last holder seen", d.last_holder ? d.last_holder.toLowerCase() : "not yet"]]);
  const lg = $("d-log"); lg.replaceChildren();
  for (const e of d.log || []) { const li = el("li"); li.append(el("strong", null, `${hhmmss(e.at)} ${e.what}`), el("span", null, e.note ? ` ${String(e.note).replace(/(\d+) wei/g, (_m, n) => gen(n))}` : "")); lg.append(li); }
  drawActions();
}

function lastNoReading(d) {
  const l = (d.log || []).slice(-1)[0];
  return l && l.what === "READING" && /^N\d_/.test(l.note || "") ? `The last reading found nothing usable (${l.note}), so nothing moved; this is the safe outcome. ` : "";
}
function nextStep() {
  const d = current.d, t = d.terms, D = t.accept_by, c = t.confirm_seconds, now = nowS();
  if (DONE.includes(d.state)) return { text: `Done: ${d.settled_reason || d.state}. Each side withdraws what was credited to it (buttons under Accounts).`, can: [] };
  if (d.state === "OFFERED") {
    if (now >= D) return { text: "The acceptance deadline has passed without payment. Apply deadlines to close the offer.", can: ["settle"] };
    if (!d.baseline) return { text: lastNoReading(d) + `Read the register first: it must show the seller holding the claim. The buyer can then pay, until ${hhmmss(D)} (in ${inWords(D - now)}).`, can: ["read"] };
    const stale = d.baseline.at + BASELINE_PERIODS * c;
    if (now > stale) return { text: "The baseline reading is too old for the buyer to rely on. Read the register again.", can: ["read"] };
    return { text: `Baseline good: the seller holds the claim. Buyer, pay the price into escrow before ${hhmmss(Math.min(D, stale))} (in ${inWords(Math.min(D, stale) - now)}).`, can: ["accept"] };
  }
  // ACTIVE
  if (!d.transfer.confirmed_at) {
    if (now < D + FLIP_AT) return { text: `The price is in escrow. The register shows the transfer to the buyer from ${hhmmss(D + FLIP_AT)} (in ${inWords(D + FLIP_AT - now)}). Then read it twice, at least ${c} s apart.`, can: ["settle"] };
    const f = d.transfer.first_seen;
    if (f && now < f + c + 10) return { text: `Transfer first seen at ${hhmmss(f)}. Read again from ${hhmmss(f + c + 10)} (in ${inWords(f + c + 10 - now)}) to confirm it.`, can: ["settle"] };
    return { text: lastNoReading(d) + (f ? "Read the register again to confirm the transfer." : "Read the register: validators open the page and copy the holder, status and allowed amount."), can: ["read", "settle"] };
  }
  if (now < D + DECIDE_AT) return { text: `Transfer confirmed: the upfront went to the seller. The register shows the court's decision from ${hhmmss(D + DECIDE_AT)} (in ${inWords(D + DECIDE_AT - now)}); then read twice again.`, can: ["settle"] };
  const df = d.decision.first_seen;
  if (df && now < df.at + c + 10) return { text: `Decision first seen at ${hhmmss(df.at)}. Read again from ${hhmmss(df.at + c + 10)} (in ${inWords(df.at + c + 10 - now)}) to confirm it.`, can: ["settle"] };
  return { text: lastNoReading(d) + (df ? "Read the register again to confirm the decision." : "Read the register for the court's decision."), can: ["read", "settle"] };
}
const HELP = {
  read: ["Read the register", "Every validator opens the claim's register page and copies five lines; code checks them; validators must agree exactly. One to three minutes."],
  settle: ["Apply deadlines", "Applies any deadline that has passed, without reading the page."],
  accept: ["Buyer: pay the price into escrow", "Sends exactly the price and the terms' fingerprint; a wrong amount is refused and credited straight back."],
};
const readerRole = () => (roles.buyer ? "buyer" : roles.seller ? "seller" : null);
function drawActions() {
  const box = $("d-actions"); box.replaceChildren();
  const ns = nextStep();
  $("d-next").textContent = ns.text;
  const d = current.d;
  const done = DONE.includes(d.state);
  if (!done && d.state === "ACTIVE" && nowS() >= d.terms.accept_by) {
    const lab = el("label", "auto");
    const cb = el("input"); cb.type = "checkbox"; cb.checked = auto;
    cb.addEventListener("change", () => { auto = cb.checked; autoCount = 0; drawActions(); });
    lab.append(cb, el("strong", null, " Keep reading for me. "), el("span", "small", `This page sends each reading as soon as it is due, and reads again after a reading that found nothing usable (at most ${AUTO_MAX} readings; ${autoCount} sent so far). Keep the page open.`));
    box.append(lab);
  }
  if (auto && !busy && ns.can.includes("read") && autoCount < AUTO_MAX && Date.now() - lastEnd > 20000) {
    const who = readerRole();
    if (who) { autoCount += 1; setTimeout(() => send(who, "read_register", [current.id], 0n, `Read the register (automatic reading ${autoCount} of at most ${AUTO_MAX})`), 0); }
  }
  if (done) auto = false;
  for (const c of ns.can) {
    const row = el("div", "act");
    const [label, help] = HELP[c];
    let fn;
    if (c === "accept") fn = () => roles.buyer ? send("buyer", "accept", [current.id, d.digest], BigInt(d.price), `The buyer pays ${gen(d.price)} into escrow`) : acctError("Set up both accounts first.");
    else fn = () => { const who = readerRole(); return who ? send(who, c === "read" ? "read_register" : "settle", [current.id], 0n, c === "read" ? "Read the register" : "Apply deadlines") : acctError("Set up both accounts first."); };
    const b = el("button", c === "settle" ? "ghost" : null, label); b.type = "button"; b.addEventListener("click", fn);
    row.append(b, el("p", "small", help));
    box.append(row);
  }
}

// ------------------------------------------------- transaction lifecycle

const STEPS = [["SENT", "Sent", "Signed in this browser and sent."], ["PENDING", "Queued", "Waiting for a leader."], ["PROPOSING", "Leader works", "One validator runs the call; for a reading it opens the register page now."], ["COMMITTING", "Validators check", "The others run it on their own and vote."], ["REVEALING", "Votes revealed", "Votes are opened and counted."], ["ACCEPTED", "Accepted", "A majority agreed; the new state is recorded and any payout credited."], ["FINALIZED", "Finalized", "The appeal window has passed. A withdrawal reaches the wallet now."]];
const ORDER = STEPS.map((s) => s[0]);
const BAD = { UNDETERMINED: "The validators did not agree, so nothing changed. Read again.", CANCELED: "Cancelled; nothing changed.", LEADER_TIMEOUT: "The leader did not answer in time; check the explorer before trying again.", VALIDATORS_TIMEOUT: "The validators did not answer in time; check the explorer before trying again." };
const statusOf = (tx) => String(tx?.statusName ?? tx?.status_name ?? "").toUpperCase();
function drawSteps(cur, failed) {
  const ol = $("steps"); ol.replaceChildren(); const at = ORDER.indexOf(cur);
  STEPS.forEach(([key, title, help], i) => { const li = el("li"); li.className = failed && i >= Math.max(at, 0) ? (i === Math.max(at, 0) ? "failed" : "todo") : i < at ? "done" : i === at ? (key === "FINALIZED" ? "done" : "now") : "todo"; li.append(el("strong", null, title), el("span", null, help)); ol.append(li); });
}
function answer(tx) {
  try {
    const lr = tx?.consensus_data?.leader_receipt; const r = (Array.isArray(lr) ? lr[0] : lr)?.result;
    if (!r) return null;
    if (r.status === "rollback") return { reverted: String(r.payload || "") };
    if (typeof r.raw === "string") {
      // Studio returns the result as base64: one result-code byte, then the value.
      const bytes = Uint8Array.from(atob(r.raw), (ch) => ch.charCodeAt(0));
      if (bytes[0] === 0) return plain(abi.calldata.decode(bytes.slice(1)));
      return { reverted: new TextDecoder().decode(bytes.slice(1)) || "the call was refused" };
    }
    const p = r.payload;
    if (p && typeof p === "object" && "readable" in p) { try { return JSON.parse(p.readable); } catch { return null; } }
    return null;
  } catch { return null; }
}
let busy = false;
async function send(role, fn, args, value, what) {
  if (busy) return null;
  const who = roles[role];
  if (!who) { acctError("Set up both accounts first."); return null; }
  busy = true; document.querySelectorAll("#d-actions button, #btn-offer").forEach((b) => (b.disabled = true));
  $("life").hidden = false; $("life-what").textContent = what; $("life-hash").replaceChildren(); $("life-note").textContent = "Signing in this browser…"; drawSteps("", false);
  let hash, err;
  try { hash = await who.client.writeContract({ address: CONTRACT, functionName: fn, args, value: value || 0n, fees: await studioFees(who.client) }); } catch (e) { err = e; }
  let out = null;
  if (err) { drawSteps("SENT", true); $("life-note").textContent = `The network did not confirm the send (${short(err)}). Studio's gateway sometimes refuses for a moment when it is busy. It may or may not have gone out, so this page does not resend it: press Reload in a minute and check before trying again.`; auto = false; }
  else {
    $("life-hash").append("Transaction: ", el("code", null, hash), " · ", link(`${EXPLORER}/tx/${hash}`, "view on the explorer"));
    drawSteps("SENT", false);
    let last = "SENT", fin = null; const t0 = Date.now();
    while (Date.now() - t0 < 10 * 60 * 1000) {
      $("life-note").textContent = `Sent ${Math.round((Date.now() - t0) / 1000)} s ago. ${fn === "read_register" ? "A reading takes one to three minutes." : "Usually under a minute."}`;
      await new Promise((r) => setTimeout(r, 6000));
      let tx; try { tx = await reader.getTransaction({ hash }); } catch { continue; }
      const st = statusOf(tx);
      if (st && st !== last && ORDER.includes(st)) { last = st; drawSteps(st, false); }
      if (st === "ACCEPTED" || st === "FINALIZED") { fin = { ok: true, tx }; break; }
      if (BAD[st]) { fin = { ok: false, st }; break; }
    }
    if (!fin) $("life-note").textContent = "Not settled after ten minutes. It may still complete; press Reload later.";
    else if (!fin.ok) { drawSteps(last, true); $("life-note").textContent = BAD[fin.st]; }
    else {
      const ans = answer(fin.tx);
      if (ans && ans.reverted) { drawSteps("REVEALING", true); $("life-note").textContent = `The contract refused this step: ${ans.reverted}`; }
      else if (ans && ans.ok === false) { drawSteps("REVEALING", true); $("life-note").textContent = `Refused and credited straight back: ${ans.error}`; }
      else if (ans && ans.reading) { const r = ans.reading; $("life-note").textContent = r.kind === "READ" ? `Validators agreed on: holder ${String(r.holder).toLowerCase()}, status ${String(r.status).toLowerCase()}${r.amount ? ", allowed " + usd(r.amount) : ""}.` : `No reading (${r.reason}); nothing moved. Read again.`; }
      else if (ans && ans.read === false && ans.note) $("life-note").textContent = ans.note;
      else if (ans && ans.amount) $("life-note").textContent = `Accepted: ${gen(ans.amount)} is on its way; it reaches the wallet when the transaction is finalized.`;
      else $("life-note").textContent = "Accepted by a majority of validators.";
      out = { hash, answer: ans };
    }
  }
  busy = false; lastEnd = Date.now(); document.querySelectorAll("#d-actions button, #btn-offer").forEach((b) => (b.disabled = false));
  await reload();
  return out;
}

// ----------------------------------------------------------------- start

$("foot-contract").append("Contract on GenLayer Studio: ", link(`${EXPLORER}/address/${CONTRACT}`, CONTRACT), " · ", link(`https://studio.genlayer.com/?import-contract=${CONTRACT}`, "open it in GenLayer Studio"));
drawStories();
drawSlot();
refreshBalances();
const qid = new URLSearchParams(location.search).get("id");
const start = qid && /^\d+$/.test(qid) ? qid : store.get("ce.current");
if (start) openDeal(start);
setInterval(() => { drawSlot(); if (current) drawActions(); }, 5000);
setInterval(() => { if (current && !busy && document.visibilityState === "visible") reload(); }, 60000);
