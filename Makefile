.PHONY: help fmt test snapshot coverage clean deploy-sepolia

help:
	@echo "Targets:"
	@echo "  fmt            Format Solidity (forge fmt)"
	@echo "  test           Run tests (forge test)"
	@echo "  snapshot       Gas snapshot (forge snapshot)"
	@echo "  coverage       Coverage (forge coverage)"
	@echo "  clean          Clean build artifacts"
	@echo "  deploy-sepolia Deploy+verify to Sepolia (requires env vars)"

fmt:
	forge fmt

test:
	forge test -vvv

snapshot:
	forge snapshot

coverage:
	forge coverage

clean:
	rm -rf out cache broadcast reports

deploy-sepolia:
	@if [ -z "$$RPC_URL" ]; then echo "RPC_URL is required"; exit 1; fi
	@if [ -z "$$PRIVATE_KEY" ]; then echo "PRIVATE_KEY is required"; exit 1; fi
	@if [ -z "$$ETHERSCAN_API_KEY" ]; then echo "ETHERSCAN_API_KEY is required"; exit 1; fi
	forge script script/DeploySourceMint.s.sol:DeploySourceMint \
		--rpc-url $$RPC_URL \
		--broadcast \
		--verify \
		--chain sepolia \
		--etherscan-api-key $$ETHERSCAN_API_KEY \
		-vvvv
