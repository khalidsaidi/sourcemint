

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
    if len(log["topics"]) != 3:
        raise ValueError("Transfer must have 3 topics")

    if(log["topics"][0] != TRANSFER_TOPIC):
        raise ValueError("topics[0] must be Transfer signature")
    
    sender_topics = log["topics"][1]
    receiver_topics = log["topics"][2]

    if len(sender_topics) != 66:
        raise ValueError("Invalid sender topic length")

    if len(receiver_topics) != 66:
        raise ValueError("Invalid receiver topic length")

    sender = "0x" + sender_topics[-40:]
    receiver = "0x" + receiver_topics[-40:]

    data = log["data"]

    if len(log["data"]) != 66:
        raise ValueError("Invalid data topic length")

    if not data.startswith("0x"):
        raise ValueError("Data must start witn 0x")

    if any(char not in "0123456789abcdefABCDEF" for char in data[2:]):
        raise ValueError("Data must contain only hex characters")

    amount = int(data, 16)

    return{
        "from": {"hash": sender},
        "to": {"hash": receiver},
        "transaction_hash": log["transactionHash"],
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


    