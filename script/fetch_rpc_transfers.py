from script.block_windows import block_windows
from script.decode_transfer_fixture import decode_transfer, TRANSFER_TOPIC


def fetch_rpc_transfers(token, start, end, rpc_call):
    transfers = []

    for first, last in block_windows(start, end):
        request = {
            "jsonrpc": "2.0",
            "id": first,
            "method": "eth_getLogs",
            "params": [{
                "address": token,
                "fromBlock": hex(first),
                "toBlock": hex(last),
                "topics": [TRANSFER_TOPIC],
            }],
        }

        respons = rpc_call(request)

        if "error" in respons:
            raise ValueError("RPC returned an error")

        if "result" not in respons:
            raise ValueError("RPC response missing result")

        logs = respons["result"]

        if not isinstance(logs, list):
            raise ValueError("RPC result must be a list")

        for event_log in logs:
            transfers.append(decode_transfer(event_log))
    return transfers