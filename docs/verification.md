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

## What a nonce cannot see

A third party spending an allowance via `transferFrom` moves tokens without
our wallet signing anything. No nonce increments, and the transfer sits in a
block this derivation never reads.

Two things address it.

`balanceOf` and `totalSupply` are reconciled against what the ledger implies,
so an unexplained balance reveals a movement nobody here signed. That catches
the ordinary case but not a round trip, where tokens leave and the same amount
returns and the balance is unchanged.

So the verifier also refuses to claim completeness while any allowance is
outstanding. Granting an allowance is itself a transaction a project wallet
signed, so it appears in a block already being read: the same single request
per block returns `Approval` logs alongside `Transfer` logs, at no extra cost.
Every spender ever approved is then checked with `allowance`, and a non-zero
result fails the run with the spender named.

That is deliberately strict. A live allowance does not mean anything has gone
wrong — it means this check cannot prove that nothing has, and saying so is
the point.

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
