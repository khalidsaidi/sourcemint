import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import call, patch

import script.verify_ledger as verifier


TOKEN = "0x" + "11" * 20
RECEIVER = "0x" + "22" * 20
IDLE_WALLET = "0x" + "33" * 20
TX_HASH = "0x" + "aa" * 32
SECOND_TX_HASH = "0x" + "bb" * 32
BLOCK = hex(10100)
AMOUNT_WEI = 10**18
BALANCE_OF_SELECTOR = "0x70a08231"
TOTAL_SUPPLY_SELECTOR = "0x18160ddd"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

TRANSFER = {
    "from": {"hash": "0x" + "00" * 20},
    "to": {"hash": RECEIVER},
    "transaction_hash": TX_HASH,
    "total": {"value": str(AMOUNT_WEI)},
}


def rpc_response(result):
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": result,
    }


def make_mock_ledger(tx_hashes=(TX_HASH,)):
    return {
        "token": TOKEN,
        "project_wallets": {"treasury": RECEIVER},
        "entries": [{
            "tx": tx_hash,
            "from": "mint",
            "to": RECEIVER,
            "amount": "1",
            "reason": "Offline mint fixture",
        } for tx_hash in tx_hashes],
    }


def make_receipt_response(tx_hash):
    amount = "0x" + format(AMOUNT_WEI, "064x")
    return rpc_response({
        "status": "0x1",
        "transactionHash": tx_hash,
        "logs": [{
            "address": TOKEN,
            "topics": [
                TRANSFER_TOPIC,
                "0x" + "00" * 32,
                "0x" + RECEIVER[2:].zfill(64),
            ],
            "data": amount,
            "transactionHash": tx_hash,
        }],
    })


def make_rpc_responses(tx_hashes=(TX_HASH,)):
    amount = "0x" + format(len(tx_hashes) * AMOUNT_WEI, "064x")
    return [make_receipt_response(tx_hash) for tx_hash in tx_hashes] + [
        rpc_response(BLOCK),
        rpc_response(amount),
        rpc_response(amount),
    ]


class TestLedgerFallback(unittest.TestCase):
    def run_main(self, pages, responses, *, ledger=None):
        output = io.StringIO()
        with (
            patch.object(verifier, "LEDGER_PATH") as ledger_path,
            patch.object(verifier, "_get_page", side_effect=pages) as get_page,
            patch.object(verifier, "rpc_call", side_effect=responses) as rpc,
            redirect_stdout(output),
        ):
            ledger_path.read_text.return_value = json.dumps(
                make_mock_ledger() if ledger is None else ledger,
            )
            exit_code = verifier.main()

        return exit_code, output.getvalue(), get_page, rpc

    def assert_receipt_balance_and_supply_requests(
        self, rpc, *, tx_hashes=(TX_HASH,), wallets=(RECEIVER,),
    ):
        expected = [
            call({
                "jsonrpc": "2.0", "id": 1,
                "method": "eth_getTransactionReceipt", "params": [tx_hash],
            }) for tx_hash in tx_hashes
        ]
        expected.append(call({
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_blockNumber", "params": [],
        }))
        expected.extend(
            call({
                "jsonrpc": "2.0", "id": 1, "method": "eth_call",
                "params": [{
                    "to": TOKEN,
                    "data": BALANCE_OF_SELECTOR + wallet[2:].zfill(64),
                }, BLOCK],
            }) for wallet in wallets
        )
        expected.append(call({
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": TOKEN, "data": TOTAL_SUPPLY_SELECTOR}, BLOCK],
        }))
        self.assertEqual(rpc.call_args_list, expected)

    def test_second_receipt_unavailable_stops_before_balance_verification(self):
        tx_hashes = (TX_HASH, SECOND_TX_HASH)
        ledger = make_mock_ledger(tx_hashes)
        responses = [make_receipt_response(TX_HASH), rpc_response(None)]
        with patch.object(
            verifier, "verify_balances_total_supply",
            wraps=verifier.verify_balances_total_supply,
        ) as balances:
            exit_code, output, _, rpc = self.run_main(
                verifier.SourceUnavailable("primary down"), responses, ledger=ledger,
            )

        self.assertEqual(rpc.call_args_list, [
            call({
                "jsonrpc": "2.0", "id": 1,
                "method": "eth_getTransactionReceipt", "params": [tx_hash],
            }) for tx_hash in tx_hashes
        ])
        balances.assert_not_called()
        self.assertEqual(exit_code, 2)
        self.assertIn("COULD NOT VERIFY: Transaction receipt unavailable", output)
        self.assertNotIn("RESULT: OK", output)

    def test_all_receipts_are_checked_before_balances_and_supply(self):
        tx_hashes = (TX_HASH, SECOND_TX_HASH)
        ledger = make_mock_ledger(tx_hashes)
        with patch.object(
            verifier, "verify_balances_total_supply",
            wraps=verifier.verify_balances_total_supply,
        ) as balances:
            exit_code, output, _, rpc = self.run_main(
                verifier.SourceUnavailable("primary down"),
                make_rpc_responses(tx_hashes), ledger=ledger,
            )

        self.assert_receipt_balance_and_supply_requests(rpc, tx_hashes=tx_hashes)
        balances.assert_called_once_with(ledger, TOKEN, rpc)
        self.assertEqual(exit_code, 0)
        self.assertIn("RESULT: OK", output)
        self.assertNotIn("COULD NOT VERIFY", output)

    def test_missing_or_invalid_receipt_status_returns_exit_2(self):
        for status in ("missing", None, "hello", "0x2", True):
            with self.subTest(status=status):
                responses = make_rpc_responses()
                if status == "missing":
                    del responses[0]["result"]["status"]
                else:
                    responses[0]["result"]["status"] = status

                exit_code, output, _, rpc = self.run_main(
                    verifier.SourceUnavailable("primary down"), responses,
                )

                self.assertEqual(exit_code, 2)
                self.assertIn("COULD NOT VERIFY", output)
                self.assertNotIn("RESULT: OK", output)
                self.assertEqual(rpc.call_count, 1)

    def test_receipt_status_zero_returns_exit_1(self):
        responses = make_rpc_responses()
        responses[0]["result"]["status"] = "0x0"
        exit_code, output, _, rpc = self.run_main(
            verifier.SourceUnavailable("primary down"), responses,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Transaction failed", output)
        self.assertNotIn("COULD NOT VERIFY", output)
        self.assertNotIn("RESULT: OK", output)
        self.assertEqual(rpc.call_count, 1)

    def test_short_or_empty_balance_and_supply_results_return_exit_2(self):
        for index, method in ((2, "balanceOf"), (3, "totalSupply")):
            for result in ("0x1", "0x"):
                with self.subTest(method=method, result=result):
                    responses = make_rpc_responses()
                    responses[index]["result"] = result
                    exit_code, output, _, rpc = self.run_main(
                        verifier.SourceUnavailable("primary down"), responses,
                    )

                    self.assertEqual(exit_code, 2)
                    self.assertIn("COULD NOT VERIFY", output)
                    self.assertIn(method, output)
                    self.assertNotIn("Balances not matched", output)
                    self.assertNotIn("Total supply mismatch", output)
                    self.assertNotIn("RESULT: OK", output)
                    self.assertEqual(rpc.call_count, index + 1)

    def test_invalid_balance_and_supply_response_metadata_returns_exit_2(self):
        for index, method in ((2, "balanceOf"), (3, "totalSupply")):
            valid_response = make_rpc_responses()[index]
            invalid_responses = {
                "wrong_jsonrpc": {**valid_response, "jsonrpc": "1.0"},
                "wrong_id": {**valid_response, "id": 2},
                "missing_id": {key: value for key, value in valid_response.items() if key != "id"},
                "boolean_id": {**valid_response, "id": True},
            }
            for name, response in invalid_responses.items():
                with self.subTest(method=method, invalid_field=name):
                    responses = make_rpc_responses()
                    responses[index] = response
                    exit_code, output, _, rpc = self.run_main(
                        verifier.SourceUnavailable("primary down"), responses,
                    )

                    self.assertEqual(exit_code, 2)
                    self.assertIn("COULD NOT VERIFY", output)
                    self.assertIn(method, output)
                    self.assertNotIn("RESULT: OK", output)
                    self.assertEqual(rpc.call_count, index + 1)

    def test_project_wallet_without_entries_has_zero_balance(self):
        ledger = make_mock_ledger()
        ledger["project_wallets"]["rewards"] = IDLE_WALLET
        responses = make_rpc_responses()
        responses.insert(3, rpc_response("0x" + "00" * 32))
        exit_code, output, _, rpc = self.run_main(
            verifier.SourceUnavailable("primary down"), responses, ledger=ledger,
        )

        self.assert_receipt_balance_and_supply_requests(
            rpc, wallets=(RECEIVER, IDLE_WALLET),
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("RESULT: OK", output)
        self.assertNotIn("COULD NOT VERIFY", output)

    def test_balance_or_supply_rpc_failure_returns_exit_2_without_success(self):
        endpoint = "https://rpc.invalid"
        real_rpc_call = verifier.rpc_call
        failures = {
            "timeout": TimeoutError("timed out"),
            "connection": verifier.URLError("Connection refused"),
            "http": verifier.HTTPError(endpoint, 429, "Too Many Requests", {}, None),
            "json_rpc": {
                "jsonrpc": "2.0", "id": 1,
                "error": {"code": -32603, "message": "Internal error"},
            },
        }
        for index, method in ((2, "balanceOf"), (3, "totalSupply")):
            for name, failure in failures.items():
                with self.subTest(method=method, failure=name):
                    responses = make_rpc_responses()
                    responses[index] = failure
                    http_responses = [
                        response if isinstance(response, Exception)
                        else io.BytesIO(json.dumps(response).encode("utf-8"))
                        for response in responses
                    ]
                    with (
                        patch.dict(os.environ, {"BASE_RPC_URL": endpoint}),
                        patch.object(verifier, "urlopen", side_effect=http_responses) as transport,
                    ):
                        exit_code, output, _, rpc = self.run_main(
                            verifier.SourceUnavailable("primary down"), real_rpc_call,
                        )

                    self.assertEqual(exit_code, 2)
                    self.assertIn("COULD NOT VERIFY", output)
                    self.assertNotIn("RESULT: OK", output)
                    self.assertEqual(rpc.call_count, index + 1)
                    self.assertEqual(transport.call_count, index + 1)

    def test_primary_success_skips_rpc(self):
        exit_code, output, get_page, rpc = self.run_main(
            [{"items": [TRANSFER], "next_page_params": None}], [],
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("RESULT: OK", output)
        self.assertIn("ledger entries matched: 1/1", output)
        get_page.assert_called_once_with(verifier.SOURCES[0].format(token=TOKEN), {})
        rpc.assert_not_called()

    def test_fractional_amounts_match_primary_history_exactly(self):
        cases = {
            "0.5": 500_000_000_000_000_000,
            "1.2300": 1_230_000_000_000_000_000,
            "0.000000000000000001": 1,
            "1.000000000000000001": 1_000_000_000_000_000_001,
            "1000000.123456789012345678": 1_000_000_123_456_789_012_345_678,
        }
        for amount, amount_wei in cases.items():
            with self.subTest(amount=amount):
                ledger = make_mock_ledger()
                ledger["entries"][0]["amount"] = amount
                transfer = {**TRANSFER, "total": {"value": str(amount_wei)}}

                exit_code, output, _, rpc = self.run_main(
                    [{"items": [transfer], "next_page_params": None}], [], ledger=ledger,
                )

                self.assertEqual(exit_code, 0)
                self.assertIn("ledger entries matched: 1/1", output)
                rpc.assert_not_called()

    def test_fractional_amounts_match_receipts_balances_and_supply_exactly(self):
        for amount, amount_wei in (
            ("0.5", 500_000_000_000_000_000),
            ("0.000000000000000001", 1),
            ("1.000000000000000001", 1_000_000_000_000_000_001),
            ("1000000.123456789012345678", 1_000_000_123_456_789_012_345_678),
        ):
            with self.subTest(amount=amount):
                ledger = make_mock_ledger()
                ledger["entries"][0]["amount"] = amount
                encoded = "0x" + format(amount_wei, "064x")
                responses = make_rpc_responses()
                responses[0]["result"]["logs"][0]["data"] = encoded
                responses[2]["result"] = encoded
                responses[3]["result"] = encoded

                exit_code, output, _, rpc = self.run_main(
                    verifier.SourceUnavailable("primary down"), responses, ledger=ledger,
                )

                self.assertEqual(exit_code, 0)
                self.assertIn("RESULT: OK", output)
                self.assert_receipt_balance_and_supply_requests(rpc)

    def test_fractional_primary_mismatch_of_one_base_unit_is_rejected(self):
        ledger = make_mock_ledger()
        ledger["entries"][0]["amount"] = "1.000000000000000001"

        exit_code, output, _, rpc = self.run_main(
            [{"items": [TRANSFER], "next_page_params": None}], [], ledger=ledger,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("UNACCOUNTED", output)
        self.assertIn("LEDGER entries not found on-chain", output)
        rpc.assert_not_called()

    def test_fractional_fallback_mismatch_of_one_base_unit_is_rejected(self):
        for index in (0, 2, 3):
            with self.subTest(response_index=index):
                ledger = make_mock_ledger()
                ledger["entries"][0]["amount"] = "1.000000000000000001"
                responses = make_rpc_responses()
                encoded = "0x" + format(AMOUNT_WEI + 1, "064x")
                responses[0]["result"]["logs"][0]["data"] = encoded
                responses[2]["result"] = encoded
                responses[3]["result"] = encoded
                if index == 0:
                    responses[0]["result"]["logs"][0]["data"] = "0x" + format(AMOUNT_WEI, "064x")
                else:
                    responses[index]["result"] = "0x" + format(AMOUNT_WEI, "064x")

                exit_code, output, _, _ = self.run_main(
                    verifier.SourceUnavailable("primary down"), responses, ledger=ledger,
                )

                self.assertEqual(exit_code, 1)
                self.assertNotIn("RESULT: OK", output)
                self.assertNotIn("COULD NOT VERIFY", output)

    def test_unaccounted_fraction_is_displayed_without_rounding(self):
        transfer = {**TRANSFER, "total": {"value": str(AMOUNT_WEI + 1)}}
        exit_code, output, _, _ = self.run_main(
            [{"items": [transfer], "next_page_params": None}], [],
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("1.000000000000000001 SRCMNT", output)

    def test_invalid_amount_returns_exit_1_before_network_requests(self):
        for amount in ("0.0000000000000000001", "-0.5", "NaN", "invalid", 0.5):
            with self.subTest(amount=amount):
                ledger = make_mock_ledger()
                ledger["entries"][0]["amount"] = amount
                exit_code, output, get_page, rpc = self.run_main([], [], ledger=ledger)

                self.assertEqual(exit_code, 1)
                self.assertIn("Invalid ledger", output)
                get_page.assert_not_called()
                rpc.assert_not_called()

    def test_fetch_transfers_failure_does_not_call_rpc(self):
        with (
            patch.object(verifier, "_get_page", side_effect=verifier.SourceUnavailable("primary down")),
            patch.object(verifier, "rpc_call") as rpc,
            patch.object(verifier, "verify_rpc_fallback") as fallback,
        ):
            with self.assertRaisesRegex(verifier.SourceUnavailable, "primary down"):
                verifier.fetch_transfers(TOKEN)

        rpc.assert_not_called()
        fallback.assert_not_called()

    def test_primary_failure_uses_receipt_fallback(self):
        exit_code, output, _, rpc = self.run_main(
            verifier.SourceUnavailable("primary down"), make_rpc_responses(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("primary unavailable", output)
        self.assertNotIn("COULD NOT VERIFY", output)
        self.assert_receipt_balance_and_supply_requests(rpc)
        self.assertIn("RESULT: OK", output)
        self.assertIn(
            "degraded fallback; full transfer history not checked",
            output,
        )

    def test_both_sources_fail_returns_exit_2(self):
        exit_code, output, _, rpc = self.run_main(
            verifier.SourceUnavailable("primary down"),
            verifier.SourceUnavailable("RPC HTTP 429"),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("COULD NOT VERIFY: RPC HTTP 429", output)
        self.assertNotIn("RESULT:", output)
        self.assertNotIn("UNACCOUNTED", output)
        rpc.assert_called_once_with({
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_getTransactionReceipt", "params": [TX_HASH],
        })

    def test_receipt_unavailable_returns_exit_2(self):
        exit_code, output, _, rpc = self.run_main(
            verifier.SourceUnavailable("primary down"), [rpc_response(None)],
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("COULD NOT VERIFY: Transaction receipt unavailable", output)
        self.assertNotIn("RESULT:", output)
        self.assertEqual(rpc.call_count, 1)

    def test_empty_receipt_logs_returns_exit_1(self):
        responses = make_rpc_responses()
        responses[0]["result"]["logs"] = []
        exit_code, output, _, rpc = self.run_main(
            verifier.SourceUnavailable("primary down"), responses,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn(TX_HASH, output)
        self.assertNotIn("COULD NOT VERIFY", output)
        self.assertEqual(rpc.call_count, 1)

    def test_balance_mismatch_returns_exit_1(self):
        responses = make_rpc_responses()
        responses[2]["result"] = "0x" + format(AMOUNT_WEI + 1, "064x")
        exit_code, output, _, rpc = self.run_main(
            verifier.SourceUnavailable("primary down"), responses,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Balances not matched", output)
        self.assertNotIn("COULD NOT VERIFY", output)
        self.assertEqual(rpc.call_count, 3)

    def test_total_supply_mismatch_returns_exit_1(self):
        responses = make_rpc_responses()
        responses[3]["result"] = "0x" + format(AMOUNT_WEI + 1, "064x")
        exit_code, output, _, rpc = self.run_main(
            verifier.SourceUnavailable("primary down"), responses,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Total supply mismatch", output)
        self.assertNotIn("COULD NOT VERIFY", output)
        self.assert_receipt_balance_and_supply_requests(rpc)

    def test_empty_primary_result_is_valid(self):
        with (
            patch.object(verifier, "_get_page", return_value={
                "items": [], "next_page_params": None,
            }),
            patch.object(verifier, "rpc_call") as rpc,
        ):
            self.assertEqual(verifier.fetch_transfers(TOKEN), [])

        rpc.assert_not_called()

    def test_primary_partial_page_is_discarded_before_fallback(self):
        exit_code, output, get_page, rpc = self.run_main(
            [
                {"items": [{"must_not_reach_accounting": True}], "next_page_params": {"page": 2}},
                verifier.SourceUnavailable("second page failed"),
            ],
            make_rpc_responses(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("second page failed", output)
        self.assertNotIn("COULD NOT VERIFY", output)
        url = verifier.SOURCES[0].format(token=TOKEN)
        self.assertEqual(get_page.call_args_list, [call(url, {}), call(url, {"page": 2})])
        self.assert_receipt_balance_and_supply_requests(rpc)

    def test_primary_retry_uses_three_attempts_and_six_seconds_backoff(self):
        with (
            patch.object(
                verifier.urllib.request,
                "urlopen",
                side_effect=verifier.URLError("simulated outage"),
            ) as request,
            patch.object(verifier.time, "sleep") as sleep,
        ):
            with self.assertRaises(verifier.SourceUnavailable):
                verifier._get_page(
                    "https://example.invalid/transfers",
                    {},
                )

        delays = [
            call.args[0]
            for call in sleep.call_args_list
        ]

        self.assertEqual(request.call_count, 3)
        self.assertEqual(delays, [2, 4])
        self.assertEqual(sum(delays), 6)


if __name__ == "__main__":
    unittest.main()
