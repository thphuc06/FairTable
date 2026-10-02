"""The single DynamoDB table, same key schema as `server/store/table.py`, and the bucket for Fair Drop audits."""

from aws_cdk import RemovalPolicy, Stack, Tags
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
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
            # Offers (D-059) carry a `ttl`: DynamoDB removes the old ones. The expiry is also checked on every read.
            time_to_live_attribute="ttl",
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=False
            ),
        )
        # A copy of each Fair Drop audit (D-062): private, encrypted, TLS only. Destroyed with the stack, objects
        # included (a small custom resource empties it first). The name carries the account and region at deploy time.
        self.audit_bucket = s3.Bucket(
            self,
            "AuditBucket",
            bucket_name=f"fairtable-audit-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        for index in GSI_NAMES:
            self.table.add_global_secondary_index(
                index_name=index,
                partition_key=_string_attr(f"{index}PK"),
                sort_key=_string_attr(f"{index}SK"),
                projection_type=dynamodb.ProjectionType.ALL,
            )
        Tags.of(self).add("project", "fairtable")
