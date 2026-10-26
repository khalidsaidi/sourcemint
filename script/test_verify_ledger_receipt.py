from script.verify_ledger import verify_rpc_fallback, AccountingViolation, SourceUnavailable
import unittest
from copy import deepcopy


TOKEN = "0x" + "11" * 20
OTHERS_TOKEN = "0x" + "33" * 20
SENDER = "0x" + "12" * 20
RECEIVER = "0x" + "22" * 20
TX_HASH = "0x" + "aa" * 32
ZERO_ADDRESS = "0x" + "00" * 20
BALANCE_OF_SELECTOR = "0x70a08231"
TOTAL_SUPPLY_SELECTOR = "0x18160ddd"
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)
APPROVAL_TOPIC = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"


ledger = {
    "project_wallets": {
        "treasury": RECEIVER,
    },
    "entries": [
        {
            "tx": TX_HASH,
            "from": "mint",
            "to": RECEIVER,
            "amount": "100",
        }
    ]
}

others_token_transfer_log = {
    "address": OTHERS_TOKEN,
    "topics": [
        TRANSFER_TOPIC,
        "0x" + ZERO_ADDRESS[2:].zfill(64),
        "0x" + RECEIVER[2:].zfill(64),
    ],
    "data": "0x" + format(100 * 10**18, "064x"),
    "transactionHash": TX_HASH,
}

mint_log = {
    "address": TOKEN,
    "topics": [
        TRANSFER_TOPIC,
        "0x" + ZERO_ADDRESS[2:].zfill(64),
        "0x" + RECEIVER[2:].zfill(64),
    ],
    "data": "0x" + format(100 * 10**18, "064x"),
    "transactionHash": TX_HASH,
}

transfer_log = {
    "address": TOKEN,
    "topics": [
        TRANSFER_TOPIC,
        "0x" + SENDER[2:].zfill(64),
        "0x" + RECEIVER[2:].zfill(64),
    ],
    "data": "0x" + format(100 * 10**18, "064x"),
    "transactionHash": TX_HASH,
}

approval_log = {
    "address": TOKEN,
    "topics": [
        APPROVAL_TOPIC,
        "0x" + SENDER[2:].zfill(64),
        "0x" + RECEIVER[2:].zfill(64),
    ],
    "data": "0x" + format(100 * 10**18, "064x"),
    "transactionHash": TX_HASH,
}

valid_response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "status": "0x1",
            "transactionHash": TX_HASH,
            "logs": [
                approval_log,
                others_token_transfer_log,
                mint_log,
            ],
        },
    }


def make_fake_rpc(response):
    def fake_rpc(payload):
        method = payload["method"]
        if method == "eth_getTransactionReceipt":
            result = deepcopy(response)
            result["id"] = payload["id"]
            return result

        if method == "eth_blockNumber":
            result = hex(10100)
        elif method == "eth_call":
            call, block = payload["params"]
            assert call["to"].lower() == TOKEN.lower(), "Wrong token"
            assert block == hex(10100), "Wrong block"

            data = call["data"].lower()
            receiver_balance_data = BALANCE_OF_SELECTOR + RECEIVER[2:].zfill(64)
            if data not in (receiver_balance_data, TOTAL_SUPPLY_SELECTOR):
                raise ValueError(f"Unsupported fake RPC call data: {data}")

            result = "0x" + format(100 * 10**18, "064x")
        else:
            raise ValueError(f"Unsupported fake RPC method: {method}")

        return {"jsonrpc": "2.0", "id": payload["id"], "result": result}

    return fake_rpc


class TestVerifyLedger(unittest.TestCase):

    def test_only_other_token_rejected(self):
        response = deepcopy(valid_response)
        response["result"]["logs"] = [
            deepcopy(others_token_transfer_log)
        ]

        with self.assertRaises(AccountingViolation):
            verify_rpc_fallback(
                ledger, TOKEN, make_fake_rpc(response)
            )

    def test_invalid_amount(self):
        bad_log = deepcopy(valid_response)
        bad_log["result"]["logs"][2]["data"] = (
            "0x" + format(99 * 10**18, "064x")
        )

        fake_rpc = make_fake_rpc(bad_log)

        with self.assertRaises(AccountingViolation):
            verify_rpc_fallback(ledger, TOKEN, fake_rpc)

    def test_logs_onlyapproval_logs(self):
        bad_log = deepcopy(valid_response)
        bad_log["result"]["logs"] = [deepcopy(approval_log)]

        fake_rpc = make_fake_rpc(bad_log)

        with self.assertRaises(AccountingViolation):
            verify_rpc_fallback(ledger, TOKEN, fake_rpc)

    def test_status_0x0(self):
        bad_log = deepcopy(valid_response)
        bad_log["result"]["status"] = "0x0"

        with self.assertRaises(AccountingViolation):
            verify_rpc_fallback(ledger, TOKEN, make_fake_rpc(bad_log))


    def test_result_null(self):
        bad_log = deepcopy(valid_response)
        bad_log["result"] = None

        fake_rpc = make_fake_rpc(bad_log)

        with self.assertRaises(SourceUnavailable):
            verify_rpc_fallback(ledger, TOKEN, fake_rpc)


    def test_valid_response(self):
        fake_rpc = make_fake_rpc(valid_response)

        self.assertEqual(verify_rpc_fallback(ledger, TOKEN, fake_rpc), 0)
