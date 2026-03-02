/**
 * AWS Amplify configuration for Cognito + API Gateway.
 * Values are injected at build time or fetched from CloudFormation outputs.
 */
const awsConfig = {
  Auth: {
    Cognito: {
      userPoolId: process.env.REACT_APP_USER_POOL_ID || 'us-east-1_PLACEHOLDER',
      userPoolClientId: process.env.REACT_APP_USER_POOL_CLIENT_ID || 'PLACEHOLDER',
      signUpVerificationMethod: 'code',
    },
  },
  API: {
    REST: {
      GhostAPI: {
        endpoint: process.env.REACT_APP_API_URL || 'https://api.example.com/v1',
        region: process.env.REACT_APP_AWS_REGION || 'us-east-1',
      },
    },
  },
};

export default awsConfig;
