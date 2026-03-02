"""
ChatHandler Lambda — "Ask the Ghost" conversational AI.

Uses Nova 2 Lite with RAG context to answer supply chain questions.
Cites evidence, shows reliability data, explains cost math.
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
BEDROCK = boto3.client("bedrock-runtime")

RISK_TABLE = os.environ["RISK_TABLE"]
NOVA_MODEL_ID = os.environ.get("NOVA_MODEL_ID", "amazon.nova-lite-v1:0")


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


# ── Supplier data for cost comparisons (mirrors decision engine) ──
SUPPLIER_DATA = {
    "Supplier A (Shenzhen Electronics Co)": {"reliability": 0.62, "unit_price": 45.00, "lead_time": 14},
    "Supplier B (Taiwan Semiconductor)": {"reliability": 0.85, "unit_price": 52.00, "lead_time": 10},
    "Supplier C (Rotterdam Logistics)": {"reliability": 0.78, "unit_price": 48.00, "lead_time": 7},
    "Supplier D (Vietnam Manufacturing)": {"reliability": 0.71, "unit_price": 40.00, "lead_time": 16},
}

SYSTEM_PROMPT = """You are the Supply Chain Ghost — an AI assistant for supply chain operations.

You have access to risk assessments, supplier data, and decision analysis.
When answering questions:

1. **Cite evidence**: Reference specific risk scores, supplier reliability data, and signal sources.
2. **Show satellite confirmation**: If visual verification was performed, cite the confidence %.
3. **Explain cost math**: Break down delay costs vs switch costs with actual numbers.
   - Delay Cost = (Estimated Delay Days × Revenue Loss Per Day) × (1 + (1 - Reliability))
   - Switch Cost = (Price Difference × Quantity) + Expedited Freight ($15,000)
   - Revenue per day: Product Line Alpha=$125K, Beta=$85K, Gamma=$45K
4. **Be transparent**: Explain your reasoning and confidence levels.
5. **Be concise**: Give clear, actionable answers.
6. **Supplier context**: 
   - Supplier A (Shenzhen Electronics): Reliability 62%, $45/unit, 14-day lead
   - Supplier B (Taiwan Semiconductor): Reliability 85%, $52/unit, 10-day lead
   - Supplier C (Rotterdam Logistics): Reliability 78%, $48/unit, 7-day lead
   - Supplier D (Vietnam Manufacturing): Reliability 71%, $40/unit, 16-day lead

You build trust by being specific, citing data, and acknowledging uncertainty.

Current context will be provided with each question."""


def _get_recent_context() -> str:
    """Fetch recent risk assessments for context."""
    table = DDB.Table(RISK_TABLE)
    try:
        response = table.scan(Limit=10)
    except Exception as e:
        logger.warning("Failed to scan risk table: %s", str(e))
        return "No recent risk assessments available (table may be empty)."

    items = response.get("Items", [])

    if not items:
        return "No recent risk assessments available."

    context_parts = []
    for item in sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)[:5]:
        decision = item.get("decision", {})
        decision_str = ""
        if decision:
            try:
                decision_str = json.dumps(decision, default=str, cls=_DecimalEncoder)[:400]
            except Exception:
                decision_str = str(decision)[:400]

        context_parts.append(
            f"Assessment {item.get('assessment_id', 'N/A')}:\n"
            f"  Title: {item.get('title', 'N/A')}\n"
            f"  Risk Score: {item.get('risk_score', 'N/A')}\n"
            f"  Confidence: {item.get('confidence_pct', item.get('confidence', 'N/A'))}%\n"
            f"  Status: {item.get('status', 'N/A')}\n"
            f"  Est. Delay: {item.get('estimated_delay_days', 'N/A')} days\n"
            f"  Financial Impact: ${item.get('financial_impact_usd', 'N/A')}\n"
            f"  Action: {item.get('action_recommendation', 'N/A')}\n"
            f"  Reasoning: {str(item.get('reasoning', 'N/A'))[:300]}\n"
            f"  Decision: {decision_str}\n"
        )
    return "\n".join(context_parts) if context_parts else "No risk assessment data available."


def _get_assessment_detail(assessment_id: str) -> str:
    """Get detailed assessment for context."""
    table = DDB.Table(RISK_TABLE)
    try:
        response = table.query(
            KeyConditionExpression="assessment_id = :aid",
            ExpressionAttributeValues={":aid": assessment_id},
            Limit=1,
        )
        items = response.get("Items", [])
        if items:
            return json.dumps(items[0], default=str, cls=_DecimalEncoder)
    except Exception:
        # Fallback: try scan
        try:
            response = table.scan(
                FilterExpression="assessment_id = :aid",
                ExpressionAttributeValues={":aid": assessment_id},
                Limit=1,
            )
            items = response.get("Items", [])
            if items:
                return json.dumps(items[0], default=str, cls=_DecimalEncoder)
        except Exception:
            pass
    return "Assessment not found."


def handler(event, context):
    """
    Chat handler — processes user questions and returns AI responses.
    
    Input: { "message": "Why switch to Supplier B?", "assessment_id": "optional" }
    Output: { "response": "...", "sources": [...], "confidence": <number> }
    """
    logger.info("ChatHandler invoked")

    body = {}
    if isinstance(event.get("body"), str):
        try:
            body = json.loads(event["body"])
        except json.JSONDecodeError:
            body = {}
    elif isinstance(event, dict) and "message" in event:
        body = event
    elif event.get("body") and isinstance(event["body"], dict):
        body = event["body"]

    user_message = body.get("message", "")
    assessment_id = body.get("assessment_id", "")
    conversation_history = body.get("history", [])

    if not user_message:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "POST,OPTIONS",
            },
            "body": json.dumps({"error": "Message is required"}),
        }

    # Build context
    try:
        if assessment_id:
            context_str = _get_assessment_detail(assessment_id)
        else:
            context_str = _get_recent_context()
    except Exception as e:
        logger.warning("Context fetch failed: %s", str(e))
        context_str = "Context unavailable. Answering based on general supply chain knowledge."

    # Build messages from conversation history
    messages = []
    for msg in conversation_history[-10:]:  # Last 10 messages
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({
                "role": role,
                "content": [{"text": content}],
            })

    # Add current message with context
    messages.append({
        "role": "user",
        "content": [{"text": f"""CONTEXT (Recent Assessments & Decisions):
{context_str}

USER QUESTION:
{user_message}

Provide a detailed, evidence-based answer. Cite specific numbers, risk scores, cost figures, and supplier data. If comparing costs, show the math step by step."""}],
    })

    # Build list of sources from context
    sources = []
    if "Assessment " in context_str:
        import re
        ids = re.findall(r"Assessment (risk-\w+)", context_str)
        for aid in ids[:3]:
            sources.append(f"Risk Assessment: {aid[:16]}")
    sources.append("Supplier Reliability Database")
    sources.append("Cost Analysis Engine")

    # Invoke Nova
    answer = ""
    confidence = 85
    try:
        response = BEDROCK.invoke_model(
            modelId=NOVA_MODEL_ID,
            body=json.dumps({
                "messages": messages,
                "system": [{"text": SYSTEM_PROMPT}],
                "inferenceConfig": {
                    "maxTokens": 2048,
                    "temperature": 0.3,
                },
            }),
            contentType="application/json",
            accept="application/json",
        )

        result = json.loads(response["body"].read())
        answer = result["output"]["message"]["content"][0]["text"]
        # Estimate confidence based on context availability
        confidence = 90 if assessment_id else (85 if "Assessment " in context_str else 70)

    except Exception as e:
        logger.error("Nova invocation failed: %s", str(e))
        error_msg = str(e)
        if "AccessDeniedException" in error_msg:
            answer = (
                "I don't have access to the AI model yet. Please ensure Amazon Bedrock "
                "model access is enabled for `amazon.nova-lite-v1:0` in the AWS Console "
                "(Bedrock → Model access → Request access)."
            )
        elif "ResourceNotFoundException" in error_msg:
            answer = (
                "The AI model `amazon.nova-lite-v1:0` is not available in this region. "
                "Please check your Bedrock model configuration."
            )
        elif "ThrottlingException" in error_msg:
            answer = (
                "The AI service is temporarily throttled due to high demand. "
                "Please wait a moment and try again."
            )
        else:
            answer = (
                f"I'm experiencing a temporary issue accessing the AI model: {error_msg[:200]}. "
                "Please try again in a moment."
            )
        confidence = 0
        sources = []

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps({
            "response": answer,
            "sources": sources,
            "confidence": confidence,
            "assessment_id": assessment_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }),
    }
