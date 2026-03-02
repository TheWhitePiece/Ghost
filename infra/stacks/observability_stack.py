"""
Observability Stack — CloudWatch Dashboards, X-Ray, Alarms.
"""
import aws_cdk as cdk
from aws_cdk import (
    aws_cloudwatch as cw,
    aws_apigateway as apigw,
    aws_lambda as _lambda,
    aws_logs as logs,
)
from constructs import Construct


class ObservabilityStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        api: apigw.RestApi,
        lambdas: dict,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # ── Model Invocation Logs ──
        model_log_group = logs.LogGroup(
            self, "ModelInvocationLogs",
            log_group_name="/aws/bedrock/model-invocations",
            retention=logs.RetentionDays.SIX_MONTHS,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # ── CloudWatch Dashboard ──
        dashboard = cw.Dashboard(
            self, "GhostDashboard",
            dashboard_name="SupplyChainGhost-Operations",
        )

        # API metrics
        dashboard.add_widgets(
            cw.TextWidget(width=24, height=1, markdown="# 🚢 Supply Chain Ghost — Operations Dashboard"),
            cw.GraphWidget(
                title="API Latency (p50/p90/p99)",
                width=12, height=6,
                left=[
                    api.metric_latency(statistic="p50"),
                    api.metric_latency(statistic="p90"),
                    api.metric_latency(statistic="p99"),
                ],
            ),
            cw.GraphWidget(
                title="API Requests & Errors",
                width=12, height=6,
                left=[api.metric_count()],
                right=[
                    api.metric_server_error(),
                    api.metric_client_error(),
                ],
            ),
        )

        # Lambda metrics
        reasoning_fn = lambdas.get("reasoning")
        if reasoning_fn:
            dashboard.add_widgets(
                cw.GraphWidget(
                    title="Reasoning Engine — Duration",
                    width=12, height=6,
                    left=[
                        reasoning_fn.metric_duration(statistic="Average"),
                        reasoning_fn.metric_duration(statistic="p99"),
                    ],
                ),
                cw.GraphWidget(
                    title="Reasoning Engine — Errors",
                    width=12, height=6,
                    left=[
                        reasoning_fn.metric_errors(),
                        reasoning_fn.metric_throttles(),
                    ],
                ),
            )

        # Custom KPI widgets
        dashboard.add_widgets(
            cw.TextWidget(width=24, height=1, markdown="## 📊 KPIs"),
            cw.SingleValueWidget(
                title="Detection Latency (avg ms)",
                width=6, height=4,
                metrics=[cw.Metric(
                    namespace="SupplyChainGhost",
                    metric_name="DetectionLatency",
                    statistic="Average",
                )],
            ),
            cw.SingleValueWidget(
                title="Action Latency (avg ms)",
                width=6, height=4,
                metrics=[cw.Metric(
                    namespace="SupplyChainGhost",
                    metric_name="ActionLatency",
                    statistic="Average",
                )],
            ),
            cw.SingleValueWidget(
                title="Risk Prediction Accuracy",
                width=6, height=4,
                metrics=[cw.Metric(
                    namespace="SupplyChainGhost",
                    metric_name="PredictionAccuracy",
                    statistic="Average",
                )],
            ),
            cw.SingleValueWidget(
                title="Cost Savings ($)",
                width=6, height=4,
                metrics=[cw.Metric(
                    namespace="SupplyChainGhost",
                    metric_name="CostSavings",
                    statistic="Sum",
                )],
            ),
        )

        # ── Alarms ──
        cw.Alarm(
            self, "HighErrorRate",
            metric=api.metric_server_error(),
            threshold=10,
            evaluation_periods=2,
            alarm_description="High 5xx error rate on Ghost API",
        )
