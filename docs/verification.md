# How the ledger is verified

SourceMint's claim is that every SRCMNT transfer out of a project wallet is
recorded in [`rewards/ledger.json`](../rewards/ledger.json) with a stated
reason. `script/verify_ledger.py` is what makes that claim falsifiable.

## The chain is the source

The complete transfer history is derived from the chain itself, by paging
`eth_getLogs` over the token's `Transfer` events from its deployment block
(41988939) to the current head.

This needs **no API key, no account and nobody's permission**. Any public Base
RPC endpoint will serve it. That property is the point: a claim that can only
be checked by asking a particular company for access is not a claim a stranger
can check.

It costs about 11,000 sequential requests, roughly two hours.

## Indexers are a shortcut, not a dependency

`INDEXERS` lists services that answer the same question in seconds. They are
tried first. If one answers, the run takes moments; if none does, the history
comes from the chain and the run takes hours. Losing every indexer costs time,
never the ability to verify.

Configure the endpoint with `BASE_RPC_URL` and the window size with
`BASE_RPC_WINDOW` (default 1000, the largest range free endpoints generally
allow; `mainnet.base.org` refuses `eth_getLogs` entirely).

## Verdicts

| Outcome | Exit |
|---|---|
| Every project-wallet movement has a ledger entry, and every entry exists on-chain | 0 |
| A movement is unaccounted, or an entry has no on-chain counterpart | 1 |
| No source could supply the history | 2 |

Exit 2 is never an accounting finding. A source outage is an outage, and
because each run re-derives the entire history rather than a delta, a deferred
check loses nothing — the next successful run covers everything the skipped one
would have.

Amounts are compared in integer wei. A discrepancy of one base unit fails.

## Running it

```bash
python3 script/verify_ledger.py
```
