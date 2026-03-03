"""
NovaActExecutor Lambda — Browser automation for ERP purchase order creation.

Supports two execution modes:
  1. Nova Act browser automation (requires Docker container image with Chromium)
  2. ERP REST API fallback (works in standard Lambda, requires ERP_URL + credentials)

Set ERP_URL to your real ERP endpoint (SAP, Oracle NetSuite, etc.) before deploy.
For Nova Act mode, deploy as a container image using the included Dockerfile.

Env vars:
    RISK_TABLE       — DynamoDB risk assessments table
    AUDIT_BUCKET     — S3 bucket for audit records / screenshots
    ERP_SECRET_ARN   — Secrets Manager ARN with {username, password, api_key}
    ERP_URL          — Base URL of the ERP system (REQUIRED for real operation)
    EXECUTION_MODE   — "nova_act" or "api" (default: "api")
"""
import os
import json
import logging
import base64
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3 = boto3.client("s3")
DDB = boto3.resource("dynamodb")
SECRETS = boto3.client("secretsmanager")
CW = boto3.client("cloudwatch")

RISK_TABLE = os.environ["RISK_TABLE"]
AUDIT_BUCKET = os.environ["AUDIT_BUCKET"]
ERP_SECRET_ARN = os.environ["ERP_SECRET_ARN"]

MAX_RETRIES = 3
ERP_BASE_URL = os.environ.get("ERP_URL", "")
EXECUTION_MODE = os.environ.get("EXECUTION_MODE", "api")


def _get_erp_credentials() -> dict:
    """Retrieve ERP credentials from Secrets Manager."""
    try:
        response = SECRETS.get_secret_value(SecretId=ERP_SECRET_ARN)
        return json.loads(response["SecretString"])
    except ClientError as e:
        logger.error("Failed to get ERP credentials: %s", str(e))
        raise


def _store_screenshot(screenshot_b64: str, assessment_id: str, step: str) -> str:
    """Store a screenshot in the S3 audit bucket."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    key = f"screenshots/{assessment_id}/{step}_{timestamp}.png"
    S3.put_object(
        Bucket=AUDIT_BUCKET,
        Key=key,
        Body=base64.b64decode(screenshot_b64),
        ContentType="image/png",
    )
    return key


def _store_audit_record(assessment_id: str, action: str, details: dict):
    """Store an immutable audit record."""
    timestamp = datetime.now(timezone.utc).isoformat()
    key = f"audit/{assessment_id}/{action}_{timestamp}.json"
    S3.put_object(
        Bucket=AUDIT_BUCKET,
        Key=key,
        Body=json.dumps({
            "assessment_id": assessment_id,
            "action": action,
            "timestamp": timestamp,
            "details": details,
        }, default=str),
        ContentType="application/json",
    )


def _execute_with_nova_act(decision: dict, credentials: dict) -> dict:
    """
    Execute ERP automation using Nova Act.
    
    Nova Act navigates the ERP web interface to create a purchase order draft.
    In production, this uses the nova-act SDK for browser automation.
    """
    try:
        # Import Nova Act SDK
        from nova_act import NovaAct

        assessment_id = decision.get("assessment_id", "unknown")
        supplier = decision.get("recommended_supplier", {})
        order = decision.get("proposed_order", {})

        steps_completed = []
        screenshots = []

        with NovaAct(starting_page=ERP_BASE_URL) as nova:
            # Step 1: Login
            logger.info("Nova Act: Logging into ERP")
            nova.act(
                f"Log into the ERP system with username '{credentials['username']}' "
                f"and password '{credentials['password']}'"
            )
            steps_completed.append("login")

            # Step 2: Navigate to Procurement
            logger.info("Nova Act: Navigating to procurement module")
            nova.act("Click on the 'Procurement' or 'Purchase Orders' menu item in the navigation")
            steps_completed.append("navigate_procurement")

            # Step 3: Create New PO
            logger.info("Nova Act: Creating new purchase order")
            nova.act("Click the 'Create New Purchase Order' or 'New PO' button")
            steps_completed.append("new_po")

            # Step 4: Select Supplier
            logger.info("Nova Act: Selecting supplier")
            nova.act(
                f"In the supplier field, search for and select '{supplier.get('full_name', supplier.get('name', ''))}'"
            )
            steps_completed.append("select_supplier")

            # Step 5: Add Line Items
            logger.info("Nova Act: Adding line items")
            for sku in decision.get("affected_skus", ["SKU-001"]):
                nova.act(
                    f"Add a line item: SKU '{sku}', Quantity: {order.get('quantity', 5000)}, "
                    f"Unit Price: ${order.get('unit_price', 0):.2f}"
                )
            steps_completed.append("add_items")

            # Step 6: Set Delivery Details
            logger.info("Nova Act: Setting delivery details")
            nova.act(
                f"Set delivery method to 'Expedited Air Freight' "
                f"and expected delivery to {order.get('expected_delivery_days', 10)} days from today"
            )
            steps_completed.append("delivery_details")

            # Step 7: Screenshot
            logger.info("Nova Act: Taking screenshot of draft PO")
            screenshot = nova.act("Take a screenshot of the current purchase order form")
            if hasattr(screenshot, 'screenshot') and screenshot.screenshot:
                ss_key = _store_screenshot(
                    base64.b64encode(screenshot.screenshot).decode(),
                    assessment_id, "po_draft"
                )
                screenshots.append(ss_key)
            steps_completed.append("screenshot")

            # Step 8: Save Draft (do NOT submit — human approval needed)
            logger.info("Nova Act: Saving draft")
            nova.act("Click 'Save as Draft' to save the purchase order without submitting")
            steps_completed.append("save_draft")

        return {
            "status": "SUCCESS",
            "method": "nova_act",
            "steps_completed": steps_completed,
            "screenshots": screenshots,
            "po_details": {
                "supplier": supplier.get("name", ""),
                "total_cost": order.get("total_cost", 0),
                "quantity": order.get("quantity", 0),
                "status": "DRAFT",
            },
        }

    except ImportError:
        logger.warning("Nova Act SDK not available, falling back to API mode")
        return None
    except Exception as e:
        logger.error("Nova Act execution failed: %s", str(e))
        return None


def _execute_with_api_fallback(decision: dict, credentials: dict) -> dict:
    """
    Create PO via ERP REST API (works in standard Lambda).
    Requires ERP_URL to be set to a real ERP endpoint.
    """
    import requests

    if not ERP_BASE_URL or "example.com" in ERP_BASE_URL:
        return {
            "status": "FAILED",
            "method": "api_fallback",
            "error": (
                "ERP_URL is not configured. Set the ERP_URL environment variable "
                "to your real ERP endpoint (e.g. SAP, Oracle NetSuite, Coupa)."
            ),
        }

    assessment_id = decision.get("assessment_id", "unknown")
    supplier = decision.get("recommended_supplier", {})
    order = decision.get("proposed_order", {})

    try:
        # Authenticate
        auth_response = requests.post(
            f"{ERP_BASE_URL}/api/auth/login",
            json={
                "username": credentials["username"],
                "password": credentials["password"],
            },
            timeout=10,
        )
        auth_response.raise_for_status()
        token = auth_response.json().get("token", "")

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Create PO draft
        po_payload = {
            "supplier_id": supplier.get("name", ""),
            "supplier_name": supplier.get("full_name", ""),
            "status": "DRAFT",
            "line_items": [
                {
                    "sku": sku,
                    "quantity": order.get("quantity", 5000),
                    "unit_price": order.get("unit_price", 0),
                }
                for sku in decision.get("affected_skus", ["SKU-001"])
            ],
            "delivery_method": "EXPEDITED_AIR",
            "expected_delivery_days": order.get("expected_delivery_days", 10),
            "notes": f"Auto-generated by Supply Chain Ghost. Assessment: {assessment_id}",
        }

        po_response = requests.post(
            f"{ERP_BASE_URL}/api/purchase-orders",
            json=po_payload,
            headers=headers,
            timeout=15,
        )
        po_response.raise_for_status()
        po_data = po_response.json()

        return {
            "status": "SUCCESS",
            "method": "api_fallback",
            "po_id": po_data.get("po_id", ""),
            "po_details": {
                "supplier": supplier.get("name", ""),
                "total_cost": order.get("total_cost", 0),
                "quantity": order.get("quantity", 0),
                "status": "DRAFT",
            },
        }

    except Exception as e:
        logger.error("API fallback failed: %s", str(e))
        return {
            "status": "FAILED",
            "method": "api_fallback",
            "error": str(e),
        }


def handler(event, context):
    """
    Nova Act execution handler with self-healing retry logic.

    Retry strategy (escalating):
      Attempt 1 — preferred mode (nova_act or api, per EXECUTION_MODE)
      Attempt 2 — same mode, after exponential backoff
      Attempt 3 — opposite mode as last resort (nova_act ↔ api)
    If all 3 fail → escalate to human.
    """
    import time

    logger.info("NovaActExecutor invoked")
    start_time = datetime.now(timezone.utc)

    decision = event.get("decision", event)
    assessment_id = decision.get("assessment_id", "unknown")

    # Get credentials
    try:
        credentials = _get_erp_credentials()
    except Exception:
        return {
            "status": "FAILED",
            "reason": "Could not retrieve ERP credentials",
            "escalate": True,
        }

    # ── Self-Healing Retry Loop (escalating strategy) ──
    result = None
    attempts = []

    # Build the attempt plan: [preferred, preferred, opposite]
    opposite_mode = "api" if EXECUTION_MODE == "nova_act" else "nova_act"
    attempt_modes = [EXECUTION_MODE, EXECUTION_MODE, opposite_mode]
    backoff_secs = [0, 2, 4]  # exponential-ish: 0 s, 2 s, 4 s

    for attempt_idx, mode in enumerate(attempt_modes):
        attempt_num = attempt_idx + 1

        # Exponential backoff between retries
        if backoff_secs[attempt_idx] > 0:
            logger.info("Backing off %ds before attempt %d", backoff_secs[attempt_idx], attempt_num)
            time.sleep(backoff_secs[attempt_idx])

        logger.info("Execution attempt %d/%d (mode=%s)", attempt_num, MAX_RETRIES, mode)

        if mode == "nova_act":
            result = _execute_with_nova_act(decision, credentials)
            method_label = "nova_act"
        else:
            result = _execute_with_api_fallback(decision, credentials)
            method_label = "api"

        if result and result.get("status") == "SUCCESS":
            attempts.append({"attempt": attempt_num, "method": method_label, "status": "SUCCESS"})
            break

        attempts.append({
            "attempt": attempt_num,
            "method": method_label,
            "status": "FAILED",
            "error": result.get("error", "Unknown") if result else "Unknown",
        })

    # ── Determine Final Status ──
    final_status = "SUCCESS" if result and result.get("status") == "SUCCESS" else "FAILED"
    escalate = final_status == "FAILED"

    execution_result = {
        "status": final_status,
        "assessment_id": assessment_id,
        "attempts": attempts,
        "method": result.get("method", "none") if result else "none",
        "po_details": result.get("po_details", {}) if result else {},
        "screenshots": result.get("screenshots", []) if result else [],
        "escalate": escalate,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Store audit record
    _store_audit_record(assessment_id, "execution", execution_result)

    # Emit metrics
    elapsed_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
    try:
        CW.put_metric_data(
            Namespace="SupplyChainGhost",
            MetricData=[
                {
                    "MetricName": "ActionLatency",
                    "Value": elapsed_ms,
                    "Unit": "Milliseconds",
                },
                {
                    "MetricName": "ExecutionSuccess",
                    "Value": 1.0 if final_status == "SUCCESS" else 0.0,
                    "Unit": "Count",
                },
            ],
        )
    except Exception:
        pass

    logger.info("Execution complete: %s (attempts: %d)", final_status, len(attempts))
    return execution_result
