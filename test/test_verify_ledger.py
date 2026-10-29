"""Integration tests for the verifier's source selection and verdicts.

The chain is the source of truth; indexers are a shortcut. These tests pin
that an indexer is used when it answers, that the chain carries the run when
no indexer does, and that a source failure is never reported as an accounting
finding.
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
OUTSIDE = "0x7Be179c6Aa4cD1C4B3cDFbeF574c955DABa2c70c"
TX = "0x" + "11" * 32


def ledger(amount="500"):
    return {
        "token": TOKEN,
        "chain_id": 8453,
        "project_wallets": {"treasury": TREASURY},
        "entries": [{"tx": TX, "date": "2026-10-28", "from": TREASURY,
                     "to": OUTSIDE, "amount": amount, "reason": "test"}],
    }


def transfer(amount_wei=str(500 * 10**18)):
    return {"from": {"hash": TREASURY}, "to": {"hash": OUTSIDE},
            "transaction_hash": TX, "total": {"value": amount_wei}}


class SourceSelection(unittest.TestCase):
    def run_main(self, *, pages=None, rpc=None, led=None):
        with (
            patch.object(verifier.time, "sleep"),
            patch.object(verifier, "_get_page", side_effect=pages) as gp,
            patch.object(verifier, "rpc_call", side_effect=rpc) as rc,
            patch.object(Path, "read_text", return_value=json.dumps(led or ledger())),
        ):
            try:
                code = verifier.main()
            except SystemExit as e:
                code = e.code
        return code, gp, rc

    def test_indexer_answering_means_no_chain_scan(self):
        page = {"items": [transfer()], "next_page_params": None}
        code, gp, rc = self.run_main(pages=[page], rpc=[])
        self.assertEqual(code, 0)
        self.assertEqual(rc.call_count, 0, "chain must not be scanned when an indexer answers")

    def test_chain_carries_the_run_when_no_indexer_answers(self):
        log = {"topics": [verifier.TRANSFER_TOPIC,
                          "0x" + "0" * 24 + TREASURY[2:].lower(),
                          "0x" + "0" * 24 + OUTSIDE[2:].lower()],
               "data": "0x" + f"{500 * 10**18:064x}", "transactionHash": TX}
        rpc = [{"jsonrpc": "2.0", "id": 1, "result": hex(verifier.DEPLOYMENT_BLOCK)},
               {"jsonrpc": "2.0", "id": verifier.DEPLOYMENT_BLOCK, "result": [log]}]
        code, _, rc = self.run_main(
            pages=[verifier.SourceUnavailable("indexer down")], rpc=rpc)
        self.assertEqual(code, 0)
        self.assertGreater(rc.call_count, 0, "chain must be scanned when no indexer answers")

    def test_every_source_failing_is_exit_2_not_a_violation(self):
        code, _, _ = self.run_main(
            pages=[verifier.SourceUnavailable("indexer down")],
            rpc=[verifier.SourceUnavailable("rpc down")])
        self.assertEqual(code, 2, "an outage must never be an accounting verdict")

    def test_unaccounted_movement_fails_the_build(self):
        stray = transfer()
        stray["transaction_hash"] = "0x" + "22" * 32
        page = {"items": [transfer(), stray], "next_page_params": None}
        code, _, _ = self.run_main(pages=[page], rpc=[])
        self.assertEqual(code, 1)

    def test_one_base_unit_discrepancy_is_rejected(self):
        page = {"items": [transfer(str(500 * 10**18 + 1))], "next_page_params": None}
        code, _, _ = self.run_main(pages=[page], rpc=[])
        self.assertEqual(code, 1, "integer wei comparison must not round")


if __name__ == "__main__":
    unittest.main()
