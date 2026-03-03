"""
PortCongestionCollector Lambda — Fetches shipping congestion metrics and port status.

Uses BarentsWatch AIS API (free, Norwegian Coastal Administration) for vessel
positions and derives congestion metrics per port bounding-box.

Env vars:
    RAW_BUCKET         — S3 bucket for raw data
    SIGNALS_TABLE      — DynamoDB table for signals
    BARENTSWATCH_CLIENT_ID     — BarentsWatch API client ID
    BARENTSWATCH_CLIENT_SECRET — BarentsWatch API client secret
    (optional) MARINETRAFFIC_API_KEY — MarineTraffic PS07 endpoint key
"""
import os
import json
import logging
import math
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

# API credentials (set via CDK environment / Secrets Manager)
BARENTSWATCH_CLIENT_ID = os.environ.get("BARENTSWATCH_CLIENT_ID", "")
BARENTSWATCH_CLIENT_SECRET = os.environ.get("BARENTSWATCH_CLIENT_SECRET", "")
MARINETRAFFIC_API_KEY = os.environ.get("MARINETRAFFIC_API_KEY", "")

# Major ports to monitor — with bounding boxes for AIS geo-queries
PORTS = [
    {"code": "USLAX", "name": "Los Angeles", "country": "US", "lat": 33.74, "lon": -118.27,
     "bbox": [-118.35, 33.68, -118.15, 33.80], "avg_berths": 70},
    {"code": "USLGB", "name": "Long Beach", "country": "US", "lat": 33.77, "lon": -118.19,
     "bbox": [-118.25, 33.72, -118.10, 33.82], "avg_berths": 66},
    {"code": "CNSHA", "name": "Shanghai", "country": "CN", "lat": 31.23, "lon": 121.47,
     "bbox": [121.35, 31.10, 121.60, 31.40], "avg_berths": 120},
    {"code": "CNSZN", "name": "Shenzhen", "country": "CN", "lat": 22.54, "lon": 114.06,
     "bbox": [113.85, 22.40, 114.20, 22.65], "avg_berths": 80},
    {"code": "SGSIN", "name": "Singapore", "country": "SG", "lat": 1.26, "lon": 103.82,
     "bbox": [103.70, 1.15, 104.00, 1.35], "avg_berths": 100},
    {"code": "NLRTM", "name": "Rotterdam", "country": "NL", "lat": 51.92, "lon": 4.48,
     "bbox": [3.90, 51.85, 4.55, 52.00], "avg_berths": 90},
    {"code": "DEHAM", "name": "Hamburg", "country": "DE", "lat": 53.55, "lon": 9.99,
     "bbox": [9.85, 53.50, 10.10, 53.60], "avg_berths": 50},
    {"code": "KRPUS", "name": "Busan", "country": "KR", "lat": 35.18, "lon": 129.08,
     "bbox": [128.95, 35.05, 129.20, 35.25], "avg_berths": 75},
    {"code": "AEJEA", "name": "Jebel Ali", "country": "AE", "lat": 25.01, "lon": 55.06,
     "bbox": [54.95, 24.95, 55.15, 25.10], "avg_berths": 60},
    {"code": "USNYC", "name": "New York/New Jersey", "country": "US", "lat": 40.66, "lon": -74.05,
     "bbox": [-74.15, 40.55, -73.95, 40.75], "avg_berths": 65},
]

# Congestion thresholds
THRESHOLDS = {
    "vessels_at_anchor": {"HIGH": 30, "MEDIUM": 15},
    "avg_wait_days": {"HIGH": 7, "MEDIUM": 3},
    "berth_utilization_pct": {"HIGH": 90, "MEDIUM": 75},
}


# ── AIS data providers ──────────────────────────────────────────────────

def _get_barentswatch_token() -> str:
    """Obtain OAuth2 token from BarentsWatch (free Norwegian Coastal Admin AIS)."""
    resp = requests.post(
        "https://id.barentswatch.no/connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": BARENTSWATCH_CLIENT_ID,
            "client_secret": BARENTSWATCH_CLIENT_SECRET,
            "scope": "api",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _fetch_ais_barentswatch(port: dict) -> list:
    """Fetch live AIS positions inside port bbox from BarentsWatch Open AIS."""
    token = _get_barentswatch_token()
    bbox = port["bbox"]  # [min_lon, min_lat, max_lon, max_lat]
    resp = requests.get(
        "https://live.ais.barentswatch.no/v1/latest/combined",
        params={
            "xmin": bbox[0], "ymin": bbox[1],
            "xmax": bbox[2], "ymax": bbox[3],
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()  # list of vessel dicts


def _fetch_ais_marinetraffic(port: dict) -> list:
    """Fallback: fetch vessel positions from MarineTraffic PS07 endpoint."""
    bbox = port["bbox"]
    resp = requests.get(
        "https://services.marinetraffic.com/api/exportvessels/v:8/"
        f"{MARINETRAFFIC_API_KEY}/MINLAT:{bbox[1]}/MAXLAT:{bbox[3]}/"
        f"MINLON:{bbox[0]}/MAXLON:{bbox[2]}/protocol:jsono",
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _classify_vessel(vessel: dict) -> str:
    """Classify vessel as 'anchor', 'berth', or 'transit' based on speed/navstat."""
    speed = vessel.get("speedOverGround") or vessel.get("sog") or vessel.get("SPEED") or 0
    nav_status = vessel.get("navigationalStatus") or vessel.get("navstat") or vessel.get("STATUS") or -1

    # AIS Nav Status: 1 = at anchor, 5 = moored
    if nav_status in (1, "1", "At Anchor"):
        return "anchor"
    if nav_status in (5, "5", "Moored"):
        return "berth"
    if float(speed) < 0.5:
        return "anchor"  # stationary but status unknown → likely anchored
    return "transit"


def _compute_congestion_index(at_anchor: int, at_berth: int, avg_berths: int,
                               wait_days: float, berth_util: float) -> float:
    """Composite 0-100 congestion score."""
    anchor_score = min(at_anchor / max(avg_berths * 0.5, 1), 1.0) * 40
    berth_score = min(berth_util / 100, 1.0) * 35
    wait_score = min(wait_days / 10, 1.0) * 25
    return round(min(anchor_score + berth_score + wait_score, 100), 1)


def _fetch_port_data(port: dict) -> dict:
    """
    Fetch real AIS-based congestion data for a port.
    Primary: BarentsWatch AIS (free).  Fallback: MarineTraffic PS07.
    """
    vessels = []
    data_source = "unknown"

    # Try BarentsWatch first (free), then MarineTraffic
    if BARENTSWATCH_CLIENT_ID and BARENTSWATCH_CLIENT_SECRET:
        try:
            vessels = _fetch_ais_barentswatch(port)
            data_source = "barentswatch_ais"
        except Exception as e:
            logger.warning("BarentsWatch AIS failed for %s: %s", port["code"], e)

    if not vessels and MARINETRAFFIC_API_KEY:
        try:
            vessels = _fetch_ais_marinetraffic(port)
            data_source = "marinetraffic"
        except Exception as e:
            logger.warning("MarineTraffic failed for %s: %s", port["code"], e)

    if not vessels:
        logger.warning("No AIS data available for %s — API keys may be missing", port["code"])
        data_source = "unavailable"

    # Classify vessels
    at_anchor = sum(1 for v in vessels if _classify_vessel(v) == "anchor")
    at_berth = sum(1 for v in vessels if _classify_vessel(v) == "berth")
    in_transit = len(vessels) - at_anchor - at_berth

    avg_berths = port.get("avg_berths", 60)
    berth_util = round(min((at_berth / avg_berths) * 100, 100), 1) if avg_berths else 0
    # Estimate wait days from anchor-to-berth ratio (heuristic)
    avg_wait_days = round(max((at_anchor / max(at_berth, 1)) * 2, 0), 1)
    congestion_idx = _compute_congestion_index(at_anchor, at_berth, avg_berths, avg_wait_days, berth_util)

    return {
        "port_code": port["code"],
        "port_name": port["name"],
        "country": port["country"],
        "vessels_at_anchor": at_anchor,
        "vessels_at_berth": at_berth,
        "total_vessels_in_port": len(vessels),
        "avg_wait_days": avg_wait_days,
        "berth_utilization_pct": berth_util,
        "container_dwell_time_days": 0,  # requires port authority data
        "inbound_vessels_24h": in_transit,  # approximation
        "outbound_vessels_24h": 0,
        "congestion_index": congestion_idx,
        "data_source": data_source,
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
