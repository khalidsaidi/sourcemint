# GCP Cloud Build (CI + Manual Deploy)

This repo uses **GCP-only automation**:
- CI on push to `main` (no secrets used)
- Manual-only deploy trigger for Base mainnet (secrets from Secret Manager)

## Project

- Project ID: `sourcemint-prod-260210-28679`
- Region: `us-central1`
- GitHub connection: `sourcemint-github-owner`
- Connected repository resource:
  `projects/sourcemint-prod-260210-28679/locations/us-central1/connections/sourcemint-github-owner/repositories/sourcemint`

## Secrets (Secret Manager)

Deployment secrets are stored only in Secret Manager:
- `SRCMNT_BASE_RPC_URL`
- `SRCMNT_BASE_PRIVATE_KEY`
- `SRCMNT_ETHERSCAN_API_KEY`

Trigger execution SA:
- `sourcemint-cloudbuild-runner@sourcemint-prod-260210-28679.iam.gserviceaccount.com`

Least privilege:
- Grant `roles/secretmanager.secretAccessor` on only the three secrets above to the trigger execution SA.

## Build Config Files

- `cloudbuild/ci.yaml`
  - Updates submodules
  - Runs `make fmt`, checks for diff, then `make test`
  - Uses no secrets

- `cloudbuild/deploy-base-mainnet.yaml`
  - Updates submodules
  - Runs `forge fmt --check` and `forge test -vvv`
  - Injects `RPC_URL`, `PRIVATE_KEY`, `ETHERSCAN_API_KEY` from Secret Manager
  - Runs deploy + verify on Base mainnet (`chainId 8453`)
  - Safety guard blocks redeploy by default

## Triggers

- CI trigger (push to main):
  - Name: `sourcemint-ci-main`
  - ID: `9ada4bc3-e0bb-46c7-9245-ba4262a58285`
  - URL: https://console.cloud.google.com/cloud-build/triggers;region=us-central1/edit/9ada4bc3-e0bb-46c7-9245-ba4262a58285?project=sourcemint-prod-260210-28679

- Deploy trigger (manual only):
  - Name: `sourcemint-deploy-base-mainnet`
  - ID: `ee5aeb46-523f-42fa-9a32-17662096fbd0`
  - URL: https://console.cloud.google.com/cloud-build/triggers;region=us-central1/edit/ee5aeb46-523f-42fa-9a32-17662096fbd0?project=sourcemint-prod-260210-28679
  - Default substitution: `_ALLOW_REDEPLOY=false`

## Running Deploy Trigger

Run from Cloud Console trigger page or via CLI:

```bash
gcloud builds triggers run sourcemint-deploy-base-mainnet \
  --project=sourcemint-prod-260210-28679 \
  --region=us-central1 \
  --branch=main
```

If intentionally deploying a new contract version, override guard:

```bash
gcloud builds triggers run sourcemint-deploy-base-mainnet \
  --project=sourcemint-prod-260210-28679 \
  --region=us-central1 \
  --branch=main \
  --substitutions=_ALLOW_REDEPLOY=true
```

## GA Reminder

Do **not** redeploy v1.0.0 token unless intentional:
- Base mainnet (8453): `0x914F6b6a0DaD39A3CB932dcf4D1af885C7c08EeB`
- Verified: https://basescan.org/address/0x914f6b6a0dad39a3cb932dcf4d1af885c7c08eeb#code
