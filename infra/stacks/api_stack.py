"""
API Stack — API Gateway + Lambda handlers + Cognito auth.
"""
import os
import aws_cdk as cdk
from aws_cdk import (
    aws_apigateway as apigw,
    aws_lambda as _lambda,
    aws_ec2 as ec2,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_cognito as cognito,
    aws_iam as iam,
    Duration,
)
from constructs import Construct


class ApiStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        user_pool: cognito.UserPool,
        signals_table: dynamodb.Table,
        risk_table: dynamodb.Table,
        audit_bucket: s3.Bucket,
        reasoning_lambda: _lambda.Function,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # ── API Handler Lambda ──
        api_handler = _lambda.Function(
            self, "ApiHandler",
            function_name="SCG-ApiHandler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="api_handler.handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api")
            ),
            environment={
                "SIGNALS_TABLE": signals_table.table_name,
                "RISK_TABLE": risk_table.table_name,
                "AUDIT_BUCKET": audit_bucket.bucket_name,
                "REASONING_FN_NAME": reasoning_lambda.function_name,
                "POWERTOOLS_SERVICE_NAME": "api",
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            timeout=Duration.seconds(30),
            memory_size=512,
            tracing=_lambda.Tracing.ACTIVE,
        )
        signals_table.grant_read_data(api_handler)
        risk_table.grant_read_write_data(api_handler)
        audit_bucket.grant_read(api_handler)
        reasoning_lambda.grant_invoke(api_handler)

        # EventBridge permission for simulation triggers
        api_handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=["*"],
            )
        )
        # Allow invoking approval handler
        api_handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:function:SCG-ApprovalHandler"],
            )
        )

        # ── Chat Lambda ("Ask the Ghost") ──
        chat_handler = _lambda.Function(
            self, "ChatHandler",
            function_name="SCG-ChatHandler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="chat_handler.handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "api")
            ),
            environment={
                "RISK_TABLE": risk_table.table_name,
                "NOVA_MODEL_ID": "amazon.nova-lite-v1:0",
                "POWERTOOLS_SERVICE_NAME": "chat",
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            timeout=Duration.seconds(120),
            memory_size=1024,
            tracing=_lambda.Tracing.ACTIVE,
        )
        risk_table.grant_read_data(chat_handler)
        chat_handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:Retrieve"],
                resources=["*"],
            )
        )

        # ── API Gateway ──
        self.api = apigw.RestApi(
            self, "GhostApi",
            rest_api_name="SupplyChainGhost-API",
            description="Supply Chain Ghost REST API",
            deploy_options=apigw.StageOptions(
                stage_name="v1",
                tracing_enabled=True,
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=True,
                metrics_enabled=True,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization", "X-Api-Key"],
            ),
        )

        # Cognito Authorizer
        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "GhostAuthorizer",
            cognito_user_pools=[user_pool],
        )

        auth_kwargs = dict(
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # ── Routes ──
        api_integration = apigw.LambdaIntegration(api_handler)
        chat_integration = apigw.LambdaIntegration(chat_handler)

        # /signals
        signals = self.api.root.add_resource("signals")
        signals.add_method("GET", api_integration, **auth_kwargs)

        # /risks
        risks = self.api.root.add_resource("risks")
        risks.add_method("GET", api_integration, **auth_kwargs)
        risk_detail = risks.add_resource("{assessment_id}")
        risk_detail.add_method("GET", api_integration, **auth_kwargs)

        # /risks/{id}/approve
        approve = risk_detail.add_resource("approve")
        approve.add_method("POST", api_integration, **auth_kwargs)

        # /simulate
        simulate = self.api.root.add_resource("simulate")
        simulate.add_method("POST", api_integration, **auth_kwargs)

        # /chat
        chat = self.api.root.add_resource("chat")
        chat.add_method("POST", chat_integration, **auth_kwargs)

        # /dashboard (KPIs)
        dashboard = self.api.root.add_resource("dashboard")
        dashboard.add_method("GET", api_integration, **auth_kwargs)

        # /audit
        audit = self.api.root.add_resource("audit")
        audit.add_method("GET", api_integration, **auth_kwargs)

        # ── Outputs ──
        cdk.CfnOutput(self, "ApiUrl", value=self.api.url)
