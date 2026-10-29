"""A single blip must not discard a 180-request derivation.

Throttling arrives in three shapes: an HTTP status, a dropped connection, and
a successful HTTP 200 whose JSON-RPC body carries an error. The third is the
one that looks like success at the transport layer, and it is how several
public endpoints report a rate limit.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_ledger as verifier  # noqa: E402

PAYLOAD = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
GOOD = {"jsonrpc": "2.0", "id": 1, "result": "0x1"}


class Response:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def read(self, *_):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def rpc_with(side_effect):
    with (patch.object(verifier, "urlopen", side_effect=side_effect) as opened,
          patch.object(verifier.time, "sleep")):
        verifier._pace[0] = verifier.RPC_MIN_INTERVAL
        verifier._last_call[0] = 0.0
        with patch.object(verifier.json, "load",
                          side_effect=lambda r: json.loads(r.read())):
            return verifier.rpc_call(PAYLOAD, endpoint="https://example.invalid"), opened


class Retry(unittest.TestCase):
    def test_a_throttle_inside_a_successful_response_is_retried(self):
        throttled = Response({"jsonrpc": "2.0", "id": 1,
                              "error": {"code": -32005, "message": "rate limit"}})
        result, opened = rpc_with([throttled, Response(GOOD)])
        self.assertEqual(result, GOOD)
        self.assertEqual(opened.call_count, 2, "a transient error must be retried")

    def test_a_throttle_named_only_in_the_message_is_retried(self):
        throttled = Response({"jsonrpc": "2.0", "id": 1,
                              "error": {"code": -1, "message": "too many requests"}})
        result, opened = rpc_with([throttled, Response(GOOD)])
        self.assertEqual(result, GOOD)

    def test_a_permanent_error_is_returned_not_retried(self):
        # "range too large" is not going to succeed on the next attempt
        bad = {"jsonrpc": "2.0", "id": 1,
               "error": {"code": -32602, "message": "invalid params",
                         "data": "Block range too large for public access"}}
        result, opened = rpc_with([Response(bad)])
        self.assertEqual(result, bad, "a permanent error is the caller's to handle")
        self.assertEqual(opened.call_count, 1)

    def test_a_transport_failure_is_retried(self):
        result, opened = rpc_with([verifier.URLError("dropped"), Response(GOOD)])
        self.assertEqual(result, GOOD)
        self.assertEqual(opened.call_count, 2)

    def test_giving_up_names_the_last_failure(self):
        throttled = Response({"jsonrpc": "2.0", "id": 1,
                              "error": {"code": -32005, "message": "rate limit"}})
        with self.assertRaises(verifier.SourceUnavailable) as caught:
            rpc_with([throttled] * verifier.RPC_ATTEMPTS)
        self.assertIn("rate limit", str(caught.exception))

    def test_throttling_slows_every_later_call(self):
        throttled = Response({"jsonrpc": "2.0", "id": 1,
                              "error": {"code": -32005, "message": "rate limit"}})
        rpc_with([throttled, Response(GOOD)])
        self.assertGreater(verifier._pace[0], verifier.RPC_MIN_INTERVAL,
                           "the next few hundred calls would hit the same wall")
        verifier._pace[0] = verifier.RPC_MIN_INTERVAL


if __name__ == "__main__":
    unittest.main()
