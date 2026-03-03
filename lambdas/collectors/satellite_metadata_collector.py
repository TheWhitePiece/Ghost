"""
SatelliteMetadataCollector Lambda — Retrieves port satellite imagery and metadata
for visual verification by Nova Premier.

Uses Sentinel Hub (ESA Copernicus) free tier for Sentinel-2 imagery.
Stores actual images to S3 at the path the verification engine expects.

Env vars:
    RAW_BUCKET                   — S3 bucket for raw data / images
    SIGNALS_TABLE                — DynamoDB signals table
    SENTINEL_HUB_CLIENT_ID       — Sentinel Hub OAuth client ID
    SENTINEL_HUB_CLIENT_SECRET   — Sentinel Hub OAuth client secret
    SENTINEL_HUB_INSTANCE_ID     — (optional) Sentinel Hub configuration instance
"""
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3 = boto3.client("s3")
DDB = boto3.resource("dynamodb")

RAW_BUCKET = os.environ["RAW_BUCKET"]
SIGNALS_TABLE = os.environ["SIGNALS_TABLE"]

SENTINEL_CLIENT_ID = os.environ.get("SENTINEL_HUB_CLIENT_ID", "")
SENTINEL_CLIENT_SECRET = os.environ.get("SENTINEL_HUB_CLIENT_SECRET", "")

# Port areas of interest for satellite monitoring
PORT_AOIS = [
    {
        "port_code": "USLAX",
        "name": "Los Angeles Port Complex",
        "bbox": [-118.30, 33.70, -118.20, 33.78],
    },
    {
        "port_code": "CNSHA",
        "name": "Shanghai Yangshan Deep-Water Port",
        "bbox": [121.90, 30.60, 122.10, 30.70],
    },
    {
        "port_code": "SGSIN",
        "name": "Singapore Port/Strait",
        "bbox": [103.75, 1.20, 103.90, 1.30],
    },
    {
        "port_code": "NLRTM",
        "name": "Rotterdam Europoort",
        "bbox": [3.90, 51.88, 4.50, 51.96],
    },
    {
        "port_code": "EGSCN",
        "name": "Suez Canal Northern Approach",
        "bbox": [32.30, 30.40, 32.40, 30.50],
    },
]


# ── Sentinel Hub integration ────────────────────────────────────────────

def _get_sentinel_token() -> str:
    """Obtain OAuth2 token from Sentinel Hub."""
    resp = requests.post(
        "https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": SENTINEL_CLIENT_ID,
            "client_secret": SENTINEL_CLIENT_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _search_sentinel_catalog(bbox: list, token: str) -> dict | None:
    """Search Sentinel Hub Catalog for recent Sentinel-2 scenes over the bbox."""
    now = datetime.now(timezone.utc)
    time_from = (now - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")
    time_to = now.strftime("%Y-%m-%dT23:59:59Z")

    search_body = {
        "bbox": bbox,
        "datetime": f"{time_from}/{time_to}",
        "collections": ["sentinel-2-l2a"],
        "limit": 5,
        "filter": "eo:cloud_cover < 40",
    }

    resp = requests.post(
        "https://services.sentinel-hub.com/api/v1/catalog/1.0.0/search",
        json=search_body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if features:
        # Return most recent, lowest cloud cover
        features.sort(key=lambda f: f["properties"].get("eo:cloud_cover", 100))
        return features[0]
    return None


def _download_sentinel_image(bbox: list, token: str, date_str: str) -> bytes | None:
    """Download a true-color Sentinel-2 image via the Process API."""
    evalscript = """
//VERSION=3
function setup() {
  return { input: ["B04","B03","B02"], output: { bands: 3 } };
}
function evaluatePixel(sample) {
  return [2.5*sample.B04, 2.5*sample.B03, 2.5*sample.B02];
}
"""
    process_body = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": f"{date_str}T00:00:00Z",
                        "to": f"{date_str}T23:59:59Z",
                    },
                    "maxCloudCoverage": 40,
                },
            }],
        },
        "output": {
            "width": 512, "height": 512,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": evalscript,
    }

    resp = requests.post(
        "https://services.sentinel-hub.com/api/v1/process",
        json=process_body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "image/png",
        },
        timeout=30,
    )
    if resp.status_code == 200 and len(resp.content) > 1000:
        return resp.content
    logger.warning("Sentinel image download returned status %s / %d bytes",
                    resp.status_code, len(resp.content))
    return None


def _fetch_satellite_metadata(aoi: dict) -> dict:
    """
    Fetch real satellite metadata + actual image for a port AOI.
    Primary: Sentinel Hub (ESA, free tier).
    Stores the image to S3 at satellite/{port_code}/{date}/image.png so
    the verification engine can consume it.
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data_source = "unavailable"
    image_bytes = None
    catalog_entry = None
    cloud_cover = 100.0

    if SENTINEL_CLIENT_ID and SENTINEL_CLIENT_SECRET:
        try:
            token = _get_sentinel_token()

            # 1. Search catalog for recent imagery
            catalog_entry = _search_sentinel_catalog(aoi["bbox"], token)
            if catalog_entry:
                acq_date = catalog_entry["properties"].get("datetime", date_str)[:10]
                cloud_cover = catalog_entry["properties"].get("eo:cloud_cover", 100.0)
                data_source = "sentinel_hub"

                # 2. Download actual image
                image_bytes = _download_sentinel_image(aoi["bbox"], token, acq_date)
                if image_bytes:
                    # 3. Store to S3 at the path verification_engine expects
                    s3_key = f"satellite/{aoi['port_code']}/{date_str}/image.png"
                    S3.put_object(
                        Bucket=RAW_BUCKET,
                        Key=s3_key,
                        Body=image_bytes,
                        ContentType="image/png",
                    )
                    logger.info("Stored satellite image: s3://%s/%s (%d bytes)",
                                RAW_BUCKET, s3_key, len(image_bytes))
                else:
                    logger.warning("Image download failed for %s", aoi["port_code"])
        except Exception as e:
            logger.warning("Sentinel Hub failed for %s: %s", aoi["port_code"], e)
    else:
        logger.warning("Sentinel Hub credentials not configured — no satellite imagery")

    image_available = image_bytes is not None and len(image_bytes) > 1000

    return {
        "port_code": aoi["port_code"],
        "port_name": aoi["name"],
        "bbox": aoi["bbox"],
        "latest_image": {
            "acquisition_date": (catalog_entry["properties"]["datetime"]
                                 if catalog_entry else datetime.now(timezone.utc).isoformat()),
            "satellite": "Sentinel-2" if catalog_entry else "N/A",
            "resolution_m": 10 if catalog_entry else 0,
            "cloud_cover_pct": cloud_cover,
            "image_id": (catalog_entry.get("id", "")
                         if catalog_entry
                         else f"NONE_{aoi['port_code']}_{date_str}"),
        },
        # Vessel detection is deferred to the verification engine (Nova Premier multimodal)
        "vessel_detection": {
            "detected_vessels": 0,
            "vessels_at_anchor": 0,
            "vessels_in_transit": 0,
            "dock_occupancy_pct": 0.0,
            "movement_density_index": 0.0,
            "detection_note": "Deferred to Nova Premier multimodal verification",
        },
        "change_detection": {
            "compared_to": "7_days_ago",
            "vessel_count_change_pct": 0.0,
            "dock_occupancy_change_pct": 0.0,
            "detection_note": "Deferred to Nova Premier multimodal verification",
        },
        "image_available_for_analysis": image_available,
        "image_size_bytes": len(image_bytes) if image_bytes else 0,
        "data_source": data_source,
    }


def handler(event, context):
    """
    Triggered by EventBridge schedule.
    Retrieves satellite metadata for port areas, flags anomalies.
    """
    logger.info("SatelliteMetadataCollector invoked: %s", json.dumps(event, default=str))

    table = DDB.Table(SIGNALS_TABLE)
    ts = datetime.now(timezone.utc).isoformat()
    signals_found = 0

    for aoi in PORT_AOIS:
        try:
            metadata = _fetch_satellite_metadata(aoi)

            # Store raw metadata
            S3.put_object(
                Bucket=RAW_BUCKET,
                Key=f"satellite/{aoi['port_code']}/{ts[:10]}/metadata.json",
                Body=json.dumps(metadata, default=str),
                ContentType="application/json",
            )

            # If imagery is available, create a signal so the verification
            # engine knows there is a fresh image to analyse with Nova Premier.
            # Anomaly detection (vessel clustering, change detection) is
            # performed by the multimodal verification engine, not here.
            vessel_change = metadata["change_detection"]["vessel_count_change_pct"]
            dock_change = metadata["change_detection"]["dock_occupancy_change_pct"]

            create_signal = (
                abs(vessel_change) >= 30
                or abs(dock_change) >= 20
                or metadata["image_available_for_analysis"]
            )

            if create_signal:
                severity = "HIGH" if abs(vessel_change) >= 50 or abs(dock_change) >= 40 else "MEDIUM"
                # If image is available but no change data yet, default to LOW
                # so that the verification engine can still pick it up.
                if abs(vessel_change) < 30 and abs(dock_change) < 20:
                    severity = "LOW"

                signal_id = f"satellite-{aoi['port_code'].lower()}-{ts[:10]}"
                signal = {
                    "signal_id": signal_id,
                    "timestamp": ts,
                    "signal_type": "SATELLITE",
                    "source": f"satellite:{aoi['port_code']}",
                    "title": f"Satellite image captured at {aoi['name']}",
                    "summary": (
                        f"Fresh satellite image available for analysis. "
                        f"Vessel count change: {vessel_change:+.1f}%, "
                        f"Dock occupancy change: {dock_change:+.1f}%. "
                        f"Data source: {metadata['data_source']}."
                    ),
                    "severity": severity,
                    "port_code": aoi["port_code"],
                    "port_name": aoi["name"],
                    "vessel_count_change_pct": Decimal(str(round(vessel_change, 2))),
                    "dock_occupancy_pct": Decimal(str(round(
                        metadata["vessel_detection"]["dock_occupancy_pct"], 2
                    ))),
                    "image_id": metadata["latest_image"]["image_id"],
                    "image_available": metadata["image_available_for_analysis"],
                    "ttl": int(datetime.now(timezone.utc).timestamp()) + 86400 * 3,
                }
                table.put_item(Item=signal)
                signals_found += 1

        except Exception as e:
            logger.error("Satellite metadata failed for %s: %s", aoi["port_code"], str(e))

    logger.info("SatelliteMetadataCollector complete: %d signals", signals_found)
    return {"signals_found": signals_found, "source": "SatelliteMetadataCollector"}
