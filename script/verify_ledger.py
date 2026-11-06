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
  2  COULD NOT VERIFY: coverage, canonical identity or a required read
     could not be established within the configured budgets

A run scans this token's Transfer logs continuously from DEPLOYMENT_BLOCK
through a fixed head. Success trusts complete RPC responses; it is not an
independent receipt proof. A later failed page preserves canonical observations,
while missing coverage cannot prove a ledger entry false. State reads use the
same canonical block hash. Budgets can make a run inconclusive; no nonce-based
fallback is used.

Run: python3 script/verify_ledger.py
"""

import json
import sys
from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass
import math
import time
import re
import os
import urllib.request
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path

if __package__:
    from .decode_transfer_fixture import decode_transfer
else:
    from decode_transfer_fixture import decode_transfer

LEDGER_PATH = Path(__file__).resolve().parent.parent / "rewards" / "ledger.json"

# Scan the configured token from its deployment through one fixed head.
# These endpoints must serve the ledger's chain; both are checked before use.
DEPLOYMENT_BLOCK = 41988939
LOGS_RPC_URL = os.environ.get(
    "BASE_LOGS_RPC_URL", "https://base.gateway.tenderly.co")
DECIMALS = 10**18
ZERO_ADDRESS = "0x" + "00" * 20
# Approval(address indexed owner, address indexed spender, uint256 value)
ALLOWANCE_SELECTOR = "0xdd62ed3e"
APPROVAL_TOPIC = (
    "0x8c5be1e5ebec7d5bd14f71427d1e84f3"
    "dd0314c0f7b2291e5b200ac8c7c3b925"
)
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


# Retain pacing/retry settings, but every wire attempt during verification
# shares the history's request, elapsed-time and response-size budgets.
RPC_MIN_INTERVAL = float(os.environ.get("BASE_RPC_MIN_INTERVAL", "0.05"))
_last_call = [0.0]
_pace = [RPC_MIN_INTERVAL]      # grows if the endpoint pushes back
RPC_ATTEMPTS = int(os.environ.get("BASE_RPC_ATTEMPTS", "6"))


# JSON-RPC error codes that mean "ask again later" rather than "you asked for
# something impossible". -32005 is the standard limit-exceeded code; providers
# also use -32011 and -32097 for their own throttling. -32000 is deliberately
# absent: it is the generic server-error code and carries no meaning, so
# retrying it would retry permanent failures six times over. A provider that
# throttles with -32000 will say so in the message, which is checked below.
_TRANSIENT_RPC_CODES = {-32005, -32011, -32097}
_TRANSIENT_RPC_WORDS = ("rate", "limit", "throttl", "timeout", "timed out",
                        "capacity", "overloaded", "try again", "too many")


def _is_transient(error: dict) -> bool:
    """Whether a JSON-RPC error is worth retrying.

    An HTTP 200 whose body is an error is the easiest throttle to mistake for
    a permanent failure; a range that is too large looks identical at the
    transport layer and must not be retried.
    """
    if error.get("code") in _TRANSIENT_RPC_CODES:
        return True
    blob = f"{error.get('message', '')} {error.get('data', '')}".lower()
    return any(word in blob for word in _TRANSIENT_RPC_WORDS)


def rpc_call(payload: dict, endpoint: str = None) -> dict:
    budget = _active_budget.get()
    if budget is not None:
        budget.check()
    wait = _pace[0] - (time.monotonic() - _last_call[0])
    if wait > 0:
        budget.pause(wait) if budget is not None else time.sleep(wait)
    _last_call[0] = time.monotonic()

    endpoint = endpoint or os.environ.get("BASE_RPC_URL")
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

    # Retry transient transport failures within the shared run budget.
    # Throttling arrives in three different shapes: an HTTP status, a
    # dropped connection, or — the one that is easy to miss — a perfectly
    # successful HTTP 200 whose JSON-RPC body carries an error. All three are
    # transient and all three are retried.
    last = None
    cause = None          # keep the original exception so the traceback survives
    for attempt in range(RPC_ATTEMPTS):
        try:
            if budget is not None:
                budget.attempt()
            timeout = min(30, budget.deadline - time.monotonic()) if budget else 30
            with urlopen(http_request, timeout=timeout) as resp:
                cap = budget.response_bytes if budget else 8 * 1024**2
                body = resp.read(cap + 1)
                if len(body) > cap:
                    raise SourceUnavailable("RPC response exceeds byte budget")
                response = json.loads(body)
        except HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise SourceUnavailable(f"RPC HTTP {e.code}") from e
            last, cause = f"RPC HTTP {e.code}", e
            if e.code == 429:
                _pace[0] = min(max(_pace[0], 0.05) * 2, 1.0)
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeError) as e:
            last, cause = f"RPC transport/JSON failure: {type(e).__name__}", e
        else:
            error = response.get("error") if isinstance(response, dict) else None
            if not isinstance(error, dict) or not _is_transient(error):
                return response
            last = f"RPC error {error.get('code')}: {str(error.get('message'))[:60]}"
            _pace[0] = min(max(_pace[0], 0.05) * 2, 1.0)

        if attempt < RPC_ATTEMPTS - 1:
            delay = 2 ** (attempt + 1)
            budget.pause(delay) if budget is not None else time.sleep(delay)
    raise SourceUnavailable(last or "unknown RPC error") from cause

_WIRE_RPC_CALL = rpc_call


@dataclass
class TransferHistory:
    transfers: list
    head: int
    head_hash: str
    covered_to: int
    complete: bool = False
    canonical: bool = False
    error: str = ""
    budget: object = None

    @property
    def block_ref(self):
        return {"blockHash": self.head_hash, "requireCanonical": True}


_active_budget = ContextVar("ledger_rpc_budget", default=None)


class RpcBudget:
    def __init__(self, requests=2048, seconds=300, response_bytes=8 * 1024**2):
        if type(requests) is not int or requests <= 0:
            raise SourceUnavailable("request budget must be a positive integer")
        if not math.isfinite(seconds) or seconds <= 0:
            raise SourceUnavailable("time budget must be finite and positive")
        if type(response_bytes) is not int or response_bytes <= 0:
            raise SourceUnavailable("response budget must be a positive integer")
        self.limit = requests
        self.used = 0
        self.reserve = 0
        self.deadline = time.monotonic() + seconds
        self.response_bytes = response_bytes

    def check(self):
        if self.used >= self.limit - self.reserve:
            raise SourceUnavailable("RPC request budget exhausted")
        if time.monotonic() >= self.deadline:
            raise SourceUnavailable("RPC time budget exhausted")

    def attempt(self):
        self.check()
        self.used += 1

    def pause(self, seconds):
        if seconds >= self.deadline - time.monotonic():
            raise SourceUnavailable("RPC time budget exhausted before retry")
        time.sleep(seconds)

    def call(self, rpc, payload, endpoint=None):
        self.check()
        before = self.used
        token = _active_budget.set(self)
        try:
            # Tests and custom adapters may implement one logical request
            # without entering rpc_call's wire-attempt loop.
            return rpc(payload) if endpoint is None else rpc(payload, endpoint=endpoint)
        finally:
            _active_budget.reset(token)
            if self.used == before and rpc is not _WIRE_RPC_CALL:
                self.attempt()


def _quantity(value):
    if not isinstance(value, str) or re.fullmatch(
            r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value) is None:
        raise SourceUnavailable("invalid RPC quantity")
    return int(value, 16)


def _request(budget, method, params, endpoint=None):
    return _rpc_result(budget.call(rpc_call, {
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
    }, endpoint), method)


def _header(budget, number, endpoint=None):
    result = _request(budget, "eth_getBlockByNumber", [number, False], endpoint)
    if number != "latest" and _quantity(result["number"]) != _quantity(number):
        raise SourceUnavailable("RPC returned the wrong block height")
    return result


class HistoryConflict(SourceUnavailable):
    """RPC event metadata contradicts this snapshot or earlier observations."""


def _history_page(logs, token, start, end, head, head_hash):
    page = {}
    for raw in logs:
        if not isinstance(raw, dict) or raw.get("removed", False) is not False:
            raise SourceUnavailable("invalid or removed log")
        if not is_hex_bytes(raw.get("address"), 20) or raw["address"].lower() != token.lower():
            raise SourceUnavailable("log belongs to another token")
        number = _quantity(raw.get("blockNumber"))
        index = _quantity(raw.get("logIndex"))
        tx_index = _quantity(raw.get("transactionIndex"))
        if not start <= number <= end or not is_hex_bytes(raw.get("blockHash"), 32):
            raise SourceUnavailable("log is outside the requested range or has no block hash")
        topics = raw.get("topics")
        if not isinstance(topics, list) or len(topics) != 3 or any(
                not is_hex_bytes(t, 32) for t in topics):
            raise SourceUnavailable("invalid ERC20 Transfer topics")
        if topics[0].lower() != TRANSFER_TOPIC:
            raise SourceUnavailable("unexpected event signature")
        if any(int(t[2:26], 16) for t in topics[1:]):
            raise SourceUnavailable("nonzero address padding in Transfer topic")
        normalized = dict(raw, topics=[t.lower() for t in topics])
        try:
            decoded = decode_transfer(normalized)
        except (ValueError, TypeError, KeyError) as exc:
            raise SourceUnavailable(f"invalid Transfer: {exc}") from exc
        decoded["transaction_hash"] = decoded["transaction_hash"].lower()
        decoded["from"]["hash"] = decoded["from"]["hash"].lower()
        decoded["to"]["hash"] = decoded["to"]["hash"].lower()
        identity = (raw["blockHash"].lower(), index)
        if number == head and raw["blockHash"].lower() != head_hash:
            raise HistoryConflict("log at the fixed head has a different hash")
        value = (number, tx_index, index, decoded)
        if identity in page and page[identity] != value:
            raise HistoryConflict("conflicting copies of one log")
        page[identity] = value
    return page


def derive_transfers(token: str, wallets, chain_id=8453):
    """Continuous token-log coverage, never wallet-nonce sampling.

    Successful eth_getLogs responses are trusted RPC evidence, not receipt
    proofs. Budgets or bad responses leave explicit incomplete coverage.
    """
    try:
        span = int(os.environ.get("BASE_HISTORY_BLOCK_SPAN", "10000"))
        log_cap = int(os.environ.get("BASE_HISTORY_MAX_LOGS_PER_PAGE", "10000"))
        total_log_cap = int(os.environ.get("BASE_HISTORY_MAX_LOGS", "100000"))
        budget = RpcBudget(
            int(os.environ.get("BASE_HISTORY_MAX_REQUESTS", "2048")),
            float(os.environ.get("BASE_HISTORY_TIMEOUT", "300")),
            int(os.environ.get("BASE_HISTORY_MAX_RESPONSE_BYTES", str(8 * 1024**2))))
    except (TypeError, ValueError, OverflowError) as exc:
        raise SourceUnavailable("invalid history budget configuration") from exc
    if span <= 0 or log_cap <= 0 or total_log_cap <= 0 or not is_hex_bytes(token, 20):
        raise SourceUnavailable("invalid token or history page limits")
    if type(chain_id) is not int or chain_id <= 0 or any(
            not is_hex_bytes(w, 20) for w in wallets):
        raise SourceUnavailable("invalid chain or project wallet")
    for endpoint in (None, LOGS_RPC_URL):
        if _quantity(_request(budget, "eth_chainId", [], endpoint)) != chain_id:
            raise SourceUnavailable("RPC chain ID differs from ledger.chain_id")
    header = _header(budget, "latest")
    head = _quantity(header["number"])
    if head < DEPLOYMENT_BLOCK:
        raise SourceUnavailable("chain head precedes the deployment block")
    history = TransferHistory([], head, header["hash"].lower(),
                              DEPLOYMENT_BLOCK - 1, budget=budget)
    log_header = _header(budget, hex(head), LOGS_RPC_URL)
    if log_header["hash"].lower() != history.head_hash:
        raise SourceUnavailable("RPC endpoints disagree about the fixed head")
    cursor = DEPLOYMENT_BLOCK
    seen, number_hash, hash_number = {}, {}, {}
    # Reserve both endpoint head checks. Even after a page exhausts its
    # request allowance, earlier pages can still be confirmed or rejected.
    budget.reserve = 2
    try:
        while cursor <= head:
            end = min(head, cursor + span - 1)
            logs = _request(budget, "eth_getLogs", [{
                "address": token, "topics": [TRANSFER_TOPIC],
                "fromBlock": hex(cursor), "toBlock": hex(end),
            }], LOGS_RPC_URL)
            # A provider cap may mean an incomplete array even with HTTP200.
            # Do not accept a capped page as complete or advance its cursor.
            if len(logs) >= log_cap:
                raise SourceUnavailable("log page reached the configured result cap")
            page = _history_page(logs, token, cursor, end, head, history.head_hash)
            staged_numbers, staged_hashes = dict(number_hash), dict(hash_number)
            added = []
            for identity, value in page.items():
                block_hash, _ = identity
                number = value[0]
                if ((number in staged_numbers and staged_numbers[number] != block_hash)
                        or (block_hash in staged_hashes and staged_hashes[block_hash] != number)):
                    raise HistoryConflict("conflicting block number/hash in history")
                if identity in seen and seen[identity] != value:
                    raise HistoryConflict("log identity changed between pages")
                staged_numbers[number] = block_hash
                staged_hashes[block_hash] = number
                if identity not in seen:
                    added.append(value)
            if len(seen) + len(added) > total_log_cap:
                raise SourceUnavailable("history log-memory budget exhausted")
            seen.update(page)
            number_hash, hash_number = staged_numbers, staged_hashes
            history.transfers.extend(value[3] for value in sorted(added,
                                        key=lambda value: value[:3]))
            history.covered_to = end
            cursor = end + 1
        history.complete = True
    except HistoryConflict as exc:
        # A self-contradictory provider invalidates this run's observations;
        # do not preserve a finding produced by the contradictory records.
        history.error = str(exc)
        return history
    except SourceUnavailable as exc:
        history.error = str(exc)
    finally:
        budget.reserve = 0
    try:
        for endpoint in (None, LOGS_RPC_URL):
            current = _header(budget, hex(head), endpoint)
            if current["hash"].lower() != history.head_hash:
                raise SourceUnavailable("fixed-head hash changed during history scan")
        history.canonical = True
    except SourceUnavailable as exc:
        history.complete = False
        history.error = str(exc)
    return history


def fetch_transfers(token: str, wallets, chain_id=8453):
    return derive_transfers(token, wallets, chain_id)


def _srcmnt(wei, signed=False):
    """Whole-token rendering for operator-facing messages. Integer math only."""
    sign = "+" if (signed and wei > 0) else ("-" if wei < 0 else "")
    whole, frac = divmod(abs(wei), DECIMALS)
    body = f"{whole:,}" if frac == 0 else f"{whole:,}.{frac:018d}".rstrip("0").rstrip(".")
    return sign + body


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

    if method in ("balanceOf", "totalSupply", "allowance"):
        if not is_hex_bytes(result, 32):
            raise SourceUnavailable(f"{method}: expected 32-byte hex")

    elif method == "eth_getTransactionCount":
        if (
            not isinstance(result, str)
            or re.fullmatch(r"0x[0-9a-fA-F]+", result) is None
        ):
            raise SourceUnavailable(f"{method}: expected a hex quantity")

    elif method == "eth_getLogs":
        if not isinstance(result, list):
            raise SourceUnavailable(f"{method}: expected a list of logs")

    elif method in ("eth_blockNumber", "eth_chainId"):
        if (
            not isinstance(result, str)
            or re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", result) is None
        ):
            raise SourceUnavailable(f"{method}: invalid block number")

    elif method == "eth_getBlockByNumber":
        if not isinstance(result, dict) or not is_hex_bytes(result.get("hash"), 32):
            raise SourceUnavailable("invalid block header")
        _quantity(result.get("number"))
    elif method == "eth_getTransactionReceipt":
        if result is not None and not isinstance(result, dict):
            raise SourceUnavailable("invalid transaction receipt")
    else:
        raise SourceUnavailable(f"Unsupported method: {method}")

    return result


def verify_balances_total_supply(ledger, token, rpc, block=None):
    wallets = ledger["project_wallets"]
    expected_state = calculate_expected_state(ledger)

    if block is None:
        block = _rpc_result(rpc({"jsonrpc": "2.0", "method": "eth_blockNumber",
                                 "params": [], "id": 1}), "eth_blockNumber")

    for name, address in wallets.items():
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
            delta = actual_amount - expected_amount
            raise AccountingViolation(
                f"{name} wallet {address} holds {_srcmnt(actual_amount)} SRCMNT, "
                f"but the ledger accounts for {_srcmnt(expected_amount)} "
                f"({_srcmnt(delta, signed=True)} unaccounted). "
                "A transfer out of a project wallet is missing from rewards/ledger.json."
            )

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
        history = fetch_transfers(token, wallets, ledger["chain_id"])
        if not isinstance(history, TransferHistory):
            raise SourceUnavailable("history source did not provide coverage metadata")
        transfers = history.transfers
    except SourceUnavailable as e:
        print("COULD NOT VERIFY: no transfer history could be obtained.")
        print(f"  tried: {e}")
        print("  This is an infrastructure outage, not a finding about the ledger.")
        print("  The next successful run re-checks the full history.")
        return 2

    if not history.canonical:
        print("COULD NOT VERIFY: fixed-head history was not confirmed canonical.")
        print(f"  {history.error}")
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

    print(f"history coverage: {DEPLOYMENT_BLOCK}..{history.covered_to} "
          f"of fixed head {history.head} ({history.head_hash})")
    if not history.complete:
        print(f"history incomplete: {history.error}")
        if unaccounted:
            print("\nRESULT: FAIL — confirmed unaccounted movement in covered history.")
            return 1
        print("COULD NOT VERIFY: unobserved entries are not findings in partial history.")
        return 2

    # An absent entry can refer to a pending or post-snapshot transaction.
    # Only a canonical receipt inside this covered interval makes absence a
    # finding; null, future or unavailable receipts leave it inconclusive.
    unresolved = False
    missing_finding = False
    def state_rpc(payload):
        return history.budget.call(rpc_call, payload) if history.budget else rpc_call(payload)

    if history.budget:
        history.budget.reserve = 2  # final fixed-head checks cannot be spent on state/retries
    if missing_onchain:
        for tx in {key[0] for key in entries if entries[key] > observed[key]}:
            try:
                receipt = _rpc_result(state_rpc({"jsonrpc": "2.0", "id": 1,
                    "method": "eth_getTransactionReceipt", "params": [tx]}),
                    "eth_getTransactionReceipt")
                if receipt is None:
                    unresolved = True
                    continue
                number = _quantity(receipt.get("blockNumber"))
                if (not is_hex_bytes(receipt.get("transactionHash"), 32) or
                        receipt["transactionHash"].lower() != tx or
                        not is_hex_bytes(receipt.get("blockHash"), 32)):
                    raise SourceUnavailable("receipt identity is invalid")
                if not DEPLOYMENT_BLOCK <= number <= history.head:
                    unresolved = True
                    continue
                header = _rpc_result(state_rpc({"jsonrpc": "2.0", "id": 1,
                    "method": "eth_getBlockByNumber", "params": [hex(number), False]}),
                    "eth_getBlockByNumber")
                if (_quantity(header["number"]) != number or
                        header["hash"].lower() != receipt["blockHash"].lower()):
                    unresolved = True
                else:
                    missing_finding = True
            except SourceUnavailable as exc:
                print(f"note: missing-entry receipt unchecked ({exc})")
                unresolved = True
        ok = not (unaccounted or missing_finding)

    # A pending/future ledger item does not belong to the H-time state.
    # Never compare its nonzero amount against H and call that a violation.
    state_unavailable = False
    if not unresolved:
        try:
            verify_balances_total_supply(ledger, token, state_rpc, history.block_ref)
        except AccountingViolation as exc:
            ok = False
            print("\nBALANCE UNEXPLAINED:")
            print(f"  {exc}")
        except SourceUnavailable as exc:
            state_unavailable = True
            print(f"note: snapshot balances unchecked ({exc})")

    # Receipts and state must not introduce findings from a later fork.
    # Confirm H again after those reads, including after state errors.
    if history.budget:
        history.budget.reserve = 0
    try:
        for endpoint in (None, LOGS_RPC_URL):
            payload = {"jsonrpc": "2.0", "id": 1,
                       "method": "eth_getBlockByNumber", "params": [hex(history.head), False]}
            response = (history.budget.call(rpc_call, payload, endpoint)
                        if history.budget else rpc_call(payload, endpoint=endpoint))
            current = _rpc_result(response, "eth_getBlockByNumber")
            if (_quantity(current["number"]) != history.head or
                    current["hash"].lower() != history.head_hash):
                raise SourceUnavailable("fixed-head identity changed after receipt/state reads")
    except SourceUnavailable as exc:
        print(f"COULD NOT VERIFY: final snapshot identity unavailable ({exc}).")
        return 2

    if unresolved and not unaccounted and not missing_finding:
        print("COULD NOT VERIFY: ledger entries are outside or unresolved at the snapshot.")
        return 2
    if state_unavailable and ok:
        print("COULD NOT VERIFY: no finding established and snapshot state unreadable.")
        return 2
    # Complete Transfer coverage includes transferFrom irrespective of current
    # allowance. A live allowance is future authority, not past missing history.
    print("\nRESULT:", "OK — ledger matches trusted RPC history at the fixed head."
          if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
