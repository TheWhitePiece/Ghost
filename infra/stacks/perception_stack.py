"""
Perception Stack — EventBridge + Collector Lambdas.
"""
import os
import aws_cdk as cdk
from aws_cdk import (
    aws_lambda as _lambda,
    aws_events as events,
    aws_events_targets as targets,
    aws_ec2 as ec2,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    Duration,
)
from constructs import Construct

LAMBDA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "collectors")


class PerceptionStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        raw_bucket: s3.Bucket,
        signals_table: dynamodb.Table,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # Shared Lambda layer (bundled from shared utils)
        deps_layer = _lambda.LayerVersion(
            self, "CollectorDeps",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "shared")
            ),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            description="Shared deps for collector lambdas",
        )

        # Common environment variables
        common_env = {
            "RAW_BUCKET": raw_bucket.bucket_name,
            "SIGNALS_TABLE": signals_table.table_name,
            "POWERTOOLS_SERVICE_NAME": "perception",
        }

        # ── Collector Factory ──
        collectors = {
            "NewsCollector": {
                "handler": "news_collector.handler",
                "description": "Scrapes RSS feeds for supply chain keywords",
                "timeout": 120,
                "memory": 512,
            },
            "WeatherCollector": {
                "handler": "weather_collector.handler",
                "description": "Pulls storm and regional weather data",
                "timeout": 60,
                "memory": 256,
            },
            "PortCongestionCollector": {
                "handler": "port_congestion_collector.handler",
                "description": "Fetches shipping congestion metrics",
                "timeout": 120,
                "memory": 512,
            },
            "CommodityPriceCollector": {
                "handler": "commodity_price_collector.handler",
                "description": "Tracks raw material price changes",
                "timeout": 60,
                "memory": 256,
            },
            "SatelliteMetadataCollector": {
                "handler": "satellite_metadata_collector.handler",
                "description": "Retrieves port satellite image metadata",
                "timeout": 180,
                "memory": 1024,
            },
        }

        self.collector_fns = {}
        for name, config in collectors.items():
            fn = _lambda.Function(
                self, name,
                function_name=f"SCG-{name}",
                runtime=_lambda.Runtime.PYTHON_3_12,
                handler=config["handler"],
                code=_lambda.Code.from_asset(LAMBDA_DIR),
                layers=[deps_layer],
                environment=common_env,
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
                timeout=Duration.seconds(config["timeout"]),
                memory_size=config["memory"],
                tracing=_lambda.Tracing.ACTIVE,
                description=config["description"],
            )
            raw_bucket.grant_write(fn)
            signals_table.grant_write_data(fn)
            self.collector_fns[name] = fn

        # ── EventBridge: Scheduled Polling (every 30 min) ──
        schedule_rule = events.Rule(
            self, "ScheduledCollection",
            rule_name="SCG-ScheduledCollection",
            schedule=events.Schedule.rate(Duration.minutes(30)),
            description="Trigger all collectors every 30 minutes",
        )
        for name, fn in self.collector_fns.items():
            schedule_rule.add_target(targets.LambdaFunction(fn))

        # ── EventBridge: External Webhook Bus ──
        self.webhook_bus = events.EventBus(
            self, "WebhookBus",
            event_bus_name="SCG-WebhookBus",
        )

        webhook_rule = events.Rule(
            self, "WebhookAlerts",
            event_bus=self.webhook_bus,
            rule_name="SCG-WebhookAlerts",
            event_pattern=events.EventPattern(
                source=["scg.webhook"],
                detail_type=["weather.alert", "shipping.alert", "disruption.manual"],
            ),
        )
        # Route webhook events to relevant collectors
        webhook_rule.add_target(
            targets.LambdaFunction(self.collector_fns["WeatherCollector"])
        )
        webhook_rule.add_target(
            targets.LambdaFunction(self.collector_fns["PortCongestionCollector"])
        )

        # ── Manual Disruption Trigger (simulated via EventBridge) ──
        manual_rule = events.Rule(
            self, "ManualDisruption",
            event_bus=self.webhook_bus,
            rule_name="SCG-ManualDisruption",
            event_pattern=events.EventPattern(
                source=["scg.dashboard"],
                detail_type=["disruption.simulate"],
            ),
        )
        for fn in self.collector_fns.values():
            manual_rule.add_target(targets.LambdaFunction(fn))

        # ── Outputs ──
        cdk.CfnOutput(self, "WebhookBusArn", value=self.webhook_bus.event_bus_arn)
