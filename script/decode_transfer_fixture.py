log = {
    "topics": [
        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
        "0x" + "0" * 24 + "11" * 20,
        "0x" + "0" * 24 + "22" * 20,
    ],
    "data": "0x" + "20000000000001".zfill(64),
    "transactionHash": "0x" + "ab" * 32,
}

TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)


def decode_transfer(log):
    if not isinstance(log, dict):
        raise ValueError("log must be an object")

    topics = log.get("topics")

    if not isinstance(topics, list):
        raise ValueError("topics must be a list")

    if len(topics) != 3:
        raise ValueError("Transfer must have 3 topics")

    if(topics[0] != TRANSFER_TOPIC):
        raise ValueError("topics[0] must be Transfer signature")

    sender_topics = topics[1]
    receiver_topics = topics[2]

    if not isinstance(sender_topics, str) or len(sender_topics) != 66:
        raise ValueError("Invalid sender topic or length")

    if not isinstance(receiver_topics, str) or len(receiver_topics) != 66:
        raise ValueError("Invalid receiver topic or length")

    for name, topic in (("sender", sender_topics), ("receiver", receiver_topics)):
        if not topic.startswith("0x"):
            raise ValueError(f"{name} topic must start with 0x")
        if any(char not in "0123456789abcdefABCDEF" for char in topic[2:]):
            raise ValueError(f"{name} topic must contain only hex characters")

    sender = "0x" + sender_topics[-40:]
    receiver = "0x" + receiver_topics[-40:]

    data = log.get("data")

    if not isinstance(data, str) or len(data) != 66:
        raise ValueError("Invalid data topic or length")

    if not data.startswith("0x"):
        raise ValueError("Data must start witn 0x")

    if any(char not in "0123456789abcdefABCDEF" for char in data[2:]):
        raise ValueError("Data must contain only hex characters")

    amount = int(data, 16)
    txs_hash = log.get("transactionHash")

    if (
        not isinstance(txs_hash, str)
        or len(txs_hash) != 66
        or not txs_hash.startswith("0x")
        or any(c not in "0123456789abcdefABCDEF" for c in txs_hash[2:])
    ):
        raise ValueError("Invalid transaction hash")

    return{
        "from": {"hash": sender},
        "to": {"hash": receiver},
        "transaction_hash": txs_hash,
        "total": {"value": str(amount)},
    }


if __name__ == "__main__":
    result = decode_transfer(log);

    assert result["from"]["hash"] == "0x" + "11" * 20
    assert result["to"]["hash"] == "0x" + "22" * 20
    assert result["transaction_hash"] == log["transactionHash"]
    assert result["total"]["value"] == str(2**53 + 1)

    print(result)
    print("All assertion PASS")
