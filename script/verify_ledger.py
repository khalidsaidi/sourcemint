#!/usr/bin/env python3
"""Verify SourceMint's accounting invariant against the chain.

Invariant: every on-chain SRCMNT transfer OUT of a project wallet (treasury,
rewards) must have a matching entry in rewards/ledger.json with a stated
reason. The genesis mint must also be ledgered. Transfers between third
parties are outside project accounting and are ignored.

Exits non-zero if any project-wallet movement is unaccounted, or if the
ledger claims a transfer the chain does not show. Uses the Blockscout
indexer (no API key) with the token's full transfer history.

Run: python3 script/verify_ledger.py
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parent.parent / "rewards" / "ledger.json"
BLOCKSCOUT = "https://base.blockscout.com/api/v2/tokens/{token}/transfers"
DECIMALS = 10**18


def fetch_transfers(token: str):
    """Yield all transfer items from Blockscout, following pagination."""
    url = BLOCKSCOUT.format(token=token)
    params = {}
    while True:
        full = url + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(full, headers={"User-Agent": "sourcemint-ledger-verifier"})
        page = None
        for attempt in range(6):  # the indexer 500s intermittently; retry with backoff
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    page = json.load(resp)
                break
            except urllib.error.HTTPError as e:
                if e.code >= 500 and attempt < 5:
                    time.sleep(2**attempt)
                    continue
                raise
        assert page is not None
        yield from page.get("items", [])
        nxt = page.get("next_page_params")
        if not nxt:
            return
        params = nxt


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

    for t in fetch_transfers(token):
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
