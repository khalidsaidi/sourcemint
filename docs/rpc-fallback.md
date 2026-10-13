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
| Primary fails and RPC fails with a transport error, HTTP 429, invalid JSON, or malformed data | `COULD NOT VERIFY`, exit 2; no accounting verdict. |
| Later RPC window fails | Reject the entire scan, including earlier windows. |
| Valid RPC `result: []` | A successful query with zero matching logs; accounting still compares against ledger entries. |
| Verified history agrees / disagrees with ledger | Exit 0 / exit 1 respectively. |

## Reproducible offline validation

Run the Python tests from the repository root:

```sh
python3 -B -m unittest discover -s script -p 'test_*.py' -v
python3 -B -m unittest discover -s test -p 'test_*.py' -v
```

Regression tests cover strict response IDs (including boolean/float rejection),
missing/null/wrong-type log fields, invalid transaction hashes, real decoder-to-ledger
matching, partial history rejection, transport failures, and both CLI entrypoints.
All provider calls in the Python tests are mocked; no live RPC is called.

Validated locally on 2026-10-13 in `sourcemint` on `rpc-fallback`:
18 decoder/adapter tests and 13 integration/regression tests passed
(31 Python tests total). `git diff --check` and
`forge fmt --check test/SourceMint.t.sol` also passed.
Solidity tests were not rerun during repository consolidation.

## Runtime evidence and draft limitations

The primary retry policy now uses three attempts with backoff delays
of 2 and 4 seconds. An offline regression test uses the production
retry setting and verifies six seconds of scheduled sleep without
actually waiting.

This verifies the retry policy, not network request duration or
full-history RPC runtime. The approximately three-minute target
for the RPC fallback remains unverified.

Full-history success through the public RPC and its runtime are not established
by offline tests. The earlier single-block public endpoint attempt returned HTTP
429 / RPC -32011. Public RPC compatibility and the runtime target remain unverified
until live validation succeeds.

This patch does not change existing ledger amount formatting.
