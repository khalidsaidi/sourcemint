---
title: SourceMint (SRCMNT)
---

![SourceMint logo](assets/logo.svg)

# SourceMint (SRCMNT)

SourceMint (SRCMNT) is an open-source ERC-20 token contract and a Foundry-based deployment/tooling repository.
It is designed to be transparent and easy to audit: fixed supply minted at deployment, verified source code on BaseScan, and open-source code on GitHub.

This project is early-stage and intended for open-source experimentation, developer tooling demos, and community reward prototypes. It is not financial advice.

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

## Official channels

- GitHub repo: https://github.com/khalidsaidi/sourcemint
- GitHub Discussions: https://github.com/khalidsaidi/sourcemint/discussions
- GitHub Issues: https://github.com/khalidsaidi/sourcemint/issues

## Contact

Official email: khalidsaidi66@gmail.com
