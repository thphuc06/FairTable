"""P3-12 on the real account: one notice reaches the SNS topic (opt-in, after ``cdk deploy FairTableNotify``).

``pytest -m aws tests/aws/test_sns_notice.py``. It publishes one short message through ``SnsNotifier`` with the real
client. What it settles that the fake client cannot: the topic exists, the caller may publish, and the subject
passes SNS's own checks. Delivery to the developer's inbox is seen by the developer (the e-mail subscription must
have been confirmed once); nothing here reads a mailbox.
"""

import boto3
import pytest
from botocore.exceptions import ClientError

from server.notify import SnsNotifier

pytestmark = pytest.mark.aws
STACK = "FairTableNotify"


@pytest.fixture(scope="module")
def topic_arn():
    try:
        boto3.client("cloudformation").describe_stacks(StackName=STACK)
    except ClientError as e:
        pytest.skip(f"{STACK} is not deployed: {e}")
    sns = boto3.client("sns")
    arns = [t["TopicArn"] for t in sns.list_topics()["Topics"] if t["TopicArn"].endswith(":fairtable-notices")]
    if not arns:
        pytest.skip("the stack has no fairtable-notices topic")
    return arns[0]


def test_a_notice_is_accepted_by_the_topic(topic_arn):
    sns = boto3.client("sns")
    sent = []
    real_publish = sns.publish

    def publish(**kwargs):
        response = real_publish(**kwargs)
        sent.append(response["MessageId"])
        return response

    sns.publish = publish
    SnsNotifier(sns, topic_arn).notify(
        "unused-sub", subject="A table opened up (test)",
        body="This is a test notice from the FairTable AWS tests. Nothing was booked.",
    )
    assert len(sent) == 1, "the topic did not accept the notice (see the log for the error)"
