"""
WeatherCollector Lambda — Pulls storm, hurricane, and severe weather data.

- US regions: NWS API (National Weather Service) — free, no key needed.
- International regions: Open-Meteo API — free, no key needed.

Env vars:
    RAW_BUCKET    — S3 bucket for raw data
    SIGNALS_TABLE — DynamoDB signals table
    (optional) OPENWEATHERMAP_API_KEY — for enhanced international data
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
OWM_API_KEY = os.environ.get("OPENWEATHERMAP_API_KEY", "")

# Key supply chain regions to monitor
MONITORED_REGIONS = [
    {"name": "Gulf Coast", "lat": 29.76, "lon": -95.37, "region_code": "gulf", "country": "US"},
    {"name": "Los Angeles Port", "lat": 33.74, "lon": -118.26, "region_code": "la_port", "country": "US"},
    {"name": "Shanghai Port", "lat": 31.23, "lon": 121.47, "region_code": "shanghai", "country": "CN"},
    {"name": "Rotterdam", "lat": 51.92, "lon": 4.48, "region_code": "rotterdam", "country": "NL"},
    {"name": "Singapore Strait", "lat": 1.26, "lon": 103.82, "region_code": "singapore", "country": "SG"},
    {"name": "Suez Canal", "lat": 30.46, "lon": 32.35, "region_code": "suez", "country": "EG"},
    {"name": "Panama Canal", "lat": 9.08, "lon": -79.68, "region_code": "panama", "country": "PA"},
    {"name": "Shenzhen", "lat": 22.54, "lon": 114.06, "region_code": "shenzhen", "country": "CN"},
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

# WMO Weather Codes → description
WMO_CODES = {
    0: "Clear", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime Fog",
    51: "Light Drizzle", 53: "Moderate Drizzle", 55: "Heavy Drizzle",
    61: "Light Rain", 63: "Moderate Rain", 65: "Heavy Rain",
    71: "Light Snow", 73: "Moderate Snow", 75: "Heavy Snow",
    80: "Light Showers", 81: "Moderate Showers", 82: "Violent Showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ Hail", 99: "Severe Thunderstorm w/ Hail",
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


def _fetch_open_meteo(region: dict) -> dict:
    """Fetch current weather from Open-Meteo (free, no API key, worldwide)."""
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": region["lat"],
                "longitude": region["lon"],
                "current": "temperature_2m,wind_speed_10m,wind_gusts_10m,weather_code,precipitation",
                "wind_speed_unit": "kn",  # nautical knots
                "timezone": "auto",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})

        wind_knots = current.get("wind_speed_10m", 0)
        gusts_knots = current.get("wind_gusts_10m", 0)
        weather_code = current.get("weather_code", 0)
        precipitation = current.get("precipitation", 0)
        conditions = WMO_CODES.get(weather_code, "Unknown")

        # Estimate wave height from wind (Pierson-Moskowitz approx: Hs ≈ 0.02 * U^2 in m for knots)
        wave_height_m = round(0.02 * (wind_knots ** 1.5) / 10, 1) if wind_knots > 0 else 0

        # Estimate visibility (impaired by fog/heavy rain)
        if weather_code in (45, 48):
            visibility_nm = 0.5
        elif weather_code in (65, 75, 82, 95, 96, 99):
            visibility_nm = 2
        elif weather_code in (63, 73, 81):
            visibility_nm = 5
        else:
            visibility_nm = 10

        return {
            "region": region["name"],
            "region_code": region["region_code"],
            "lat": region["lat"],
            "lon": region["lon"],
            "conditions": conditions,
            "weather_code": weather_code,
            "wind_speed_knots": round(wind_knots, 1),
            "wind_gusts_knots": round(gusts_knots, 1),
            "wave_height_m": wave_height_m,
            "visibility_nm": round(visibility_nm, 1),
            "precipitation_mm": round(precipitation, 1),
            "temperature_c": current.get("temperature_2m", 0),
            "data_source": "open_meteo",
        }
    except Exception as e:
        logger.warning("Open-Meteo failed for %s: %s", region["name"], e)
        return {
            "region": region["name"],
            "region_code": region["region_code"],
            "lat": region["lat"],
            "lon": region["lon"],
            "conditions": "unavailable",
            "wind_speed_knots": 0,
            "wave_height_m": 0,
            "visibility_nm": 10,
            "data_source": "unavailable",
        }


def _fetch_openweathermap(region: dict) -> dict | None:
    """Optional enhanced provider: OpenWeatherMap (requires API key)."""
    if not OWM_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat": region["lat"],
                "lon": region["lon"],
                "appid": OWM_API_KEY,
                "units": "metric",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        wind_ms = data.get("wind", {}).get("speed", 0)
        wind_knots = round(wind_ms * 1.943844, 1)
        vis_m = data.get("visibility", 10000)
        vis_nm = round(vis_m / 1852, 1)
        conditions = data.get("weather", [{}])[0].get("main", "Unknown")
        return {
            "region": region["name"],
            "region_code": region["region_code"],
            "lat": region["lat"],
            "lon": region["lon"],
            "conditions": conditions,
            "wind_speed_knots": wind_knots,
            "wind_gusts_knots": round(data.get("wind", {}).get("gust", 0) * 1.943844, 1),
            "wave_height_m": round(0.02 * (wind_knots ** 1.5) / 10, 1) if wind_knots > 0 else 0,
            "visibility_nm": vis_nm,
            "precipitation_mm": data.get("rain", {}).get("1h", 0),
            "temperature_c": data.get("main", {}).get("temp", 0),
            "data_source": "openweathermap",
        }
    except Exception as e:
        logger.warning("OpenWeatherMap failed for %s: %s", region["name"], e)
        return None


def _fetch_weather_for_region(region: dict) -> dict:
    """Fetch current weather for any region worldwide.
    Primary: Open-Meteo (free, global).  Fallback: OpenWeatherMap (API key).
    """
    # Try OpenWeatherMap first if key is available (richer data)
    result = _fetch_openweathermap(region)
    if result:
        return result
    # Otherwise Open-Meteo (always free, no key)
    return _fetch_open_meteo(region)


def _assess_regional_weather(conditions: dict) -> tuple:
    """Assess regional weather severity and return (severity, reasons)."""
    reasons = []
    severity = "LOW"

    wind = conditions.get("wind_speed_knots", 0)
    gusts = conditions.get("wind_gusts_knots", 0)
    waves = conditions.get("wave_height_m", 0)
    vis = conditions.get("visibility_nm", 10)
    precip = conditions.get("precipitation_mm", 0)

    if wind >= 50 or gusts >= 65:
        severity = "HIGH"
        reasons.append(f"Storm-force winds: {wind} kn (gusts {gusts} kn)")
    elif wind >= 34 or gusts >= 45:
        severity = "MEDIUM" if severity != "HIGH" else severity
        reasons.append(f"Gale-force winds: {wind} kn (gusts {gusts} kn)")

    if waves >= 4:
        severity = "HIGH"
        reasons.append(f"Dangerous wave height: {waves}m")
    elif waves >= 2.5:
        severity = "MEDIUM" if severity != "HIGH" else severity
        reasons.append(f"Elevated waves: {waves}m")

    if vis <= 1:
        severity = "HIGH" if severity != "HIGH" else severity
        reasons.append(f"Very poor visibility: {vis} nm")
    elif vis <= 3:
        severity = "MEDIUM" if severity != "HIGH" else severity
        reasons.append(f"Reduced visibility: {vis} nm")

    if precip >= 30:
        severity = "HIGH" if severity != "HIGH" else severity
        reasons.append(f"Heavy precipitation: {precip} mm/h")

    return severity, reasons


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

    # 2. Monitor regions (international + US) with real weather data
    for region in MONITORED_REGIONS:
        try:
            conditions = _fetch_weather_for_region(region)
            S3.put_object(
                Bucket=RAW_BUCKET,
                Key=f"weather/regions/{region['region_code']}/{ts[:10]}.json",
                Body=json.dumps(conditions, default=str),
                ContentType="application/json",
            )

            # Assess severity and create signals for dangerous conditions
            severity, reasons = _assess_regional_weather(conditions)
            if severity in ("HIGH", "MEDIUM"):
                signal_id = f"weather-regional-{region['region_code']}-{ts[:13]}"
                signal = {
                    "signal_id": signal_id,
                    "timestamp": ts,
                    "signal_type": "WEATHER",
                    "source": f"weather:{region['region_code']}",
                    "title": f"Severe weather at {region['name']}: {conditions.get('conditions', 'Unknown')}",
                    "summary": "; ".join(reasons),
                    "severity": severity,
                    "area": region["name"],
                    "region_code": region["region_code"],
                    "wind_speed_knots": conditions.get("wind_speed_knots", 0),
                    "wave_height_m": conditions.get("wave_height_m", 0),
                    "visibility_nm": conditions.get("visibility_nm", 10),
                    "data_source": conditions.get("data_source", "unknown"),
                    "ttl": int(datetime.now(timezone.utc).timestamp()) + 86400 * 3,
                }
                table.put_item(Item=signal)
                signals_found += 1

        except Exception as e:
            logger.error("Weather fetch failed for %s: %s", region["name"], str(e))

    logger.info("WeatherCollector complete: %d signals found", signals_found)
    return {"signals_found": signals_found, "source": "WeatherCollector"}
