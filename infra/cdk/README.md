# infra/cdk – the AWS profile (Phase 2)

Python CDK app. Nothing account-specific is stored here: account and region come from your CLI credentials (`AWS_PROFILE` / `AWS_REGION`, target `us-east-1`), the table name from `TABLE_NAME`, the alert address from `BUDGET_EMAIL`.

| Stack | What it creates | Notes |
|---|---|---|
| `FairTableData` | DynamoDB table (on-demand, `GSI1`, `GSI2`, same keys as `server/store/table.py`) | destroyed with the stack; tag `project=fairtable` |
| `FairTableBudget` | budget `fairtable-cap-<limit>usd`; default limit $150 with alerts at $50 / $100 / $140 of actual spend, credits excluded; for a small account `BUDGET_LIMIT_USD=5 BUDGET_ALERTS=1,3,4.5` | only created when `BUDGET_EMAIL` is set; free |

## One-time setup
```bash
cd infra/cdk
python -m venv .venv && source .venv/bin/activate      # Windows Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt                         # exact versions
npm install                                             # pins the CDK CLI (run it with npx cdk)
export AWS_REGION=us-east-1                             # sign in first: aws login
npx cdk bootstrap aws://<account-id>/us-east-1 --tags project=fairtable   # once per account and region
```

## Deploy and destroy
```bash
npx cdk diff                      # always look first
npx cdk deploy FairTableData
BUDGET_EMAIL=you@example.com npx cdk deploy FairTableBudget
npx cdk destroy FairTableData     # the table and its data are removed
```
The bootstrap stack `CDKToolkit` is not part of the app and `cdk destroy` leaves it. Remove it only when no CDK app will be deployed in this account and region any more (empty its bucket first). The scripted teardown for the whole phase is plan task P2-8.

## Running the tests against the real table
boto3 needs `awscrt` to read `aws login` credentials, and that package may be blocked on your PC (it is on a Windows machine with Application Control). `scripts/aws_credential_process.py` hands the same credentials to boto3 through a throw-away config file, and boto3 refreshes them by itself (nothing is written to your real `~/.aws/config`):
```bash
printf '[profile ft]
credential_process = "%s" "%s"
region = us-east-1
' "$(which python)" "$PWD/scripts/aws_credential_process.py" > /tmp/ft-aws-config
export AWS_CONFIG_FILE=/tmp/ft-aws-config AWS_PROFILE=ft
export DDB_ENDPOINT_URL= AWS_REGION=us-east-1     # an empty endpoint means the real service
export FT_TEST_SHARED_TABLE=1                      # one table for the run, emptied after every test
python -m pytest tests/integration/test_store_ddb.py tests/integration/test_write_pipeline.py tests/integration/test_reservation_hold.py
```
Without `FT_TEST_SHARED_TABLE=1` every test creates and deletes its own table (25 to 45 s each on the real service). Even shared, expect about 30 s per test from a far-away PC: each SDK call took about 1 s from Vietnam to us-east-1 (see the friction log). `test_ddb_spike.py` is a Phase 0 spike for DynamoDB Local only (dummy credentials); do not run it on AWS. If a run is killed, delete the leftover `ft-test-*` tables.

## One command instead of the steps above
`python infra/aws_ctl.py status | up | seed | down` (see the docstring of `infra/aws_ctl.py` and `docs/aws-integration.md`). `down` is a dry run unless `--yes` is given.
