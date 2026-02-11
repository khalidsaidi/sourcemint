# GCP Cloud Build (CI + Manual Deploy)

This repo uses **GCP Cloud Build** for:
- CI on pushes to `main` (no secrets)
- Manual-only deploy trigger for Base mainnet (secrets injected from Secret Manager)

## Project

- GCP project: `sourcemint-prod-260210-28679`

## Secrets (Secret Manager)

All deployment secrets live in **Secret Manager**:
- `SRCMNT_BASE_RPC_URL`
- `SRCMNT_BASE_PRIVATE_KEY`
- `SRCMNT_ETHERSCAN_API_KEY`

Least privilege: grant only `roles/secretmanager.secretAccessor` on those three
secrets to the Cloud Build service account:

- `925412503432@cloudbuild.gserviceaccount.com`

## Cloud Build Configs In This Repo

- `cloudbuild/ci.yaml`
  - Runs: `forge fmt --check`, `forge test -vvv`
  - No secrets are used.

- `cloudbuild/deploy-base-mainnet.yaml`
  - Manual trigger only.
  - Injects `RPC_URL`, `PRIVATE_KEY`, `ETHERSCAN_API_KEY` from Secret Manager.
  - Includes a redeploy guard to prevent accidental redeploys of the GA token.

## Triggers

### CI Trigger (push to main)

Configured to run on pushes to `main` using `cloudbuild/ci.yaml`.

### Manual Deploy Trigger (Base mainnet)

Configured as **manual-only** using `cloudbuild/deploy-base-mainnet.yaml`.

Redeploy guard:
- Default: `_ALLOW_REDEPLOY=false` blocks deployment if `deployments/8453.json`
  already contains the GA address.
- To intentionally deploy a new contract version, run the trigger with:
  - `_ALLOW_REDEPLOY=true`

## GA Reminder

Do **not** redeploy the v1.0.0 GA token:
- Base mainnet (8453) GA address: `0x914F6b6a0DaD39A3CB932dcf4D1af885C7c08EeB`
- Verified: https://basescan.org/address/0x914f6b6a0dad39a3cb932dcf4d1af885c7c08eeb#code

