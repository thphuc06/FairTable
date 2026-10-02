# scripts/

- `seed.py` – creates the DynamoDB table if needed and loads the demo data (3 restaurants, 14 days of slots including a hot Saturday table at Ember Grill and a Friday Fair-Drop seat at Sakura Counter, and one Fair Drop per Friday seat with a freshly drawn secret seed whose commitment is public). Reads `TABLE_NAME`, `DDB_ENDPOINT_URL`, `AWS_REGION`; `--reset` drops the table first. Safe to run twice.

- `SEED_PROVIDER=kms python scripts/seed.py` draws the secret seed of each Fair Drop with AWS KMS `GenerateRandom` instead of this machine (AWS profile; the default is local).
- `voice_demo.ps1` / `voice_demo.sh`: read the settings of the deployed AWS stacks and start the web app with the voice page (`/voice`). See the README, "Voice demo".
