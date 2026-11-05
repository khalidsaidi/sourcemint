"""An allowance outage must preserve an already-observed accounting finding."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

import verify_ledger as verifier
from test_allowances import PERMIT2, ledger, transfers


class AllowanceOutage(unittest.TestCase):
    def run_verifier(self, observed=None, balance_error=None):
        output = io.StringIO()
        with (
            patch.object(verifier, "LIVE_SPENDERS", [PERMIT2]),
            patch.object(verifier, "LEDGER_PATH") as ledger_path,
            patch.object(verifier, "fetch_transfers", return_value=(
                transfers() if observed is None else observed)),
            patch.object(verifier, "verify_balances_total_supply",
                         side_effect=balance_error),
            patch.object(verifier, "rpc_call", side_effect=(
                verifier.SourceUnavailable("allowance source unavailable"))) as rpc,
            contextlib.redirect_stdout(output),
        ):
            ledger_path.read_text.return_value = json.dumps(ledger())
            code = verifier.main()
        self.assertEqual(rpc.call_count, 1)
        self.assertTrue(rpc.call_args.args[0]["params"][0]["data"].startswith(
            verifier.ALLOWANCE_SELECTOR))
        return code, output.getvalue()

    def test_observed_unaccounted_transfer_remains_a_violation(self):
        observed = transfers()
        observed.append(dict(observed[-1], transaction_hash="0x" + "22" * 32))
        code, output = self.run_verifier(observed=observed)
        self.assertEqual(code, 1)
        self.assertIn("UNACCOUNTED on-chain movements", output)
        self.assertIn("allowance", output)
        self.assertNotIn("COULD NOT VERIFY", output)

    def test_observed_balance_mismatch_remains_a_violation(self):
        code, output = self.run_verifier(
            balance_error=verifier.AccountingViolation("balance mismatch"))
        self.assertEqual(code, 1)
        self.assertIn("BALANCE UNEXPLAINED", output)
        self.assertNotIn("COULD NOT VERIFY", output)

    def test_no_observed_violation_remains_inconclusive(self):
        code, output = self.run_verifier()
        self.assertEqual(code, 2)
        self.assertIn("COULD NOT VERIFY", output)

    def test_missing_sampled_entry_alone_is_not_an_observed_violation(self):
        code, output = self.run_verifier(observed=transfers()[:1])
        self.assertEqual(code, 2)
        self.assertIn("LEDGER entries not found on-chain", output)
        self.assertIn("COULD NOT VERIFY", output)


if __name__ == "__main__":
    unittest.main()
