import json
import os
import unittest
from io import BytesIO
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from script.verify_ledger import (
    AccountingViolation,
    SourceUnavailable,
    calculate_expected_state,
    rpc_call,
    verify_balances_total_supply,
)



TREASURY = "0x" + "11" * 20
REWARDS = "0x" + "22" * 20
EXTERNAL = "0x" + "33" * 20
CONTRIBUTOR = "0x" + "44" * 20
ZERO_ADDRESS = "0x" + "00" * 20

BALANCE_OF_SELECTOR = "0x70a08231"
TOTAL_SUPPLY_SELECTOR = "0x18160ddd"
TOKEN = "0x914F6b6a0DaD39A3CB932dcf4D1af885C7c08EeB"
FAKE_RPC_URL = "https://rpc.invalid"
_DEFAULT_RESPONSE = object()

def make_mock_ledger():
    return {
        "project_wallets": {
            "treasury": TREASURY,
            "rewards": REWARDS,
        },
        "entries": [
            {
                "tx": "0x" + "aa" * 32,
                "from": "mint",
                "to": TREASURY,
                "amount": "100"
            },
            {
                "tx": "0x" + "bb" * 32,
                "from": TREASURY,
                "to": REWARDS,
                "amount": "30"
            },
            {
                "tx": "0x" + "cc" * 32,
                "from": TREASURY,
                "to": EXTERNAL,
                "amount": "10"
            },
            {
                "tx": "0x" + "dd" * 32,
                "from": REWARDS,
                "to": CONTRIBUTOR,
                "amount": "5"
            }
        ]
    }

def make_fake_rpc(
    supply_wei=0,
    balances_wei=0,
    *,
    block_response=_DEFAULT_RESPONSE,
    balance_response=_DEFAULT_RESPONSE,
    supply_response=_DEFAULT_RESPONSE,
):

    block = hex(10100)
    def respond(payload, result, override):
        if override is _DEFAULT_RESPONSE:
            response = {
                "jsonrpc": "2.0",
                "id": payload.get("id", 1),
                "result": result,
            }
        else:
            response = override

        if isinstance(response, Exception):
            transport_options = {"side_effect": response}
        else:
            body = (
                response if isinstance(response, bytes)
                else json.dumps(response).encode("utf-8")
            )
            transport_options = {"return_value": BytesIO(body)}

        with patch.dict(os.environ, {"BASE_RPC_URL": FAKE_RPC_URL}):
            with patch("script.verify_ledger.urlopen", **transport_options):
                return rpc_call(payload)

    def fake_rpc(payload):
        nonlocal block
        method = payload["method"]

        if method == "eth_blockNumber":
            response = respond(payload, block, block_response)
            if isinstance(response, dict) and "result" in response:
                block = response["result"]
            return response
        elif method == "eth_call":
            params = payload["params"]

            assert len(params) == 2, "eth_call must have 2 params"
            assert params[0]["to"].lower() == TOKEN.lower(), "Wrong token"
            assert params[1] == block, "Wrong block"

            data = params[0]["data"].lower()
            if data == TOTAL_SUPPLY_SELECTOR:
                amount = 100 * 10**18 + supply_wei
                override = supply_response
            elif data.startswith(BALANCE_OF_SELECTOR) and len(data) == 74:
                assert data[10:34] == "0" * 24, "Invalid address padding"

                address = "0x" + data[-40:]
                balances = {
                    TREASURY.lower(): 60,
                    REWARDS.lower(): 25,
                }
                if address not in balances:
                    raise ValueError(f"Unknown fake RPC address: {address}")
                amount = balances[address] * 10**18 + balances_wei
                override = balance_response
            else:
                raise ValueError(f"Unsupported fake RPC call data: {data}")

            result = "0x" + format(amount, "064x")
        else:
            raise ValueError(f"Unsupported fake RPC method: {method}")

        return respond(payload, result, override)
    return fake_rpc


class TestVerifyBalances(unittest.TestCase):
    def test_block_request_failure(self):
        rpc = Mock(wraps=make_fake_rpc(
            block_response=TimeoutError("timed out"),
        ))

        with self.assertRaisesRegex(SourceUnavailable, "RPC transport/JSON failure: TimeoutError"):
            verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

        self.assertEqual(rpc.call_count, 1)
        self.assertEqual(rpc.call_args.args[0]["method"], "eth_blockNumber")

    def test_balance_request_failure(self):
        rpc = Mock(wraps=make_fake_rpc(
            balance_response=URLError("Connection refused"),
        ))

        with self.assertRaisesRegex(SourceUnavailable, "RPC transport/JSON failure: URLError"):
            verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

        self.assertEqual(rpc.call_count, 2)
        self.assertTrue(rpc.call_args.args[0]["params"][0]["data"].startswith(
            BALANCE_OF_SELECTOR,
        ))

    def test_supply_request_failure(self):
        rpc = Mock(wraps=make_fake_rpc(
            supply_response=HTTPError(FAKE_RPC_URL, 503, "Service Unavailable", {}, None),
        ))

        with self.assertRaisesRegex(SourceUnavailable, "RPC HTTP 503"):
            verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

        self.assertEqual(rpc.call_count, 4)
        self.assertEqual(
            rpc.call_args.args[0]["params"][0]["data"], TOTAL_SUPPLY_SELECTOR,
        )

    def test_balance_error_response(self):
        rpc = make_fake_rpc(balance_response={
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32000, "message": "Balance unavailable"},
        })

        with self.assertRaisesRegex(SourceUnavailable, "Balance unavailable"):
            verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

    def test_json_rpc_error_at_each_stage(self):
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32603, "message": "Internal error"},
        }
        for stage, expected_calls in (
            ("block_response", 1),
            ("balance_response", 2),
            ("supply_response", 4),
        ):
            with self.subTest(stage=stage):
                rpc = Mock(wraps=make_fake_rpc(**{stage: response}))

                with self.assertRaisesRegex(SourceUnavailable, "Internal error"):
                    verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

                self.assertEqual(rpc.call_count, expected_calls)

    def test_invalid_json_at_each_stage(self):
        for stage, expected_calls in (
            ("block_response", 1),
            ("balance_response", 2),
            ("supply_response", 4),
        ):
            with self.subTest(stage=stage):
                rpc = Mock(wraps=make_fake_rpc(**{
                    stage: b"<html>Bad Gateway</html>",
                }))

                with self.assertRaisesRegex(SourceUnavailable, "JSONDecodeError"):
                    verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

                self.assertEqual(rpc.call_count, expected_calls)

    def test_invalid_response_envelopes_at_each_stage(self):
        for stage, expected_calls in (
            ("block_response", 1),
            ("balance_response", 2),
            ("supply_response", 4),
        ):
            for response in (None, [], {}):
                with self.subTest(stage=stage, response=response):
                    rpc = Mock(wraps=make_fake_rpc(**{stage: response}))

                    with self.assertRaises(SourceUnavailable):
                        verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

                    self.assertEqual(rpc.call_count, expected_calls)

    def test_null_result_at_each_stage(self):
        response = {"jsonrpc": "2.0", "id": 1, "result": None}
        for stage, expected_calls in (
            ("block_response", 1),
            ("balance_response", 2),
            ("supply_response", 4),
        ):
            with self.subTest(stage=stage):
                rpc = Mock(wraps=make_fake_rpc(**{stage: response}))

                with self.assertRaises(SourceUnavailable):
                    verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

                self.assertEqual(rpc.call_count, expected_calls)

    def test_empty_balance_and_supply_results_are_unavailable(self):
        response = {"jsonrpc": "2.0", "id": 1, "result": "0x"}
        for stage, expected_calls in (
            ("balance_response", 2),
            ("supply_response", 4),
        ):
            with self.subTest(stage=stage):
                rpc = Mock(wraps=make_fake_rpc(**{stage: response}))

                with self.assertRaises(SourceUnavailable):
                    verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

                self.assertEqual(rpc.call_count, expected_calls)

    def test_zero_balances_and_supply_are_valid(self):
        ledger = make_mock_ledger()
        for entry in ledger["entries"]:
            entry["amount"] = "0"

        zero_response = {"jsonrpc": "2.0", "id": 1, "result": "0x" + "00" * 32}
        rpc = make_fake_rpc(
            block_response={"jsonrpc": "2.0", "id": 1, "result": "0x0"},
            balance_response=zero_response,
            supply_response=zero_response,
        )

        verify_balances_total_supply(ledger, TOKEN, rpc)

    def test_custom_block_response(self):
        rpc = make_fake_rpc(block_response={
            "jsonrpc": "2.0", "id": 1, "result": "0x1234",
        })

        verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

    def test_custom_block_raw_json_body(self):
        rpc = make_fake_rpc(block_response=(
            b'{"jsonrpc": "2.0", "id": 1, "result": "0x1234"}'
        ))

        verify_balances_total_supply(make_mock_ledger(), TOKEN, rpc)

    def test_with_1wei_supply_differences(self):
        ledger = make_mock_ledger()
        fake_rpc = make_fake_rpc(1,0)

        with self.assertRaisesRegex(AccountingViolation, "Total supply mismatch"):
            verify_balances_total_supply(ledger, TOKEN, fake_rpc)

    def test_with_1wei_balances_differences(self):
        ledger = make_mock_ledger()
        fake_rpc = make_fake_rpc(0, 1)

        with self.assertRaisesRegex(AccountingViolation, "Balances not matched"):
            verify_balances_total_supply(ledger, TOKEN, fake_rpc)

    def test_verify_balances(self):
        ledger = make_mock_ledger()
        fake_rpc = make_fake_rpc(0, 0)

        verify_balances_total_supply(ledger, TOKEN, fake_rpc)

class TestFakeRPC(unittest.TestCase):
    def test_transport_failures_are_converted_by_real_rpc_call(self):
        failures = (
            (TimeoutError("timed out"), "RPC transport/JSON failure: TimeoutError"),
            (URLError("Connection refused"), "RPC transport/JSON failure: URLError"),
            (URLError(TimeoutError("timed out")), "RPC transport/JSON failure: URLError"),
            (HTTPError(FAKE_RPC_URL, 429, "Too Many Requests", {}, None), "RPC HTTP 429"),
            (HTTPError(FAKE_RPC_URL, 503, "Service Unavailable", {}, None), "RPC HTTP 503"),
        )
        for failure, expected_message in failures:
            with self.subTest(failure=repr(failure)):
                rpc = make_fake_rpc(block_response=failure)

                with self.assertRaisesRegex(SourceUnavailable, expected_message) as caught:
                    rpc({"jsonrpc": "2.0", "method": "eth_blockNumber", "id": 1})

                self.assertIs(caught.exception.__cause__, failure)

    def test_json_rpc_error_is_returned_without_result(self):
        response = {
            "jsonrpc": "2.0",
            "id": 7,
            "error": {"code": -32603, "message": "Internal error"},
        }
        rpc = make_fake_rpc(block_response=response)

        actual = rpc({"jsonrpc": "2.0", "method": "eth_blockNumber", "id": 7})

        self.assertEqual(actual, response)
        self.assertNotIn("result", actual)

    def test_invalid_json_is_decoded_by_real_rpc_call(self):
        for body in (b"", b"<html>Bad Gateway</html>", b'{"jsonrpc":'):
            with self.subTest(body=body):
                rpc = make_fake_rpc(block_response=body)

                with self.assertRaisesRegex(SourceUnavailable, "JSONDecodeError") as caught:
                    rpc({"jsonrpc": "2.0", "method": "eth_blockNumber", "id": 1})

                self.assertIsInstance(caught.exception.__cause__, json.JSONDecodeError)

    def test_transport_and_environment_are_restored(self):
        from script import verify_ledger

        original_urlopen = verify_ledger.urlopen
        with patch.dict(os.environ, {"BASE_RPC_URL": "https://original.invalid"}):
            make_fake_rpc()({"method": "eth_blockNumber", "id": 1})
            self.assertEqual(os.environ["BASE_RPC_URL"], "https://original.invalid")
            self.assertIs(verify_ledger.urlopen, original_urlopen)

            with self.assertRaises(SourceUnavailable):
                make_fake_rpc(block_response=TimeoutError("timed out"))({
                    "method": "eth_blockNumber", "id": 1,
                })

            self.assertEqual(os.environ["BASE_RPC_URL"], "https://original.invalid")
            self.assertIs(verify_ledger.urlopen, original_urlopen)

    def test_custom_responses_are_returned_unchanged(self):
        requests = {
            "block_response": {"method": "eth_blockNumber", "id": 7},
            "balance_response": {
                "method": "eth_call",
                "id": 7,
                "params": [{
                    "to": TOKEN,
                    "data": BALANCE_OF_SELECTOR + TREASURY[2:].zfill(64),
                }, hex(10100)],
            },
            "supply_response": {
                "method": "eth_call",
                "id": 7,
                "params": [{
                    "to": TOKEN, "data": TOTAL_SUPPLY_SELECTOR,
                }, hex(10100)],
            },
        }
        responses = (
            None,
            [],
            {},
            {"jsonrpc": "2.0", "id": 7, "result": None},
            {"jsonrpc": "2.0", "id": 7, "result": "0x01"},
            {"jsonrpc": "2.0", "id": 7, "error": {"code": -32000}},
        )
        for stage, payload in requests.items():
            for response in responses:
                with self.subTest(stage=stage, response=response):
                    rpc = make_fake_rpc(**{stage: response})
                    self.assertEqual(rpc(payload), response)

    def test_response_changes_do_not_leak(self):
        response = {"error": {"code": -32000, "message": "Block unavailable"}}
        rpc = make_fake_rpc(block_response=response)
        payload = {"method": "eth_blockNumber", "id": 1}

        first_response = rpc(payload)
        first_response["error"]["message"] = "Changed"

        self.assertEqual(rpc(payload), response)
        self.assertEqual(response["error"]["message"], "Block unavailable")
        verify_balances_total_supply(make_mock_ledger(), TOKEN, make_fake_rpc())

class TestExpectedState(unittest.TestCase):

    def test_fractional_amounts_preserve_every_base_unit(self):
        ledger = make_mock_ledger()
        for entry, amount in zip(ledger["entries"], (
            "100.000000000000000001", "30.25", "10.125", "5.0625",
        )):
            entry["amount"] = amount

        balances, supply = calculate_expected_state(ledger)

        self.assertEqual(supply, 100_000_000_000_000_000_001)
        self.assertEqual(balances, {
            TREASURY: 59_625_000_000_000_000_001,
            REWARDS: 25_187_500_000_000_000_000,
            EXTERNAL: 10_125_000_000_000_000_000,
            CONTRIBUTOR: 5_062_500_000_000_000_000,
        })

    def test_calculate_expected_state(self):
        balances, supply = calculate_expected_state(
            make_mock_ledger()
        )

        self.assertEqual(balances[TREASURY], 60 * 10**18)
        self.assertEqual(balances[REWARDS], 25 * 10**18)
        self.assertEqual(balances[EXTERNAL], 10 * 10**18)
        self.assertEqual(balances[CONTRIBUTOR], 5 * 10**18)
        self.assertEqual(supply, 100 * 10**18)

    def test_verify_balances_total_supply(self):
        fake_rpc = make_fake_rpc(0, 0)
        verify_balances_total_supply(make_mock_ledger(), TOKEN, fake_rpc)