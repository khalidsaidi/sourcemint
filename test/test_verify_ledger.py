"""Where the transfer history comes from, and what happens when it doesn't.

The chain is the source of truth: history is derived from it with no API key
and nobody's permission. Indexers answer the same question in one request
instead of roughly two hundred, so they are a shortcut tried first — never a
dependency. These tests pin that arrangement and the verdicts around it.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "script"))
import verify_ledger as verifier  # noqa: E402

TOKEN = "0x914F6b6a0DaD39A3CB932dcf4D1af885C7c08EeB"
TREASURY = "0x497d34b1d0790f374B32467093d303533399c819"
WALLETS = {TREASURY.lower()}


def rpc_responses(nonce_by_block, logs_by_block, head):
    """Answer the three methods the derivation uses."""
    def rpc(payload, endpoint=None):
        method = payload["method"]
        if method == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(head)}
        if method == "eth_getTransactionCount":
            block = int(payload["params"][1], 16)
            n = max((v for b, v in sorted(nonce_by_block.items()) if b <= block),
                    default=0)
            return {"jsonrpc": "2.0", "id": 1, "result": hex(n)}
        if method == "eth_getLogs":
            block = int(payload["params"][0]["fromBlock"], 16)
            return {"jsonrpc": "2.0", "id": 1,
                    "result": logs_by_block.get(block, [])}
        raise AssertionError(f"unexpected method {method}")
    return rpc


def log(frm, to, wei):
    return {"topics": [verifier.TRANSFER_TOPIC,
                       "0x" + "0" * 24 + frm[2:].lower(),
                       "0x" + "0" * 24 + to[2:].lower()],
            "data": "0x" + f"{wei:064x}",
            "transactionHash": "0x" + "ab" * 32}


class OneSource(unittest.TestCase):
    """There is one source and it is the chain.

    An indexer would be faster, but it is somebody's service to withdraw, and
    the approvals that guard completeness are only collected while reading the
    chain. A shortcut that skips a check when it works is worse than none.
    """

    def test_history_always_comes_from_the_chain(self):
        with patch.object(verifier, "derive_transfers",
                          return_value=(["derived"], {"0xspender"})) as derive:
            self.assertEqual(verifier.fetch_transfers(TOKEN, WALLETS), ["derived"])
        derive.assert_called_once()

    def test_approvals_found_while_reading_are_kept_for_the_allowance_check(self):
        verifier.LIVE_SPENDERS.clear()
        with patch.object(verifier, "derive_transfers",
                          return_value=([], {"0xabc"})):
            verifier.fetch_transfers(TOKEN, WALLETS)
        self.assertIn("0xabc", verifier.LIVE_SPENDERS)
        verifier.LIVE_SPENDERS.clear()

    def test_a_failure_raises_rather_than_returning_nothing(self):
        with patch.object(verifier, "derive_transfers",
                          side_effect=verifier.SourceUnavailable("rpc down")):
            with self.assertRaises(verifier.SourceUnavailable):
                verifier.fetch_transfers(TOKEN, WALLETS)


class Derivation(unittest.TestCase):
    def derive(self, nonces, logs, head=None):
        head = head or verifier.DEPLOYMENT_BLOCK + 1_000_000
        with patch.object(verifier, "rpc_call",
                          side_effect=rpc_responses(nonces, logs, head)):
            return verifier.derive_transfers(TOKEN, WALLETS)[0]

    def test_finds_a_movement_in_a_block_the_wallet_transacted_in(self):
        out = self.derive({verifier.DEPLOYMENT_BLOCK + 500_000: 1},
                          {verifier.DEPLOYMENT_BLOCK + 500_000: [log(TREASURY, TOKEN, 5 * 10**18)]})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["from"]["hash"].lower(), TREASURY.lower())

    def test_an_idle_wallet_yields_only_the_deployment_block(self):
        self.assertEqual(self.derive({}, {}), [])

    def test_logs_removed_by_a_reorg_are_discarded(self):
        entry = log(TREASURY, TOKEN, 5 * 10**18)
        entry["removed"] = True
        self.assertEqual(self.derive({verifier.DEPLOYMENT_BLOCK + 500_000: 1}, {500_000: [entry]}), [])

    def test_a_head_before_deployment_is_an_outage_not_a_verdict(self):
        with patch.object(verifier, "rpc_call",
                          side_effect=rpc_responses({}, {}, verifier.DEPLOYMENT_BLOCK - 1)):
            with self.assertRaises(verifier.SourceUnavailable):
                verifier.derive_transfers(TOKEN, WALLETS)


if __name__ == "__main__":
    unittest.main()
