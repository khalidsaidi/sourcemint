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
import urllib.request
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path

if __package__:
    from .chain_history import blocks_with_transactions
    from .decode_transfer_fixture import decode_transfer
else:
    from chain_history import blocks_with_transactions
    from decode_transfer_fixture import decode_transfer

LEDGER_PATH = Path(__file__).resolve().parent.parent / "rewards" / "ledger.json"

# The chain is the source of truth. Transfer history is derived from it with
# no API key, no account and nobody's permission — see derive_transfers below.
# The indexers here answer the same question in one request instead of ~190,
# so they are tried first as a shortcut. Losing them costs seconds, not the
# ability to verify.
DEPLOYMENT_BLOCK = 41988939

# Spenders a project wallet has ever granted an allowance to. A live allowance
# means tokens can leave via transferFrom: no nonce increment, and in a block
# the derivation never reads. The verifier must not claim completeness while
# one is outstanding, so it checks each and says so plainly.
LIVE_SPENDERS = []

# No single free Base endpoint serves both halves of the derivation, so there
# are two. Nonces and balances come from BASE_RPC_URL; mainnet.base.org is
# fine for those and refuses eth_getLogs entirely. The handful of single-block
# log reads go to BASE_LOGS_RPC_URL. Both are public and need no key.
LOGS_RPC_URL = os.environ.get(
    "BASE_LOGS_RPC_URL", "https://base.gateway.tenderly.co")
DECIMALS = 10**18
ATTEMPTS_PER_SOURCE = 3   # 3 attempts; 2s + 4s backoff before RPC fallback
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


# Deriving history makes a couple of hundred calls back to back. Free
# endpoints throttle that, so leave a gap between them; the whole run still
# finishes in well under a minute.
RPC_MIN_INTERVAL = float(os.environ.get("BASE_RPC_MIN_INTERVAL", "0.05"))
_last_call = [0.0]


def rpc_call(payload: dict, endpoint: str = None) -> dict:
    wait = RPC_MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
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

    try:
        with urlopen(http_request, timeout=10) as resp:
            return json.load(resp)
    except HTTPError as e:
        raise SourceUnavailable(f"RPC HTTP {e.code}") from e
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        raise SourceUnavailable(
            f"RPC transport/JSON failure: {type(e).__name__}"
        ) from e

def derive_transfers(token: str, wallets):
    """Every SRCMNT movement involving a project wallet, derived from the chain.

    Reading all 11M+ blocks since deployment to find a handful of transactions
    is O(chain). This is O(our own activity):

      1. A nonce is monotonic, so binary-searching `eth_getTransactionCount`
         over block height finds every block in which a wallet sent a
         transaction. Nothing hides there — unlike a balance, a nonce never
         comes back down, so tokens sent out and returned are still two
         separate increments.
      2. Logs are read only for those blocks, plus the deployment block for
         the mint, which no wallet signed.

    A movement the wallet did not sign — a third party spending an allowance
    via `transferFrom` — leaves the nonce untouched. That case is the exact
    complement and is caught by the balance reconciliation in main().

    Needs no API key, no account and no indexer.
    """
    def nonce_at(address, block):
        return int(_rpc_result(
            rpc_call({"jsonrpc": "2.0", "id": 1,
                      "method": "eth_getTransactionCount",
                      "params": [address, hex(block)]}),
            "eth_getTransactionCount"), 16)

    head = int(_rpc_result(
        rpc_call({"jsonrpc": "2.0", "id": 1,
                  "method": "eth_blockNumber", "params": []}),
        "eth_blockNumber"), 16)
    if head < DEPLOYMENT_BLOCK:
        raise SourceUnavailable("chain head precedes the deployment block")

    blocks = {DEPLOYMENT_BLOCK}          # the mint itself
    for address in sorted(wallets):
        blocks.update(blocks_with_transactions(
            address, DEPLOYMENT_BLOCK - 1, head, nonce_at))

    transfers = []
    spenders = set()
    for block in sorted(blocks):
        # One unfiltered read per block gets Transfers and Approvals together;
        # filtering by topic would cost a second request for no benefit.
        logs = _rpc_result(
            rpc_call({"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs",
                      "params": [{"address": token,
                                  "fromBlock": hex(block),
                                  "toBlock": hex(block)}]},
                     endpoint=LOGS_RPC_URL),
            "eth_getLogs")
        for log in logs:
            if log.get("removed"):
                continue             # dropped by a reorg; not part of history
            topics = log.get("topics") or []
            if not topics:
                continue
            if topics[0].lower() == TRANSFER_TOPIC.lower():
                transfers.append(decode_transfer(log))
            elif topics[0].lower() == APPROVAL_TOPIC.lower() and len(topics) == 3:
                owner = "0x" + topics[1][-40:]
                if owner.lower() in {w.lower() for w in wallets}:
                    spenders.add("0x" + topics[2][-40:])
    return transfers, spenders


def fetch_transfers(token: str, wallets):
    """The complete transfer history, derived from the chain.

    There is one source and it is the chain. An indexer would answer faster,
    but every one of them is somebody's service to withdraw — and a shortcut
    that silently skips checks when it works is worse than no shortcut. If a
    free, keyless indexer for Base reappears, it belongs here only if it
    supplies the approvals too.
    """
    transfers, spenders = derive_transfers(token, wallets)
    LIVE_SPENDERS.extend(spenders)
    return transfers


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
        transfers = fetch_transfers(token, wallets)
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

    # Everything above checks movements we signed. A third party spending an
    # allowance moves tokens without touching our nonce and without appearing
    # in a block we looked at — the exact complement. A balance that the
    # ledger cannot explain is what that looks like.
    try:
        verify_balances_total_supply(ledger, token, rpc_call)
    except AccountingViolation as e:
        ok = False
        print("\nBALANCE UNEXPLAINED (a movement we did not sign):")
        print(f"  {e}")
    except SourceUnavailable as e:
        # A violation already found is a finding; an outage must never
        # downgrade it to "could not verify".
        if not ok:
            print(f"\nnote: balances unchecked ({e})")
        else:
            print("COULD NOT VERIFY: transfers matched, but balances could "
                  f"not be read to rule out a movement we did not sign ({e}).")
            return 2

    # An outstanding allowance lets tokens leave without our wallet signing,
    # in a block this derivation never reads. Claiming completeness while one
    # is live would be claiming more than was checked.
    outstanding = []
    for spender in sorted(set(LIVE_SPENDERS)):
        for name, wallet in ledger["project_wallets"].items():
            try:
                raw = _rpc_result(rpc_call({
                    "jsonrpc": "2.0", "id": 1, "method": "eth_call",
                    "params": [{"to": token,
                                "data": ALLOWANCE_SELECTOR
                                        + wallet[2:].lower().zfill(64)
                                        + spender[2:].lower().zfill(64)},
                               "latest"]}), "allowance")
            except SourceUnavailable as e:
                print(f"\nCOULD NOT VERIFY: allowance for {spender} unreadable ({e}).")
                return 2
            if int(raw, 16):
                outstanding.append((name, spender, int(raw, 16)))

    if outstanding:
        ok = False
        print("\nOUTSTANDING ALLOWANCES (tokens can leave without us signing):")
        for name, spender, amount in outstanding:
            shown = "unlimited" if amount > 2**255 else f"{amount // DECIMALS:,}"
            print(f"  {name} -> {spender} : {shown} SRCMNT")
        print("  While these stand, transfers made by the spender do not appear")
        print("  in any block this check reads. Revoke them or the history is")
        print("  not provably complete.")

    print("\nRESULT:", "OK — every project-wallet movement is accounted for." if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
