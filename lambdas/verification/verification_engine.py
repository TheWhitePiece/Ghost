"""
VerificationEngine Lambda — Nova 2 Omni Multimodal Cross-Check.

Triggered when risk > 60% and visual evidence is available.
Analyzes satellite imagery and documents to verify/contradict reasoning.
"""
import os
import json
import logging
import base64
from datetime import datetime, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DDB = boto3.resource("dynamodb")
BEDROCK = boto3.client("bedrock-runtime")
S3 = boto3.client("s3")

RISK_TABLE = os.environ["RISK_TABLE"]
NOVA_OMNI_MODEL_ID = os.environ.get("NOVA_OMNI_MODEL_ID", "amazon.nova-premier-v1:0")

PORT_CONGESTION_PROMPT = """Analyze this satellite/port image for supply chain disruption indicators.

Evaluate and report:
1. **Vessel Clustering**: How many vessels appear anchored or waiting? Rate density 1-10.
2. **Dock Occupancy %**: Estimate what percentage of visible berths are occupied.
3. **Movement Density**: Rate the apparent vessel movement/congestion 1-10.
4. **Anomaly Detection**: Any unusual patterns (vessel clustering, empty docks, blocked channels)?
5. **Congestion Assessment**: Overall port congestion level (LOW/MEDIUM/HIGH/CRITICAL).
6. **Confidence**: Your confidence in this visual assessment (0-100%).

Return your analysis as JSON:
{
  "vessel_clustering_score": <1-10>,
  "estimated_vessels_at_anchor": <count>,
  "dock_occupancy_pct": <0-100>,
  "movement_density_score": <1-10>,
  "anomalies_detected": [<list of observations>],
  "congestion_level": "<LOW|MEDIUM|HIGH|CRITICAL>",
  "confidence_pct": <0-100>,
  "visual_summary": "<brief description of what's visible>"
}"""

BOL_VALIDATION_PROMPT = """Analyze this Bill of Lading (BOL) document image for anomalies and fraud indicators.

Check for:
1. **OCR Anomalies**: Blurred text, inconsistent fonts, resolution differences
2. **Date Mismatches**: Inconsistent or impossible dates
3. **Seal Number Validation**: Missing, illegible, or suspicious seal numbers
4. **Signature Verification**: Missing or unusual signatures
5. **Weight/Volume Inconsistencies**: Numbers that don't add up
6. **Fraud Indicators**: Signs of tampering, whiteout, digital manipulation

Return your analysis as JSON:
{
  "document_type": "BOL",
  "ocr_quality_score": <1-10>,
  "anomalies_detected": [
    {"type": "<anomaly type>", "description": "<detail>", "severity": "<LOW|MEDIUM|HIGH>", "location": "<where in document>"}
  ],
  "date_consistency": <true|false>,
  "seal_numbers_present": <true|false>,
  "seal_numbers_valid": <true|false>,
  "fraud_risk_score": <0-100>,
  "confidence_pct": <0-100>,
  "recommendation": "<APPROVED|FLAG_FOR_REVIEW|REJECT>",
  "summary": "<brief assessment>"
}"""


def _fetch_image_from_s3(bucket: str, key: str) -> bytes:
    """Fetch image bytes from S3."""
    response = S3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _invoke_nova_omni(prompt: str, image_bytes: bytes = None, image_format: str = "png") -> dict:
    """Invoke Nova 2 Omni with optional image input."""
    content = []

    if image_bytes:
        content.append({
            "image": {
                "format": image_format,
                "source": {"bytes": base64.b64encode(image_bytes).decode("utf-8")},
            }
        })

    content.append({"text": prompt})

    body = {
        "messages": [{"role": "user", "content": content}],
        "system": [{"text": "You are a multimodal supply chain verification AI. Analyze images and documents with precision. Always return valid JSON."}],
        "inferenceConfig": {
            "maxTokens": 4096,
            "temperature": 0.1,
        },
    }

    response = BEDROCK.invoke_model(
        modelId=NOVA_OMNI_MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )

    result = json.loads(response["body"].read())
    return result


def _verify_port_congestion(assessment: dict) -> dict:
    """Verify port congestion using satellite imagery."""
    port_code = None
    for signal_id in assessment.get("signal_ids", []):
        if "port-" in str(signal_id):
            port_code = str(signal_id).replace("port-", "").split("-")[0].upper()
            break

    if not port_code:
        return {"verification_type": "PORT_CONGESTION", "status": "SKIPPED", "reason": "No port signal found"}

    # Try to fetch satellite image
    image_bytes = None
    try:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        image_bytes = _fetch_image_from_s3(
            os.environ.get("RAW_BUCKET", ""),
            f"satellite/{port_code}/{date_str}/image.png"
        )
    except Exception as e:
        logger.warning("No satellite image available for %s: %s", port_code, str(e))

    # Invoke Nova Omni
    response = _invoke_nova_omni(PORT_CONGESTION_PROMPT, image_bytes)

    try:
        output_text = response["output"]["message"]["content"][0]["text"]
        if "```json" in output_text:
            output_text = output_text.split("```json")[1].split("```")[0]
        verification = json.loads(output_text)
    except Exception:
        verification = {"status": "PARSE_ERROR", "raw": str(response)[:500]}

    verification["verification_type"] = "PORT_CONGESTION"
    verification["port_code"] = port_code
    verification["verified_at"] = datetime.now(timezone.utc).isoformat()
    return verification


def _verify_bol(assessment: dict) -> dict:
    """Verify Bill of Lading documents."""
    # Check for BOL images in audit trail 
    bol_image = None
    try:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        bol_image = _fetch_image_from_s3(
            os.environ.get("RAW_BUCKET", ""),
            f"documents/bol/{date_str}/latest.png"
        )
    except Exception:
        logger.info("No BOL document available for verification")
        return {"verification_type": "BOL", "status": "SKIPPED", "reason": "No BOL image available"}

    response = _invoke_nova_omni(BOL_VALIDATION_PROMPT, bol_image)

    try:
        output_text = response["output"]["message"]["content"][0]["text"]
        if "```json" in output_text:
            output_text = output_text.split("```json")[1].split("```")[0]
        verification = json.loads(output_text)
    except Exception:
        verification = {"status": "PARSE_ERROR"}

    verification["verification_type"] = "BOL"
    verification["verified_at"] = datetime.now(timezone.utc).isoformat()
    return verification


def handler(event, context):
    """
    Multimodal verification handler.
    
    Input: Assessment from reasoning engine
    Output: Verification results, potentially with corrected risk score
    """
    logger.info("VerificationEngine invoked")

    assessment = event.get("reasoning", event)
    risk_score = float(assessment.get("risk_score", 0))

    if risk_score <= 60:
        logger.info("Risk score %s <= 60, skipping verification", risk_score)
        return {
            "verification_status": "SKIPPED",
            "reason": "Risk below threshold",
            "original_risk_score": risk_score,
            "verified_risk_score": risk_score,
        }

    verifications = []

    # 1. Port congestion verification
    port_verification = _verify_port_congestion(assessment)
    verifications.append(port_verification)

    # 2. BOL verification
    bol_verification = _verify_bol(assessment)
    verifications.append(bol_verification)

    # 3. Cross-check: Does visual evidence agree with reasoning?
    visual_agrees = True
    correction_reason = None
    adjusted_score = risk_score

    port_v = port_verification
    if port_v.get("congestion_level") and port_v.get("status") != "SKIPPED":
        visual_congestion = port_v.get("congestion_level", "UNKNOWN")
        reasoning_severity = "HIGH" if risk_score > 75 else "MEDIUM" if risk_score > 50 else "LOW"

        severity_map = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        visual_level = severity_map.get(visual_congestion, 0)
        reasoning_level = severity_map.get(reasoning_severity, 0)

        if abs(visual_level - reasoning_level) >= 2:
            visual_agrees = False
            correction_reason = (
                f"Visual shows {visual_congestion} congestion but reasoning assessed {reasoning_severity}. "
                f"Self-correction triggered."
            )
            # Adjust score based on visual evidence
            if visual_level > reasoning_level:
                adjusted_score = min(100, risk_score + 15)
            else:
                adjusted_score = max(0, risk_score - 15)

    result = {
        "verification_status": "COMPLETED",
        "verifications": verifications,
        "original_risk_score": risk_score,
        "verified_risk_score": adjusted_score,
        "visual_agrees_with_reasoning": visual_agrees,
        "self_correction_applied": not visual_agrees,
        "correction_reason": correction_reason,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        # Pass through assessment data
        "assessment_id": assessment.get("assessment_id"),
        "action_recommendation": assessment.get("action_recommendation"),
        "confidence_pct": assessment.get("confidence_pct"),
    }

    # Update risk table
    if assessment.get("assessment_id"):
        risk_table = DDB.Table(RISK_TABLE)
        try:
            risk_table.update_item(
                Key={
                    "assessment_id": assessment["assessment_id"],
                    "created_at": assessment.get("created_at", ""),
                },
                UpdateExpression="SET verification = :v, verified_risk_score = :s, #st = :status",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":v": json.loads(json.dumps(result, default=str), parse_float=Decimal),
                    ":s": Decimal(str(adjusted_score)),
                    ":status": "VERIFIED",
                },
            )
        except Exception as e:
            logger.error("Failed to update risk table: %s", str(e))

    logger.info(
        "Verification complete: original=%s verified=%s agrees=%s correction=%s",
        risk_score, adjusted_score, visual_agrees, bool(correction_reason)
    )
    return result
