"""
Storage Stack — S3, DynamoDB, Aurora Serverless v2.
"""
import aws_cdk as cdk
from aws_cdk import (
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_rds as rds,
    aws_ec2 as ec2,
    RemovalPolicy,
)
from constructs import Construct


class StorageStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ═══════════════════════════════════
        #  S3 Buckets
        # ═══════════════════════════════════

        self.raw_bucket = s3.Bucket(
            self, "RawSignals",
            bucket_name=f"scg-raw-signals-{cdk.Aws.ACCOUNT_ID}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INTELLIGENT_TIERING,
                            transition_after=cdk.Duration.days(30),
                        )
                    ]
                )
            ],
        )

        self.knowledge_bucket = s3.Bucket(
            self, "KnowledgeBase",
            bucket_name=f"scg-knowledge-base-{cdk.Aws.ACCOUNT_ID}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.audit_bucket = s3.Bucket(
            self, "AuditTrail",
            bucket_name=f"scg-audit-trail-{cdk.Aws.ACCOUNT_ID}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            object_lock_enabled=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.dashboard_bucket = s3.Bucket(
            self, "DashboardAssets",
            bucket_name=f"scg-dashboard-{cdk.Aws.ACCOUNT_ID}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            website_index_document="index.html",
            website_error_document="index.html",
            public_read_access=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ═══════════════════════════════════
        #  DynamoDB Tables
        # ═══════════════════════════════════

        self.signals_table = dynamodb.Table(
            self, "SignalsTable",
            table_name="SCG_Signals",
            partition_key=dynamodb.Attribute(
                name="signal_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
        )
        self.signals_table.add_global_secondary_index(
            index_name="by-type",
            partition_key=dynamodb.Attribute(
                name="signal_type", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
        )

        self.risk_table = dynamodb.Table(
            self, "RiskAssessments",
            table_name="SCG_RiskAssessments",
            partition_key=dynamodb.Attribute(
                name="assessment_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
        )
        self.risk_table.add_global_secondary_index(
            index_name="by-risk-score",
            partition_key=dynamodb.Attribute(
                name="status", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="risk_score", type=dynamodb.AttributeType.NUMBER
            ),
        )

        self.suppliers_table = dynamodb.Table(
            self, "SuppliersTable",
            table_name="SCG_Suppliers",
            partition_key=dynamodb.Attribute(
                name="supplier_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ═══════════════════════════════════
        #  Aurora Serverless v2 (PostgreSQL)
        # ═══════════════════════════════════

        self.aurora_cluster = rds.DatabaseCluster(
            self, "SupplierHistoryDB",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_4,
            ),
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=4,
            writer=rds.ClusterInstance.serverless_v2("writer"),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            default_database_name="supply_chain_ghost",
            credentials=rds.Credentials.from_generated_secret("ghost_admin"),
            storage_encrypted=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── Outputs ──
        cdk.CfnOutput(self, "RawBucketArn", value=self.raw_bucket.bucket_arn)
        cdk.CfnOutput(self, "AuditBucketArn", value=self.audit_bucket.bucket_arn)
        cdk.CfnOutput(self, "SignalsTableArn", value=self.signals_table.table_arn)
        cdk.CfnOutput(self, "AuroraEndpoint",
                       value=self.aurora_cluster.cluster_endpoint.hostname)
