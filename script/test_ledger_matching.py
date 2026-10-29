"""The comparison at the centre of the verifier.

A movement is (tx, from, to, amount) and the comparison is between two
multisets, not two sets. Both of those were wrong until 2026-10-28: `from` was
not part of the key, so an entry could name the wrong source wallet and match;
and matching was set-membership, so one entry discharged any number of
identical movements in the same transaction.
"""
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_ledger as verifier  # noqa: E402

TOKEN = "0x914F6b6a0DaD39A3CB932dcf4D1af885C7c08EeB"
TREASURY = "0x497d34b1d0790f374B32467093d303533399c819"
REWARDS = "0x1af3cBcE941a2AC9D987E853b5385b05c405E16F"
OUTSIDE = "0x7Be179c6Aa4cD1C4B3cDFbeF574c955DABa2c70c"
TX = "0x" + "11" * 32
WEI = str(500 * 10**18)


def ledger(entries=None):
    return {"token": TOKEN, "chain_id": 8453,
            "project_wallets": {"treasury": TREASURY, "rewards": REWARDS},
            "entries": entries if entries is not None else
            [{"tx": TX, "date": "2026-10-28", "from": TREASURY, "to": OUTSIDE,
              "amount": "500", "reason": "a payment"}]}


def transfer(frm=TREASURY, to=OUTSIDE, tx=TX, wei=WEI):
    return {"from": {"hash": frm}, "to": {"hash": to},
            "transaction_hash": tx, "total": {"value": wei}}


def run(transfers, led=None):
    with (patch.object(verifier, "fetch_transfers", return_value=transfers),
          patch.object(Path, "read_text", return_value=json.dumps(led or ledger()))):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = verifier.main()
    return code, buf.getvalue()


class Matching(unittest.TestCase):
    def test_an_honest_movement_passes(self):
        self.assertEqual(run([transfer()])[0], 0)

    def test_the_same_movement_twice_needs_two_entries(self):
        code, out = run([transfer(), transfer()])
        self.assertEqual(code, 1, "one entry must not discharge two movements")
        self.assertIn("UNACCOUNTED", out)

    def test_two_movements_with_two_entries_passes(self):
        led = ledger()
        led["entries"].append(dict(led["entries"][0]))
        self.assertEqual(run([transfer(), transfer()], led)[0], 0)

    def test_entry_naming_the_wrong_source_wallet_fails(self):
        code, out = run([transfer(frm=REWARDS)])
        self.assertEqual(code, 1, "`from` must be part of the movement's identity")

    def test_entry_with_no_onchain_counterpart_fails(self):
        code, out = run([])
        self.assertEqual(code, 1)
        self.assertIn("not found on-chain", out)

    def test_claimed_twice_observed_once_reports_the_shortfall(self):
        led = ledger()
        led["entries"].append(dict(led["entries"][0]))
        code, out = run([transfer()], led)
        self.assertEqual(code, 1)
        self.assertIn("x1", out)

    def test_third_party_transfers_are_ignored(self):
        self.assertEqual(run([transfer(), transfer(frm=OUTSIDE, to=OUTSIDE,
                                                  tx="0x" + "22" * 32)])[0], 0)

    def test_the_mint_sentinel_resolves_to_the_zero_address(self):
        led = ledger([{"tx": TX, "date": "2026-02-10", "from": "mint",
                       "to": TREASURY, "amount": "500", "reason": "genesis"}])
        self.assertEqual(run([transfer(frm=verifier.ZERO_ADDRESS, to=TREASURY)], led)[0], 0)


if __name__ == "__main__":
    unittest.main()
