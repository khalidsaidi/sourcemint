# SourceMint (SRCMNT)

[![Ledger](https://github.com/khalidsaidi/sourcemint/actions/workflows/ledger.yml/badge.svg)](https://github.com/khalidsaidi/sourcemint/actions/workflows/ledger.yml)

**Contribution, minted.** SourceMint is an experiment in accounting for open-source
contribution on-chain: a fixed-supply ERC-20 on Base that is never sold — outside a
documented treasury, tokens move only as recognition for merged contributions
([reward policy](REWARDS.md)). The invariant is enforced by code: every transfer out
of a project wallet must be recorded in [`rewards/ledger.json`](rewards/ledger.json)
with a reason, and [CI verifies the ledger against the chain](.github/workflows/ledger.yml)
— an unaccounted movement fails the build in public.

Website: https://srcmnt.xyz

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
