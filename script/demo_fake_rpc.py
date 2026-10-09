from script.fetch_rpc_transfers import fetch_rpc_transfers


def fake_rpc(request):
    print("Request diterima:", request)
    return {"result": []}


result = fetch_rpc_transfers(
    "0x" + "33" * 20,
    100,
    106,
    fake_rpc,
)

print("Hasil:", result)