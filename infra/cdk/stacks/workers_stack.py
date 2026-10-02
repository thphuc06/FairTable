"""The background workers (plan task P3-15, decision D-062): a clock for the lazy routines of the server.

One Lambda (`workers.handler.handler`, the same zip as the Runtime, arm64, Python 3.12) runs the hold sweeper and
the Fair Drop allocator (`server/workers.py`). EventBridge Scheduler calls it once a minute (rate(1 minute)); the
tools keep working without it, because the same routines also run lazily inside requests. The function reads and
writes the table, publishes notices to the SNS topic and writes audit copies to the bucket, nothing else.

A tick lasts well under the minute; if one ever overlapped the next, both are safe (conditional writes).
The account's Lambda concurrency limit is 10, so no concurrency is reserved for it.

Prices checked 2026-10-02 on the official price files (us-east-1): Scheduler $1.00 per million invocations after
14 million free a month, Lambda arm64 $0.20 per million requests and $0.0000133334 per GB-second after the free tier;
about 43,200 invocations a month are far inside both.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_sns as sns
from constructs import Construct

HANDLER = "workers.handler.handler"
FUNCTION_NAME = "FairTableWorkers"
SCHEDULE_NAME = "FairTableWorkersEveryMinute"
SKIP_ENV = {"AWS_REGION", "MCP_ALLOWED_HOSTS"}  # Lambda sets the region itself; the hosts belong to the server


class WorkersStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table: dynamodb.ITable,
        environment: dict[str, str],
        package_path: Path,
        notify_topic: sns.ITopic | None = None,
        audit_bucket: s3.IBucket | None = None,
        every_minutes: int = 1,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env = {k: v for k, v in environment.items() if k not in SKIP_ENV}
        log_group = logs.LogGroup(
            self, "Logs", log_group_name=f"/aws/lambda/{FUNCTION_NAME}", retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY)
        function = lambda_.Function(
            self,
            "Function",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=HANDLER,
            code=lambda_.Code.from_asset(str(package_path)),
            timeout=Duration.seconds(55),  # one tick must end before the next one starts
            memory_size=512,
            environment=env,
            function_name=FUNCTION_NAME,
            log_group=log_group,
            description="FairTable hold sweeper and Fair Drop allocator (runs every minute)",
        )
        # What the store does: point reads and queries, conditional writes (also the ones inside TransactWriteItems).
        function.add_to_role_policy(iam.PolicyStatement(
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem",
                     "dynamodb:DeleteItem", "dynamodb:ConditionCheckItem"],
            resources=[table.table_arn, f"{table.table_arn}/index/*"]))
        if notify_topic is not None:
            function.add_to_role_policy(iam.PolicyStatement(actions=["sns:Publish"], resources=[notify_topic.topic_arn]))
            function.add_environment("NOTIFY_TOPIC_ARN", notify_topic.topic_arn)
        if audit_bucket is not None:
            function.add_to_role_policy(iam.PolicyStatement(
                actions=["s3:PutObject"], resources=[audit_bucket.arn_for_objects("drops/*")]))
            function.add_environment("AUDIT_BUCKET", audit_bucket.bucket_name)

        invoke_role = iam.Role(
            self,
            "SchedulerRole",
            assumed_by=iam.ServicePrincipal(
                "scheduler.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": self.account}}),
        )
        invoke_role.add_to_policy(iam.PolicyStatement(actions=["lambda:InvokeFunction"], resources=[function.function_arn]))
        rate = f"rate({every_minutes} minute{'s' if every_minutes != 1 else ''})"
        scheduler.CfnSchedule(
            self,
            "Schedule",
            name=SCHEDULE_NAME,
            description="Runs the FairTable workers: release expired holds, draw due Fair Drops",
            schedule_expression=rate,
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=function.function_arn,
                role_arn=invoke_role.role_arn,
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(maximum_retry_attempts=0),
            ),
            state="ENABLED",
        )
        self.function = function
        CfnOutput(self, "FunctionName", value=function.function_name)
        CfnOutput(self, "ScheduleName", value=SCHEDULE_NAME)
        Tags.of(self).add("project", "fairtable")
