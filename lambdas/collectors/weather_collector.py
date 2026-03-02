"""
WeatherCollector Lambda — Pulls storm, hurricane, and severe weather data.
Uses NWS (National Weather Service) and OpenWeatherMap APIs.
"""
import os
import json
import logging
from datetime import datetime, timezone

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3 = boto3.client("s3")
DDB = boto3.resource("dynamodb")

RAW_BUCKET = os.environ["RAW_BUCKET"]
SIGNALS_TABLE = os.environ["SIGNALS_TABLE"]

# Key supply chain regions to monitor
MONITORED_REGIONS = [
    {"name": "Gulf Coast", "lat": 29.76, "lon": -95.37, "region_code": "gulf"},
    {"name": "Los Angeles Port", "lat": 33.74, "lon": -118.26, "region_code": "la_port"},
    {"name": "Shanghai Port", "lat": 31.23, "lon": 121.47, "region_code": "shanghai"},
    {"name": "Rotterdam", "lat": 51.92, "lon": 4.48, "region_code": "rotterdam"},
    {"name": "Singapore Strait", "lat": 1.26, "lon": 103.82, "region_code": "singapore"},
    {"name": "Suez Canal", "lat": 30.46, "lon": 32.35, "region_code": "suez"},
    {"name": "Panama Canal", "lat": 9.08, "lon": -79.68, "region_code": "panama"},
    {"name": "Shenzhen", "lat": 22.54, "lon": 114.06, "region_code": "shenzhen"},
]

# NWS Alerts API (US only)
NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

# Severity mapping
WEATHER_SEVERITY = {
    "Extreme": "CRITICAL",
    "Severe": "HIGH",
    "Moderate": "MEDIUM",
    "Minor": "LOW",
}


def _fetch_nws_alerts():
    """Fetch active severe weather alerts from NWS."""
    alerts = []
    try:
        resp = requests.get(
            NWS_ALERTS_URL,
            params={"status": "actual", "message_type": "alert"},
            headers={"User-Agent": "SupplyChainGhost/1.0"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        for feature in data.get("features", [])[:30]:
            props = feature.get("properties", {})
            severity = props.get("severity", "Unknown")
            if severity in ("Extreme", "Severe"):
                alerts.append({
                    "source": "NWS",
                    "event": props.get("event", ""),
                    "headline": props.get("headline", ""),
                    "severity": WEATHER_SEVERITY.get(severity, "MEDIUM"),
                    "area": props.get("areaDesc", ""),
                    "onset": props.get("onset", ""),
                    "expires": props.get("expires", ""),
                    "description": (props.get("description", ""))[:500],
                })
    except Exception as e:
        logger.error("NWS fetch failed: %s", str(e))
    return alerts


def _fetch_weather_for_region(region: dict):
    """Fetch current weather conditions for a monitored region (simulated)."""
    # In production, use OpenWeatherMap or similar API
    # Here we use NWS-style response format
    return {
        "region": region["name"],
        "region_code": region["region_code"],
        "lat": region["lat"],
        "lon": region["lon"],
        "conditions": "monitoring",
        "wind_speed_knots": 0,
        "wave_height_m": 0,
        "visibility_nm": 10,
    }


def handler(event, context):
    """
    Triggered by EventBridge schedule or weather webhook.
    Collects severe weather alerts and regional conditions.
    """
    logger.info("WeatherCollector invoked: %s", json.dumps(event, default=str))

    table = DDB.Table(SIGNALS_TABLE)
    ts = datetime.now(timezone.utc).isoformat()
    signals_found = 0

    # 1. Fetch NWS severe alerts
    alerts = _fetch_nws_alerts()
    for alert in alerts:
        signal_id = f"weather-{alert['event'][:20].replace(' ', '_').lower()}-{ts[:13]}"
        signal = {
            "signal_id": signal_id,
            "timestamp": ts,
            "signal_type": "WEATHER",
            "source": "NWS",
            "title": alert["headline"][:200],
            "summary": alert["description"],
            "severity": alert["severity"],
            "area": alert["area"][:200],
            "event_type": alert["event"],
            "onset": alert.get("onset", ""),
            "expires": alert.get("expires", ""),
            "ttl": int(datetime.now(timezone.utc).timestamp()) + 86400 * 3,
        }
        table.put_item(Item=signal)
        signals_found += 1

        S3.put_object(
            Bucket=RAW_BUCKET,
            Key=f"weather/{ts[:10]}/{signal_id}.json",
            Body=json.dumps(signal, default=str),
            ContentType="application/json",
        )

    # 2. Monitor regions
    for region in MONITORED_REGIONS:
        try:
            conditions = _fetch_weather_for_region(region)
            S3.put_object(
                Bucket=RAW_BUCKET,
                Key=f"weather/regions/{region['region_code']}/{ts[:10]}.json",
                Body=json.dumps(conditions, default=str),
                ContentType="application/json",
            )
        except Exception as e:
            logger.error("Weather fetch failed for %s: %s", region["name"], str(e))

    logger.info("WeatherCollector complete: %d signals found", signals_found)
    return {"signals_found": signals_found, "source": "WeatherCollector"}
