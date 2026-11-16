# How the ledger is verified

SourceMint claims that every SRCMNT transfer out of a project wallet is
recorded in [`rewards/ledger.json`](../rewards/ledger.json) with a stated
reason. `script/verify_ledger.py` makes that claim falsifiable.

## The chain is the source

History is read from the chain itself, needing **no API key, no account and
nobody's permission**. Any public Base RPC endpoint will serve it.

Every block from the token's deployment (41988939) to a fixed head is read in
order, in `eth_getLogs` pages, with nothing skipped. The head is pinned at the
start and re-checked at the end so a reorg cannot turn a later fork's state
into a finding.

That is deliberately the expensive option. It was not always.

## Why not a cheaper method

Between 2026-10-29 and 2026-11-16 this script used wallet nonces as an index:
a nonce is monotonic, so binary-searching `eth_getTransactionCount` finds every
block in which a project wallet *signed* a transaction, and only those blocks
need their logs read. About 180 requests instead of sixteen thousand.

It was wrong, and [#10](https://github.com/khalidsaidi/sourcemint/issues/10)
is why. A nonce only moves when our wallet signs. A spender using an allowance
moves tokens by `transferFrom` without touching it, so those blocks were never
read. An allowance check was supposed to cover that case, but an allowance is
only evidence while it is live: send tokens out, send them back, revoke the
approval, and the balance nets to zero, the nonce never moved, the allowance
reads zero, and the verifier reported success for history it had never seen.

Reported by @Chandain, reproduced independently by @gjwang, fixed by @gjwang
in [#11](https://github.com/khalidsaidi/sourcemint/pull/11). Both cases are
permanent offline regressions in `script/test_history_scan.py`.

The lesson is narrower than "nonces are bad": the method sampled, and a sample
cannot support a claim of completeness. Anything cheaper than reading every
block has to prove it is not sampling.

## Three states, not two

A single pass/fail flag conflates things that are not the same, which is how
an outage used to downgrade an already-observed violation to "could not
verify". They are now distinct:

- An unledgered movement that was actually observed is a **finding**. It stays
  a finding whatever happens afterwards — a later page failing, a state read
  timing out, the budget running out.
- Coverage that did not complete is **inconclusive**. No verdict is available
  about blocks that were not read.
- A ledger entry simply absent from an incomplete range is **neither**. It may
  be in a block not yet reached.

## What this costs, and for how long

At 1,000 blocks per page — the largest range free keyless endpoints serve —
the token's history is about 16,300 requests and an hour.

Base produces roughly 317,000 blocks a day, so that grows by about eight
minutes of scanning every week. Extrapolated, a complete pass passes GitHub
Actions' six-hour job limit within about a year of 2026-11-16.

This is a known limit, not a solved problem. When it binds, the options are a
keyed endpoint with larger ranges, or a committed checkpoint of the last
verified block and its hash — which trades "every run re-derives everything"
for "every run trusts the last one", and should not be done quietly.

## Verdicts

| Outcome | Exit |
|---|---|
| Every movement has an entry, and every entry exists on-chain | 0 |
| A movement is unaccounted, or an entry has no on-chain counterpart | 1 |
| No source could supply the history | 2 |

Exit 2 is never an accounting finding. A source outage is an outage, and since
each run re-derives the whole history rather than a delta, a deferred check
loses nothing. A violation already found is never downgraded to exit 2 by a
later outage.

Amounts are compared in integer wei; a discrepancy of one base unit fails.
Movements are matched as `(tx, from, to, amount)` multisets, so an entry
naming the wrong sender does not match, and one entry cannot discharge two
identical movements in the same transaction.

## Running it

```bash
BASE_RPC_URL=https://mainnet.base.org python3 script/verify_ledger.py
```
