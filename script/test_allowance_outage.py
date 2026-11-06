"""Coverage and state outages must preserve confirmed accounting findings.

Supersedes the old allowance-read gate now that Transfer history is scanned.
"""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

import verify_ledger as verifier
from test_allowances import ledger, transfers


class AccountingOutages(unittest.TestCase):
    def run_verifier(self, observed=None, balance_error=None, complete=True):
        history = verifier.TransferHistory(
            transfers() if observed is None else observed,
            verifier.DEPLOYMENT_BLOCK, "0x" + "ab" * 32,
            verifier.DEPLOYMENT_BLOCK, complete=complete, canonical=True,
            error="later page unavailable" if not complete else "")
        output = io.StringIO()
        with (patch.object(verifier, "LEDGER_PATH") as ledger_path,
              patch.object(verifier, "fetch_transfers", return_value=history),
              patch.object(verifier, "verify_balances_total_supply", side_effect=balance_error),
              patch.object(verifier, "rpc_call", side_effect=lambda payload, endpoint=None: {
                  "jsonrpc": "2.0", "id": 1, "result": {
                      "number": payload["params"][0], "hash": "0x" + "ab" * 32}}),
              contextlib.redirect_stdout(output)):
            ledger_path.read_text.return_value = json.dumps(ledger())
            code = verifier.main()
        return code, output.getvalue()

    def test_observed_unaccounted_transfer_survives_state_outage(self):
        observed = transfers()
        observed.append(dict(observed[-1], transaction_hash="0x" + "22" * 32))
        code, output = self.run_verifier(observed,
            verifier.SourceUnavailable("state unavailable"))
        self.assertEqual(code, 1)
        self.assertIn("UNACCOUNTED", output)

    def test_observed_balance_mismatch_remains_a_violation(self):
        code, output = self.run_verifier(
            balance_error=verifier.AccountingViolation("balance mismatch"))
        self.assertEqual(code, 1)
        self.assertIn("BALANCE UNEXPLAINED", output)

    def test_no_observed_violation_with_state_outage_is_inconclusive(self):
        code, output = self.run_verifier(
            balance_error=verifier.SourceUnavailable("state unavailable"))
        self.assertEqual(code, 2)
        self.assertIn("COULD NOT VERIFY", output)

    def test_missing_entry_in_partial_history_is_not_a_finding(self):
        code, output = self.run_verifier(observed=transfers()[:1], complete=False)
        self.assertEqual(code, 2)
        self.assertIn("COULD NOT VERIFY", output)


if __name__ == "__main__":
    unittest.main()
