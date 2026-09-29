# scripts/

- `seed.py` – creates the DynamoDB table if needed and loads the demo data (3 restaurants, 14 days of slots including a hot Saturday table at Ember Grill and a Friday Fair-Drop seat at Sakura Counter, and two standing mandates). Reads `TABLE_NAME`, `DDB_ENDPOINT_URL`, `AWS_REGION`; `--reset` drops the table first. Safe to run twice.
