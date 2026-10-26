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
import time
import re
import os
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parent.parent / "rewards" / "ledger.json"

# Transfer-history sources, tried in order. Add more here if another free,
# no-key indexer for Base becomes available; the loop below handles failover.
SOURCES = (
    "https://base.blockscout.com/api/v2/tokens/{token}/transfers",
)
DECIMALS = 10**18
ATTEMPTS_PER_SOURCE = 3   # 3 attempts; 2s + 4s backoff before RPC fallback
ZERO_ADDRESS = "0x" + "00" * 20
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)
BALANCE_OF_SELECTOR = "0x70a08231"
TOTAL_SUPPLY_SELECTOR = "0x18160ddd"


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

    try:
        with urlopen(http_request, timeout=10) as resp:
            return json.load(resp)
    except HTTPError as e:
        raise SourceUnavailable(f"RPC HTTP {e.code}") from e
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        raise SourceUnavailable(
            f"RPC transport/JSON failure: {type(e).__name__}"
        ) from e

def fetch_transfers(token: str):
    """Return complete transfer history; discard partial data on failure."""
    problems = []
    for template in SOURCES:
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
            if template is not SOURCES[0]:
                print(f"note: primary source unavailable, used {url.split('/')[2]}")
            return items
        except SourceUnavailable as e:
            problems.append(f"{url.split('/')[2]}: {e}")
    raise SourceUnavailable("; ".join(problems))

def verify_rpc_fallback(ledger, token, rpc):
    for entry in ledger["entries"]:
            tx_hash = entry["tx"]
            expected_amount = amount_to_wei(entry["amount"])
            response = rpc({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getTransactionReceipt",
                "params": [tx_hash],
            })

            if not isinstance(response, dict):
                raise SourceUnavailable("RPC response must be an object")

            if (
                response.get("jsonrpc") != "2.0"
                or type(response.get("id")) is not int
                or response.get("id") != 1
                or "error" in response
            ):
                raise SourceUnavailable("Invalid or failed receipt response")

            if "result" not in response:
                raise SourceUnavailable("RPC result field missing")

            result = response.get("result")

            if result is None:
                raise SourceUnavailable("Transaction receipt unavailable")

            if not isinstance(result, dict):
                raise SourceUnavailable("RPC response must be an object")


            receipt_tx = result.get("transactionHash")

            if not is_hex_bytes(receipt_tx, 32):
                raise SourceUnavailable("Invalid receipt transactionHash")

            if receipt_tx.lower() != tx_hash.lower():
                raise SourceUnavailable("Receipt transactionHash mismatch")

            status = result.get("status")

            if (status == "0x0"):
                raise AccountingViolation("Transaction failed")

            if(status != "0x1"):
                raise SourceUnavailable("Invalid or missing receipt status")

            logs = result.get("logs")

            if not isinstance(logs, list):
                raise SourceUnavailable("Receipt logs must be list")

            matched = False

            for log in logs:
                if not isinstance(log, dict):
                    raise SourceUnavailable("Each log must be an object")

                address = log.get("address")
                if not is_hex_bytes(address, 20):
                    raise SourceUnavailable("Invalid log address")

                if address.lower() != token.lower():
                    continue

                topics = log.get("topics")
                if not isinstance(topics, list):
                    raise SourceUnavailable("Log topics must be a list")

                if not topics:
                    continue

                if not is_hex_bytes(topics[0], 32):
                    raise SourceUnavailable("Invalid event signature topic")

                if topics[0].lower() != TRANSFER_TOPIC.lower():
                    continue

                if len(topics) != 3:
                    raise SourceUnavailable("ERC20 Transfer must have 3 topics")

                if not all(is_hex_bytes(topic, 32) for topic in topics[1:]):
                    raise SourceUnavailable("Invalid Transfer address topics")

                if any(topic[2:26] != "0" * 24 for topic in topics[1:]):
                    raise SourceUnavailable("Invalid address topic padding")

                data = log.get("data")

                if not is_hex_bytes(data, 32):
                    raise SourceUnavailable("Transfer data must be 32-byte hex")

                log_tx = log.get("transactionHash")

                if not is_hex_bytes(log_tx, 32):
                    raise SourceUnavailable("Invalid Transfer transactionHash")

                if log_tx.lower() != tx_hash.lower():
                    raise SourceUnavailable("Transfer transactionHash mismatch")

                sender_topics = topics[1]
                receiver_topics = topics[2]

                sender = "0x" + sender_topics[-40:]
                receiver = "0x" + receiver_topics[-40:]

                if (entry["from"] == "mint"):
                    expected_sender = ZERO_ADDRESS
                else:
                    expected_sender = entry["from"]

                if(sender.lower() != expected_sender.lower()):
                    continue

                if(receiver.lower() != entry["to"].lower()):
                    continue

                if(int(data, 16) != expected_amount):
                    continue

                matched = True

            if (not matched):
                raise AccountingViolation(f"Ledger not matched wit RPC respons: {entry["tx"]} ")

    verify_balances_total_supply(ledger, token, rpc)

    print(
        "RESULT: OK — receipt and balance checks passed "
        "(degraded fallback; full transfer history not checked)."
    )

    return 0

def calculate_expected_state(ledger):
    balances = {}
    total_supply = 0

    for entry in ledger["entries"]:
        sender = entry["from"].lower()
        receiver = entry["to"].lower()
        amount = amount_to_wei(entry["amount"])

        if (sender == "mint"):
            balances[receiver] = balances.get(receiver, 0) + amount
            total_supply += amount
            continue

        elif (receiver == ZERO_ADDRESS):
            balance = balances.get(sender, 0)
            if (balance < amount):
                raise AccountingViolation("Balance sender not enough to burn")

            balances[sender] = balance - amount
            total_supply -= amount
            continue

        balances[sender] = balances.get(sender, 0) - amount
        balances[receiver] = balances.get(receiver, 0) + amount


    return balances, total_supply

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


def verify_balances_total_supply(ledger, token, rpc):
    wallets = ledger["project_wallets"]
    expected_state = calculate_expected_state(ledger)

    response_block = rpc({
        "jsonrpc": "2.0",
        "method": "eth_blockNumber",
        "params": [],
        "id": 1
    })
    block = _rpc_result(response_block, "eth_blockNumber")

    for address in wallets.values():
        address = address.lower()

        response_balance = rpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [
                {
                    "to": token.lower(),
                    "data": BALANCE_OF_SELECTOR + address[2:].zfill(64),
                },
                block
            ],
        })

        balance = _rpc_result(response_balance, "balanceOf")

        actual_amount = int(balance, 16)
        state = expected_state[0]
        expected_amount = state.get(address, 0)


        if (actual_amount != expected_amount):
            raise AccountingViolation("Balances not matched")

    response_total_supply = rpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [
                {
                    "to": token,
                    "data": TOTAL_SUPPLY_SELECTOR,
                },
                block
            ],
        })

    total_supply = int(_rpc_result(response_total_supply, "totalSupply"), 16)

    if (total_supply != expected_state[1]):
        raise AccountingViolation("Total supply mismatch")



def main() -> int:
    ledger = json.loads(LEDGER_PATH.read_text())
    token = ledger["token"]
    wallets = {a.lower() for a in ledger["project_wallets"].values()}
    try:
        entries = {
            (e["tx"].lower(), e["to"].lower(), amount_to_wei(e["amount"])): e
            for e in ledger["entries"]
        }
    except AccountingViolation as exc:
        print(f"Invalid ledger: {exc}")
        return 1
    seen_keys = set()
    unaccounted = []
    checked = 0

    try:
        transfers = fetch_transfers(token)
    except SourceUnavailable as primary_error:
        print(f"note: primary unavailable: {primary_error}")

        try:
            return verify_rpc_fallback(ledger, token, rpc_call)
        except SourceUnavailable as rpc_error:
            print(f"COULD NOT VERIFY: {rpc_error}")
            return 2
        except AccountingViolation as rpc_error:
            print(f"Data: {rpc_error}")
            return 1

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
        key = (tx, to, amount_wei)
        if key in entries:
            seen_keys.add(key)
        else:
            unaccounted.append(f"  {tx} {'mint' if is_mint else frm} -> {to} : {amount} SRCMNT")

    missing_onchain = [
        f"  {e['tx']} -> {e['to']} : {e['amount']} SRCMNT ({e['reason'][:50]}...)"
        for key, e in entries.items()
        if key not in seen_keys
    ]

    print(f"project-wallet transfers checked on-chain: {checked}")
    print(f"ledger entries matched: {len(seen_keys)}/{len(entries)}")

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
