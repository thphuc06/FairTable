"""The single DynamoDB table, same key schema as `server/store/table.py`."""

from aws_cdk import RemovalPolicy, Stack, Tags
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

GSI_NAMES = ("GSI1", "GSI2")


def _string_attr(name: str) -> dynamodb.Attribute:
    return dynamodb.Attribute(name=name, type=dynamodb.AttributeType.STRING)


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, table_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.table = dynamodb.Table(
            self,
            "Table",
            table_name=table_name,
            partition_key=_string_attr("PK"),
            sort_key=_string_attr("SK"),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            # Encrypted at rest with an AWS-owned key (always on, no charge, no KMS requests).
            encryption=dynamodb.TableEncryption.DEFAULT,
            # Demo table, recreated from the seed script: destroyed with the stack (D-004).
            removal_policy=RemovalPolicy.DESTROY,
            deletion_protection=False,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=False
            ),
        )
        for index in GSI_NAMES:
            self.table.add_global_secondary_index(
                index_name=index,
                partition_key=_string_attr(f"{index}PK"),
                sort_key=_string_attr(f"{index}SK"),
                projection_type=dynamodb.ProjectionType.ALL,
            )
        Tags.of(self).add("project", "fairtable")
