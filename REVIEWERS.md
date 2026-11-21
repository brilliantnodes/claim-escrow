# ClaimEscrow: start here (for reviewers, 5 minutes)

**What it is, in plain words:** an escrow for buying a bankruptcy claim. The buyer's money waits in the contract and moves only on what GenLayer validators read on the public claims register page: who holds the claim, its status and its allowed amount. Market: litigation funding, about $25bn in 2025 ([Custom Market Insights](https://www.custommarketinsights.com/report/litigation-funding-investment-market/)). 

## 1. How consensus binds the money

- **The model copies; code decides.** Each validator renders the register page itself; its model copies the debtor, the claim number, and the holder, status and allowed amount, each with its label. Plain Python checks every copy against the validator's own rendering, maps the status through a closed phrase table (anything unknown is `UNCLEAR` and moves nothing) and classes the holder as `BUYER`, `SELLER` or `OTHER`. Details: README, [What validators do, and what code does](README.md#what-validators-do-and-what-code-does).
- **Exact agreement on everything stored.** A validator accepts the leader's result only if kind, reason, holder class, status and amount are equal to its own. Two readings that would pay differently cannot both be accepted, so every accepted reading leads to the same payout. A `NO_READING` binds nothing; anyone may read again.
- **Nothing moves on one look.** A transfer, a decision or a holder change counts only when seen twice, at least `confirm_seconds` apart, by each reading's own transaction stamp.
- **Every amount is integer code.** The payout table (README, [How it works](README.md#how-it-works), step 6) sums exactly to the escrow at every step; `totals()` reconciles the balance as `locked + credited`.
- **No stuck money.** `settle()` applies the deadlines without a model (no transfer: buyer refunded; no decision: fixed split).

## 2. Check it in five steps

1. Open the contract on Studio: [explorer](https://explorer-studio.genlayer.com/address/0x0Ea5b829bF0EF137a4EBbDFd6A6B30d22bAD9674) or [import it into GenLayer Studio](https://studio.genlayer.com/?import-contract=0x0Ea5b829bF0EF137a4EBbDFd6A6B30d22bAD9674).
2. Call `get_rules()` to see the frozen register hosts and minimum confirmation time.
3. Read the live run s8 table in the README ([Live results](README.md#live-results)): nine fictional deals, 67 transactions, all finalized; each row links its transaction.
4. Compare with the independent check: [`examples/live-studio-s8-check.json`](examples/live-studio-s8-check.json) (every transaction re-read from the chain; balance, locked and credits all zero at the end).
5. The same nine deals on Testnet Bradbury: [contract](https://scan.bradbury.genlayer.com/address/0xdE2e969ecFE0229849ad95CF3Df8aC803F079131), 70 transactions, all finalized (README, [Run b1](README.md#run-b1-on-testnet-bradbury)).

## 3. Links

- Video (1.5 min): https://www.youtube.com/watch?v=MFiW9LkCT1s
- Site: https://claims.brilliantnodes.com
- Source: [`contracts/claim_escrow.py`](contracts/claim_escrow.py)

*Fictional case, debtor, creditors and agent; test GEN only. Not legal advice.*
