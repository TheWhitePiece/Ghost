"""
Execution tools for the Strands Agent.
"""
import json
import boto3
from strands import tool

LAMBDA_CLIENT = boto3.client("lambda")


@tool
def execute_po(decision_json: str) -> str:
    """
    Execute a purchase order using Nova Act browser automation.
    Falls back to API mode if browser automation fails.
    
    Args:
        decision_json: JSON string of the decision (must include recommended_supplier and proposed_order).
    
    Returns:
        Execution result with status, method used, screenshots, and PO details.
    """
    try:
        decision = json.loads(decision_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid decision JSON"})

    try:
        response = LAMBDA_CLIENT.invoke(
            FunctionName="SCG-NovaActExecutor",
            InvocationType="RequestResponse",
            Payload=json.dumps({"decision": decision}, default=str),
        )
        result = json.loads(response["Payload"].read())
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def request_approval(assessment_id: str, approver: str = "dashboard_user", comments: str = "") -> str:
    """
    Submit a PO for human approval or process an approval/rejection.
    
    Args:
        assessment_id: The assessment ID tied to the pending PO.
        approver: Username of the approver.
        comments: Optional comments for the approval.
    
    Returns:
        Approval status.
    """
    try:
        response = LAMBDA_CLIENT.invoke(
            FunctionName="SCG-ApprovalHandler",
            InvocationType="RequestResponse",
            Payload=json.dumps({
                "approval_action": "APPROVE",
                "assessment_id": assessment_id,
                "approver": approver,
                "comments": comments,
            }),
        )
        result = json.loads(response["Payload"].read())
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
