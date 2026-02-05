# SourceMint (SRCMNT)

Open-source ERC20 token contract built with Foundry.

## Contract
- Name: `SourceMint`
- Symbol: `SRCMNT`
- Decimals: 18
- Supply model: fixed supply minted to deployer at deployment time
- Extensions: Burnable + Permit (gasless approvals)

## Requirements
- Foundry: `forge`, `cast`

## Dev Commands
- `make fmt`
- `make test`
- `make snapshot`
- `make coverage`

## Deploy (Sepolia)
Set env vars (DO NOT COMMIT THESE):

```bash
export RPC_URL="https://sepolia.YOUR-RPC-PROVIDER.example"
export PRIVATE_KEY="0xYOUR_PRIVATE_KEY"
export ETHERSCAN_API_KEY="YOUR_ETHERSCAN_API_KEY"
export INITIAL_SUPPLY="1000000000000000000000000"
```

Deploy + verify:

```bash
make deploy-sepolia
```

Deployment artifacts:
- `deployments/11155111.json` (auto-written by the script)

## Deployments
- Sepolia (11155111): **TBD** (after deploy, update this line with the contract address)
