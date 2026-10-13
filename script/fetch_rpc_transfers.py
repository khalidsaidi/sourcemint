if __package__:
    from .block_windows import block_windows
    from .decode_transfer_fixture import decode_transfer, TRANSFER_TOPIC
else:
    from block_windows import block_windows
    from decode_transfer_fixture import decode_transfer, TRANSFER_TOPIC


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

        response = rpc_call(request)


        if not isinstance(response, dict):
            raise ValueError("RPC response must be an object")

        if response.get("jsonrpc") != "2.0":
            raise ValueError("Invalid JSON-RPC version")

        if (
            type(response.get("id")) is not int
            or response["id"] != request["id"]
        ):
            raise ValueError("RPC response ID mismatch")

        if "error" in response:
            raise ValueError("RPC returned an error")

        if "result" not in response:
            raise ValueError("RPC response missing result")

        logs = response["result"]

        if not isinstance(logs, list):
            raise ValueError("RPC result must be a list")

        for event_log in logs:
            transfers.append(decode_transfer(event_log))
    return transfers
