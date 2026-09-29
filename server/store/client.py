"""Connection settings for the store. Nothing account-specific: table, endpoint and region come from
the environment (``TABLE_NAME``, ``DDB_ENDPOINT_URL``, ``AWS_REGION``).

With ``DDB_ENDPOINT_URL`` set (DynamoDB Local) the client uses dummy credentials, so the local
profile needs no AWS account. Without it the normal boto3 credential chain is used; that path is
only exercised in the AWS profile and is scaffold-only until the developer wires AWS (D-016).
"""

import os
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config


@dataclass(frozen=True)
class StoreConfig:
    table_name: str
    endpoint_url: str | None = None
    region: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "StoreConfig":
        env = os.environ if env is None else env
        endpoint = env.get("DDB_ENDPOINT_URL") or None
        region = env.get("AWS_REGION") or ("us-east-1" if endpoint else None)
        return cls(env.get("TABLE_NAME", "fairtable-dev"), endpoint, region)


def make_client(config: StoreConfig) -> Any:
    kwargs: dict[str, Any] = {
        "region_name": config.region,
        "config": Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=3,
                         read_timeout=10),
    }
    if config.endpoint_url:
        kwargs.update(
            endpoint_url=config.endpoint_url,
            aws_access_key_id="local",  # DynamoDB Local ignores credentials
            aws_secret_access_key="local",
        )
    return boto3.client("dynamodb", **kwargs)
