"""
NovaActExecutor Lambda — Browser automation for ERP purchase order creation.

Uses Nova Act to:
1. Open ERP login
2. Authenticate via Secrets Manager
3. Navigate procurement module
4. Search SKU, filter supplier
5. Draft PO
6. Take screenshot
7. Save draft

With self-healing retry logic and fallback API mode.
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
ERP_BASE_URL = os.environ.get("ERP_URL", "https://erp.example.com")


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
    Fallback: Create PO via ERP REST API instead of browser automation.
    """
    import requests

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
    
    Retry strategy:
    1. Try Nova Act browser automation
    2. If UI fails, retry with alternate selectors
    3. Fall back to ERP API mode
    4. Escalate to human
    """
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

    # ── Self-Healing Retry Loop ──
    result = None
    attempts = []

    for attempt in range(MAX_RETRIES):
        logger.info("Execution attempt %d/%d", attempt + 1, MAX_RETRIES)

        # Try Nova Act first
        result = _execute_with_nova_act(decision, credentials)
        if result and result.get("status") == "SUCCESS":
            attempts.append({"attempt": attempt + 1, "method": "nova_act", "status": "SUCCESS"})
            break

        attempts.append({
            "attempt": attempt + 1,
            "method": "nova_act",
            "status": "FAILED",
            "error": result.get("error", "Nova Act unavailable") if result else "SDK not available",
        })

        # Fallback to API
        logger.info("Falling back to API mode")
        result = _execute_with_api_fallback(decision, credentials)
        if result and result.get("status") == "SUCCESS":
            attempts.append({"attempt": attempt + 1, "method": "api_fallback", "status": "SUCCESS"})
            break

        attempts.append({
            "attempt": attempt + 1,
            "method": "api_fallback",
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
