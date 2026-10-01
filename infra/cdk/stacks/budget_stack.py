"""Spend alerts (plan task P2-1).

One monthly cost budget with absolute-value alerts on actual spend. The defaults suit the hackathon
credit ($150, alerts at $50, $100 and $140); a small account sets `BUDGET_LIMIT_USD` and `BUDGET_ALERTS`
(for example 5 and "1,3,4.5"). The name is `fairtable-cap-<limit>usd`, so it can never be mistaken for a
budget the developer made by hand. Credits are
excluded (`IncludeCredit` defaults to true, which would keep the spend near zero while the
credit lasts and the alerts silent). A cost budget without actions is free (AWS Budgets price
list, `BudgetsUsage`, $0.00 per budget-day).
"""

from aws_cdk import Stack, Tags
from aws_cdk import aws_budgets as budgets
from constructs import Construct

LIMIT_USD = 150
ALERT_AT_USD = (50, 100, 140)
NAME_PREFIX = "fairtable-cap-"


def budget_name(limit_usd: float) -> str:
    return f"{NAME_PREFIX}{limit_usd:g}usd"


def check_alerts(limit_usd: float, alerts_usd: list[float]) -> list[float]:
    """Alerts must be positive, below the limit and in rising order, or the budget is not what it says."""
    if limit_usd <= 0 or not alerts_usd:
        raise ValueError("the budget needs a positive limit and at least one alert")
    if any(a <= 0 or a >= limit_usd for a in alerts_usd) or sorted(set(alerts_usd)) != list(alerts_usd):
        raise ValueError(f"alerts {alerts_usd} must rise and stay below the limit {limit_usd}")
    return list(alerts_usd)


class BudgetStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, email: str, limit_usd: float = LIMIT_USD,
                 alerts_usd: tuple[float, ...] = ALERT_AT_USD, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        alerts = check_alerts(limit_usd, list(alerts_usd))

        budgets.CfnBudget(
            self,
            "CreditBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=budget_name(limit_usd),
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=limit_usd, unit="USD"),
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
                for amount in alerts
            ],
        )
        Tags.of(self).add("project", "fairtable")
