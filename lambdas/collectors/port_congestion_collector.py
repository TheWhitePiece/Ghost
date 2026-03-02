"""
PortCongestionCollector Lambda — Fetches shipping congestion metrics and port status.
"""
import os
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3 = boto3.client("s3")
DDB = boto3.resource("dynamodb")

RAW_BUCKET = os.environ["RAW_BUCKET"]
SIGNALS_TABLE = os.environ["SIGNALS_TABLE"]

# Major ports to monitor
PORTS = [
    {"code": "USLAX", "name": "Los Angeles", "country": "US", "lat": 33.74, "lon": -118.27},
    {"code": "USLGB", "name": "Long Beach", "country": "US", "lat": 33.77, "lon": -118.19},
    {"code": "CNSHA", "name": "Shanghai", "country": "CN", "lat": 31.23, "lon": 121.47},
    {"code": "CNSZN", "name": "Shenzhen", "country": "CN", "lat": 22.54, "lon": 114.06},
    {"code": "SGSIN", "name": "Singapore", "country": "SG", "lat": 1.26, "lon": 103.82},
    {"code": "NLRTM", "name": "Rotterdam", "country": "NL", "lat": 51.92, "lon": 4.48},
    {"code": "DEHAM", "name": "Hamburg", "country": "DE", "lat": 53.55, "lon": 9.99},
    {"code": "KRPUS", "name": "Busan", "country": "KR", "lat": 35.18, "lon": 129.08},
    {"code": "AEJEA", "name": "Jebel Ali", "country": "AE", "lat": 25.01, "lon": 55.06},
    {"code": "USNYC", "name": "New York/New Jersey", "country": "US", "lat": 40.66, "lon": -74.05},
]

# Congestion thresholds
THRESHOLDS = {
    "vessels_at_anchor": {"HIGH": 30, "MEDIUM": 15},
    "avg_wait_days": {"HIGH": 7, "MEDIUM": 3},
    "berth_utilization_pct": {"HIGH": 90, "MEDIUM": 75},
}


def _fetch_port_data(port: dict) -> dict:
    """
    Fetch congestion data for a port.
    In production, integrate with MarineTraffic/VesselFinder/PortCast API.
    This provides the data structure for the pipeline.
    """
    # Simulated realistic data structure
    return {
        "port_code": port["code"],
        "port_name": port["name"],
        "country": port["country"],
        "vessels_at_anchor": 0,
        "vessels_at_berth": 0,
        "total_vessels_in_port": 0,
        "avg_wait_days": 0,
        "berth_utilization_pct": 0,
        "container_dwell_time_days": 0,
        "inbound_vessels_24h": 0,
        "outbound_vessels_24h": 0,
        "congestion_index": 0.0,  # 0-100 composite score
        "data_source": "simulated",
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def _assess_congestion(data: dict) -> tuple:
    """Return (severity, reasons) based on port congestion metrics."""
    reasons = []
    severity = "LOW"

    if data["vessels_at_anchor"] >= THRESHOLDS["vessels_at_anchor"]["HIGH"]:
        severity = "HIGH"
        reasons.append(f"{data['vessels_at_anchor']} vessels at anchor")
    elif data["vessels_at_anchor"] >= THRESHOLDS["vessels_at_anchor"]["MEDIUM"]:
        severity = max(severity, "MEDIUM")
        reasons.append(f"{data['vessels_at_anchor']} vessels at anchor")

    if data["avg_wait_days"] >= THRESHOLDS["avg_wait_days"]["HIGH"]:
        severity = "HIGH"
        reasons.append(f"Avg wait: {data['avg_wait_days']} days")
    elif data["avg_wait_days"] >= THRESHOLDS["avg_wait_days"]["MEDIUM"]:
        severity = max(severity, "MEDIUM")
        reasons.append(f"Avg wait: {data['avg_wait_days']} days")

    if data["berth_utilization_pct"] >= THRESHOLDS["berth_utilization_pct"]["HIGH"]:
        severity = "HIGH"
        reasons.append(f"Berth utilization: {data['berth_utilization_pct']}%")
    elif data["berth_utilization_pct"] >= THRESHOLDS["berth_utilization_pct"]["MEDIUM"]:
        severity = max(severity, "MEDIUM")
        reasons.append(f"Berth utilization: {data['berth_utilization_pct']}%")

    return severity, reasons


def handler(event, context):
    """
    Triggered by EventBridge schedule or shipping webhook.
    Collects port congestion data and creates disruption signals.
    """
    logger.info("PortCongestionCollector invoked: %s", json.dumps(event, default=str))

    table = DDB.Table(SIGNALS_TABLE)
    ts = datetime.now(timezone.utc).isoformat()
    signals_found = 0

    for port in PORTS:
        try:
            data = _fetch_port_data(port)

            # Store raw data
            S3.put_object(
                Bucket=RAW_BUCKET,
                Key=f"ports/{port['code']}/{ts[:10]}/{ts[:13]}.json",
                Body=json.dumps(data, default=str),
                ContentType="application/json",
            )

            severity, reasons = _assess_congestion(data)

            if severity in ("HIGH", "MEDIUM"):
                signal_id = f"port-{port['code'].lower()}-{ts[:13]}"
                signal = {
                    "signal_id": signal_id,
                    "timestamp": ts,
                    "signal_type": "PORT_CONGESTION",
                    "source": f"port-monitor:{port['code']}",
                    "title": f"Port congestion alert: {port['name']}",
                    "summary": "; ".join(reasons),
                    "severity": severity,
                    "port_code": port["code"],
                    "port_name": port["name"],
                    "country": port["country"],
                    "congestion_index": Decimal(str(data["congestion_index"])),
                    "vessels_at_anchor": data["vessels_at_anchor"],
                    "avg_wait_days": Decimal(str(data["avg_wait_days"])),
                    "berth_utilization_pct": Decimal(str(data["berth_utilization_pct"])),
                    "ttl": int(datetime.now(timezone.utc).timestamp()) + 86400 * 2,
                }
                signal_json = json.loads(json.dumps(signal, default=str), parse_float=Decimal)
                table.put_item(Item=signal_json)
                signals_found += 1

        except Exception as e:
            logger.error("Port %s collection failed: %s", port["code"], str(e))

    logger.info("PortCongestionCollector complete: %d signals", signals_found)
    return {"signals_found": signals_found, "source": "PortCongestionCollector"}
