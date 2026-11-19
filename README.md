# ClaimEscrow

**Escrow for the purchase of a bankruptcy claim, settled on GenLayer from the claim's entry in the public claims register.** The whole price sits in escrow, and it moves only on what validators read on the register page: who holds the claim, its status and its allowed amount. Code decides every amount.

**Live on GenLayer Studio:** contract [`0x0Ea5b829bF0EF137a4EBbDFd6A6B30d22bAD9674`](https://explorer-studio.genlayer.com/address/0x0Ea5b829bF0EF137a4EBbDFd6A6B30d22bAD9674), nine fictional deals, 67 transactions, all finalized ([results](#live-results)) · **Live on Testnet Bradbury:** contract [`0xdE2e969ecFE0229849ad95CF3Df8aC803F079131`](https://scan.bradbury.genlayer.com/address/0xdE2e969ecFE0229849ad95CF3Df8aC803F079131), the same nine deals, 70 transactions, all finalized ([results](#run-b1-on-testnet-bradbury)) · **Video (1.5 min, with voice):** https://claims.brilliantnodes.com/claimescrow-demo.mp4 · **Site:** https://claims.brilliantnodes.com · **Contract source:** [`contracts/claim_escrow.py`](contracts/claim_escrow.py) · **Live runs:** see [Live results](#live-results) · MIT

> Fictional case, debtor, creditors and agent; test GEN only. Not legal advice.

## The trust problem

When a company goes bankrupt, its creditors hold claims against it, and claims are bought and sold. A supplier that is owed money and wants cash now sells its claim to an investor who will wait. The price is a share of the claim's amount, but what the claim is worth is decided later: it is allowed in full, cut, or rejected.

Today one side has to trust the other:

- **The buyer pays in full** and must chase the seller for a refund if the claim is later cut or rejected (the seller's "recourse" obligation); or
- **the buyer holds part of the price back**, and the seller must trust the buyer to pay it when the claim is allowed.

For small trade claims, chasing a refund costs more than it returns, so the risk is simply priced in or the trade does not happen. Yet the facts that decide the money are public: the claims register shows who holds each claim, its status and its allowed amount. It is a web page made for people, with no feed a contract can use.

ClaimEscrow puts the money in escrow and lets GenLayer validators read that page.

## How it works

1. **Offer.** The seller freezes the terms with `offer(...)`:
   - the buyer's address, and **both parties' names** as the register would show them (the two names must differ and neither may contain the other);
   - the debtor, the claim number and the claim's register page, with no query string or fragment; its host must be on the list **frozen when the contract was deployed** (`get_rules()` shows it);
   - the currency, the face amount, the price rate (`rate_bp`), the conversion to test GEN (`units_per_gen`) and the share released at transfer (`upfront_bp`);
   - `confirm_seconds` (how long a state must persist; at least the deployment's minimum), and three deadlines: `accept_by`, `transfer_by` and `allowance_by`, each leaving room for two confirmation periods after the one before;
   - `no_decision_seller_bp`: the seller's share of what is left if no decision is confirmed by `allowance_by`, because many claims are allowed by silence and the register may never say so.
2. **Baseline.** Before the buyer can pay, a reading (`read_register`) must show the claim held by the seller, `PENDING` or `ALLOWED`. At `accept` it must be at most three confirmation periods old.
3. **Accept.** The buyer pays exactly the price with `accept(deal_id, terms_digest)`, consenting to the exact terms by their sha256 digest. A refused accept credits the GEN back instead of reverting. The deal joins the buyer's list (`get_deals_of`) only then, so nobody can flood a buyer's list with offers.
4. **Readings.** Anyone may call `read_register`. Every validator renders the page; its model copies the debtor, the claim number, and for the holder, the status and the allowed amount both the value and the label of its line. Plain Python decides everything that moves money (below).
5. **Nothing moves on one look.** A state counts once it is **seen twice, at least `confirm_seconds` apart**, by each reading's own transaction stamp. Three counts:
   - **transfer:** the holder is the buyer. A reading with another holder restarts it. The confirming reading must be stamped before `transfer_by`.
   - **decision** (only after the transfer is confirmed): the status and the amount. Another status or amount restarts it; a holder change does not, so the buyer cannot reset it by moving the claim to an affiliate and back. It must be confirmed before `allowance_by`, and not at a reading that shows the seller as holder.
   - **holder after the transfer:** the holder counts as changed (for example, the seller holds the claim again) only when seen twice, before `allowance_by`. While the seller is confirmed as holder, no decision settles, and only the buyer seen twice clears that: a third party seen twice does not.
   A `NO_READING` never restarts a count.
6. **Money**, all integers, every step summing exactly to the escrow:

   | Confirmed event | Seller | Buyer |
   |---|---|---|
   | Transfer, claim `PENDING` | the upfront (`upfront_bp` of the price) | nothing yet |
   | Transfer, claim `ALLOWED` at A | the smaller of the upfront and the price for A | nothing yet |
   | Transfer, claim dead or unclear | nothing yet | nothing yet |
   | Decision `ALLOWED` at A (capped at face) | the price for A, less what it already received, never below zero | the rest |
   | Decision `DISALLOWED` | keeps what it received | what is left |
   | Decision `WITHDRAWN`, the register showed the buyer holding the claim live (`PENDING` or `ALLOWED`) since the buyer was last first seen as holder (one reading with another holder before the transfer resets this) | what is left (withdrawing is the holder's act) | keeps what it received |
   | Decision `WITHDRAWN`, already shown when the transfer was confirmed, never shown live with the buyer | keeps what it received | what is left |
   | `WITHDRAWN` after a transfer confirmed while the status was unclear or disallowed, never shown live | no decision: nobody can tell who withdrew it, so the long stop's split applies | |
   | No transfer confirmed by `transfer_by` (+30 min) | nothing | everything back |
   | No decision by `allowance_by` (+30 min) | `no_decision_seller_bp` of what is left | the rest; all of it if the seller was confirmed as holder again |

   If no upfront was released at the transfer (the status was unclear, an agent printing "Transferred" say, or dead), the upfront is released later, once the buyer is seen holding the claim live twice, `confirm_seconds` apart, before `allowance_by`; its amount follows the reading that completes that run. Either way the upfront only tops the seller up to the upfront level: what the buyer has already released counts toward it. If the claim is allowed below what the upfront already paid, the gap is recorded as a **shortfall**: released money is never taken back. `paid_at_decision` records what the seller was actually paid at the decision (less than what was due if it had refunded part). A deal whose upfront empties the escrow closes at once.
7. **Deadlines need no model.** `settle(deal_id)` applies them, and so does any write; `transfer_by` and `allowance_by` each take effect 30 minutes late (an offer not accepted by `accept_by` expires at once). A reading stamped before a deadline still counts if it is processed in those 30 minutes, even after a later `settle()`, `release()` or `refund()`: counts and the `transfer_by` / `allowance_by` cut-offs use the reading's own stamp, deadlines use the deal's clock, which never runs backwards. A reading stamped before the buyer accepted, or before a reading already applied, is ignored, so the order the network processes readings in cannot shorten a count. A dead page cannot lock the money.
8. **Either side may give money to the other at any time:** the buyer `release`s to the seller (it counts against the final price), the seller `refund`s the buyer. There are no proposals to accept, so nothing can be agreed after money has already moved.
9. **Payouts are credits.** Each address takes its own with `withdraw()`. `totals()` reconciles the contract's balance as `locked + credited`, once every withdrawal has finalized.

## What validators do, and what code does

**The model copies; code decides.** For each reading, code:

- requires the page to be the entry of this claim number in this debtor's case: the debtor's name must be on the page as whole words, and the claim number must be printed as a whole token (`1042` does not match inside `21042`, `10432`, `1042-1`, `1042.1` or `1042/2`);
- acts on the model's answers that the page shows other claims or more than one holder, and refuses the page; by itself, it refuses a page that mentions a partial transfer anywhere. The model is not asked whether anything qualifies the entry: when it was (live run s4, an unpublished partial run), one validator's model disagreed on the plainest page, so code alone checks the lines next to each field (below);
- requires each copied label to be on a **closed list** (holder: `Creditor`, `Current holder`, `Claimant` and the like; status: `Status`, `Claim status`; amount: `Allowed amount` and the like, not `Claim amount`);
- requires **exactly one line** written as each field's label (`Status:`, `Creditor:`, `Status = ...`: the label followed by `:`, `|` or `=`), so a status line in an objection block or a `Creditor:` line in a notice address refuses the page. On a page whose table cells are joined by spaces (`Claim Status Pending`) no line is written that way, so this check does not apply and only the model's choice of line protects the money. Code also refuses a field whose next non-blank line qualifies it (a bracket, "partial", "voting purposes", "subject to", "reduced", "reserved", or a next line that starts with "as transferee of" or "as assignee of", the tail of a holder name that wraps), and a field on the last line of a page cut at 12,000 characters, since what followed it is unknown;
- **anchors every copy on the validator's own rendering of the page:** the label must **start its line** (only spaces, bullets or separators before it), the value must follow it with only separators in between (or start the next line), and run to the end of its line (a closing `|` allowed). So `Status` does not anchor inside `Voting status: Allowed` or `Objection status: Withdrawn`, `Creditor` not inside `Original creditor: ...`, `Allowed amount` not inside `Previously allowed amount: ...`; and a copy must be the whole value: `Allowed` is not a copy of `Allowed for voting purposes only` or `Not allowed`, and `$1,000,000` is not a copy of `$1,000,000.00`;
- looks the **whole status text** up in a closed phrase table. `Allowed`, `Allowed in full`, `Allowed in part`, `Deemed allowed`, `Disallowed`, `Disallowed by court order`, `Withdrawn by claimant` and a few more are listed; **anything else is `UNCLEAR` and moves no money**: `Not allowed`, `Allowed for voting purposes only`, `Disallowed in part`, `Objection withdrawn`, `Expunged`, `Amended`, `Superseded`, `Duplicate`, `Expunged, amended by claim 1234`, `Reduced and allowed`, `Satisfied`, `Transferred`. Every dash is read as `-`, so `Filed — Pending` is `PENDING`;
- classes the holder as `BUYER`, `SELLER` or `OTHER` by comparing every word of the name (punctuation turned into spaces). "X as transferee of Y" (or "as assignee of", with or without brackets) is X **only if Y is the other party's name, word for word**: a transfer from someone else, or one with any note after the names such as `(partial: $125,000.00)`, is `OTHER`;
- reads the allowed amount with exact integer parsing (cents dropped); a scale word, another currency, brackets, an ambiguous format or zero is no reading;
- refuses a page whose numbers use decimal commas, skipping reference lists (`Docket Nos. 12,15`, `note 4, 5 and 7`) and dotted addresses; the page is cut to 12,000 characters at a line break, so no status phrase, name or number is cut in two.

**Agreement is exact on everything stored.** A validator accepts the leader's result only if it equals its own: kind, reason, holder class, status and amount. A `NO_READING` binds nothing, so disagreement on it only means someone reads again.

## Live results

Run **s8** on GenLayer Studio, 18 Nov 2026, with this contract version: contract [`0x0Ea5b829bF0EF137a4EBbDFd6A6B30d22bAD9674`](https://explorer-studio.genlayer.com/address/0x0Ea5b829bF0EF137a4EBbDFd6A6B30d22bAD9674), nine fictional deals on the demo register, **67 transactions, all finalized**. [`tools/verify.py`](tools/verify.py) re-read every transaction from the chain after finalization: all 67 match the record, and after both parties withdrew, the contract's balance, the locked total and the credits are all zero ([record](examples/live-studio-s8.json), [check](examples/live-studio-s8-check.json)). The site replays the run: https://claims.brilliantnodes.com. Amounts are test GEN.

| Case | Claim | Price | Seller got | Buyer got | Shortfall | Ended |
|---|---|---|---|---|---|---|
| Allowed in full | 1042 | 7.5 | 7.5 | 0 | 0 | claim allowed at 1250000 USD |
| Allowed at 80% | 1077 | 5.5 | 4.4 | 1.1 | 0 | claim allowed at 800000 USD |
| Allowed at 50% with a 60% upfront | 1103 | 4.8 | 2.88 | 1.92 | 0.48 | claim allowed at 400000 USD |
| Disallowed after the transfer | 1129 | 3 | 1.2 | 1.8 | 0 | claim disallowed after the transfer |
| Withdrawn after the transfer | 1156 | 2.5 | 2.5 | 0 | 0 | claim withdrawn after the transfer |
| Never transferred | 1188 | 3.5 | 0 | 3.5 | 0 | no confirmed transfer by transfer_by |
| Unclear status until the long stop | 1204 | 4.5 | 3.825 | 0.675 | 0 | no confirmed decision by allowance_by; split by no_decision_seller_bp |
| One-sided release and refund, then allowed in full | 1231 | 5 | 4.5 | 0.5 | 0 | claim allowed at 1000000 USD |
| Withdrawn before the buyer held it live | 1257 | 2 | 0 | 2 | 0 | claim withdrawn before the buyer was shown holding it live |

In every case the seller's and the buyer's amounts add up to the price in escrow. Row 1, an offer naming a register host that is not on the deployment's frozen list, was not sent in this run: Studio's gateway answered its gas estimate with an error page. In runs s1 and s2 the same offer was sent and the contract refused it ("register_url's host must be one of this deployment's register hosts"), and a read-only call shows this deployment refuses it too. The seller withdrew 26.805 GEN. The buyer withdrew 18.994999999999999999 GEN: 11.495 GEN from the nine deals, plus 7.499999999999999999 GEN credited back by the refused `accept` in row 12, which sent 1 wei less than the price on purpose. Row 64 is a reading sent for a deal that had already settled at the reading before (the claim was withdrawn before the buyer held it live); the contract refused it.

<details>
<summary>All 68 calls of run s8 (67 transactions; row 1 was not sent)</summary>

| # | Case | Call | Outcome | Tx |
|---|---|---|---|---|
| 1 | refused offer | `offer` | SEND_FAILED / None |  |
| 2 | full | `offer` | ACCEPTED / SUCCESS · OFFERED | [`0x05e36aeb…`](https://explorer-studio.genlayer.com/tx/0x05e36aeb394968fc5e1cc9feed668bc57d7ba1860cc78cd594ce2577cfe04142) |
| 3 | eighty | `offer` | ACCEPTED / SUCCESS · OFFERED | [`0x2a8698bd…`](https://explorer-studio.genlayer.com/tx/0x2a8698bd80afe169a87535a534bdecef87a1359f6fc21c2e1e52c85e1f79ec68) |
| 4 | shortfall | `offer` | ACCEPTED / SUCCESS · OFFERED | [`0x29933c6d…`](https://explorer-studio.genlayer.com/tx/0x29933c6df806d9e57cad9d1f1ab1225ab3239049f8ef1fed15120ddd9b85bb63) |
| 5 | disallowed | `offer` | ACCEPTED / SUCCESS · OFFERED | [`0x25dc8338…`](https://explorer-studio.genlayer.com/tx/0x25dc83382fda2397fdef427294c95f4aaf5b41824826a44d222e2bbbdc2eedc6) |
| 6 | withdrawn | `offer` | ACCEPTED / SUCCESS · OFFERED | [`0xabefc11b…`](https://explorer-studio.genlayer.com/tx/0xabefc11b6b1e16cea9dfc6304d06a76264a73e45bad3f812e80db6f8bed65469) |
| 7 | no_transfer | `offer` | ACCEPTED / SUCCESS · OFFERED | [`0x325d083e…`](https://explorer-studio.genlayer.com/tx/0x325d083e5b944d6d012fb446fab5253c80624661363eaf9cd9de779dfb93f546) |
| 8 | unclear | `offer` | ACCEPTED / SUCCESS · OFFERED | [`0x18446308…`](https://explorer-studio.genlayer.com/tx/0x1844630860f355fd35dc3586baf3ffdbfe3a30c4adcbacfb9f1ac13299a4ed22) |
| 9 | one_sided | `offer` | ACCEPTED / SUCCESS · OFFERED | [`0xb3f79b93…`](https://explorer-studio.genlayer.com/tx/0xb3f79b933f559f479ea9fe58822f5496abbd023809e7b145a54f821153ab17f8) |
| 10 | withdrawn_early | `offer` | ACCEPTED / SUCCESS · OFFERED | [`0xb02b3f90…`](https://explorer-studio.genlayer.com/tx/0xb02b3f90feb24d13f20e0bde2a977cd32f618c2e58e76fe74cf4a74ac57c376a) |
| 11 | full | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0xd67e10be…`](https://explorer-studio.genlayer.com/tx/0xd67e10bec4efd87f7b59538ca282761d13456bf29d1e3bafdb3b9b406b584a61) |
| 12 | full | `accept` | ACCEPTED / SUCCESS · refused: send exactly the price: 7500000000000000000 wei (refunded 7.5 GEN) | [`0x186f3013…`](https://explorer-studio.genlayer.com/tx/0x186f301386cceb4eeaf0cb13f920a7642f7f46c5d0a47321b04e5b25f0e4c50b) |
| 13 | full | `accept` | ACCEPTED / SUCCESS · ACTIVE | [`0xaf097503…`](https://explorer-studio.genlayer.com/tx/0xaf0975032e9a3e8be23ef525bc162a392ccacd224dee50ef92013a4a8a660e47) |
| 14 | eighty | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0x27b12e16…`](https://explorer-studio.genlayer.com/tx/0x27b12e1661569f6a08c6fe2acbd2358b2ca38e23b556469363a97959d306c7f5) |
| 15 | eighty | `accept` | ACCEPTED / SUCCESS · ACTIVE | [`0xf76a8472…`](https://explorer-studio.genlayer.com/tx/0xf76a8472102501a75afbcae2d78aa39a67c23d9ac45b888c21f442261cc29162) |
| 16 | shortfall | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0xa1d8447c…`](https://explorer-studio.genlayer.com/tx/0xa1d8447cb241b290d76dbc2c51644f2729dc97c26862a1de83151a8b3d133dcf) |
| 17 | shortfall | `accept` | ACCEPTED / SUCCESS · ACTIVE | [`0x87c2b2e1…`](https://explorer-studio.genlayer.com/tx/0x87c2b2e18878b21356b5d3e707c094ad86b2df970a57f99b691eae80a9c13f8d) |
| 18 | disallowed | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0xf80a18b7…`](https://explorer-studio.genlayer.com/tx/0xf80a18b7417f656e9c93ba4c6be0afda5a51f1be4dd9741a762ec862efbdaba5) |
| 19 | disallowed | `accept` | ACCEPTED / SUCCESS · ACTIVE | [`0x3da0b0f9…`](https://explorer-studio.genlayer.com/tx/0x3da0b0f9f74514b89e3878bf572daf168bc3998398fc3d8240c76729732fb920) |
| 20 | withdrawn | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0xd6468ce3…`](https://explorer-studio.genlayer.com/tx/0xd6468ce31f26ac40df1f7f05edaa511f3c94e0d3626bf633ba8c255676cdb1e7) |
| 21 | withdrawn | `accept` | ACCEPTED / SUCCESS · ACTIVE | [`0x0dd18142…`](https://explorer-studio.genlayer.com/tx/0x0dd181427597af63439a6170e01096c200fb1f6a2c552fed9145c083a74efdcb) |
| 22 | no_transfer | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0x96c305ef…`](https://explorer-studio.genlayer.com/tx/0x96c305ef35289a0d2a9225741838b8517abccc6719ffbed4f3eb377445e9c23a) |
| 23 | no_transfer | `accept` | ACCEPTED / SUCCESS · ACTIVE | [`0x4078ff22…`](https://explorer-studio.genlayer.com/tx/0x4078ff220d1c0d584cd9223c24f5f17a3047f846e1aea0da393eaca23e915ef8) |
| 24 | unclear | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0x10dc51fe…`](https://explorer-studio.genlayer.com/tx/0x10dc51fed5d9318a8766d39f43cd1d146d3c4ffc03c795cac2aacee17224a73d) |
| 25 | unclear | `accept` | ACCEPTED / SUCCESS · ACTIVE | [`0x6ac6c136…`](https://explorer-studio.genlayer.com/tx/0x6ac6c13629bb662996acd5f0be674d10b6da25c2f5627bec00d623a5f90ca4c0) |
| 26 | one_sided | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0x12512edb…`](https://explorer-studio.genlayer.com/tx/0x12512edb6e676b020b681c4ef902d663e87f3526cf04ccbfdac79e5940547fc7) |
| 27 | one_sided | `accept` | ACCEPTED / SUCCESS · ACTIVE | [`0x13895e14…`](https://explorer-studio.genlayer.com/tx/0x13895e14713877e164300857872f4aa2dadf7bcca12267e41d4c58c9b926b5d9) |
| 28 | withdrawn_early | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0x814078cc…`](https://explorer-studio.genlayer.com/tx/0x814078ccb4dd60e330046a06e27ae99a0bb6e03ef9e9347928dab27a7dc09537) |
| 29 | withdrawn_early | `accept` | ACCEPTED / SUCCESS · ACTIVE | [`0x65b67295…`](https://explorer-studio.genlayer.com/tx/0x65b67295eb14b8c3a1b51670d7384520292b1ae5c102b09a624654044d946012) |
| 30 | one_sided | `release` | ACCEPTED / SUCCESS · ACTIVE | [`0xf1161918…`](https://explorer-studio.genlayer.com/tx/0xf1161918fa0f140a4b64039d14fce535d9af8d1af54235e1ebbc754c1df3e090) |
| 31 | one_sided | `refund` | ACCEPTED / SUCCESS · ACTIVE | [`0xdcd80d4c…`](https://explorer-studio.genlayer.com/tx/0xdcd80d4c31419563237340903870496cb159a0dedd2c947ba8935bdd7e1b5ea7) |
| 32 | full | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x372ba85a…`](https://explorer-studio.genlayer.com/tx/0x372ba85a834430ec6bfcf7b38cc6bcae25b93b8837c278357008b862a27d63e6) |
| 33 | shortfall | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x278f8910…`](https://explorer-studio.genlayer.com/tx/0x278f8910ff712e016d72d3427fbdf301a5f1d8528fda79cb07b809f7a26f6bae) |
| 34 | eighty | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x6f041aad…`](https://explorer-studio.genlayer.com/tx/0x6f041aad3d71f27e1e09ff0eda6ce0bcc1c3d174b5f91b7c5af33be3fd2f0495) |
| 35 | disallowed | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0xc8d47740…`](https://explorer-studio.genlayer.com/tx/0xc8d47740ebf3801c0ca98f87c8438b4163b37aa30dbe3a0fb38a5db19e05c58e) |
| 36 | withdrawn | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0xda76bfce…`](https://explorer-studio.genlayer.com/tx/0xda76bfceabdfb941ebc410cdda0e978590b85d02cdd619146548679c9b4d5c18) |
| 37 | no_transfer | `read_register` | ACCEPTED / SUCCESS · SELLER PENDING | [`0x1f58d846…`](https://explorer-studio.genlayer.com/tx/0x1f58d8464cb57966ef2a93007087896aa9fbc99d2dd14c9cd814dfb7d5d8432d) |
| 38 | unclear | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x8b720357…`](https://explorer-studio.genlayer.com/tx/0x8b720357848d707587481d27475caf6fd55578da74dbee4a9966a3f7377af89f) |
| 39 | one_sided | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x506bf92f…`](https://explorer-studio.genlayer.com/tx/0x506bf92f3057ae55e8c66afebd218e02efd743144069ee267a35324c75dcfdd0) |
| 40 | withdrawn_early | `read_register` | ACCEPTED / SUCCESS · BUYER WITHDRAWN | [`0x91fff8e9…`](https://explorer-studio.genlayer.com/tx/0x91fff8e9b05789af851debfd086f1e9b44f132ae60dd2513b0f363dc0bd7ccdc) |
| 41 | full | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x0817c3fe…`](https://explorer-studio.genlayer.com/tx/0x0817c3fe9324e66951e4d7f38d0b8a759e8190aeafa6f802cfef567c8e21cb19) |
| 42 | eighty | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x4363a6a2…`](https://explorer-studio.genlayer.com/tx/0x4363a6a270a32a8c03b0a6c91861bacde235dff532684c33d13e64f1ebaffd02) |
| 43 | shortfall | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x33e372f2…`](https://explorer-studio.genlayer.com/tx/0x33e372f285564a36faae3ec95c8ff88a5331c3b35995a965fd0c3553e5e24bcc) |
| 44 | disallowed | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x5667d73c…`](https://explorer-studio.genlayer.com/tx/0x5667d73c34cb992dd7141f594ae1466dbd006025a2d02a51898d868f255becc4) |
| 45 | withdrawn | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x058219ed…`](https://explorer-studio.genlayer.com/tx/0x058219ed24050ba8a20a0262b24897c2bf87e7bd718635851dacebb6ecdc3c33) |
| 46 | unclear | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x7cacb70a…`](https://explorer-studio.genlayer.com/tx/0x7cacb70abc5025b835061e18276da8581b784dcf31e17754d85f18c02f3e9312) |
| 47 | one_sided | `read_register` | ACCEPTED / SUCCESS · BUYER PENDING | [`0x0a910744…`](https://explorer-studio.genlayer.com/tx/0x0a9107441496ae80735b67178494a4496a382ba673f61ed1d3e7b1c8b5deb43d) |
| 48 | withdrawn_early | `read_register` | ACCEPTED / SUCCESS · BUYER WITHDRAWN | [`0x2452a265…`](https://explorer-studio.genlayer.com/tx/0x2452a26559b32dad701d0d14e5b95988b40094f682e31c771fee33acda76c399) |
| 49 | eighty | `read_register` | ACCEPTED / SUCCESS · BUYER ALLOWED 800,000 | [`0x3fd4a9c3…`](https://explorer-studio.genlayer.com/tx/0x3fd4a9c3c0c2846d2076536e2bd7448442871552f8117a8fd842cda2751782a0) |
| 50 | disallowed | `read_register` | ACCEPTED / SUCCESS · BUYER DISALLOWED | [`0x2e1b4c06…`](https://explorer-studio.genlayer.com/tx/0x2e1b4c069e160ac0fa85246abf6c607cc314fa86d1838042fd9e3276323ef9cf) |
| 51 | full | `read_register` | ACCEPTED / SUCCESS · BUYER ALLOWED 1,250,000 | [`0x3771831f…`](https://explorer-studio.genlayer.com/tx/0x3771831f4518c6ec42949e080604bc6bd9be39c54f6f622420bcd2a667aff3ba) |
| 52 | withdrawn | `read_register` | ACCEPTED / SUCCESS · BUYER WITHDRAWN | [`0x39595721…`](https://explorer-studio.genlayer.com/tx/0x3959572198ac6814493b4b62aad071b047c2b880ef4ef07664b484a55d5db15a) |
| 53 | one_sided | `read_register` | ACCEPTED / SUCCESS · BUYER ALLOWED 1,000,000 | [`0x3359b413…`](https://explorer-studio.genlayer.com/tx/0x3359b4130d9337e31bd29b77a125acd5d673abeec77508a0fa7e55526a58d5e2) |
| 54 | withdrawn_early | `read_register` | ACCEPTED / SUCCESS · BUYER WITHDRAWN | [`0x2a561c07…`](https://explorer-studio.genlayer.com/tx/0x2a561c075c9165ea616205631a8af4abb535ed518532dab1ba0fd1af357e91bd) |
| 55 | unclear | `read_register` | ACCEPTED / SUCCESS · BUYER UNCLEAR | [`0x8709161e…`](https://explorer-studio.genlayer.com/tx/0x8709161e1617abf066faada40caefe0cfc46f4543e03fff44718b6bd25562309) |
| 56 | shortfall | `read_register` | ACCEPTED / SUCCESS · BUYER ALLOWED 400,000 | [`0x5ce83f38…`](https://explorer-studio.genlayer.com/tx/0x5ce83f383492a318b5ad343df233cb3a011f614516190f6a96cd27d55e137d09) |
| 57 | full | `read_register` | ACCEPTED / SUCCESS · BUYER ALLOWED 1,250,000 | [`0xe510eae4…`](https://explorer-studio.genlayer.com/tx/0xe510eae4f1cf3d4909e59f245ccd4d0a38f6a228abdbb64e6eeaec8b3be69341) |
| 58 | eighty | `read_register` | ACCEPTED / SUCCESS · BUYER ALLOWED 800,000 | [`0xd5ee309e…`](https://explorer-studio.genlayer.com/tx/0xd5ee309e25a3fc8532994ceff1257fcad62423e160650aa77556058d51cd369c) |
| 59 | shortfall | `read_register` | ACCEPTED / SUCCESS · BUYER ALLOWED 400,000 | [`0x83c4c60d…`](https://explorer-studio.genlayer.com/tx/0x83c4c60d270bd5b610dbb9e13134a68185afac16dd8bca7b6575e3478d25788f) |
| 60 | disallowed | `read_register` | ACCEPTED / SUCCESS · BUYER DISALLOWED | [`0xd42b09f4…`](https://explorer-studio.genlayer.com/tx/0xd42b09f4680b51a7a420329a1f2e0d514b3d64d13a2859e2dbb4088bd70e56fe) |
| 61 | withdrawn | `read_register` | ACCEPTED / SUCCESS · BUYER WITHDRAWN | [`0x75ee7e82…`](https://explorer-studio.genlayer.com/tx/0x75ee7e821037ea1cefb5bb2945fee56cc1b86cb149e849b4197dab281958abb6) |
| 62 | unclear | `read_register` | ACCEPTED / SUCCESS · BUYER UNCLEAR | [`0x37f3316b…`](https://explorer-studio.genlayer.com/tx/0x37f3316b654c70f6793539849311bdd2a85a82eb89071d5fc0bd376fba5c47a8) |
| 63 | one_sided | `read_register` | ACCEPTED / SUCCESS · BUYER ALLOWED 1,000,000 | [`0x4df51f94…`](https://explorer-studio.genlayer.com/tx/0x4df51f946a3b4fac1d3d18292a0dd5eb41b6e2625ba40f80d55f80563972718d) |
| 64 | withdrawn_early | `read_register` | ACCEPTED / ERROR · the deal is SETTLED | [`0xb6df82c0…`](https://explorer-studio.genlayer.com/tx/0xb6df82c04e888f3dbe0b044f96dbd7e856bd3a06c539832308b793bfaa43cc3a) |
| 65 | no_transfer | `settle` | ACCEPTED / SUCCESS · SETTLED: no confirmed transfer by transfer_by | [`0xb287565b…`](https://explorer-studio.genlayer.com/tx/0xb287565bd3113b18b1dde09fdee339b9d9da3e3e248590f53857d07cbc03b72c) |
| 66 | unclear | `settle` | ACCEPTED / SUCCESS · SETTLED: no confirmed decision by allowance_by; split by no_decision_seller_bp | [`0xde5c6bea…`](https://explorer-studio.genlayer.com/tx/0xde5c6bea8b95cb7e0eac38b0e6cdb94554241d6b3ee460bcf4b395bcc2e1da6c) |
| 67 | withdraw | `withdraw` | ACCEPTED / SUCCESS · withdrew 26.805 GEN | [`0x8268e5a2…`](https://explorer-studio.genlayer.com/tx/0x8268e5a21237eeaafdd2e28d52e2d57ecd5b5282f70d5649efc2cbcafce0c88d) |
| 68 | withdraw | `withdraw` | ACCEPTED / SUCCESS · withdrew 18.995 GEN | [`0x01666b05…`](https://explorer-studio.genlayer.com/tx/0x01666b05df92cddb32e789704da20cdf337dc38d5dfb7b110dc6ab57dc059ea6) |

</details>

### Run b1 on Testnet Bradbury

Run **b1** on Testnet Bradbury (Phase 2, GenVM v0.6), 19 Nov 2026, 06:22 to 09:06 UTC, with the same frozen contract (the packed build [`bradbury/build/claim_escrow_packed.py`](bradbury/build/claim_escrow_packed.py), which unpacks to [`bradbury/build/claim_escrow.py`](bradbury/build/claim_escrow.py) byte for byte): contract [`0xdE2e969ecFE0229849ad95CF3Df8aC803F079131`](https://scan.bradbury.genlayer.com/address/0xdE2e969ecFE0229849ad95CF3Df8aC803F079131), the same nine fictional deals at prices 100 times smaller, two test wallets (seller and buyer), **70 transactions (the deploy and 69 calls), all finalized**. [`tools/verify_bradbury.py`](tools/verify_bradbury.py) re-read every transaction from Bradbury after finalization: all 70 are `FINALIZED` and match the record, and after both parties withdrew, the contract's balance, the locked total and the credits are all zero ([record](examples/live-bradbury-b1-merged.json), [check](examples/live-bradbury-b1-merged-check.json)). Every deal ended as it did on Studio in run s8, at one hundredth of the amounts. The site shows this run too: https://claims.brilliantnodes.com. Amounts are test GEN.

| Case | Claim | Price | Seller got | Buyer got | Shortfall | Ended |
|---|---|---|---|---|---|---|
| Allowed in full | 1042 | 0.075 | 0.075 | 0 | 0 | claim allowed at 1250000 USD |
| Allowed at 80% | 1077 | 0.055 | 0.044 | 0.011 | 0 | claim allowed at 800000 USD |
| Allowed at 50% with a 60% upfront | 1103 | 0.048 | 0.0288 | 0.0192 | 0.0048 | claim allowed at 400000 USD |
| Disallowed after the transfer | 1129 | 0.03 | 0.012 | 0.018 | 0 | claim disallowed after the transfer |
| Withdrawn after the transfer | 1156 | 0.025 | 0.025 | 0 | 0 | claim withdrawn after the transfer |
| Never transferred | 1188 | 0.035 | 0 | 0.035 | 0 | no confirmed transfer by transfer_by |
| Unclear status until the long stop | 1204 | 0.045 | 0.03825 | 0.00675 | 0 | no confirmed decision by allowance_by; split by no_decision_seller_bp |
| One-sided release and refund, then allowed in full | 1231 | 0.05 | 0.045 | 0.005 | 0 | claim allowed at 1000000 USD |
| Withdrawn before the buyer held it live | 1257 | 0.02 | 0 | 0.02 | 0 | claim withdrawn before the buyer was shown holding it live |

In every case the seller's and the buyer's amounts add up to the price in escrow. The seller withdrew 0.26805 GEN; the buyer withdrew 0.189949999999999999 GEN: 0.11495 GEN from the nine deals plus 0.074999999999999999 GEN credited back by the refused `accept` in row 12, which sent 1 wei less than the price on purpose. Row 1, an offer naming a register host not on the frozen list, was refused by the contract (`FINISHED_WITH_ERROR`); the same call made read-only returns "register_url's host must be one of this deployment's register hosts (see get_rules)". Row 65 is a fourth reading for a deal that had already settled at its third (withdrawn before the buyer held it live); the contract refused it.

**One reading sent by hand (row 49).** The first reading of deal 1 after the transfer (row 32, 07:15 UTC) came back as no reading, `N1_WRONG_PAGE`: the validators agreed that the copied page did not identify claim 1042's entry, so nothing was counted and no money moved. The buyer was therefore first seen as holder at the second reading (row 41, 07:26), and the script's next reading was not due until after `transfer_by` (07:49): left alone, the deal would have refunded the buyer. At 07:38 one extra `read_register` for deal 1 was sent by hand from the buyer's wallet, outside `tools/live.py`; it confirmed the transfer and released the upfront. It is kept apart in [`examples/live-bradbury-b1-extra.json`](examples/live-bradbury-b1-extra.json) and merged in time order into the published record; the record written by the script is [`examples/live-bradbury-b1.json`](examples/live-bradbury-b1.json), unchanged.

**Timing on Bradbury.** An `offer`, `accept` or `settle` was accepted about 33 seconds after it was sent (median; at most 41). The nine readings of a round share two wallets and go out one after another, so a reading waited and ran 144 seconds in all (median; at most 499). The run therefore used a wider schedule than Studio ([`tools/live.py`](tools/live.py) `SCHED`; register pages from `tools/make_register.py ... --bradbury`): readings at E + 5, 17, 52 and 63 minutes, the decision shown from E + 50, `transfer_by` E + 40, `allowance_by` E + 85. Bradbury receipts carry no return value, so the table below shows each call's consensus result and execution; what each reading saw is in the deal's log (`get_deal`), which the site shows. A deploy of the stripped build failed (intrinsic gas too low) and sent nothing; the packed build deployed in 33 seconds.

<details>
<summary>All 69 calls of run b1 (the deploy is <a href="https://scan.bradbury.genlayer.com/tx/0x5802d925c5a9706501365ab41090a3645d2ab370fd5d9c1a799f401fd8a34c9a">0x5802d925…</a>)</summary>

| # | Case | Call | Outcome | Tx |
|---|---|---|---|---|
| 1 | refused offer | `offer` | MAJORITY_AGREE / FINISHED_WITH_ERROR | [`0x85b2b580…`](https://scan.bradbury.genlayer.com/tx/0x85b2b58027f5eaea70c2ac249c14432888907be0814e93470c222d58aa5d0866) |
| 2 | full | `offer` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x0a10cb9e…`](https://scan.bradbury.genlayer.com/tx/0x0a10cb9edf8e8290dfe3e85cbff91341c1dcc105de36ec0ea62437b3b038dd9b) |
| 3 | eighty | `offer` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x45ecb696…`](https://scan.bradbury.genlayer.com/tx/0x45ecb696ef506ffc53ff499f98425bb0af5603bc065cc490b3ec47f9c7ba6f21) |
| 4 | shortfall | `offer` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x4bd0a947…`](https://scan.bradbury.genlayer.com/tx/0x4bd0a947d706796ade9b2e4fea4ea4974df1d9144d03d36175ae16df7963fd13) |
| 5 | disallowed | `offer` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x61213855…`](https://scan.bradbury.genlayer.com/tx/0x6121385574a1c476ab7c62d610805f4c3d22fa9b891869d0d62cbe34226519f4) |
| 6 | withdrawn | `offer` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x7d92ecf6…`](https://scan.bradbury.genlayer.com/tx/0x7d92ecf6a1a8498690f1ce4c9fdd3bddb1f18544c285beda319fed76653d7a2d) |
| 7 | no_transfer | `offer` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xc4d8e0f7…`](https://scan.bradbury.genlayer.com/tx/0xc4d8e0f72c1104e47f9ac698a603ffc7b19a104c9d9f4b27b6375084a9e30dc7) |
| 8 | unclear | `offer` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x2a783750…`](https://scan.bradbury.genlayer.com/tx/0x2a783750246111182b60c2e17dad13a2a9c2d31ca0c0bca357efece25200ed64) |
| 9 | one_sided | `offer` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xb7a44599…`](https://scan.bradbury.genlayer.com/tx/0xb7a445994f5cec0b84e54c4a5c96598f056c966b96af78f88011d14b3731a477) |
| 10 | withdrawn_early | `offer` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x7174c49b…`](https://scan.bradbury.genlayer.com/tx/0x7174c49b38ca20dd74fdf40774a34fc78f88a87967145004ae4f693ec373ce7e) |
| 11 | full | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x47831b65…`](https://scan.bradbury.genlayer.com/tx/0x47831b65fcaafafc40182b600ea9203b2bed1eb17b14908a3bd3c90dcd6b6342) |
| 12 | full | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xb882ac72…`](https://scan.bradbury.genlayer.com/tx/0xb882ac7205cf0e23c8d055576051631808931ce823af4704532995f84c47d8b6) |
| 13 | full | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x4d30b40b…`](https://scan.bradbury.genlayer.com/tx/0x4d30b40b999a3271b304473df8c87110445e47a011b2b27742fd8b64d35efb35) |
| 14 | eighty | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x0982e3eb…`](https://scan.bradbury.genlayer.com/tx/0x0982e3eb0fc5352b0d5730109ed1ffb9b0c0c02656eb426b647f60e5529b3306) |
| 15 | eighty | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x29cf2386…`](https://scan.bradbury.genlayer.com/tx/0x29cf2386c0ca60c4c3f19bb738e9ad0d5bb6d44e0640be679e42976e773eea08) |
| 16 | shortfall | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x7df32a24…`](https://scan.bradbury.genlayer.com/tx/0x7df32a24fbec2cb540cd908841dc5a9ce02a086c20e0fc6ea39053d34ae8cca8) |
| 17 | shortfall | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x65b79e36…`](https://scan.bradbury.genlayer.com/tx/0x65b79e3676d7ea8940d07ae7e4c7aff4d64dab4b3f99139f01ff72461577e43d) |
| 18 | disallowed | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xd651ea9a…`](https://scan.bradbury.genlayer.com/tx/0xd651ea9add05c9cffa8acfdbd1bbe31d4558609a06d2976e8d9e4d84fd56385b) |
| 19 | disallowed | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x40c94a8b…`](https://scan.bradbury.genlayer.com/tx/0x40c94a8b9d8f4c6391745722e1d2fc8ba82bf1dc1bb6055bd6b513424bd0fa4d) |
| 20 | withdrawn | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xfe944d01…`](https://scan.bradbury.genlayer.com/tx/0xfe944d01f9e4972e96e2733f97bb0f6668d63e578ff130f250c3b8e86b8b9eae) |
| 21 | withdrawn | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xd53d8faf…`](https://scan.bradbury.genlayer.com/tx/0xd53d8fafa18a7c77955d9504187292061d83b7ce0233b75c80b89edba11b5c9d) |
| 22 | no_transfer | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xe6eacaba…`](https://scan.bradbury.genlayer.com/tx/0xe6eacabace6bfa0cc79dc53542c0b4241defda46fa1a625adf2b6aa3b2ac5256) |
| 23 | no_transfer | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x3e242f73…`](https://scan.bradbury.genlayer.com/tx/0x3e242f735b3a77faed734e41d4cf5fceb242884185ae80da39370ac675aae700) |
| 24 | unclear | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x26fcb70e…`](https://scan.bradbury.genlayer.com/tx/0x26fcb70e2047f48fb7db93b683e0d0c2474d61a97cda11fb3e566c5a3d758e7d) |
| 25 | unclear | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x7eb0c9dc…`](https://scan.bradbury.genlayer.com/tx/0x7eb0c9dca60b161508883b962c927beecbbbae16c48762f0149df4784d64724d) |
| 26 | one_sided | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x1ccceccd…`](https://scan.bradbury.genlayer.com/tx/0x1ccceccd6865078ef41c4d8513068475b0a3adbf8a0e8b829af87d1cbc06630e) |
| 27 | one_sided | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x5ad0dfed…`](https://scan.bradbury.genlayer.com/tx/0x5ad0dfed0930b1ac85ae7e55012bf6b313cc6c0417f3b922531f4880e5c2c48c) |
| 28 | withdrawn_early | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x27055195…`](https://scan.bradbury.genlayer.com/tx/0x270551953eb312b055df7e0245d9cf9341f70d66d46fb1622bd199b38235bb61) |
| 29 | withdrawn_early | `accept` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x711857cc…`](https://scan.bradbury.genlayer.com/tx/0x711857ccac3318584fd14fc4868b89631049df0efe671df19fa0d941e4d5d2a4) |
| 30 | one_sided | `release` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xe94c01b0…`](https://scan.bradbury.genlayer.com/tx/0xe94c01b0f39c8f81095b39cd91225dbf454772f0c78796496d48d06388afa46a) |
| 31 | one_sided | `refund` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xfe3f1342…`](https://scan.bradbury.genlayer.com/tx/0xfe3f134205020e7d5e973d74752e241b21d69549e7057f73562cdd54e2040083) |
| 32 | full | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x7c9e2e5b…`](https://scan.bradbury.genlayer.com/tx/0x7c9e2e5b94ff3dfc6d68dc62d360afacd0e17eef3bbd8fd128824c84834da358) |
| 33 | eighty | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x2669ee1e…`](https://scan.bradbury.genlayer.com/tx/0x2669ee1e41d6af7a9188fe29f4c4e41197ae5661bab2c9132ba51303e63e505e) |
| 34 | shortfall | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x1823b7fe…`](https://scan.bradbury.genlayer.com/tx/0x1823b7fe5c0c6e033ac1897c081f8379942c5edaeb336828663dcdeb81ff971d) |
| 35 | disallowed | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xdfb90379…`](https://scan.bradbury.genlayer.com/tx/0xdfb90379d06bb20e87b478e62ee19da75ae0fdc5818a34ce247df7d2feea97b2) |
| 36 | withdrawn | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x06f6ee73…`](https://scan.bradbury.genlayer.com/tx/0x06f6ee737ceb1069db5ba55533806f94aa5fe04f052cf692a783e25873299423) |
| 37 | no_transfer | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xf262fcfd…`](https://scan.bradbury.genlayer.com/tx/0xf262fcfdb657523a7163529337683f2fd93bc09823e72255b6b37f45a9f7ad92) |
| 38 | unclear | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x1fa93149…`](https://scan.bradbury.genlayer.com/tx/0x1fa93149f2edfa3f6004c4cd9eb0efddc57b787093f14ec3015504e77dc6e771) |
| 39 | one_sided | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xdb504be0…`](https://scan.bradbury.genlayer.com/tx/0xdb504be098285e43126d20d5e7605d36d2cb65ad5b0fdd9d43f127a750eedd74) |
| 40 | withdrawn_early | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xd503c56c…`](https://scan.bradbury.genlayer.com/tx/0xd503c56cf97fb77007d4248e2b93e04e724e4763e91c201312a769a9ba573587) |
| 41 | full | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x9016331b…`](https://scan.bradbury.genlayer.com/tx/0x9016331bdc2ce308e72cad07a61031540b38b8d99c7301b1d59c2f50a1e16c86) |
| 42 | eighty | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x241d2ece…`](https://scan.bradbury.genlayer.com/tx/0x241d2ecec1813008c72b0d853768098f12d266a70a2c9755a727b6b8151ad264) |
| 43 | shortfall | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xc0793cfe…`](https://scan.bradbury.genlayer.com/tx/0xc0793cfe4e3138263b06ab7a2614ea8e9e946c65d76fc7c3a390612eff8fb63d) |
| 44 | disallowed | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xd4711e77…`](https://scan.bradbury.genlayer.com/tx/0xd4711e775a6fac80963e064b606bb42c930591f81f5d6e6a957934a351ce78c6) |
| 45 | withdrawn | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xecfffc6e…`](https://scan.bradbury.genlayer.com/tx/0xecfffc6e5f40d5c75ea95e558e516a3ead413b58b9f92c09af0b1055ad85d0d3) |
| 46 | unclear | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x36ec173f…`](https://scan.bradbury.genlayer.com/tx/0x36ec173feaa6bbef5dfc1970ce0d689890187890685dbd8220647e76c070d8ae) |
| 47 | one_sided | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xaa6f09a3…`](https://scan.bradbury.genlayer.com/tx/0xaa6f09a359a5f8b2b7f7236d2410540e6fd79614e6f6a26965de8b17d4175394) |
| 48 | withdrawn_early | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x8a27ba5f…`](https://scan.bradbury.genlayer.com/tx/0x8a27ba5f04947bbea2e0741bae6d3f4628181b8e32e92e11d5f6ebb7c2ffa0e6) |
| 49 | full | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x2199216c…`](https://scan.bradbury.genlayer.com/tx/0x2199216cd95a92831a4dd71e872d695a5cffe0d217a96f2b23470278ae08c767) |
| 50 | full | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x88565e20…`](https://scan.bradbury.genlayer.com/tx/0x88565e20cf67a59c6f65c7be3f8c0908aac6e9456e94203039fa3577beccc688) |
| 51 | eighty | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xd03918c9…`](https://scan.bradbury.genlayer.com/tx/0xd03918c97d7c3a0cd2a8a2df3e1373bf25af4a2666689035ec73baec34c6bbf4) |
| 52 | shortfall | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xbafec27b…`](https://scan.bradbury.genlayer.com/tx/0xbafec27b301964c4b18042d804a3835c4468c65867d6c37b715701a97e6c51e4) |
| 53 | disallowed | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x56afdaf1…`](https://scan.bradbury.genlayer.com/tx/0x56afdaf15865b4cae427d451e8104573a693ee1c7a16c445fe17598adbcf8ac8) |
| 54 | one_sided | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xd139b69b…`](https://scan.bradbury.genlayer.com/tx/0xd139b69bb2d0771217c6a079ff5f29225c8b75fa6bf5ddb4ceba4d054d607668) |
| 55 | withdrawn | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x8f589d14…`](https://scan.bradbury.genlayer.com/tx/0x8f589d145deb30200830fcf4e76cbbf2e77d70c11c79002fbe9dab91fe336ec9) |
| 56 | unclear | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x2f9177f9…`](https://scan.bradbury.genlayer.com/tx/0x2f9177f921e1897b5a61196d83163cddfc6015743656da075ac053fff2ac9ff4) |
| 57 | withdrawn_early | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xf002f518…`](https://scan.bradbury.genlayer.com/tx/0xf002f518a8008a9ad212a1a304736f1044460bc77f557c762be19eb62d97f8b3) |
| 58 | full | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x634f974e…`](https://scan.bradbury.genlayer.com/tx/0x634f974e1516fd1d236a8e6ab78333eea4ce667395ceb007b3363dcd2b848688) |
| 59 | shortfall | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x8c80dbf2…`](https://scan.bradbury.genlayer.com/tx/0x8c80dbf2a6f4178ad561f286f09682e1546794261b1f19bc74db88beccabe652) |
| 60 | eighty | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x3dc04a74…`](https://scan.bradbury.genlayer.com/tx/0x3dc04a748921bfb155234dfe76a1cc09e0f6a6c5183f21f26708b306cbe6a79a) |
| 61 | disallowed | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x2f23d814…`](https://scan.bradbury.genlayer.com/tx/0x2f23d814d0078f7079fa8b82270400a722fdc8fc34bafe42dfa083fdfd3437ac) |
| 62 | withdrawn | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x30d9d390…`](https://scan.bradbury.genlayer.com/tx/0x30d9d390e26c9c4c4e3db1775566b62af8c5821343753de8fd7add76c85a26e5) |
| 63 | one_sided | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x0f55852c…`](https://scan.bradbury.genlayer.com/tx/0x0f55852c1e1e91c7bf4fdba2a0c849e099f79c6374c8bbe4ecb12095291f57a2) |
| 64 | unclear | `read_register` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x98297092…`](https://scan.bradbury.genlayer.com/tx/0x98297092333beafef460660fac24fb9011073d4ff382c6b7058abf169471664c) |
| 65 | withdrawn_early | `read_register` | MAJORITY_AGREE / FINISHED_WITH_ERROR | [`0xd7237182…`](https://scan.bradbury.genlayer.com/tx/0xd7237182f2b197547db61fa4beb0c2d69fa7bade28a87d1bb76e5cf121b96f86) |
| 66 | no_transfer | `settle` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x036b6c08…`](https://scan.bradbury.genlayer.com/tx/0x036b6c087334836d3089a9f5c1d3ae7a9f1728ef4c05f3630e59f3a623043c33) |
| 67 | unclear | `settle` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xe2a0ade1…`](https://scan.bradbury.genlayer.com/tx/0xe2a0ade17d9438125aaefee3f055231d0f421882e6f37982098a7a5a75e81425) |
| 68 | withdraw | `withdraw` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0xd4a9e441…`](https://scan.bradbury.genlayer.com/tx/0xd4a9e441fe01648de274b8751515a3091ac551896ad644506f4353168839d215) |
| 69 | withdraw | `withdraw` | MAJORITY_AGREE / FINISHED_WITH_RETURN | [`0x6a945d46…`](https://scan.bradbury.genlayer.com/tx/0x6a945d46fe6badcb6e686b2cdba029f3a8377b8dee226896da76b79f92515c35) |

</details>

Earlier runs: s1 and s2 used earlier contract versions (their records and checks are in `examples/`, and the site shows them). Runs s3 to s7 did not reach the end and are not published: they were cut short by machine restarts or ran on versions that later reviews changed. In s7, on a busy Studio, the script's readings went out late, after the register had already changed, so its record does not show the order the cases need.

## Tests

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
PYTHONPATH=. venv/bin/pytest tests/direct -q             # 296 passed (GenVM v0.2); the same 296 pass on v0.6
PYTHONPATH=. venv/bin/python tools/mutate.py              # 134 of 134 mutants caught
venv/bin/genvm-lint check contracts/claim_escrow.py
```

`tests/direct/test_claim_escrow_review.py`, `test_claim_escrow_review2.py` and `test_claim_escrow_review3.py` hold the regression tests for every weak point that changed code in the first three independent reviews of 18 Nov 2026; `test_claim_escrow_review4.py` adds the fourth review's tests (refunds and the upfront top-up, a 6,000-sequence money fuzz, and the limits below). The same tests pass on GenVM v0.6 against the Bradbury build `bradbury/build/claim_escrow.py` (made by `bradbury/port.py`), with genlayer-test 0.30.0rc2 and `tests/conftest_v6.py` swapped in as `tests/direct/conftest.py`; with `CE_CONTRACT=bradbury/build/claim_escrow_packed.py`, the same 296 pass against the packed build deployed in run b1.

## Limits, stated plainly

- **When a decision is read before `allowance_by`, the escrow caps the buyer's recourse risk at the upfront level; it does not remove it.** At the long stop the seller gets the upfront plus `no_decision_seller_bp` of the rest. It does not force anyone to complete: before the transfer, the buyer can simply not file and the seller can refund.
- **The seller can lose the claim and receive nothing from the escrow.** Before `transfer_by`, every failure refunds the buyer in full: the page down or changed, no agreement, nobody reading, the register printing the buyer's name in another form (`HARROWFIELD CREDIT PARTNERS, L.P.` for `Harrowfield Credit Partners LP`), or the transfer filed to an affiliate. Meanwhile the buyer, or its affiliate, may hold the claim. The seller's only remedies are the sale agreement and its right to object to the transfer, so it should set `buyer_name` exactly as the agent prints names, capitals and punctuation included, and object to any notice that names anyone else. A buyer who lets an objection go unanswered cannot be detected.
- **Withdrawals.** A withdrawal pays the seller only if the register showed the buyer holding the claim live since it was last first seen as holder. A withdrawal the seller filed before the transfer, but which the agent shows only after it first showed the buyer holding the claim live, is still attributed to the buyer. Under Rule 3001(e)(2) the transferee is substituted only if nobody objects in 21 days, and an agent may show the transferee before that. After a transfer confirmed while the status was unclear, one reading showing the buyer holding the claim live is enough to attribute a later withdrawal to the buyer.
- **The holder decides some outcomes.** After the transfer the buyer, as holder, can amend or supersede the claim: the status becomes `UNCLEAR`, and the deal goes to the `no_decision_seller_bp` split. It can agree to a disallowance or a reduced allowance with the debtor (the register then prints "Disallowed by court order" or "Allowed" at the lower amount), perhaps for something the escrow cannot see; the escrow then refunds the buyer or pays the seller less. It can also have the register show the seller again (for example by withdrawing its notice of transfer); if that is seen twice, the long stop gives the buyer everything left, and a third party seen after that does not change it. One look at the seller just before `allowance_by` blocks a confirmation at that reading, so a decision first seen late can fall to the split.
- **The seller can withdraw the claim while it is still its own.** Under Rule 3001(e)(2) the seller stays the creditor of record until the transfer is substituted, and an agent may show the buyer as holder before that. If one reading shows the buyer holding the claim live (`Pending`) and the seller then files a withdrawal, two readings of the withdrawal pay the seller everything left, because a withdrawal after the buyer was shown holding the claim live is attributed to the buyer. The buyer's protection is the sale agreement, and watching the claim during the objection period.
- **The buyer can sell the claim on before the second look.** If the register first shows "Third Fund as transferee of the buyer", the holder reads as `OTHER`, the transfer to the buyer is never confirmed, and at `transfer_by` the buyer is refunded in full. The seller gets no notice of the second transfer from the register. The seller's protection is the sale agreement, and its right to object to the first notice of transfer.
- **A second sale shown straight away.** If the register goes straight from the buyer to a third party ("Other Fund as transferee of the seller": the seller sold the claim again), a decision read then pays as usual, even at the first reading that shows the third party: "Allowed" pays the seller the price and a withdrawal pays the seller everything. The seller-hold rule only protects the buyer when the seller is first seen twice as holder again. The buyer gets no notice of such a transfer from the register, so it should watch the claim.
- **A buyer's affiliate after the seller holds the claim again.** Once the seller is confirmed as holder again, a third party seen twice does not change that, even if it is the buyer's own affiliate holding an allowed claim: the long stop then refunds the buyer everything left. The seller is mailed notice of such a transfer and can object.
- **Settlement is final.** A claim reconsidered after it settled (§502(j)), or a ruling reversed on appeal, does not undo the escrow. GenLayer appeals re-read the page as it then stands.
- **Only the total allowed amount is read.** A claim allowed in full but moved to a lower class pays in full. "Allowed in part" counts as allowed at the printed amount; "Disallowed in part" is `UNCLEAR`. Both choices are conservative.
- **The currency check reads the code or the sign.** A currency written in words (`US dollars`) refuses an allowed reading. `$` cannot tell US from Canadian, Australian or Hong Kong dollars; the seller's choice of code and the frozen host list carry that.
- **Nothing links the seller's address to the creditor on the register.**
- **One host.** This deployment accepts only the fictional demo register. A real deployment would freeze the official registers' hosts, and a register page that redirects or echoes its address could hand the reading to someone else. Many real registers have no stable address per claim, sit behind a login, or carry disclaimers; the reading also needs each field printed as "label: value" at the start of its line (or the value on the next line), once. The common grid of claimed, scheduled and allowed amounts in columns never anchors an allowed amount, so on such a page an allowed claim gives no reading and the deal ends at the long stop's split. Code checks only a field's own line and the next non-blank line: a qualifier elsewhere in the entry, or behind a separator line (`---`), is not detected. Ordinary text right after a field line (`(fictional)`, `All rights reserved`, `subject to change`, `non-contingent`, or a case `Status:` line) refuses the page: before the transfer the buyer is then refunded, after it the long stop's split applies.
- **`confirm_seconds` in the demo is minutes.** Real use needs at least the objection period.
- **Views do not apply deadlines.** `get_deal` shows `ACTIVE` after a deadline until someone writes; the site marks such a deal "settle due". The log's times are the deal clock, and each reading's own stamp for reading events.
- **Timestamps and rendering.** A reading is stamped when it is sent, but Studio renders the page when it processes the transaction. In run s8 a reading was accepted about 90 seconds after it was sent (median), and at most 5 minutes after. Run s7 is not shown: under heavier load the script's readings went out late, after the register had changed. The demo schedule now leaves 24 minutes between a reading and the next change of the register. On a real register, changes are days or weeks apart.
- **A reading can come back empty, and the demo script does not re-read on its own.** In run b1 one of 43 readings was a no-reading (`N1_WRONG_PAGE`); the contract counted nothing, as designed, and one extra reading was sent by hand so the deal could confirm its transfer before `transfer_by`. A real deployment would read the register more often than the demo's fixed rounds.
- Test GEN at a fixed conversion. Not legal advice. No real case, creditor or debtor is used.

## Facts about real claims trading (for context, US Chapter 11)

- Under 11 U.S.C. §502(a) a filed claim is deemed allowed unless a party in interest objects, so many claims never get a ruling. Under §502(j) an allowed or disallowed claim can be reconsidered for cause.
- Under Federal Rule of Bankruptcy Procedure 3001(e)(2), when a claim is transferred (other than for security, and other than a claim based on a publicly traded note, bond or debenture) after its proof of claim is filed, the transferee files evidence of the transfer; the alleged transferor has 21 days after the clerk mails the notice to object (the court may extend the time). If nobody objects in time, the transferee is substituted for the transferor.
- Under Rule 3006 a creditor may withdraw its claim as of right, but needs a court order, after notice and a hearing, once an objection to the claim has been filed, a complaint has been filed against it in an adversary proceeding, or it has accepted or rejected the plan or otherwise taken a significant part in the case.
- "Expunged" is not always the end of a claim: a claim is also expunged as a duplicate, or as amended by a later proof of claim.
- In large cases a claims agent keeps the public register on its own site; the court's own docket may need a login.
- Sale agreements often treat an objection being filed as impairment and add interest on refunds. ClaimEscrow does neither.

## Repository

- `contracts/claim_escrow.py`: the contract (GenVM v0.2, Studio). `bradbury/build/claim_escrow.py`: the GenVM v0.6 build; `bradbury/build/claim_escrow_packed.py`: the same build compressed (`port.py --pack`), as deployed on Bradbury.
- `tests/direct/`: direct-mode tests. `tools/mutate.py`: the mutation check.
- `examples/cases.json`: the nine fictional cases. `tools/make_register.py`: the claims agent's pages, which carry their own schedule and show the entry as it stands at the reader's clock.
- `tools/live.py`: runs the cases live on Studio or Bradbury and records every transaction it sends (a failed reading send is retried; if the node had in fact received the first, that one is not in the record). `tools/verify.py` (Studio) and `tools/verify_bradbury.py` (Bradbury): re-read every recorded transaction from the chain after finalization and reconcile the balance. `tools/summary.py`: the record as a table.
- `examples/live-studio-*.json`, `examples/live-bradbury-b1*.json`: the live records and their checks. `docs/`: the site, served at https://claims.brilliantnodes.com, with the records in `docs/runs/`.
- `tools/video/`: the demo video from a live record (`make_data.py` reads the record, `voice.py` writes the narration with an offline voice, `render.py` draws `stage.html` frame by frame).

Built by Brilliant Nodes.
