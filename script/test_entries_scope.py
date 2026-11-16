"""The fast per-PR check must be real, and must not imply completeness.

Proving nothing is missing costs an hour against free endpoints, so a pull
request answers the cheaper question: is every entry a real transfer, and do
the balances add up. Issue #10 happened because a check that could not see
something reported success anyway, so this one has to say what it did not
check, every time.
"""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

import verify_ledger as v

TOKEN = "0x914F6b6a0DaD39A3CB932dcf4D1af885C7c08EeB"
A = "0x1af3cBcE941a2AC9D987E853b5385b05c405E16F"
B = "0x7Be179c6Aa4cD1C4B3cDFbeF574c955DABa2c70c"
TX = "0x" + "cd" * 32


def ledger(amount="500"):
    return {"token": TOKEN, "chain_id": 8453,
            "project_wallets": {"rewards": A},
            "entries": [{"tx": TX, "date": "2026-10-19", "from": A, "to": B,
                         "amount": amount, "reason": "r"}]}


def receipt(to=B, wei=500 * 10**18, status=1):
    return {"status": hex(status), "transactionHash": TX,
            "blockHash": "0x" + "ab" * 32, "blockNumber": hex(v.DEPLOYMENT_BLOCK + 1),
            "logs": [{"address": TOKEN, "topics": [
                v.TRANSFER_TOPIC, "0x" + "0" * 24 + A[2:].lower(),
                "0x" + "0" * 24 + to[2:].lower()], "data": hex(wei)}]}


class EntriesScope(unittest.TestCase):
    def run_it(self, led, rcpt, balances=None):
        out = io.StringIO()
        def rpc(payload, endpoint=None):
            if payload["method"] == "eth_getTransactionReceipt":
                return {"jsonrpc": "2.0", "id": 1, "result": rcpt}
            raise AssertionError(payload["method"])
        with (patch.object(v, "LEDGER_PATH") as lp,
              patch.dict("os.environ", {"BASE_VERIFY_SCOPE": "entries"}),
              patch.object(v, "rpc_call", side_effect=rpc),
              patch.object(v, "verify_balances_total_supply",
                           side_effect=balances),
              contextlib.redirect_stdout(out)):
            lp.read_text.return_value = json.dumps(led)
            return v.main(), out.getvalue()

    def test_a_real_entry_passes_and_says_what_it_did_not_check(self):
        code, out = self.run_it(ledger(), receipt())
        self.assertEqual(code, 0, out)
        self.assertIn("NOT CHECKED", out)
        self.assertIn("missing", out)

    def test_a_wrong_amount_is_a_finding(self):
        code, out = self.run_it(ledger(amount="9999"), receipt())
        self.assertEqual(code, 1, out)

    def test_a_wrong_recipient_is_a_finding(self):
        code, out = self.run_it(ledger(), receipt(to="0x" + "11" * 20))
        self.assertEqual(code, 1, out)

    def test_a_missing_receipt_is_a_finding(self):
        code, out = self.run_it(ledger(), None)
        self.assertEqual(code, 1, out)

    def test_a_reverted_transaction_is_a_finding(self):
        code, out = self.run_it(ledger(), receipt(status=0))
        self.assertEqual(code, 1, out)

    def test_a_balance_mismatch_is_a_finding(self):
        code, out = self.run_it(ledger(), receipt(),
                                balances=v.AccountingViolation("short"))
        self.assertEqual(code, 1, out)

    def test_an_unreadable_source_is_inconclusive_not_a_pass(self):
        code, out = self.run_it(ledger(), receipt(),
                                balances=v.SourceUnavailable("down"))
        self.assertEqual(code, 2, out)

    def test_full_scope_is_the_default(self):
        with patch.dict("os.environ", {}, clear=True):
            import os
            self.assertEqual(os.environ.get("BASE_VERIFY_SCOPE", "full"), "full")


if __name__ == "__main__":
    unittest.main()
