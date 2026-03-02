"""
VPC Stack — Network isolation for Supply Chain Ghost.
Public + Private + Isolated subnets with security groups.
"""
import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
)
from constructs import Construct


class VpcStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── VPC with 3 subnet tiers ──
        self.vpc = ec2.Vpc(
            self, "GhostVPC",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # ── Security Groups ──

        # Lambda / Strands runtime
        self.lambda_sg = ec2.SecurityGroup(
            self, "LambdaSG",
            vpc=self.vpc,
            description="Lambda + Strands agents",
            allow_all_outbound=True,
        )

        # Nova Act browser sandbox — outbound HTTPS only
        self.nova_act_sg = ec2.SecurityGroup(
            self, "NovaActSG",
            vpc=self.vpc,
            description="Nova Act browser automation sandbox",
            allow_all_outbound=False,
        )
        self.nova_act_sg.add_egress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(443),
            "Allow outbound HTTPS only",
        )

        # Aurora database
        self.db_sg = ec2.SecurityGroup(
            self, "AuroraSG",
            vpc=self.vpc,
            description="Aurora Serverless",
            allow_all_outbound=False,
        )
        self.db_sg.add_ingress_rule(
            self.lambda_sg,
            ec2.Port.tcp(5432),
            "Allow Lambda to Aurora on port 5432",
        )

        # VPC Endpoints for AWS services (cost optimization + security)
        self.vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )
        self.vpc.add_gateway_endpoint(
            "DynamoEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB,
        )
        self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
        )
        self.vpc.add_interface_endpoint(
            "BedrockEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService("bedrock-runtime"),
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
        )

        # ── Outputs ──
        cdk.CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
