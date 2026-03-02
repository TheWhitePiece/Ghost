#!/usr/bin/env python3
"""
Supply Chain Ghost — CDK Application Entry Point.
Deploys all infrastructure stacks in dependency order.
"""
import os
import aws_cdk as cdk
from stacks.vpc_stack import VpcStack
from stacks.storage_stack import StorageStack
from stacks.auth_stack import AuthStack
from stacks.perception_stack import PerceptionStack
from stacks.reasoning_stack import ReasoningStack
from stacks.execution_stack import ExecutionStack
from stacks.api_stack import ApiStack
from stacks.dashboard_stack import DashboardStack
from stacks.observability_stack import ObservabilityStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

project = app.node.try_get_context("project_name") or "SupplyChainGhost"

# --- 1. VPC & Networking ---
vpc_stack = VpcStack(app, f"{project}-VPC", env=env)

# --- 2. Storage (S3, DynamoDB, Aurora) ---
storage_stack = StorageStack(app, f"{project}-Storage", vpc=vpc_stack.vpc, env=env)

# --- 3. Authentication (Cognito) ---
auth_stack = AuthStack(app, f"{project}-Auth", env=env)

# --- 4. Perception Layer (Collectors + EventBridge) ---
perception_stack = PerceptionStack(
    app, f"{project}-Perception",
    vpc=vpc_stack.vpc,
    raw_bucket=storage_stack.raw_bucket,
    signals_table=storage_stack.signals_table,
    env=env,
)

# --- 5. Reasoning Layer (Nova 2 Lite + RAG + Memory) ---
reasoning_stack = ReasoningStack(
    app, f"{project}-Reasoning",
    vpc=vpc_stack.vpc,
    signals_table=storage_stack.signals_table,
    risk_table=storage_stack.risk_table,
    knowledge_bucket=storage_stack.knowledge_bucket,
    env=env,
)

# --- 6. Execution Layer (Nova Act + Step Functions) ---
execution_stack = ExecutionStack(
    app, f"{project}-Execution",
    vpc=vpc_stack.vpc,
    risk_table=storage_stack.risk_table,
    audit_bucket=storage_stack.audit_bucket,
    env=env,
)

# --- Cross-stack dependencies for function name lookups ---
execution_stack.add_dependency(reasoning_stack)

# --- 7. API Layer ---
api_stack = ApiStack(
    app, f"{project}-API",
    vpc=vpc_stack.vpc,
    user_pool=auth_stack.user_pool,
    signals_table=storage_stack.signals_table,
    risk_table=storage_stack.risk_table,
    audit_bucket=storage_stack.audit_bucket,
    reasoning_lambda=reasoning_stack.reasoning_fn,
    env=env,
)

# --- 8. Dashboard (CloudFront + S3) ---
dashboard_stack = DashboardStack(
    app, f"{project}-Dashboard",
    api=api_stack.api,
    user_pool=auth_stack.user_pool,
    user_pool_client=auth_stack.user_pool_client,
    env=env,
)

# --- 9. Observability (X-Ray, CloudWatch Dashboards) ---
observability_stack = ObservabilityStack(
    app, f"{project}-Observability",
    api=api_stack.api,
    lambdas={
        "reasoning": reasoning_stack.reasoning_fn,
    },
    env=env,
)

app.synth()
