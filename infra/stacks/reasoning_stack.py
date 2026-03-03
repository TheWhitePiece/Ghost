"""
Reasoning Stack — Nova 2 Lite + Bedrock Knowledge Base + Memory.
"""
import os
import aws_cdk as cdk
from aws_cdk import (
    aws_lambda as _lambda,
    aws_ec2 as ec2,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_iam as iam,
    Duration,
)
from constructs import Construct


class ReasoningStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        signals_table: dynamodb.Table,
        risk_table: dynamodb.Table,
        knowledge_bucket: s3.Bucket,
        suppliers_table: dynamodb.Table = None,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # ── Bedrock Permissions Policy ──
        bedrock_policy = iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
                "bedrock:Retrieve",
                "bedrock:RetrieveAndGenerate",
                "bedrock:GetFoundationModel",
                "bedrock:ListFoundationModels",
                "bedrock:CreateMemory",
                "bedrock:GetMemory",
                "bedrock:UpdateMemory",
                "bedrock:ListMemories",
            ],
            resources=["*"],
        )

        # ── Reasoning Lambda (Nova 2 Lite Extended Thinking) ──
        self.reasoning_fn = _lambda.Function(
            self, "ReasoningEngine",
            function_name="SCG-ReasoningEngine",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="reasoning_engine.handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "reasoning")
            ),
            environment={
                "SIGNALS_TABLE": signals_table.table_name,
                "RISK_TABLE": risk_table.table_name,
                "KNOWLEDGE_BUCKET": knowledge_bucket.bucket_name,
                "SUPPLIERS_TABLE": suppliers_table.table_name if suppliers_table else "SCG_Suppliers",
                "KNOWLEDGE_BASE_ID": "",  # Set after running seed_knowledge_base.py
                "NOVA_MODEL_ID": "amazon.nova-lite-v1:0",
                "POWERTOOLS_SERVICE_NAME": "reasoning",
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            timeout=Duration.seconds(300),
            memory_size=2048,
            tracing=_lambda.Tracing.ACTIVE,
            description="Nova Lite reasoning with extended thinking",
        )
        self.reasoning_fn.add_to_role_policy(bedrock_policy)
        signals_table.grant_read_data(self.reasoning_fn)
        risk_table.grant_read_write_data(self.reasoning_fn)
        knowledge_bucket.grant_read(self.reasoning_fn)
        if suppliers_table:
            suppliers_table.grant_read_data(self.reasoning_fn)

        # ── Verification Lambda (Nova 2 Omni Multimodal) ──
        self.verification_fn = _lambda.Function(
            self, "VerificationEngine",
            function_name="SCG-VerificationEngine",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="verification_engine.handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "verification")
            ),
            environment={
                "RISK_TABLE": risk_table.table_name,
                "RAW_BUCKET": knowledge_bucket.bucket_name,
                "NOVA_OMNI_MODEL_ID": "amazon.nova-premier-v1:0",
                "POWERTOOLS_SERVICE_NAME": "verification",
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            timeout=Duration.seconds(300),
            memory_size=3072,
            tracing=_lambda.Tracing.ACTIVE,
            description="Nova Premier multimodal verification",
        )
        self.verification_fn.add_to_role_policy(bedrock_policy)
        risk_table.grant_read_write_data(self.verification_fn)

        # ── Decision Engine Lambda ──
        self.decision_fn = _lambda.Function(
            self, "DecisionEngine",
            function_name="SCG-DecisionEngine",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="decision_engine.handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "decision")
            ),
            environment={
                "RISK_TABLE": risk_table.table_name,
                "SUPPLIERS_TABLE": suppliers_table.table_name if suppliers_table else "SCG_Suppliers",
                "POWERTOOLS_SERVICE_NAME": "decision",
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            timeout=Duration.seconds(60),
            memory_size=512,
            tracing=_lambda.Tracing.ACTIVE,
            description="Cost-based decision engine",
        )
        risk_table.grant_read_write_data(self.decision_fn)
        if suppliers_table:
            suppliers_table.grant_read_write_data(self.decision_fn)

        # ── Outputs ──
        cdk.CfnOutput(self, "ReasoningFnArn", value=self.reasoning_fn.function_arn)
        cdk.CfnOutput(self, "VerificationFnArn", value=self.verification_fn.function_arn)
