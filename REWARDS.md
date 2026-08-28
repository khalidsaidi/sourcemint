# SourceMint contribution rewards

SourceMint's mission is to make open-source contribution visible and rewarded
on-chain. SRCMNT is not sold and not airdropped: outside the documented
treasury, the only way tokens move is as recognition for contributions to this
repository.

## The accounting invariant

Every transfer of SRCMNT out of a project wallet is recorded in
[`rewards/ledger.json`](rewards/ledger.json) with the transaction hash, the
recipient, the amount, and the reason. CI
([`ledger.yml`](.github/workflows/ledger.yml)) verifies the ledger against the
Base blockchain on every change and weekly: an unaccounted movement fails the
build in public. Anyone can run the check themselves:

```bash
python3 script/verify_ledger.py
```

## What is rewarded

Merged contributions to this repository, at the maintainer's discretion:

- code (contract tooling, deployment scripts, tests)
- documentation and site improvements
- reproducible bug reports with fixes

## How it works

1. Open an issue or pick an existing one; discuss the approach first for
   anything non-trivial.
2. Submit a PR. Include a Base address in the PR description if you want a
   reward. Never share private keys — an address only.
3. If the PR is merged and the maintainer assigns a reward, payment is sent
   from the rewards wallet
   (`0x1af3cBcE941a2AC9D987E853b5385b05c405E16F`), and the transaction is
   added to the ledger in the same or a follow-up commit, with the PR as the
   reason.

Reward sizes are set per contribution by the maintainer and recorded in the
ledger; there is no fixed price list. SRCMNT has no established market value,
and rewards are recognition within this project, not payment for work or an
investment.

## What is not rewarded

Spam PRs, cosmetic churn, AI-generated bulk changes without substance, or any
contribution made only to farm rewards. The maintainer's decision is final.
