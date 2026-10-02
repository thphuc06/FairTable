"""One SNS topic for waitlist and Fair Drop notices (plan task P3-12, decision D-054).

The developer subscribes their own e-mail address once (`NOTIFY_EMAIL` at deploy time, never in the repository);
AWS e-mails a confirmation link that has to be clicked before anything is delivered. There is no per-user address:
this stands in for a real notification service. A standard topic with an e-mail subscription costs nothing while
idle; the SNS price list (2026-09-15) gives the first 1,000 e-mail notifications a month free (docs/DECISIONS.md D-054).
"""

from aws_cdk import Stack, Tags
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct

TOPIC_NAME = "fairtable-notices"


class NotifyStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, email: str | None = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.topic = sns.Topic(self, "Notices", topic_name=TOPIC_NAME, display_name="FairTable")
        if email:
            self.topic.add_subscription(subscriptions.EmailSubscription(email))
        Tags.of(self).add("project", "fairtable")
