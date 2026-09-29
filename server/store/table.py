"""Table lifecycle: one single table with two overloaded global secondary indexes."""

from typing import Any

from botocore.exceptions import ClientError


def _attr(name: str) -> dict[str, str]:
    return {"AttributeName": name, "AttributeType": "S"}


def table_exists(client: Any, name: str) -> bool:
    try:
        client.describe_table(TableName=name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def create_table(client: Any, name: str) -> None:
    client.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[_attr(a) for a in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": index,
                "KeySchema": [
                    {"AttributeName": f"{index}PK", "KeyType": "HASH"},
                    {"AttributeName": f"{index}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for index in ("GSI1", "GSI2")
        ],
    )
    client.get_waiter("table_exists").wait(TableName=name)


def ensure_table(client: Any, name: str) -> bool:
    """Create the table if missing. Returns True when it was created."""
    if table_exists(client, name):
        return False
    create_table(client, name)
    return True


def delete_table(client: Any, name: str) -> None:
    try:
        client.delete_table(TableName=name)
        client.get_waiter("table_not_exists").wait(TableName=name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
