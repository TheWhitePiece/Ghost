"""
Auth Stack — Amazon Cognito User Pool + App Client.
"""
import aws_cdk as cdk
from aws_cdk import (
    aws_cognito as cognito,
)
from constructs import Construct


class AuthStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        self.user_pool = cognito.UserPool(
            self, "GhostUserPool",
            user_pool_name="SupplyChainGhostUsers",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        self.user_pool_client = cognito.UserPoolClient(
            self, "GhostWebClient",
            user_pool=self.user_pool,
            user_pool_client_name="ghost-web-client",
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                    implicit_code_grant=True,
                ),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.PROFILE],
                callback_urls=["https://localhost:3000/callback"],
                logout_urls=["https://localhost:3000/"],
            ),
            prevent_user_existence_errors=True,
        )

        # Admin group
        cognito.CfnUserPoolGroup(
            self, "AdminGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="Admins",
            description="Supply chain operations administrators",
        )

        # Approver group
        cognito.CfnUserPoolGroup(
            self, "ApproverGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="Approvers",
            description="Users who can approve PO switches",
        )

        # ── Outputs ──
        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId",
                       value=self.user_pool_client.user_pool_client_id)
