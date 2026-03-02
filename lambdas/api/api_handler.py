"""
API Handler Lambda — REST API for the Supply Chain Ghost dashboard.
Handles: signals, risks, approvals, simulations, dashboard KPIs, audit.
"""
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DDB = boto3.resource("dynamodb")
S3 = boto3.client("s3")
LAMBDA_CLIENT = boto3.client("lambda")
EVENTS = boto3.client("events")

SIGNALS_TABLE = os.environ["SIGNALS_TABLE"]
RISK_TABLE = os.environ["RISK_TABLE"]
AUDIT_BUCKET = os.environ["AUDIT_BUCKET"]
REASONING_FN_NAME = os.environ.get("REASONING_FN_NAME", "SCG-ReasoningEngine")


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _json_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
        },
        "body": json.dumps(body, cls=DecimalEncoder, default=str),
    }


def _get_signals(params: dict) -> dict:
    """Fetch recent signals with optional filtering."""
    table = DDB.Table(SIGNALS_TABLE)
    signal_type = params.get("type")
    severity = params.get("severity")
    hours = int(params.get("hours", "24"))
    limit = int(params.get("limit", "50"))

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    try:
        if signal_type:
            response = table.query(
                IndexName="by-type",
                KeyConditionExpression="signal_type = :t AND #ts >= :cutoff",
                ExpressionAttributeNames={"#ts": "timestamp"},
                ExpressionAttributeValues={
                    ":t": signal_type,
                    ":cutoff": cutoff,
                },
                Limit=limit,
                ScanIndexForward=False,
            )
        else:
            response = table.scan(
                FilterExpression="#ts >= :cutoff",
                ExpressionAttributeNames={"#ts": "timestamp"},
                ExpressionAttributeValues={":cutoff": cutoff},
                Limit=limit,
            )
    except Exception as e:
        logger.warning("Signal query failed, falling back to scan: %s", str(e))
        response = table.scan(Limit=limit)

    items = response.get("Items", [])
    if severity:
        items = [i for i in items if i.get("severity") == severity]

    return {
        "signals": sorted(items, key=lambda x: x.get("timestamp", ""), reverse=True),
        "count": len(items),
        "filter": {"type": signal_type, "severity": severity, "hours": hours},
    }


def _get_risks(params: dict) -> dict:
    """Fetch risk assessments."""
    table = DDB.Table(RISK_TABLE)
    status = params.get("status")
    limit = int(params.get("limit", "20"))

    try:
        if status:
            response = table.query(
                IndexName="by-risk-score",
                KeyConditionExpression="#st = :status",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={":status": status},
                Limit=limit,
                ScanIndexForward=False,
            )
        else:
            response = table.scan(Limit=limit)
    except Exception as e:
        logger.warning("Risk query failed, falling back to scan: %s", str(e))
        response = table.scan(Limit=limit)

    items = response.get("Items", [])
    # Sort by risk_score descending
    items = sorted(items, key=lambda x: float(x.get("risk_score", 0)), reverse=True)

    return {
        "assessments": items[:limit],
        "count": len(items),
    }


def _get_risk_detail(assessment_id: str) -> dict:
    """Fetch detailed risk assessment."""
    table = DDB.Table(RISK_TABLE)
    try:
        response = table.query(
            KeyConditionExpression="assessment_id = :aid",
            ExpressionAttributeValues={":aid": assessment_id},
            ScanIndexForward=False,  # most recent first
            Limit=1,
        )
        items = response.get("Items", [])
        if items:
            return items[0]
    except Exception as e:
        logger.warning("Query failed for %s, trying scan: %s", assessment_id, str(e))
        # Fallback to scan if query fails
        try:
            response = table.scan(
                FilterExpression="assessment_id = :aid",
                ExpressionAttributeValues={":aid": assessment_id},
                Limit=1,
            )
            items = response.get("Items", [])
            if items:
                return items[0]
        except Exception:
            pass
    return None


def _approve_risk(assessment_id: str, body: dict) -> dict:
    """Forward approval to the approval handler."""
    payload = {
        "approval_action": body.get("action", "APPROVE"),
        "assessment_id": assessment_id,
        "approver": body.get("approver", "dashboard_user"),
        "comments": body.get("comments", body.get("notes", "")),
    }

    approval_fn = os.environ.get("APPROVAL_FN_NAME", "SCG-ApprovalHandler")

    try:
        response = LAMBDA_CLIENT.invoke(
            FunctionName=approval_fn,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )
        result = json.loads(response["Payload"].read())
    except Exception as e:
        logger.error("Approval handler invocation failed: %s", str(e))
        # Fallback: update status directly in DynamoDB
        table = DDB.Table(RISK_TABLE)
        new_status = "APPROVED" if payload["approval_action"] == "APPROVE" else "REJECTED"
        try:
            # Get the item to find its sort key
            query_resp = table.query(
                KeyConditionExpression="assessment_id = :aid",
                ExpressionAttributeValues={":aid": assessment_id},
                Limit=1,
            )
            items = query_resp.get("Items", [])
            if items:
                table.update_item(
                    Key={
                        "assessment_id": assessment_id,
                        "created_at": items[0]["created_at"],
                    },
                    UpdateExpression="SET #st = :status, approved_by = :approver, approval_comments = :comments, approved_at = :ts",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={
                        ":status": new_status,
                        ":approver": payload["approver"],
                        ":comments": payload["comments"],
                        ":ts": datetime.now(timezone.utc).isoformat(),
                    },
                )
                result = {"status": new_status, "message": f"Assessment {new_status.lower()} (direct update)"}
            else:
                result = {"status": "ERROR", "message": "Assessment not found"}
        except Exception as e2:
            logger.error("Direct DynamoDB update also failed: %s", str(e2))
            result = {"status": "ERROR", "message": str(e)}

    return result


def _simulate_disruption(body: dict) -> dict:
    """Trigger a manual disruption simulation."""
    disruption_type = body.get("type") or body.get("disruption_type", "general")
    region = body.get("region", "Gulf Coast")
    severity = body.get("severity", "HIGH")
    description = body.get("description") or body.get("details", "Manual disruption simulation")

    errors = []

    # Send event to EventBridge (best-effort — may fail if bus doesn't exist or no permission)
    try:
        EVENTS.put_events(
            Entries=[{
                "Source": "scg.dashboard",
                "DetailType": "disruption.simulate",
                "EventBusName": "SCG-WebhookBus",
                "Detail": json.dumps({
                    "type": disruption_type,
                    "region": region,
                    "severity": severity,
                    "description": description,
                    "simulated_at": datetime.now(timezone.utc).isoformat(),
                }),
            }]
        )
    except Exception as e:
        logger.warning("EventBridge put_events failed (non-fatal): %s", str(e))
        errors.append(f"EventBridge: {str(e)[:100]}")

    # Trigger reasoning directly (this is the important one)
    reasoning_triggered = False
    try:
        LAMBDA_CLIENT.invoke(
            FunctionName=REASONING_FN_NAME,
            InvocationType="Event",  # async
            Payload=json.dumps({
                "source": "simulation",
                "details": {
                    "type": disruption_type,
                    "region": region,
                    "severity": severity,
                    "description": description,
                },
            }),
        )
        reasoning_triggered = True
    except Exception as e:
        logger.error("Reasoning Lambda invoke failed: %s", str(e))
        errors.append(f"Reasoning: {str(e)[:100]}")

    result = {
        "status": "SIMULATION_TRIGGERED" if reasoning_triggered else "PARTIALLY_TRIGGERED",
        "type": disruption_type,
        "region": region,
        "severity": severity,
    }
    if errors:
        result["warnings"] = errors
    return result


def _get_dashboard_kpis() -> dict:
    """Compute KPI metrics for the dashboard."""
    # Signals stats
    signals_table = DDB.Table(SIGNALS_TABLE)
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    signals = signals_table.scan(
        FilterExpression="#ts >= :cutoff",
        ExpressionAttributeNames={"#ts": "timestamp"},
        ExpressionAttributeValues={":cutoff": cutoff_24h},
        Select="COUNT",
    )

    # Risk stats
    risk_table = DDB.Table(RISK_TABLE)
    risks = risk_table.scan(Select="ALL_ATTRIBUTES", Limit=100)
    risk_items = risks.get("Items", [])

    active_risks = [r for r in risk_items if r.get("status") not in ("CLOSED", "APPROVED", "REJECTED")]
    pending_approvals = [r for r in risk_items if r.get("status") in ("AWAITING_APPROVAL", "pending_approval")]

    avg_risk_score = 0
    if risk_items:
        scores = [float(r.get("risk_score", 0)) for r in risk_items if r.get("risk_score")]
        avg_risk_score = sum(scores) / len(scores) if scores else 0

    total_savings = sum(
        float(r.get("decision", {}).get("cost_analysis", {}).get("net_savings_usd", 0))
        for r in risk_items
        if r.get("status") == "APPROVED"
    )

    return {
        "kpis": {
            "signals_24h": signals.get("Count", 0),
            "active_risks": len(active_risks),
            "pending_approvals": len(pending_approvals),
            "avg_risk_score": round(avg_risk_score, 1),
            "total_assessments": len(risk_items),
            "total_cost_savings_usd": round(total_savings, 2),
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _get_audit_trail(params: dict) -> dict:
    """List audit trail entries from S3."""
    assessment_id = params.get("assessment_id", "")
    prefix = f"audit/{assessment_id}/" if assessment_id else "audit/"
    limit = int(params.get("limit", "50"))

    response = S3.list_objects_v2(
        Bucket=AUDIT_BUCKET,
        Prefix=prefix,
        MaxKeys=limit,
    )
    events = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        # Try to read S3 object content for structured event data
        try:
            obj_resp = S3.get_object(Bucket=AUDIT_BUCKET, Key=key)
            event_data = json.loads(obj_resp["Body"].read().decode("utf-8"))
            events.append(event_data)
        except Exception:
            # Fallback: construct event from S3 key metadata
            parts = key.replace("audit/", "").rstrip("/").split("/")
            events.append({
                "key": key,
                "action": parts[-1].split("_")[0] if parts else "unknown",
                "assessment_id": parts[0] if len(parts) > 1 else "",
                "timestamp": obj["LastModified"].isoformat(),
                "details": f"Audit entry: {key}",
                "actor": "system",
            })
    return {"events": events, "audit_entries": events, "count": len(events)}


def handler(event, context):
    """
    Main API router. Routes based on path and method.
    """
    logger.info("API request: %s %s", event.get("httpMethod"), event.get("path"))

    method = event.get("httpMethod", "GET")
    path = event.get("path", "")
    params = event.get("queryStringParameters") or {}
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except json.JSONDecodeError:
            return _json_response(400, {"error": "Invalid JSON body"})

    path_params = event.get("pathParameters") or {}

    try:
        # /signals
        if path == "/signals" and method == "GET":
            return _json_response(200, _get_signals(params))

        # /risks
        elif path == "/risks" and method == "GET":
            return _json_response(200, _get_risks(params))

        # /risks/{assessment_id}
        elif "/risks/" in path and method == "GET" and "approve" not in path:
            assessment_id = path_params.get("assessment_id", path.split("/")[-1])
            detail = _get_risk_detail(assessment_id)
            if detail:
                return _json_response(200, detail)
            return _json_response(404, {"error": "Assessment not found"})

        # /risks/{assessment_id}/approve
        elif "/approve" in path and method == "POST":
            assessment_id = path_params.get("assessment_id", path.split("/")[-2])
            result = _approve_risk(assessment_id, body)
            return _json_response(200, result)

        # /simulate
        elif path == "/simulate" and method == "POST":
            result = _simulate_disruption(body)
            return _json_response(200, result)

        # /dashboard
        elif path == "/dashboard" and method == "GET":
            return _json_response(200, _get_dashboard_kpis())

        # /audit
        elif path == "/audit" and method == "GET":
            return _json_response(200, _get_audit_trail(params))

        else:
            return _json_response(404, {"error": "Not found", "path": path})

    except Exception as e:
        logger.error("API error: %s", str(e), exc_info=True)
        return _json_response(500, {"error": "Internal server error", "detail": str(e)})
