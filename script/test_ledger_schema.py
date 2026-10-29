import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger_schema import validate  # noqa: E402

REAL = json.loads((Path(__file__).resolve().parent.parent
                   / "rewards" / "ledger.json").read_text())


def mutated(**changes):
    d = json.loads(json.dumps(REAL))
    entry = d["entries"][1]
    entry.update(changes)
    return d


class LedgerSchema(unittest.TestCase):
    def test_the_committed_ledger_is_valid(self):
        self.assertEqual(validate(REAL), [])

    def test_genesis_mint_sentinel_is_allowed(self):
        self.assertEqual(REAL["entries"][0]["from"], "mint")
        self.assertEqual(validate(REAL), [])

    def test_amount_beyond_18_decimals_is_rejected(self):
        self.assertTrue(validate(mutated(amount="1.0000000000000000001")))

    def test_amount_must_be_a_string_not_a_float(self):
        self.assertTrue(validate(mutated(amount=500.0)))

    def test_malformed_tx_hash_is_rejected(self):
        self.assertTrue(validate(mutated(tx="0xdead")))

    def test_blank_reason_is_rejected(self):
        self.assertTrue(validate(mutated(reason="   ")))

    def test_unknown_field_is_rejected(self):
        self.assertTrue(validate(mutated(note="smuggled")))

    def test_duplicate_movement_is_rejected(self):
        d = json.loads(json.dumps(REAL))
        d["entries"].append(dict(d["entries"][1]))
        self.assertTrue(validate(d))

    def test_wrong_chain_is_rejected(self):
        d = json.loads(json.dumps(REAL))
        d["chain_id"] = 1
        self.assertTrue(validate(d))

    def test_non_object_ledger_is_rejected(self):
        self.assertTrue(validate([]))


if __name__ == "__main__":
    unittest.main()


class SiteMatchesLedger(unittest.TestCase):
    """The published allocation must match what the ledger says was allocated.

    The site states a fixed allocation; the ledger records every movement since.
    These are different numbers by design, but the allocation itself must not
    drift from the record.
    """

    def test_published_allocation_matches_the_ledger(self):
        import re
        root = Path(__file__).resolve().parent.parent
        html = (root / "docs" / "index.html").read_text()

        allocated = {}
        for e in REAL["entries"]:
            if e["from"] == "mint" or e["date"] <= "2026-08-28":
                allocated[e["to"].lower()] = e["amount"]

        treasury = REAL["project_wallets"]["treasury"].lower()
        rewards = REAL["project_wallets"]["rewards"].lower()
        # treasury keeps the mint minus what it sent out on allocation day
        minted = int(allocated[treasury])
        to_rewards = int(allocated[rewards])
        to_pool = sum(int(e["amount"]) for e in REAL["entries"]
                      if e["from"].lower() == treasury
                      and e["to"].lower() not in (treasury, rewards)
                      and e["date"] <= "2026-08-28")
        treasury_alloc = minted - to_rewards - to_pool

        for label, value in (("Treasury", treasury_alloc),
                             ("Rewards", to_rewards),
                             ("Liquidity", to_pool)):
            self.assertIn(f"{label} · {value:,}", html,
                          f"site states a {label} allocation that the ledger does not")
