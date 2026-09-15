# Contributing

Thanks for considering contributing. SourceMint rewards merged contributions
with SRCMNT from the rewards wallet — see [REWARDS.md](REWARDS.md) for how
that works and what is and isn't rewarded.

## Where to start

- Issues labelled [`good first issue`](https://github.com/khalidsaidi/sourcemint/issues?q=is%3Aopen+label%3A%22good+first+issue%22)
  are scoped, self-contained, and have acceptance criteria.
- Issues labelled [`help wanted`](https://github.com/khalidsaidi/sourcemint/issues?q=is%3Aopen+label%3A%22help+wanted%22)
  are open to anyone; comment on one to claim it before starting.
- Anything else: open an issue first and describe the approach.

## Development

- Install [Foundry](https://book.getfoundry.sh/) (`forge`, `cast`)
- `make fmt` — format
- `make test` — run the Solidity tests
- `python3 script/verify_ledger.py` — verify the public ledger against Base

## Pull requests

- Keep PRs focused on one issue.
- Add or update tests when changing contract behaviour; never change `src/`
  for a deployed contract without an explicit issue discussing why.
- If you want a reward, include a Base address in the PR description.
  An address only — never a private key.
- Any transfer out of a project wallet must have a matching entry in
  `rewards/ledger.json` in the same change, or the Ledger CI fails.
