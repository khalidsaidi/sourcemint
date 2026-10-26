# Ledger RPC fallback: receipts, balances, and total supply

The verifier tries Blockscout first. A `SourceUnavailable` failure discards partial
primary pages and triggers RPC fallback in `main()`.

The fallback uses `eth_getTransactionReceipt` to match SRCMNT Transfer logs against
ledger entries. Balance verification derives expected balances and total supply
from the ledger, fetches a block with `eth_blockNumber`, then reads `balanceOf`
and `totalSupply` using `eth_call` at that block. It uses only the Python standard
library.

Ledger `amount` values are strings in whole-token units, including fractions:
`"0.5"` means half a SRCMNT. The verifier converts these values to integer base
units internally (`"0.5"` becomes `500000000000000000`) and uses exact integer
comparisons for primary history, receipts, balances, and total supply. It never
uses floating-point arithmetic for amounts. Values requiring precision beyond
18 decimal places, negative amounts, non-finite values, and non-string amounts
are rejected with exit 1; trailing fractional zeros are accepted without rounding.

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
| Primary fails, receipt and balance checks succeed | Exit 0. |
| Primary fails and RPC fails with a transport error, HTTP 429, invalid JSON, or malformed data | `COULD NOT VERIFY`, exit 2; no accounting verdict. |
| A receipt has no matching Transfer log | Accounting violation, exit 1. |
| Balance or supply differs from the ledger by even one wei | Accounting violation, exit 1. |
| RPC `result` is null, or balance/supply data is `"0x"` | `COULD NOT VERIFY`, exit 2. Empty data is not a zero balance. |
| A valid encoded zero matches the ledger | Verification succeeds. |
| Primary history agrees / disagrees with ledger | Exit 0 / exit 1 respectively. |

## Reproducible offline validation

Run the Python tests from the repository root:

```sh
python3 -B -m unittest discover -s script -p 'test_*.py' -v
python3 -B -m unittest discover -s test -p 'test_*.py' -v
```

The script tests cover receipt matching, balance and supply calculations,
one-wei mismatches, null and empty results, and transport failures. The fake RPC
in the balance tests runs the real `rpc_call` with a mocked HTTP transport, so
timeouts, connection failures, HTTP errors, and invalid JSON exercise its actual
exception handling.

The integration tests cover primary success, fallback request ordering, partial
primary page rejection, and exit codes 0, 1, and 2. All provider calls in these
tests are mocked; no live RPC is called.

## Runtime evidence and draft limitations

The primary retry policy now uses three attempts with backoff delays
of 2 and 4 seconds. An offline regression test uses the production
retry setting and verifies six seconds of scheduled sleep without
actually waiting.

Offline tests establish behavior under mocked responses. Public RPC availability
and fallback runtime still require live validation. Receipt and balance checks
do not reconstruct the complete history of on-chain transfers.
