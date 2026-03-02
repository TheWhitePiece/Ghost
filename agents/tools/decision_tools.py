"""
Decision tools for the Strands Agent.
"""
import json
import boto3
from strands import tool

LAMBDA_CLIENT = boto3.client("lambda")


@tool
def make_decision(assessment_json: str) -> str:
    """
    Run the cost-based decision engine on a risk assessment.
    Calculates delay cost vs switch cost and recommends action.
    
    Args:
        assessment_json: JSON string of the assessed risk (post-verification).
    
    Returns:
        Decision including action (MONITOR/SWITCH_SUPPLIER/ESCALATE), cost breakdown, and supplier comparison.
    """
    try:
        assessment = json.loads(assessment_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid assessment JSON"})

    try:
        response = LAMBDA_CLIENT.invoke(
            FunctionName="SCG-DecisionEngine",
            InvocationType="RequestResponse",
            Payload=json.dumps({"reasoning": assessment}, default=str),
        )
        result = json.loads(response["Payload"].read())
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
