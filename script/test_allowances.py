"""Complete Transfer history covers delegated transfers independently of allowance.

These state fixtures retain nonzero and revoked allowances to ensure that
future spending authority does not become a false historical violation.
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
OUTSIDE = "0x7Be179c6Aa4cD1C4B3cDFbeF574c955DABa2c70c"
PERMIT2 = "0x000000000022D473030F116dDEE9F6B43aC78BA3"
MINT_TX, TX = "0x" + "99" * 32, "0x" + "11" * 32
UNLIMITED = 2**256 - 1


def ledger():
    return {"token": TOKEN, "chain_id": 8453,
            "project_wallets": {"treasury": TREASURY},
            "entries": [
                {"tx": MINT_TX, "date": "2026-02-10", "from": "mint",
                 "to": TREASURY, "amount": "1000", "reason": "genesis"},
                {"tx": TX, "date": "2026-10-29", "from": TREASURY,
                 "to": OUTSIDE, "amount": "500", "reason": "a reward"}]}


def transfers():
    return [{"from": {"hash": verifier.ZERO_ADDRESS}, "to": {"hash": TREASURY},
             "transaction_hash": MINT_TX, "total": {"value": str(1000 * 10**18)}},
            {"from": {"hash": TREASURY}, "to": {"hash": OUTSIDE},
             "transaction_hash": TX, "total": {"value": str(500 * 10**18)}}]


def run(allowance):
    led = ledger()
    state = verifier.calculate_expected_state(led)

    def rpc(payload, endpoint=None):
        if payload["method"] == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": "0x1"}
        if payload["method"] == "eth_getBlockByNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": {
                "number": payload["params"][0], "hash": "0x" + "ab" * 32}}
        data = payload["params"][0]["data"]
        if data.startswith(verifier.ALLOWANCE_SELECTOR):
            raise AssertionError("complete history must not query current allowance")
        elif data.startswith("0x18160ddd"):
            value = state[1]
        else:
            value = state[0].get("0x" + data[-40:], 0)
        return {"jsonrpc": "2.0", "id": 1, "result": "0x%064x" % value}

    with (patch.object(verifier, "fetch_transfers", return_value=verifier.TransferHistory(
              transfers(), verifier.DEPLOYMENT_BLOCK, "0x" + "ab" * 32,
              verifier.DEPLOYMENT_BLOCK, complete=True, canonical=True)),
          patch.object(verifier, "rpc_call", side_effect=rpc),
          patch.object(Path, "read_text", return_value=json.dumps(led))):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = verifier.main()
    return code, buf.getvalue()


class Allowances(unittest.TestCase):
    def test_a_live_allowance_does_not_invalidate_complete_history(self):
        code, out = run(UNLIMITED)
        self.assertEqual(code, 0)
        self.assertNotIn("OUTSTANDING ALLOWANCES", out)

    def test_an_unlimited_allowance_does_not_require_an_extra_history_gate(self):
        self.assertIn("RESULT: OK", run(UNLIMITED)[1])

    def test_a_small_allowance_is_not_a_missing_transfer(self):
        self.assertEqual(run(5 * 10**18)[0], 0)

    def test_a_revoked_allowance_does_not_block_the_verdict(self):
        code, out = run(0)
        self.assertEqual(code, 0)
        self.assertNotIn("OUTSTANDING", out)
        self.assertIn("RESULT: OK", out)


if __name__ == "__main__":
    unittest.main()
