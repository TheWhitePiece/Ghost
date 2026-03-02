"""
ReasoningEngine Lambda — Nova 2 Lite Extended Thinking for risk assessment.

This is the brain of the system: it takes in signals, RAG context, and memory
to produce structured risk assessments with full thought traces.
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
BEDROCK_AGENT = boto3.client("bedrock-agent-runtime")
CW = boto3.client("cloudwatch")

SIGNALS_TABLE = os.environ["SIGNALS_TABLE"]
RISK_TABLE = os.environ["RISK_TABLE"]
KNOWLEDGE_BUCKET = os.environ["KNOWLEDGE_BUCKET"]
NOVA_MODEL_ID = os.environ.get("NOVA_MODEL_ID", "amazon.nova-lite-v1:0")

SYSTEM_PROMPT = """You are the Supply Chain Ghost — an enterprise AI risk analyst.

You analyze supply chain signals (news, weather, port congestion, commodity prices, satellite data)
and produce structured risk assessments.

For each assessment, you must provide:
1. risk_score (0-100): Composite risk score
2. confidence_pct (0-100): Your confidence in this assessment
3. estimated_delay_days (integer): Expected delay in days
4. financial_impact_usd (number): Estimated financial impact
5. affected_suppliers (list): Suppliers likely affected
6. affected_routes (list): Trade routes affected
7. action_recommendation: One of [MONITOR, ALERT, SWITCH_SUPPLIER, EMERGENCY_STOCK, ESCALATE]
8. reasoning: Detailed explanation of your analysis

Think step by step. Consider:
- Signal severity and correlation across multiple sources
- Historical patterns from the knowledge base
- Supplier reliability scores from memory
- Current inventory levels and depletion rates
- Revenue sensitivity of affected products
- Geographic clustering of disruptions

Output your response as valid JSON only."""


def _fetch_recent_signals(hours: int = 6) -> list:
    """Fetch recent signals from DynamoDB."""
    table = DDB.Table(SIGNALS_TABLE)
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    response = table.scan(
        FilterExpression="timestamp >= :cutoff",
        ExpressionAttributeValues={":cutoff": cutoff},
    )
    return response.get("Items", [])


def _retrieve_rag_context(query: str) -> str:
    """Retrieve relevant context from Bedrock Knowledge Base."""
    try:
        # Try to use Bedrock Knowledge Base if configured
        response = BEDROCK_AGENT.retrieve(
            knowledgeBaseId=os.environ.get("KNOWLEDGE_BASE_ID", ""),
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 5,
                }
            },
        )
        contexts = []
        for result in response.get("retrievalResults", []):
            content = result.get("content", {}).get("text", "")
            if content:
                contexts.append(content)
        return "\n\n".join(contexts)
    except Exception as e:
        logger.warning("RAG retrieval failed (KB may not be configured): %s", str(e))
        return "No historical context available from knowledge base."


def _get_memory_context() -> str:
    """Retrieve supplier memory/historical context."""
    # In production, use Bedrock Memory API
    return """
SUPPLIER MEMORY (Historical):
- Supplier A (Shenzhen Electronics Co): Reliability 62%. 
  2025 Hurricane Florida: 12-day delay. 2025 Port strike: 9-day delay.
- Supplier B (Taiwan Semiconductor): Reliability 85%.
  2025 Chip shortage: 5-day delay. Generally reliable.
- Supplier C (Rotterdam Logistics): Reliability 78%.
  2025 Suez disruption: 15-day delay. Good recovery speed.
- Supplier D (Vietnam Manufacturing): Reliability 71%.
  2025 Monsoon season: 8-day delay. Improving trend.

INVENTORY STATUS:
- SKU-001 (Microcontrollers): 14 days supply remaining
- SKU-002 (Display Panels): 21 days supply remaining
- SKU-003 (Battery Cells): 7 days supply remaining (CRITICAL)
- SKU-004 (Chassis Components): 30 days supply remaining

REVENUE SENSITIVITY:
- Product Line Alpha: $125,000/day revenue impact per day of delay
- Product Line Beta: $85,000/day
- Product Line Gamma: $45,000/day
"""


def _invoke_nova_reasoning(signals: list, rag_context: str, memory: str) -> dict:
    """Invoke Nova 2 Lite with extended thinking for risk assessment."""
    prompt = f"""CURRENT SUPPLY CHAIN SIGNALS:
{json.dumps(signals, default=str, indent=2)}

KNOWLEDGE BASE CONTEXT (Historical disruptions, SLAs, contracts):
{rag_context}

MEMORY (Supplier reliability, inventory, revenue sensitivity):
{memory}

Based on all the above context, produce a comprehensive risk assessment.
Analyze signal correlations, assess multi-factor risk, and provide an actionable recommendation.

Return your analysis as a JSON object with these exact fields:
{{
  "risk_score": <0-100>,
  "confidence_pct": <0-100>,
  "estimated_delay_days": <integer>,
  "financial_impact_usd": <number>,
  "affected_suppliers": [<list of supplier names>],
  "affected_routes": [<list of route descriptions>],
  "affected_skus": [<list of SKU IDs>],
  "action_recommendation": "<MONITOR|ALERT|SWITCH_SUPPLIER|EMERGENCY_STOCK|ESCALATE>",
  "reasoning": "<detailed step-by-step reasoning>",
  "risk_factors": [
    {{"factor": "<name>", "weight": <0-1>, "score": <0-100>, "evidence": "<detail>"}}
  ],
  "mitigation_options": [
    {{"option": "<description>", "cost_usd": <number>, "time_days": <number>, "confidence": <0-100>}}
  ]
}}"""

    body = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "system": [{"text": SYSTEM_PROMPT}],
        "inferenceConfig": {
            "maxTokens": 8192,
            "temperature": 0.2,
        },
    }

    response = BEDROCK.invoke_model(
        modelId=NOVA_MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )

    result = json.loads(response["body"].read())
    return result


def handler(event, context):
    """
    Main reasoning handler. Triggered by Step Functions or direct invocation.
    
    Input event can contain:
    - signals: Pre-fetched signals (optional, will fetch if missing)
    - assessment_id: Existing assessment to re-evaluate
    """
    logger.info("ReasoningEngine invoked")
    start_time = datetime.now(timezone.utc)

    # 1. Gather signals
    signals = event.get("signals") or _fetch_recent_signals(hours=6)
    if not signals:
        logger.info("No recent signals found")
        return {
            "risk_score": 0,
            "confidence_pct": 95,
            "action_recommendation": "MONITOR",
            "reasoning": "No active disruption signals detected.",
        }

    # 2. Build query from signals for RAG
    signal_summaries = [s.get("title", "") + " " + s.get("summary", "") for s in signals[:10]]
    rag_query = " ".join(signal_summaries)[:1000]

    # 3. Retrieve context
    rag_context = _retrieve_rag_context(rag_query)
    memory_context = _get_memory_context()

    # 4. Invoke Nova 2 Lite
    nova_response = _invoke_nova_reasoning(signals, rag_context, memory_context)

    # 5. Parse response
    try:
        output_text = nova_response["output"]["message"]["content"][0]["text"]
        # Extract JSON from response
        if "```json" in output_text:
            output_text = output_text.split("```json")[1].split("```")[0]
        elif "```" in output_text:
            output_text = output_text.split("```")[1].split("```")[0]
        assessment = json.loads(output_text)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error("Failed to parse Nova response: %s", str(e))
        assessment = {
            "risk_score": 50,
            "confidence_pct": 30,
            "action_recommendation": "ESCALATE",
            "reasoning": "Unable to parse model response. Escalating for human review.",
            "raw_response": str(nova_response)[:1000],
        }

    # 6. Store assessment
    risk_table = DDB.Table(RISK_TABLE)
    assessment_id = f"risk-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    assessment["assessment_id"] = assessment_id
    assessment["created_at"] = datetime.now(timezone.utc).isoformat()
    assessment["status"] = "PENDING_VERIFICATION" if assessment.get("risk_score", 0) > 60 else "ASSESSED"
    assessment["signal_count"] = len(signals)
    assessment["signal_ids"] = [s.get("signal_id", "") for s in signals[:20]]

    # Log thought trace
    logger.info("THOUGHT_TRACE: assessment_id=%s risk_score=%s confidence=%s action=%s",
                assessment_id,
                assessment.get("risk_score"),
                assessment.get("confidence_pct"),
                assessment.get("action_recommendation"))

    # Store (convert to Decimal for DynamoDB)
    assessment_ddb = json.loads(json.dumps(assessment, default=str), parse_float=Decimal)
    risk_table.put_item(Item=assessment_ddb)

    # 7. Emit metrics
    elapsed_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
    try:
        CW.put_metric_data(
            Namespace="SupplyChainGhost",
            MetricData=[
                {
                    "MetricName": "DetectionLatency",
                    "Value": elapsed_ms,
                    "Unit": "Milliseconds",
                },
                {
                    "MetricName": "RiskScore",
                    "Value": float(assessment.get("risk_score", 0)),
                    "Unit": "None",
                },
                {
                    "MetricName": "ModelConfidence",
                    "Value": float(assessment.get("confidence_pct", 0)),
                    "Unit": "Percent",
                },
            ],
        )
    except Exception as e:
        logger.warning("Failed to emit metrics: %s", str(e))

    logger.info("ReasoningEngine complete: %s (score=%s)", assessment_id, assessment.get("risk_score"))
    return assessment
