.PHONY: help fmt test verify check deploy site-status snapshot coverage clean deploy-sepolia

help:
	@echo "Targets:"
	@echo "  fmt            Format Solidity (forge fmt)"
	@echo "  test           Run all tests (Solidity and Python)"
	@echo "  verify         Check the public ledger against Base"
	@echo "  check          Everything CI runs, locally"
	@echo "  deploy         Publish docs/ to Firebase Hosting (the site is NOT"
	@echo "                 deployed by pushing to main — this is the only way)"
	@echo "  site-status    Is the live site serving what is in docs/?"
	@echo "  snapshot       Gas snapshot (forge snapshot)"
	@echo "  coverage       Coverage (forge coverage)"
	@echo "  clean          Clean build artifacts"
	@echo "  deploy-sepolia Deploy+verify to Sepolia (requires env vars)"

fmt:
	forge fmt

# The contract is 16 lines; most of this project is Python. Running only the
# Solidity tests would miss nearly all of it.
test:
	forge test -vvv
	python3 -B -m unittest discover -s script -p 'test_*.py'
	python3 -B -m unittest discover -s test -p 'test_*.py'

verify:
	python3 -B script/ledger_schema.py
	BASE_RPC_URL=$${BASE_RPC_URL:-https://mainnet.base.org} python3 -B script/verify_ledger.py

check: fmt test verify

# Pushing to main does not publish the site. Firebase Hosting serves
# srcmnt.xyz and is deployed from here, by hand, on purpose.
deploy:
	firebase deploy --only hosting --project sourcemint-prod-260210-28679
	@$(MAKE) --no-print-directory site-status

# Catches the failure that went unnoticed for twelve days: the repository
# corrected, the live site still wrong.
site-status:
	@live=$$(curl -fsS -m 20 https://srcmnt.xyz/verify.html | shasum | cut -d" " -f1); 	repo=$$(shasum docs/verify.html | cut -d" " -f1); 	if [ "$$live" = "$$repo" ]; then 	  echo "site-status: srcmnt.xyz matches docs/"; 	else 	  echo "site-status: srcmnt.xyz DIFFERS from docs/ — run 'make deploy'"; exit 1; 	fi

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
