import unittest
from copy import deepcopy
from unittest.mock import Mock, call

from script.decode_transfer_fixture import TRANSFER_TOPIC, log
from script.fetch_rpc_transfers import fetch_rpc_transfers


class TestFetchRpcTransfers(unittest.TestCase):
    token = "0x" + "33" * 20

    def expected_request(self, first, last):
        return {
            "jsonrpc": "2.0",
            "id": first,
            "method": "eth_getLogs",
            "params": [{
                "address": self.token,
                "fromBlock": hex(first),
                "toBlock": hex(last),
                "topics": [TRANSFER_TOPIC],
            }],
        }

    def test_merges_two_windows_and_sends_expected_requests(self):
        second_log = deepcopy(log)
        second_log["transactionHash"] = "0x" + "cd" * 32
        second_log["data"] = "0x" + format(2**256 - 1, "064x")
        rpc = Mock(side_effect=[{"result": [log]}, {"result": [second_log]}])

        result = fetch_rpc_transfers(self.token, 100, 10100, rpc)

        self.assertEqual(result, [
            {
                "from": {"hash": "0x" + "11" * 20},
                "to": {"hash": "0x" + "22" * 20},
                "transaction_hash": event["transactionHash"],
                "total": {"value": str(value)},
            }
            for event, value in ((log, 2**53 + 1), (second_log, 2**256 - 1))
        ])
        self.assertEqual(rpc.call_args_list, [
            call(self.expected_request(100, 10099)),
            call(self.expected_request(10100, 10100)),
        ])

    def test_empty_result_succeeds(self):
        rpc = Mock(return_value={"result": []})
        self.assertEqual(fetch_rpc_transfers(self.token, 100, 106, rpc), [])
        rpc.assert_called_once_with(self.expected_request(100, 106))

    def test_second_window_failure_raises_instead_of_returning_partial_results(self):
        cases = (
            ({"error": {"code": -32000, "message": "failed"}}, "RPC returned an error"),
            ({}, "RPC response missing result"),
            ({"result": {}}, "RPC result must be a list"),
        )
        for response, message in cases:
            with self.subTest(response=response):
                rpc = Mock(side_effect=[{"result": [log]}, response])
                with self.assertRaisesRegex(ValueError, f"^{message}$"):
                    fetch_rpc_transfers(self.token, 100, 10100, rpc)
                self.assertEqual(rpc.call_count, 2)
