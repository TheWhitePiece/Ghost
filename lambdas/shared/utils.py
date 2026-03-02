"""
Shared utilities for all Lambda functions.
"""
import os
import json
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── AWS Clients (lazy init) ──
_s3 = None
_dynamodb = None
_bedrock = None
_cloudwatch = None


def get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def get_dynamodb():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def get_bedrock_runtime():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime")
    return _bedrock


def get_cloudwatch():
    global _cloudwatch
    if _cloudwatch is None:
        _cloudwatch = boto3.client("cloudwatch")
    return _cloudwatch


def generate_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_signal(table_name: str, signal: dict):
    """Store a structured signal in DynamoDB."""
    table = get_dynamodb().Table(table_name)
    signal.setdefault("signal_id", generate_id("sig-"))
    signal.setdefault("timestamp", now_iso())
    # Convert floats to Decimal for DynamoDB
    signal = json.loads(json.dumps(signal), parse_float=Decimal)
    table.put_item(Item=signal)
    return signal["signal_id"]


def store_raw(bucket: str, key: str, data: str):
    """Store raw data in S3."""
    get_s3().put_object(
        Bucket=bucket,
        Key=key,
        Body=data.encode("utf-8"),
        ContentType="application/json",
    )


def emit_metric(metric_name: str, value: float, unit: str = "None"):
    """Emit a custom CloudWatch metric."""
    get_cloudwatch().put_metric_data(
        Namespace="SupplyChainGhost",
        MetricData=[{
            "MetricName": metric_name,
            "Value": value,
            "Unit": unit,
            "Timestamp": datetime.now(timezone.utc),
        }],
    )


def invoke_nova(model_id: str, prompt: str, system: str = "", max_tokens: int = 4096,
                temperature: float = 0.3, images: list = None) -> dict:
    """Invoke an Amazon Nova model via Bedrock."""
    client = get_bedrock_runtime()
    messages = []
    content = []

    if images:
        for img in images:
            content.append({
                "image": {
                    "format": img.get("format", "png"),
                    "source": {"bytes": img["bytes"]},
                }
            })

    content.append({"text": prompt})
    messages.append({"role": "user", "content": content})

    body = {
        "messages": messages,
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": temperature,
        },
    }
    if system:
        body["system"] = [{"text": system}]

    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    return result


def extract_text_from_nova(response: dict) -> str:
    """Extract text content from Nova response."""
    try:
        return response["output"]["message"]["content"][0]["text"]
    except (KeyError, IndexError):
        return json.dumps(response)


def cors_response(status_code: int, body: dict) -> dict:
    """Return a CORS-enabled API Gateway response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }
