"""
SatelliteMetadataCollector Lambda — Retrieves port satellite image metadata
for visual verification by Nova 2 Omni.
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


def _fetch_satellite_metadata(aoi: dict) -> dict:
    """
    Fetch recent satellite image metadata for an area of interest.
    In production: integrate with Sentinel Hub, Planet, or Maxar APIs
    for actual satellite imagery and vessel detection.
    """
    return {
        "port_code": aoi["port_code"],
        "port_name": aoi["name"],
        "bbox": aoi["bbox"],
        "latest_image": {
            "acquisition_date": datetime.now(timezone.utc).isoformat(),
            "satellite": "Sentinel-2",
            "resolution_m": 10,
            "cloud_cover_pct": 15.0,
            "image_id": f"S2_{aoi['port_code']}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        },
        "vessel_detection": {
            "detected_vessels": 0,
            "vessels_at_anchor": 0,
            "vessels_in_transit": 0,
            "dock_occupancy_pct": 0.0,
            "movement_density_index": 0.0,
        },
        "change_detection": {
            "compared_to": "7_days_ago",
            "vessel_count_change_pct": 0.0,
            "dock_occupancy_change_pct": 0.0,
        },
        "image_available_for_analysis": True,
        "data_source": "simulated",
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

            # Check for anomalies
            vessel_change = metadata["change_detection"]["vessel_count_change_pct"]
            dock_change = metadata["change_detection"]["dock_occupancy_change_pct"]

            if abs(vessel_change) >= 30 or abs(dock_change) >= 20:
                severity = "HIGH" if abs(vessel_change) >= 50 or abs(dock_change) >= 40 else "MEDIUM"

                signal_id = f"satellite-{aoi['port_code'].lower()}-{ts[:10]}"
                signal = {
                    "signal_id": signal_id,
                    "timestamp": ts,
                    "signal_type": "SATELLITE",
                    "source": f"satellite:{aoi['port_code']}",
                    "title": f"Satellite anomaly at {aoi['name']}",
                    "summary": (
                        f"Vessel count change: {vessel_change:+.1f}%, "
                        f"Dock occupancy change: {dock_change:+.1f}%. "
                        f"Detected vessels: {metadata['vessel_detection']['detected_vessels']}."
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
