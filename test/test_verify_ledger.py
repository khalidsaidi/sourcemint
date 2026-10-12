import json
import unittest
from unittest.mock import patch

import script.verify_ledger as verifier
import script.fetch_rpc_transfers as adapter


TOKEN = "0x" + "11" * 20
START = 41988939

TRANSFER = {
    "from": {"hash": "0x" + "00" * 20},
    "to": {"hash": "0x" + "22" * 20},
    "transaction_hash": "0x" + "aa" * 32,
    "total": {"value": "1000000000000000000"},
}


def rpc_response(request, result):
    return {
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": result,
    }


class TestLedgerFallback(unittest.TestCase):

    # 1. Primary sukses: RPC tidak dipanggil.
    def test_primary_success_skips_rpc(self):
        page = {
            "items": [TRANSFER],
            "next_page_params": None,
        }

        with (
            patch.object(verifier, "_get_page", return_value=page),
            patch.object(verifier, "rpc_call") as rpc,
            patch.object(verifier, "fetch_rpc_transfers") as fallback,
        ):
            result = verifier.fetch_transfers(TOKEN)

        self.assertEqual(result, [TRANSFER])
        rpc.assert_not_called()
        fallback.assert_not_called()

    # 2. Primary gagal: hasil fallback dipakai.
    def test_primary_failure_uses_fallback(self):
        head = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": hex(START + 10),
        }

        with (
            patch.object(
                verifier,
                "_get_page",
                side_effect=verifier.SourceUnavailable("primary down"),
            ),
            patch.object(
                verifier, "rpc_call", return_value=head
            ) as rpc,
            patch.object(
                verifier,
                "fetch_rpc_transfers",
                return_value=[TRANSFER],
            ) as fallback,
        ):
            result = verifier.fetch_transfers(TOKEN)

        self.assertEqual(result, [TRANSFER])
        fallback.assert_called_once_with(
            TOKEN, START, START + 10, rpc
        )

    # 3. Primary dan RPC gagal: main mengembalikan exit code 2.
    def test_both_sources_fail_returns_exit_2(self):
        ledger = {
            "token": TOKEN,
            "project_wallets": {},
            "entries": [],
        }

        with (
            patch.object(verifier, "LEDGER_PATH") as ledger_path,
            patch.object(
                verifier,
                "_get_page",
                side_effect=verifier.SourceUnavailable("primary down"),
            ),
            patch.object(
                verifier,
                "rpc_call",
                side_effect=verifier.SourceUnavailable("RPC HTTP 429"),
            ),
            patch("builtins.print") as output,
        ):
            ledger_path.read_text.return_value = json.dumps(ledger)
            exit_code = verifier.main()

        self.assertEqual(exit_code, 2)

        printed = "\n".join(
            " ".join(map(str, call.args))
            for call in output.call_args_list
        )
        self.assertIn("COULD NOT VERIFY", printed)
        self.assertNotIn("RESULT:", printed)

    # 4. RPC result [] adalah data kosong yang valid.
    def test_empty_rpc_logs_are_valid(self):
        def fake_rpc(request):
            if request["method"] == "eth_blockNumber":
                return rpc_response(request, hex(START))

            self.assertEqual(request["method"], "eth_getLogs")
            return rpc_response(request, [])

        with (
            patch.object(
                verifier,
                "_get_page",
                side_effect=verifier.SourceUnavailable("primary down"),
            ),
            patch.object(
                verifier, "rpc_call", side_effect=fake_rpc
            ) as rpc,
            patch.object(
                adapter,
                "block_windows",
                return_value=[(START, START)],
            ),
        ):
            result = verifier.fetch_transfers(TOKEN)

        self.assertEqual(result, [])
        self.assertEqual(rpc.call_count, 2)

    # 5. Window kedua gagal: data window pertama tidak di-return.
    def test_second_window_failure_rejects_partial_data(self):
        raw_log = {"fixture": "first-window-log"}

        def fake_rpc(request):
            if request["method"] == "eth_blockNumber":
                return rpc_response(request, hex(START + 1))

            self.assertEqual(request["method"], "eth_getLogs")
            first = request["params"][0]["fromBlock"]

            if first == hex(START):
                return rpc_response(request, [raw_log])

            return {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {
                    "code": -32011,
                    "message": "request limit reached",
                },
            }

        with (
            patch.object(
                verifier,
                "_get_page",
                side_effect=verifier.SourceUnavailable("primary down"),
            ),
            patch.object(
                verifier, "rpc_call", side_effect=fake_rpc
            ) as rpc,
            patch.object(
                adapter,
                "block_windows",
                return_value=[
                    (START, START),
                    (START + 1, START + 1),
                ],
            ),
            patch.object(
                adapter,
                "decode_transfer",
                return_value=TRANSFER,
            ) as decode,
        ):
            with self.assertRaises(
                verifier.SourceUnavailable
            ) as caught:
                verifier.fetch_transfers(TOKEN)

        decode.assert_called_once_with(raw_log)
        self.assertEqual(rpc.call_count, 3)
        self.assertIn(
            "RPC data validation failed",
            str(caught.exception),
        )
        self.assertIn(
            "RPC returned an error",
            str(caught.exception),
        )

    def test_primary_retry_sleep_exceeds_three_minutes(self):
        with (
            patch.object(verifier, "ATTEMPTS_PER_SOURCE", 8),
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

        self.assertEqual(request.call_count, 8)
        self.assertEqual(delays, [2, 4, 8, 16, 32, 64, 128])
        self.assertEqual(sum(delays), 254)
        self.assertGreater(sum(delays), 180)


if __name__ == "__main__":
    unittest.main()
