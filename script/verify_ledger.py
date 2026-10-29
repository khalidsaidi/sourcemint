#!/usr/bin/env python3
"""Verify SourceMint's accounting invariant against the chain.

Invariant: every on-chain SRCMNT transfer OUT of a project wallet (treasury,
rewards) must have a matching entry in rewards/ledger.json with a stated
reason. The genesis mint must also be ledgered. Transfers between third
parties are outside project accounting and are ignored.

Exit codes:
  0  verified: every project-wallet movement is accounted for
  1  ACCOUNTING VIOLATION: an unaccounted movement, or a ledger entry the
     chain does not show
  2  COULD NOT VERIFY: no data source was reachable (an infrastructure
     outage, not a finding about the ledger)

The 1/2 split matters. The public indexers this reads are intermittently
unavailable, and an outage must never be reported as an accounting
violation. Deferring is safe: each run re-checks the token's entire
transfer history rather than a delta, so nothing can slip through a missed
run - the next successful run still sees it.

Run: python3 script/verify_ledger.py
"""

import json
import sys
from collections import Counter
import time
import re
import os
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path

if __package__:
    from .fetch_rpc_transfers import fetch_rpc_transfers
else:
    from fetch_rpc_transfers import fetch_rpc_transfers

LEDGER_PATH = Path(__file__).resolve().parent.parent / "rewards" / "ledger.json"

# The chain is the source of truth. The full transfer history is derivable from
# any public Base RPC endpoint via eth_getLogs — no API key, no account, nobody's
# permission. That is what makes this ledger checkable by a stranger.
#
# The indexers below answer the same question in seconds instead of an hour, so
# they are tried first as a shortcut. If none answers, the history is derived
# from the chain directly. Losing an indexer costs time, never verifiability.
DEPLOYMENT_BLOCK = 41988939
RPC_WINDOW = int(os.environ.get("BASE_RPC_WINDOW", "1000"))
INDEXERS = (
    "https://base.blockscout.com/api/v2/tokens/{token}/transfers",
)
DECIMALS = 10**18
ATTEMPTS_PER_SOURCE = 3   # 3 attempts; 2s + 4s backoff before RPC fallback
ZERO_ADDRESS = "0x" + "00" * 20
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)


class SourceUnavailable(Exception):
    """Every data source failed; we cannot say anything about the ledger."""

class AccountingViolation(Exception):
    pass


def amount_to_wei(amount):
    if not isinstance(amount, str):
        raise AccountingViolation("Ledger amount must be a decimal string")

    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise AccountingViolation(f"Invalid ledger amount: {amount!r}") from exc

    if not value.is_finite() or value < 0:
        raise AccountingViolation(f"Ledger amount must be finite and non-negative: {amount!r}")

    numerator, denominator = value.as_integer_ratio()
    amount_wei, remainder = divmod(numerator * DECIMALS, denominator)
    if remainder:
        raise AccountingViolation(f"Ledger amount exceeds 18 decimal places: {amount!r}")
    return amount_wei


def is_hex_bytes(value, size):
    return (
        isinstance(value, str)
        and re.fullmatch(r"0x[0-9a-fA-F]{" + str(size * 2) + r"}", value)
        is not None
    )


def _get_page(url: str, params: dict) -> dict:
    """One page, retried with exponential backoff. Raises SourceUnavailable."""
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = Request(full, headers={"User-Agent": "sourcemint-ledger-verifier"})
    last = None
    for attempt in range(ATTEMPTS_PER_SOURCE):
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code < 500:  # 4xx will not fix itself by waiting
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = type(e).__name__
        if attempt < ATTEMPTS_PER_SOURCE - 1:
            time.sleep(2 ** (attempt + 1))
    raise SourceUnavailable(last or "unknown error")


def rpc_call(payload: dict) -> dict:
    endpoint = os.environ.get("BASE_RPC_URL")
    if not endpoint:
        raise SourceUnavailable("BASE_RPC_URL is not configured")

    body = json.dumps(payload).encode("utf-8")

    http_request = Request(
        url=endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "sourcemint-ledger-verifier",
        },
        method="POST",
    )

    last = None
    for attempt in range(ATTEMPTS_PER_SOURCE):
        try:
            with urlopen(http_request, timeout=30) as resp:
                return json.load(resp)
        except HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise SourceUnavailable(f"RPC HTTP {e.code}") from e
            last = f"RPC HTTP {e.code}"
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            last = f"RPC transport/JSON failure: {type(e).__name__}"
        if attempt < ATTEMPTS_PER_SOURCE - 1:
            time.sleep(2 ** (attempt + 1))
    raise SourceUnavailable(last or "unknown RPC error")

def fetch_transfers(token: str):
    """Return complete transfer history; discard partial data on failure."""
    problems = []
    for template in INDEXERS:
        url = template.format(token=token)
        try:
            items, params = [], {}
            while True:
                page = _get_page(url, params)
                if not isinstance(page, dict):
                    raise SourceUnavailable("Primary response must be an object")
                if not isinstance(page.get("items"), list):
                    raise SourceUnavailable("Primary items missing or invalid")
                if "next_page_params" not in page:
                    raise SourceUnavailable("Primary pagination field missing")

                nxt = page.get("next_page_params")

                if nxt is not None and (not isinstance(nxt, dict) or not nxt):
                    raise SourceUnavailable("Primary pagination invalid")

                items.extend(page.get("items", []))
                if nxt is None:
                    break
                params = nxt
            return items
        except SourceUnavailable as e:
            problems.append(f"{url.split('/')[2]}: {e}")

    print(f"note: no indexer reachable ({'; '.join(problems)});"
          " deriving the full history from the chain")
    head = _rpc_result(
        rpc_call({"jsonrpc": "2.0", "id": 1,
                  "method": "eth_blockNumber", "params": []}),
        "eth_blockNumber",
    )
    try:
        return fetch_rpc_transfers(
            token, DEPLOYMENT_BLOCK, int(head, 16), rpc_call, RPC_WINDOW
        )
    except ValueError as e:
        problems.append(f"eth_getLogs: {e}")
        raise SourceUnavailable("; ".join(problems)) from e

def _rpc_result(response, method):
    if not isinstance(response, dict):
        raise SourceUnavailable(f"Response {method} must be an object")

    if (
        response.get("jsonrpc") != "2.0"
        or type(response.get("id")) is not int
        or response.get("id") != 1
    ):
        raise SourceUnavailable(f"{method}: invalid jsonrpc or id")

    if "error" in response:
        raise SourceUnavailable(f"{method} RPC response failed: {response['error']}")
    if "result" not in response:
        raise SourceUnavailable(f"{method} RPC result field missing")

    result = response["result"]

    if method in ("balanceOf", "totalSupply"):
        if not is_hex_bytes(result, 32):
            raise SourceUnavailable(f"{method}: expected 32-byte hex")

    elif method == "eth_blockNumber":
        if (
            not isinstance(result, str)
            or re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", result) is None
        ):
            raise SourceUnavailable(f"{method}: invalid block number")

    else:
        raise SourceUnavailable(f"Unsupported method: {method}")

    return result


def main() -> int:
    ledger = json.loads(LEDGER_PATH.read_text())
    token = ledger["token"]
    wallets = {a.lower() for a in ledger["project_wallets"].values()}
    try:
        # A movement is (tx, from, to, amount). `from` is part of the identity:
        # without it an entry can name the wrong source wallet and still match.
        # And this is a multiset, not a set — one transaction can carry the same
        # movement more than once, and each occurrence needs its own entry.
        entries = Counter()
        entry_by_key = {}
        for e in ledger["entries"]:
            frm = ZERO_ADDRESS if e["from"] == "mint" else e["from"].lower()
            key = (e["tx"].lower(), frm, e["to"].lower(),
                   amount_to_wei(e["amount"]))
            entries[key] += 1
            entry_by_key.setdefault(key, e)
    except AccountingViolation as exc:
        print(f"Invalid ledger: {exc}")
        return 1
    observed = Counter()
    unaccounted = []
    checked = 0

    try:
        transfers = fetch_transfers(token)
    except SourceUnavailable as e:
        print("COULD NOT VERIFY: no transfer history could be obtained.")
        print(f"  tried: {e}")
        print("  This is an infrastructure outage, not a finding about the ledger.")
        print("  The next successful run re-checks the full history.")
        return 2

    for t in transfers:
        frm = t["from"]["hash"].lower()
        to = t["to"]["hash"].lower()
        tx = t["transaction_hash"].lower()
        amount_wei = int(t["total"]["value"])
        whole, fractional = divmod(amount_wei, DECIMALS)
        amount = f"{whole}.{fractional:018d}".rstrip("0").rstrip(".")
        is_mint = frm == "0x" + "0" * 40
        if not (is_mint or frm in wallets):
            continue  # third-party movement: outside project accounting
        checked += 1
        key = (tx, frm, to, amount_wei)
        observed[key] += 1
        if observed[key] > entries[key]:
            unaccounted.append(f"  {tx} {'mint' if is_mint else frm} -> {to} : {amount} SRCMNT")

    # Every claimed occurrence must be observed, not merely the key seen once.
    missing_onchain = []
    for key, claimed in entries.items():
        shortfall = claimed - observed[key]
        if shortfall > 0:
            e = entry_by_key[key]
            times = "" if shortfall == 1 else f" x{shortfall}"
            missing_onchain.append(
                f"  {e['tx']} {e['from']} -> {e['to']} : {e['amount']} SRCMNT"
                f"{times} ({e['reason'][:50]}...)"
            )

    matched = sum(min(c, observed[k]) for k, c in entries.items())
    print(f"project-wallet transfers checked on-chain: {checked}")
    print(f"ledger entries matched: {matched}/{sum(entries.values())}")

    ok = True
    if unaccounted:
        ok = False
        print("\nUNACCOUNTED on-chain movements (no ledger entry):")
        print("\n".join(unaccounted))
    if missing_onchain:
        ok = False
        print("\nLEDGER entries not found on-chain:")
        print("\n".join(missing_onchain))

    print("\nRESULT:", "OK — every project-wallet movement is accounted for." if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
