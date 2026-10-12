"""Offline regressions for RPC validation and both verifier entrypoints."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import script.verify_ledger as verifier
from script.decode_transfer_fixture import TRANSFER_TOPIC

START = 41988939
TOKEN = "0x" + "11" * 20
RAW_LOG = {
    "topics": [TRANSFER_TOPIC, "0x" + "00" * 32, "0x" + "00" * 12 + "22" * 20],
    "data": "0x" + format(10**18, "064x"),
    "transactionHash": "0x" + "aa" * 32,
}
LEDGER = {
    "token": TOKEN,
    "project_wallets": {},
    "entries": [{
        "tx": RAW_LOG["transactionHash"],
        "to": "0x" + "22" * 20,
        "amount": "1",
        "reason": "Offline mint fixture",
    }],
}


def response(request, result):
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


class TestRpcRegressions(unittest.TestCase):
    def run_verifier(self, rpc):
        output = io.StringIO()
        with (
            patch.object(verifier, "LEDGER_PATH") as ledger_path,
            patch.object(verifier, "_get_page", side_effect=verifier.SourceUnavailable("offline primary")),
            patch.object(verifier, "rpc_call", side_effect=rpc),
            redirect_stdout(output),
        ):
            ledger_path.read_text.return_value = json.dumps(LEDGER)
            code = verifier.main()
        return code, output.getvalue()

    def assert_unverifiable(self, rpc):
        code, output = self.run_verifier(rpc)
        self.assertEqual(code, 2)
        self.assertIn("COULD NOT VERIFY", output)
        self.assertNotIn("RESULT:", output)
        self.assertNotIn("UNACCOUNTED", output)

    def test_block_number_rejects_invalid_ids_before_fetching_logs(self):
        for invalid_id in (True, False, 1.0, "1", None, 2):
            with self.subTest(id=invalid_id), patch.object(verifier, "fetch_rpc_transfers") as fetch:
                fetch.return_value = []
                self.assert_unverifiable(lambda request: {
                    "jsonrpc": "2.0", "id": invalid_id, "result": hex(START),
                })
                fetch.assert_not_called()

    def test_log_response_rejects_invalid_ids(self):
        for invalid_id in (True, float(START), str(START), None, START + 1):
            def rpc(request):
                if request["method"] == "eth_blockNumber":
                    return response(request, hex(START))
                return {"jsonrpc": "2.0", "id": invalid_id, "result": [RAW_LOG]}
            with self.subTest(id=invalid_id):
                self.assert_unverifiable(rpc)

    def test_malformed_logs_return_exit_2_not_accounting_failure(self):
        cases = [("null log", None), ("empty log", {})]
        for field in ("topics", "data", "transactionHash"):
            item = copy.deepcopy(RAW_LOG)
            del item[field]
            cases.append((field + " missing", item))
            for value in (None, 123, [], {}):
                item = copy.deepcopy(RAW_LOG)
                item[field] = value
                cases.append((field + " wrong type " + repr(value), item))
        for index in (1, 2):
            for value in (None, 123, [], {}):
                item = copy.deepcopy(RAW_LOG)
                item["topics"][index] = value
                cases.append(("topic " + str(index) + " " + repr(value), item))
        for value in ("", "0x12", "zz" + "ab" * 32, "0x" + "gg" * 32):
            item = copy.deepcopy(RAW_LOG)
            item["transactionHash"] = value
            cases.append(("invalid hash " + value, item))
        for name, item in cases:
            def rpc(request):
                return response(request, hex(START) if request["method"] == "eth_blockNumber" else [item])
            with self.subTest(case=name):
                self.assert_unverifiable(rpc)

    def test_fallback_success_uses_real_decoder_and_matches_ledger(self):
        def rpc(request):
            return response(request, hex(START) if request["method"] == "eth_blockNumber" else [RAW_LOG])
        code, output = self.run_verifier(rpc)
        self.assertEqual(code, 0)
        self.assertIn("RESULT: OK", output)
        self.assertIn("ledger entries matched: 1/1", output)

    def test_primary_partial_page_is_discarded_before_fallback(self):
        invalid_primary_item = {"must_not_reach_accounting": True}
        def rpc(request):
            return response(request, hex(START) if request["method"] == "eth_blockNumber" else [RAW_LOG])
        output = io.StringIO()
        with (
            patch.object(verifier, "LEDGER_PATH") as ledger_path,
            patch.object(verifier, "_get_page", side_effect=[
                {"items": [invalid_primary_item], "next_page_params": {"page": 2}},
                verifier.SourceUnavailable("second page failed"),
            ]),
            patch.object(verifier, "rpc_call", side_effect=rpc),
            redirect_stdout(output),
        ):
            ledger_path.read_text.return_value = json.dumps(LEDGER)
            code = verifier.main()
        self.assertEqual(code, 0)
        self.assertIn("ledger entries matched: 1/1", output.getvalue())

    def test_transport_errors_return_exit_2(self):
        failures = (
            verifier.HTTPError("https://example.invalid", 429, "rate limit", {}, None),
            verifier.URLError("offline transport"),
            TimeoutError("offline timeout"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.check_transport_failure(failure)
        self.check_transport_failure(lambda *args, **kwargs: io.BytesIO(b"not JSON"))

    def check_transport_failure(self, failure):
        output = io.StringIO()
        with (
            patch.object(verifier, "LEDGER_PATH") as ledger_path,
            patch.object(verifier, "_get_page", side_effect=verifier.SourceUnavailable("offline primary")),
            patch.dict(os.environ, {"BASE_RPC_URL": "https://example.invalid"}),
            patch.object(verifier, "urlopen", side_effect=failure),
            redirect_stdout(output),
        ):
            ledger_path.read_text.return_value = json.dumps(LEDGER)
            code = verifier.main()
        self.assertEqual(code, 2)
        self.assertIn("COULD NOT VERIFY", output.getvalue())
        self.assertNotIn("RESULT:", output.getvalue())

    def test_direct_and_module_entrypoints_import_and_exit_2_offline(self):
        root = Path(__file__).resolve().parents[1]
        # Patch transport only; do not add the repository to PYTHONPATH.
        hook = (
            "import urllib.request\n"
            "from urllib.error import HTTPError\n"
            "def offline(req, *args, **kwargs):\n"
            "    raise HTTPError('https://example.invalid', 429, 'offline', {}, None)\n"
            "urllib.request.urlopen = offline\n"
        )
        with tempfile.TemporaryDirectory(prefix="sourcemint-entrypoint-") as temp:
            Path(temp, "sitecustomize.py").write_text(hook)
            env = dict(os.environ, PYTHONPATH=temp, PYTHONDONTWRITEBYTECODE="1",
                       BASE_RPC_URL="https://example.invalid")
            for args in (["script/verify_ledger.py"], ["-m", "script.verify_ledger"]):
                with self.subTest(args=args):
                    run = subprocess.run([sys.executable, "-B", *args], cwd=root, env=env,
                                         text=True, capture_output=True, timeout=10)
                    self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                    self.assertIn("COULD NOT VERIFY", run.stdout)
                    self.assertNotIn("Traceback", run.stderr)


if __name__ == "__main__":
    unittest.main()
