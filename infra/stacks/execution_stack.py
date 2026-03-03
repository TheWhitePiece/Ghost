"""
Execution Stack — Nova Act automation + Step Functions orchestration.
"""
import os
import json
import aws_cdk as cdk
from aws_cdk import (
    aws_lambda as _lambda,
    aws_ec2 as ec2,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_secretsmanager as secretsmanager,
    Duration,
)
from constructs import Construct


class ExecutionStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.Vpc,
        risk_table: dynamodb.Table,
        audit_bucket: s3.Bucket,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # ── ERP Credentials Secret ──
        self.erp_secret = secretsmanager.Secret(
            self, "ERPCredentials",
            secret_name="scg/erp-credentials",
            description="ERP system login credentials for Nova Act",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({"username": "ghost_bot"}),
                generate_string_key="password",
                exclude_punctuation=True,
            ),
        )

        # ── Nova Act Execution Lambda ──
        # For API-only mode: use _lambda.Function (ZIP, no Docker needed).
        # For Nova Act browser mode: switch to _lambda.DockerImageFunction
        # with _lambda.DockerImageCode.from_image_asset(...) and the Dockerfile
        # in lambdas/execution/. Requires Docker Desktop running locally.
        self.nova_act_fn = _lambda.Function(
            self, "NovaActExecutor",
            function_name="SCG-NovaActExecutor",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="nova_act_executor.handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "execution")
            ),
            environment={
                "RISK_TABLE": risk_table.table_name,
                "AUDIT_BUCKET": audit_bucket.bucket_name,
                "ERP_SECRET_ARN": self.erp_secret.secret_arn,
                "POWERTOOLS_SERVICE_NAME": "execution",
                "EXECUTION_MODE": "api",  # Change to "nova_act" when using Docker image
                "ERP_URL": "",  # MUST be overridden at deploy time or via console
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            timeout=Duration.seconds(600),
            memory_size=4096,
            tracing=_lambda.Tracing.ACTIVE,
            description="ERP execution handler (API mode; switch to Docker for Nova Act)",
        )
        self.erp_secret.grant_read(self.nova_act_fn)
        risk_table.grant_read_write_data(self.nova_act_fn)
        audit_bucket.grant_write(self.nova_act_fn)
        self.nova_act_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=["*"],
            )
        )

        # ── Human Approval Lambda ──
        self.approval_fn = _lambda.Function(
            self, "ApprovalHandler",
            function_name="SCG-ApprovalHandler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="approval_handler.handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambdas", "execution")
            ),
            environment={
                "RISK_TABLE": risk_table.table_name,
                "AUDIT_BUCKET": audit_bucket.bucket_name,
                "POWERTOOLS_SERVICE_NAME": "approval",
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            timeout=Duration.seconds(30),
            memory_size=256,
            tracing=_lambda.Tracing.ACTIVE,
        )
        risk_table.grant_read_write_data(self.approval_fn)
        audit_bucket.grant_write(self.approval_fn)

        # ══════════════════════════════════════
        #  Step Functions Workflow
        # ══════════════════════════════════════

        # Import reasoning/verification functions by name
        reasoning_fn = _lambda.Function.from_function_name(
            self, "ReasoningRef", "SCG-ReasoningEngine"
        )
        verification_fn = _lambda.Function.from_function_name(
            self, "VerificationRef", "SCG-VerificationEngine"
        )
        decision_fn = _lambda.Function.from_function_name(
            self, "DecisionRef", "SCG-DecisionEngine"
        )

        # Step 1: Reasoning
        reason_step = tasks.LambdaInvoke(
            self, "Reason",
            lambda_function=reasoning_fn,
            payload_response_only=True,
            result_path="$.reasoning",
        )

        # Step 2: Check if verification needed
        needs_verification = sfn.Choice(
            self, "NeedsVerification?"
        )

        # Step 3: Verification
        verify_step = tasks.LambdaInvoke(
            self, "Verify",
            lambda_function=verification_fn,
            payload_response_only=True,
            result_path="$.verification",
        )

        # Step 4: Decision
        decide_step = tasks.LambdaInvoke(
            self, "Decide",
            lambda_function=decision_fn,
            payload_response_only=True,
            result_path="$.decision",
        )

        # Step 5: Check if action needed
        needs_action = sfn.Choice(self, "NeedsAction?")

        # Step 6: Execute
        execute_step = tasks.LambdaInvoke(
            self, "Execute",
            lambda_function=self.nova_act_fn,
            payload_response_only=True,
            result_path="$.execution",
        )

        # Step 7: Human approval (callback pattern)
        wait_for_approval = tasks.LambdaInvoke(
            self, "AwaitApproval",
            lambda_function=self.approval_fn,
            integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            payload=sfn.TaskInput.from_object({
                "taskToken": sfn.JsonPath.task_token,
                "assessment.$": "$",
            }),
            result_path="$.approval",
            heartbeat=Duration.hours(24),
        )

        # Step 8: Final close
        close_step = sfn.Pass(self, "Close", comment="Workflow complete")

        # Escalation
        escalate_step = sfn.Pass(
            self, "HumanEscalation",
            comment="Escalate to human — confidence too low or action failed",
        )

        # ── Wire the workflow ──
        definition = (
            reason_step
            .next(needs_verification
                .when(
                    sfn.Condition.number_greater_than("$.reasoning.risk_score", 60),
                    verify_step.next(decide_step)
                )
                .otherwise(decide_step)
            )
        )

        decide_step.next(
            needs_action
            .when(
                sfn.Condition.string_equals("$.decision.action", "SWITCH_SUPPLIER"),
                execute_step.next(wait_for_approval).next(close_step),
            )
            .when(
                sfn.Condition.string_equals("$.decision.action", "ESCALATE"),
                escalate_step,
            )
            .otherwise(close_step)
        )

        self.state_machine = sfn.StateMachine(
            self, "GhostWorkflow",
            state_machine_name="SCG-GhostWorkflow",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(48),
            tracing_enabled=True,
        )

        # ── Outputs ──
        cdk.CfnOutput(self, "StateMachineArn",
                       value=self.state_machine.state_machine_arn)
