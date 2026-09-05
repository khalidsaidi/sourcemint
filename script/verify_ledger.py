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
import urllib.parse
import urllib.request
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parent.parent / "rewards" / "ledger.json"

# Transfer-history sources, tried in order. Add more here if another free,
# no-key indexer for Base becomes available; the loop below handles failover.
SOURCES = (
    "https://base.blockscout.com/api/v2/tokens/{token}/transfers",
)
DECIMALS = 10**18
ATTEMPTS_PER_SOURCE = 8  # ~2+4+...+128s: rides out several minutes of downtime


class SourceUnavailable(Exception):
    """Every data source failed; we cannot say anything about the ledger."""


def _get_page(url: str, params: dict) -> dict:
    """One page, retried with exponential backoff. Raises SourceUnavailable."""
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers={"User-Agent": "sourcemint-ledger-verifier"})
    last = None
    for attempt in range(ATTEMPTS_PER_SOURCE):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
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


def fetch_transfers(token: str):
    """Yield every transfer for the token, trying each source in turn."""
    problems = []
    for template in SOURCES:
        url = template.format(token=token)
        try:
            items, params = [], {}
            while True:
                page = _get_page(url, params)
                items.extend(page.get("items", []))
                nxt = page.get("next_page_params")
                if not nxt:
                    break
                params = nxt
            if template is not SOURCES[0]:
                print(f"note: primary source unavailable, used {url.split('/')[2]}")
            return items
        except SourceUnavailable as e:
            problems.append(f"{url.split('/')[2]}: {e}")
    raise SourceUnavailable("; ".join(problems))


def main() -> int:
    ledger = json.loads(LEDGER_PATH.read_text())
    token = ledger["token"]
    wallets = {a.lower() for a in ledger["project_wallets"].values()}
    entries = {
        (e["tx"].lower(), e["to"].lower(), e["amount"]): e for e in ledger["entries"]
    }
    seen_keys = set()
    unaccounted = []
    checked = 0

    try:
        transfers = fetch_transfers(token)
    except SourceUnavailable as e:
        print("COULD NOT VERIFY: no transfer data source was reachable.")
        print(f"  tried: {e}")
        print("  This is an infrastructure outage, not a finding about the ledger.")
        print("  The next successful run re-checks the full history.")
        return 2

    for t in transfers:
        frm = t["from"]["hash"].lower()
        to = t["to"]["hash"].lower()
        tx = t["transaction_hash"].lower()
        amount_wei = int(t["total"]["value"])
        if amount_wei % DECIMALS == 0:
            amount = str(amount_wei // DECIMALS)
        else:
            amount = repr(amount_wei / DECIMALS)
        is_mint = frm == "0x" + "0" * 40
        if not (is_mint or frm in wallets):
            continue  # third-party movement: outside project accounting
        checked += 1
        key = (tx, to, amount)
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
