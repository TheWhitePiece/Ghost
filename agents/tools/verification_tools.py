"""
Verification tools for the Strands Agent.
"""
import json
import boto3
from strands import tool

LAMBDA_CLIENT = boto3.client("lambda")


@tool
def verify_assessment(assessment_json: str) -> str:
    """
    Invoke Nova 2 Omni multimodal verification on a risk assessment.
    Analyzes satellite imagery and documents to cross-check reasoning.
    
    Args:
        assessment_json: JSON string of the risk assessment to verify.
    
    Returns:
        Verification result including visual analysis, confidence, and self-correction status.
    """
    try:
        assessment = json.loads(assessment_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid assessment JSON"})

    try:
        response = LAMBDA_CLIENT.invoke(
            FunctionName="SCG-VerificationEngine",
            InvocationType="RequestResponse",
            Payload=json.dumps({"reasoning": assessment}, default=str),
        )
        result = json.loads(response["Payload"].read())
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
