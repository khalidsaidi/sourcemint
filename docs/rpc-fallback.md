# Ledger RPC fallback: validation and remaining acceptance checks

The verifier tries Blockscout first. Only a `SourceUnavailable` failure triggers
RPC fallback. Partial primary pages and partial RPC windows are discarded.
The RPC scan starts at creation block 41988939 and ends at the validated head,
using windows of at most 10,000 blocks. No third-party Python dependencies are added.

Set `BASE_RPC_URL` to the desired endpoint. The Ledger workflow supplies the public,
no-key endpoint `https://mainnet.base.org`; credentials are not stored in code.
A missing endpoint fails with exit 2 if the primary is unavailable.

```sh
BASE_RPC_URL=https://mainnet.base.org python3 script/verify_ledger.py
```

Both direct execution and `python3 -m script.verify_ledger` are supported.

| Case | Behavior |
| --- | --- |
| Primary succeeds | RPC is not called; verify the primary history. |
| Primary fails, complete RPC history succeeds | Verify the decoded RPC history. |
| Both sources fail, HTTP 429, invalid JSON or malformed log | `COULD NOT VERIFY`, exit 2; no accounting verdict. |
| Later RPC window fails | Reject the entire scan, including earlier windows. |
| Valid RPC `result: []` | A successful query with zero matching logs; accounting still compares against ledger entries. |
| Verified history agrees / disagrees with ledger | Exit 0 / exit 1 respectively. |

## Reproducible offline validation

```sh
python3 -B -m unittest discover -s script -p 'test_*.py' -v
python3 -B -m unittest discover -s test -p 'test_*.py' -v
forge fmt --check
forge test --offline -vvv
```

Regression tests cover strict response IDs (including boolean/float rejection),
missing/null/wrong-type log fields, invalid transaction hashes, real decoder-to-ledger
matching, partial history rejection, transport failures, and both CLI entrypoints.
All provider calls in the Python tests are mocked; no live RPC is called.

Validated on 2026-10-13 in a clean branch from upstream main: 18 decoder/adapter
tests + 13 integration/regression tests passed (31 total); 11 Solidity tests
passed. `forge fmt --check` and the staged `git diff --check` passed.

## Runtime evidence and draft limitations

The existing eight-attempt primary retry policy is unchanged in this patch.
Injected sleep records `2 + 4 + 8 + 16 + 32 + 64 + 128 = 254` seconds for a failed
primary request, already more than 180 seconds without counting request time.
The test does not actually sleep.

The maintainer clarified in issue #1 that the approximately three-minute target
applies to the RPC fallback itself and permitted a shorter primary retry budget.
Primary retry tuning remains a follow-up for this draft.

Full-history success through the public RPC and its runtime are NOT established
by offline tests. The earlier single-block public endpoint attempt returned HTTP
429 / RPC -32011. Do not claim public compatibility or the runtime target until
those checks succeed. This patch does not change existing ledger amount formatting.
