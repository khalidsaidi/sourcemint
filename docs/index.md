---
title: SourceMint (SRCMNT)
---

![SourceMint logo](assets/logo.svg)

# SourceMint (SRCMNT)

SourceMint (SRCMNT) is an open-source ERC-20 token contract and a Foundry-based deployment/tooling repository.
It is designed to be transparent and easy to audit: fixed supply minted at deployment, verified source code on BaseScan, and open-source code on GitHub.

This project is early-stage and intended for open-source experimentation, developer tooling demos, and community reward prototypes. It is not financial advice.

## Purpose

SourceMint exists to serve as a reference-quality, fully transparent ERC-20 deployment on Base:

- **A learning and tooling reference.** The repository shows a complete, reproducible path from Foundry project to verified mainnet contract: tests, gas snapshots, CI, deployment scripts, and recorded deployment artifacts (`deployments/8453.json`).
- **A community reward primitive.** SRCMNT is planned as the reward unit for contributions to the SourceMint open-source tooling (documentation, test coverage, deployment tooling improvements), distributed from the deployer treasury as the contributor program launches.
- **Deliberately trust-minimized.** The contract has no owner, no admin functions, no pause, no fees, and no ability to mint after deployment. What was minted at deployment (1,000,000 SRCMNT) is the supply forever; holders can only reduce it by burning.

## Roadmap

- **Q3 2026** — Publish contributor reward guidelines; begin distributing SRCMNT from the deployer treasury to early contributors.
- **Q4 2026** — Open GitHub Discussions governance for reward allocation; publish periodic treasury transparency reports on this site.
- **2027** — Evaluate liquidity provisioning and additional tooling (airdrop scripts, permit-based reward claims) based on community interest.

Progress is tracked publicly in [GitHub Issues](https://github.com/khalidsaidi/sourcemint/issues) and [Discussions](https://github.com/khalidsaidi/sourcemint/discussions).

## Official contracts

- Base Mainnet (chainId 8453)
  - Contract: `0x914F6b6a0DaD39A3CB932dcf4D1af885C7c08EeB`
  - Verified code: https://basescan.org/address/0x914f6b6a0dad39a3cb932dcf4d1af885c7c08eeb#code

- Sepolia (chainId 11155111) - testnet
  - Contract: `0x8c2B67EA395824Cc069F5e13b1d80E6016751a4A`
  - Verified code: https://sepolia.etherscan.io/address/0x8c2b67ea395824cc069f5e13b1d80e6016751a4a#code

## Token details

- Name: SourceMint
- Symbol: SRCMNT
- Decimals: 18
- Supply: fixed supply minted once at deployment (1,000,000 SRCMNT)

Contract features:
- ERC20Burnable (holders can burn)
- ERC20Permit (EIP-2612 gasless approvals)

## Project status / security

- Source code is verified on BaseScan and public on GitHub.
- Not audited. The contract is intentionally minimal.

## Team / transparency

Maintainer:
- **Khalid Saidi** — creator/maintainer of SourceMint and this repository.
  - GitHub profile: https://github.com/khalidsaidi

On-chain provenance (public, verifiable):
- Base mainnet (chainId 8453) token contract (GA): `0x914F6b6a0DaD39A3CB932dcf4D1af885C7c08EeB`
  - Verified code: https://basescan.org/address/0x914f6b6a0dad39a3cb932dcf4d1af885c7c08eeb#code
- Contract creation / deployment tx:
  - https://basescan.org/tx/0x6b06299804074d1ab8ce78d0c4ce40216e51ac653070cba10714d0fa3b42bbfa
- Deployer (initial supply recipient at deployment):
  - https://basescan.org/address/0x497d34b1d0790f374B32467093d303533399c819

## Treasury & distribution

Supply is split across two project-controlled wallets, documented here for transparency:

| Wallet | Address | Balance | Purpose |
|---|---|---|---|
| Treasury (deployer) | [`0x497d34b1d0790f374B32467093d303533399c819`](https://basescan.org/address/0x497d34b1d0790f374B32467093d303533399c819) | 900,000 SRCMNT (90%) | Long-term treasury |
| Rewards | [`0x1af3cBcE941a2AC9D987E853b5385b05c405E16F`](https://basescan.org/address/0x1af3cBcE941a2AC9D987E853b5385b05c405E16F) | 100,000 SRCMNT (10%) | Contributor rewards (see Roadmap) |

- Distribution tx (2026-08-27): [`0xc3f5e0…7979d3`](https://basescan.org/tx/0xc3f5e01e5b6b38b18a8f44943f541118fda201375ca579e0117f4a1ca07979d3)
- Any future movement from these wallets will be documented on this page.

## Official channels

- GitHub repo: https://github.com/khalidsaidi/sourcemint
- GitHub Discussions: https://github.com/khalidsaidi/sourcemint/discussions
- GitHub Issues: https://github.com/khalidsaidi/sourcemint/issues

## Brand assets

Official SourceMint logo (for explorers, wallets, and token lists):

- SVG (32×32 viewBox): [assets/logo.svg](https://khalidsaidi.github.io/sourcemint/assets/logo.svg)
- PNG 64×64: [assets/logo-64.png](https://khalidsaidi.github.io/sourcemint/assets/logo-64.png)
- PNG 256×256: [assets/logo-256.png](https://khalidsaidi.github.io/sourcemint/assets/logo-256.png)

## Contact

Official email: khalidsaidi66@gmail.com

This Gmail address is the project's official primary contact and is used for explorer/token-list applications. All official communication comes from it or from the GitHub accounts listed above.
