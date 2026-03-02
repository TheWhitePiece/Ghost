"""
ApprovalHandler Lambda — Human-in-the-Loop approval via Step Functions callback.

Manages the approval workflow for automated purchase orders.
"""
import os
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DDB = boto3.resource("dynamodb")
SFN = boto3.client("stepfunctions")
S3 = boto3.client("s3")

RISK_TABLE = os.environ["RISK_TABLE"]
AUDIT_BUCKET = os.environ["AUDIT_BUCKET"]


def _store_approval_audit(assessment_id: str, action: str, approver: str, details: dict):
    """Store approval decision in audit trail."""
    timestamp = datetime.now(timezone.utc).isoformat()
    key = f"audit/{assessment_id}/approval_{timestamp}.json"
    S3.put_object(
        Bucket=AUDIT_BUCKET,
        Key=key,
        Body=json.dumps({
            "assessment_id": assessment_id,
            "action": action,
            "approver": approver,
            "timestamp": timestamp,
            "details": details,
        }, default=str),
        ContentType="application/json",
    )


def handler(event, context):
    """
    Handles two flows:
    
    1. INITIAL: Called by Step Functions with a task token (WAIT_FOR_TASK_TOKEN).
       Stores the token and waits for human approval.
       
    2. CALLBACK: Called by API Gateway when human approves/rejects.
       Sends success/failure to Step Functions to resume workflow.
    """
    logger.info("ApprovalHandler invoked: %s", json.dumps(event, default=str))

    # ── Flow 1: Step Functions sends task token ──
    if "taskToken" in event:
        task_token = event["taskToken"]
        assessment = event.get("assessment", {})
        assessment_id = assessment.get("assessment_id", 
                        assessment.get("execution", {}).get("assessment_id", "unknown"))

        # Store token for later callback
        risk_table = DDB.Table(RISK_TABLE)
        try:
            risk_table.update_item(
                Key={
                    "assessment_id": assessment_id,
                    "created_at": assessment.get("created_at", ""),
                },
                UpdateExpression="SET task_token = :t, #st = :status, awaiting_approval_since = :ts",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":t": task_token,
                    ":status": "AWAITING_APPROVAL",
                    ":ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as e:
            logger.error("Failed to store task token: %s", str(e))

        logger.info("Approval requested for assessment %s", assessment_id)
        return {
            "status": "AWAITING_APPROVAL",
            "assessment_id": assessment_id,
            "message": "Pending human review",
        }

    # ── Flow 2: API callback with approval/rejection ──
    if "approval_action" in event:
        assessment_id = event.get("assessment_id", "")
        action = event["approval_action"]  # "APPROVE" or "REJECT"
        approver = event.get("approver", "unknown")
        comments = event.get("comments", "")

        # Fetch task token
        risk_table = DDB.Table(RISK_TABLE)
        try:
            response = risk_table.query(
                KeyConditionExpression="assessment_id = :aid",
                ExpressionAttributeValues={":aid": assessment_id},
                Limit=1,
            )
            items = response.get("Items", [])
            if not items:
                return {"status": "ERROR", "message": "Assessment not found"}

            item = items[0]
            task_token = item.get("task_token", "")

            if not task_token:
                return {"status": "ERROR", "message": "No pending approval for this assessment"}

        except Exception as e:
            logger.error("Failed to fetch assessment: %s", str(e))
            return {"status": "ERROR", "message": str(e)}

        # Send callback to Step Functions
        try:
            if action == "APPROVE":
                SFN.send_task_success(
                    taskToken=task_token,
                    output=json.dumps({
                        "approval_status": "APPROVED",
                        "approver": approver,
                        "comments": comments,
                        "approved_at": datetime.now(timezone.utc).isoformat(),
                    }),
                )
                new_status = "APPROVED"
            else:
                SFN.send_task_failure(
                    taskToken=task_token,
                    error="REJECTED",
                    cause=comments or "Rejected by human approver",
                )
                new_status = "REJECTED"

        except Exception as e:
            logger.error("Failed to send Step Functions callback: %s", str(e))
            return {"status": "ERROR", "message": f"Step Functions callback failed: {str(e)}"}

        # Update risk table
        risk_table.update_item(
            Key={
                "assessment_id": assessment_id,
                "created_at": item.get("created_at", ""),
            },
            UpdateExpression=(
                "SET #st = :status, approved_by = :approver, "
                "approval_comments = :comments, approval_timestamp = :ts "
                "REMOVE task_token"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":status": new_status,
                ":approver": approver,
                ":comments": comments,
                ":ts": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Audit trail
        _store_approval_audit(assessment_id, action, approver, {
            "comments": comments,
            "assessment_risk_score": float(item.get("risk_score", 0)),
        })

        logger.info("Assessment %s: %s by %s", assessment_id, new_status, approver)
        return {
            "status": new_status,
            "assessment_id": assessment_id,
            "approver": approver,
        }

    return {"status": "ERROR", "message": "Invalid event format"}
