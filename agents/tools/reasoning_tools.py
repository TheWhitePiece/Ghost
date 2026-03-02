"""
Reasoning tools for the Strands Agent.
"""
import json
import boto3
from strands import tool

LAMBDA_CLIENT = boto3.client("lambda")
DDB = boto3.resource("dynamodb")


@tool
def analyze_risk(signals_json: str = "") -> str:
    """
    Invoke the Nova 2 Lite reasoning engine to analyze current signals.
    
    Args:
        signals_json: Optional JSON string of pre-fetched signals. If empty, engine fetches recent signals.
    
    Returns:
        Complete risk assessment including score, confidence, delay estimate, and recommendations.
    """
    payload = {}
    if signals_json:
        try:
            payload["signals"] = json.loads(signals_json)
        except json.JSONDecodeError:
            pass

    try:
        response = LAMBDA_CLIENT.invoke(
            FunctionName="SCG-ReasoningEngine",
            InvocationType="RequestResponse",
            Payload=json.dumps(payload, default=str),
        )
        result = json.loads(response["Payload"].read())
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def get_assessment(assessment_id: str) -> str:
    """
    Retrieve a specific risk assessment by ID.
    
    Args:
        assessment_id: The assessment ID (e.g., "risk-20260301120000")
    
    Returns:
        Full assessment details including reasoning, verification, and decision data.
    """
    import os
    table = DDB.Table(os.environ.get("RISK_TABLE", "SCG_RiskAssessments"))

    try:
        response = table.query(
            KeyConditionExpression="assessment_id = :aid",
            ExpressionAttributeValues={":aid": assessment_id},
            Limit=1,
        )
        items = response.get("Items", [])
        if items:
            return json.dumps(items[0], default=str)
        return json.dumps({"error": "Assessment not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})
