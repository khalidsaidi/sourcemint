# How the ledger is verified

SourceMint claims that every SRCMNT transfer out of a project wallet is
recorded in [`rewards/ledger.json`](../rewards/ledger.json) with a stated
reason. `script/verify_ledger.py` makes that claim falsifiable.

## The chain is the source

History is derived from the chain itself, needing **no API key, no account and
nobody's permission**. Any public Base RPC endpoint will serve it.

Reading every block since deployment would be O(chain) — eleven million blocks
to find eleven transactions. Instead it is O(our own activity):

1. A nonce is monotonic, so binary-searching `eth_getTransactionCount` over
   block height finds every block in which a project wallet sent a
   transaction. Nothing hides there: unlike a balance, a nonce never comes
   back down, so tokens sent out and returned are still two increments.
2. Logs are read for those blocks only, plus the deployment block for the
   mint, which no wallet signed.

Measured against Base mainnet: **about 180 requests, under twenty seconds**,
for the token's entire history. That cost grows with our activity, not with
the chain's.

## What a nonce cannot see, and what catches it

A third party spending an allowance via `transferFrom` moves tokens without
our wallet signing anything, so no nonce increments and the movement sits in a
block we never look at.

That case is the exact complement: it changes a balance without touching a
nonce. After the transfer comparison, `balanceOf` and `totalSupply` are
reconciled against what the ledger implies. A balance the ledger cannot
explain is what an unsigned movement looks like.

Together the two leave nothing uncovered.

## Indexers

The entries in `SOURCES` answer the same question in one request instead of
roughly two hundred, so they are tried first. They are a shortcut, never a
dependency — losing every one of them costs seconds.

As of 2026-10-29 `base.blockscout.com` returns HTTP 403 to programmatic
requests, so runs take the chain path.

## Configuration

| Variable | Default | Used for |
|---|---|---|
| `BASE_RPC_URL` | — | nonces, balances, block height |
| `BASE_LOGS_RPC_URL` | `base.gateway.tenderly.co` | the handful of single-block log reads |

Two endpoints because no single free one serves both: `mainnet.base.org`
answers nonces and balances but refuses `eth_getLogs` entirely. Both are
public and need no key.

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
