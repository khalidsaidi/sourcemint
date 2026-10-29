#!/usr/bin/env python3
"""Validate the shape of rewards/ledger.json.

The ledger is this project's system of record. The verifier compares it to the
chain, but a malformed entry would surface as an exception midway through that
comparison rather than as a clear error here. Stdlib only, no dependencies.

Run: python3 script/ledger_schema.py
"""
import json
import re
import sys
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parent.parent / "rewards" / "ledger.json"

ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AMOUNT = re.compile(r"^\d+(\.\d{1,18})?$")
ENTRY_FIELDS = {"tx", "date", "from", "to", "amount", "reason"}


def validate(ledger):
    """Return a list of human-readable problems; empty means valid."""
    problems = []

    def need(cond, msg):
        if not cond:
            problems.append(msg)
        return cond

    if not need(isinstance(ledger, dict), "ledger must be a JSON object"):
        return problems

    need(ADDRESS.match(str(ledger.get("token", ""))),
         f"token must be an address, got {ledger.get('token')!r}")
    need(ledger.get("chain_id") == 8453,
         f"chain_id must be 8453 (Base mainnet), got {ledger.get('chain_id')!r}")

    wallets = ledger.get("project_wallets")
    if need(isinstance(wallets, dict) and wallets,
            "project_wallets must be a non-empty object"):
        for name, addr in wallets.items():
            need(ADDRESS.match(str(addr)),
                 f"project_wallets[{name}] must be an address, got {addr!r}")

    entries = ledger.get("entries")
    if not need(isinstance(entries, list), "entries must be a list"):
        return problems

    seen = {}
    for i, e in enumerate(entries):
        where = f"entries[{i}]"
        if not need(isinstance(e, dict), f"{where} must be an object"):
            continue
        missing = ENTRY_FIELDS - set(e)
        need(not missing, f"{where} is missing {sorted(missing)}")
        extra = set(e) - ENTRY_FIELDS - {"ref"}
        need(not extra, f"{where} has unexpected fields {sorted(extra)}")

        need(TX_HASH.match(str(e.get("tx", ""))),
             f"{where}.tx must be a 32-byte hash, got {e.get('tx')!r}")
        need(DATE.match(str(e.get("date", ""))),
             f"{where}.date must be YYYY-MM-DD, got {e.get('date')!r}")
        # The genesis entry records the mint, which has no sending account;
        # the ledger spells that "mint" rather than the zero address.
        frm = str(e.get("from", ""))
        need(ADDRESS.match(frm) or frm == "mint",
             f"{where}.from must be an address or \"mint\", got {e.get('from')!r}")
        need(ADDRESS.match(str(e.get("to", ""))),
             f"{where}.to must be an address, got {e.get('to')!r}")
        # A JSON number would be parsed as a float and lose precision; this
        # project does integer wei arithmetic throughout, so amounts are
        # strings and must stay strings.
        amount = e.get("amount")
        need(isinstance(amount, str) and AMOUNT.match(amount),
             f"{where}.amount must be a decimal *string* with at most 18 "
             f"decimal places, got {amount!r}")
        need(str(e.get("reason", "")).strip(),
             f"{where}.reason must be a non-empty explanation")

        # A transaction can carry several transfers, so the key is the whole
        # movement, not the hash alone.
        # The verifier matches movements as (tx, from, to, amount) multisets,
        # so genuine repeats are legitimate: one transaction can carry the same
        # movement twice and then needs two entries. Only flag an exact
        # duplicate that also repeats the reason, which is almost certainly a
        # copy-paste rather than a real second movement.
        key = (str(e.get("tx", "")).lower(), str(e.get("from", "")).lower(),
               str(e.get("to", "")).lower(), str(e.get("amount", "")),
               str(e.get("reason", "")))
        if key in seen:
            problems.append(
                f"{where} is identical to entries[{seen[key]}], reason included; "
                "if this is a genuine second movement, say so in the reason")
        else:
            seen[key] = i

    return problems


def supply_split(ledger):
    """Balances the ledger implies for each project wallet, in whole SRCMNT.

    The site and whitepaper state this split in prose. Deriving it here means
    a stale page is a test failure rather than something a reader notices.
    """
    from decimal import Decimal
    wallets = {n: a.lower() for n, a in ledger["project_wallets"].items()}
    held = {n: Decimal(0) for n in wallets}
    for e in ledger["entries"]:
        amount = Decimal(e["amount"])
        for name, addr in wallets.items():
            if e["to"].lower() == addr:
                held[name] += amount
            if e["from"].lower() == addr:
                held[name] -= amount
    return held


def main() -> int:
    try:
        ledger = json.loads(LEDGER_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"LEDGER INVALID: cannot read {LEDGER_PATH.name}: {e}")
        return 1

    problems = validate(ledger)
    if problems:
        print(f"LEDGER INVALID: {len(problems)} problem(s) in {LEDGER_PATH.name}")
        for p in problems:
            print(f"  {p}")
        return 1

    split = supply_split(ledger)
    print(f"LEDGER OK: {len(ledger['entries'])} entries, well-formed.")
    for name, amount in split.items():
        print(f"  {name:<10} {amount:>12,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
