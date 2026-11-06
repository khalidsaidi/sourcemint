# SourceMint (SRCMNT)

[![Ledger](https://github.com/khalidsaidi/sourcemint/actions/workflows/ledger.yml/badge.svg)](https://github.com/khalidsaidi/sourcemint/actions/workflows/ledger.yml)

**Contribution, minted.** SourceMint is an experiment in accounting for open-source
contribution on-chain: a fixed-supply ERC-20 on Base with no ICO and no token sale.
Supply enters circulation as rewards for merged contributions
([reward policy](REWARDS.md)); once distributed, the token trades freely like any
ERC-20. The accounting invariant is enforced by code: every transfer out of a
project wallet — rewards and any treasury liquidity provision alike — must be
recorded in [`rewards/ledger.json`](rewards/ledger.json) with a reason, and
[CI verifies the ledger against the chain](.github/workflows/ledger.yml) — an
unaccounted movement fails the build in public.

Website: https://srcmnt.xyz · X: https://x.com/srcmnt

Open-source ERC20 token contract built with Foundry.

## Contract
- Name: `SourceMint`
- Symbol: `SRCMNT`
- Decimals: 18
- Supply model: fixed supply minted to deployer at deployment time
- Extensions: Burnable + Permit (gasless approvals)

## Requirements
- Foundry: `forge`, `cast`

## Dev Commands
- `make fmt`
- `make test`
- `make snapshot`
- `make coverage`

## Deploy (Sepolia)
Set env vars (DO NOT COMMIT THESE):

```bash
export RPC_URL="https://sepolia.YOUR-RPC-PROVIDER.example"
export PRIVATE_KEY="0xYOUR_PRIVATE_KEY"
export ETHERSCAN_API_KEY="YOUR_ETHERSCAN_API_KEY"
export INITIAL_SUPPLY="1000000000000000000000000"
```

Deploy + verify:

```bash
make deploy-sepolia
```

Deployment artifacts:
- `deployments/11155111.json` (auto-written by the script)

## Deployments
- Base Mainnet (8453): `0x914F6b6a0DaD39A3CB932dcf4D1af885C7c08EeB` (GA)
  - Verified: https://basescan.org/address/0x914f6b6a0dad39a3cb932dcf4d1af885c7c08eeb#code
- Sepolia (11155111): `0x8c2B67EA395824Cc069F5e13b1d80E6016751a4A` (testnet)

## Ledger verification coverage

`python3 script/verify_ledger.py` scans this token's `Transfer` logs from its
configured deployment block through a fixed head. Both configured RPC endpoints
must report the ledger's chain ID and agree on that head. Balances and total
supply are read using its canonical block hash. This covers delegated
`transferFrom` movements even if balances later return to their original values
and allowances are revoked. Current allowances are not evidence of missing
historical transfers.

The verifier trusts complete RPC log responses; this is an accounting check,
not an independent cryptographic receipt proof. It keeps the existing scope:
mint events and transfers out of project wallets must match the ledger.

| Environment setting | Default | Purpose |
| --- | --- | --- |
| `BASE_HISTORY_BLOCK_SPAN` | `10000` | Maximum blocks per log request |
| `BASE_HISTORY_MAX_REQUESTS` | `2048` | Shared request budget, including wire retries and state reads |
| `BASE_HISTORY_TIMEOUT` | `300` | Deadline in seconds, checked around RPC operations and retry delays |
| `BASE_HISTORY_MAX_RESPONSE_BYTES` | `8388608` | Maximum response body per request |
| `BASE_HISTORY_MAX_LOGS_PER_PAGE` | `10000` | A page at this known/suspected result cap is incomplete |
| `BASE_HISTORY_MAX_LOGS` | `100000` | Maximum retained events across accepted pages |

Set the page span and result cap to the limits of your selected provider. A
failed, malformed, capped or unfinished range returns exit 2 when no accounting
violation has been established; it never falls back to nonce sampling or skips
the failed range. An already-observed canonical unledgered movement remains
exit 1 even if a later page fails. Exit 0 requires complete matching history and
successful snapshot state checks. Pending or post-snapshot ledger transactions
are inconclusive, rather than falsely reported absent. Larger histories may
need different explicit budgets; these defaults are not provider capacity or
runtime guarantees. Existing RPC pacing and retry settings still apply.
