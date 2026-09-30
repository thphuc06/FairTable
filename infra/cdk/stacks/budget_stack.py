"""Spend alerts for the hackathon credit (plan task P2-1).

One cost budget of $150 with three absolute-value alerts on actual spend. Credits are
excluded (`IncludeCredit` defaults to true, which would keep the spend near zero while the
credit lasts and the alerts silent). A cost budget without actions is free (AWS Budgets price
list, `BudgetsUsage`, $0.00 per budget-day).
"""

from aws_cdk import Stack, Tags
from aws_cdk import aws_budgets as budgets
from constructs import Construct

LIMIT_USD = 150
ALERT_AT_USD = (50, 100, 140)


class BudgetStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, email: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        budgets.CfnBudget(
            self,
            "CreditBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="fairtable-150usd",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=LIMIT_USD, unit="USD"),
                cost_types=budgets.CfnBudget.CostTypesProperty(include_credit=False),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=amount,
                        threshold_type="ABSOLUTE_VALUE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=email)
                    ],
                )
                for amount in ALERT_AT_USD
            ],
        )
        Tags.of(self).add("project", "fairtable")
