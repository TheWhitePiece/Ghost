"""
CommodityPriceCollector Lambda — Tracks raw material and commodity price changes.
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

# Commodities critical to supply chain
COMMODITIES = [
    {"symbol": "CL=F", "name": "Crude Oil WTI", "unit": "USD/barrel", "threshold_pct": 5.0},
    {"symbol": "NG=F", "name": "Natural Gas", "unit": "USD/MMBtu", "threshold_pct": 8.0},
    {"symbol": "HG=F", "name": "Copper", "unit": "USD/lb", "threshold_pct": 4.0},
    {"symbol": "ALI=F", "name": "Aluminum", "unit": "USD/ton", "threshold_pct": 5.0},
    {"symbol": "SI=F", "name": "Silver", "unit": "USD/oz", "threshold_pct": 5.0},
    {"symbol": "LBR", "name": "Lumber", "unit": "USD/board foot", "threshold_pct": 7.0},
    {"symbol": "CT=F", "name": "Cotton", "unit": "USD/lb", "threshold_pct": 6.0},
    {"symbol": "ZS=F", "name": "Soybeans", "unit": "USD/bushel", "threshold_pct": 5.0},
    {"symbol": "SEMI", "name": "Semiconductor Index", "unit": "index", "threshold_pct": 3.0},
    {"symbol": "BDI", "name": "Baltic Dry Index", "unit": "index", "threshold_pct": 10.0},
]


def _fetch_commodity_price(commodity: dict) -> dict:
    """
    Fetch latest price data for a commodity.
    In production: integrate with Alpha Vantage, Quandl, or Bloomberg API.
    """
    return {
        "symbol": commodity["symbol"],
        "name": commodity["name"],
        "unit": commodity["unit"],
        "current_price": 0.0,
        "previous_close": 0.0,
        "change_pct": 0.0,
        "day_high": 0.0,
        "day_low": 0.0,
        "volume": 0,
        "data_source": "simulated",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def handler(event, context):
    """
    Triggered by EventBridge schedule.
    Monitors commodity prices and flags significant movements.
    """
    logger.info("CommodityPriceCollector invoked: %s", json.dumps(event, default=str))

    table = DDB.Table(SIGNALS_TABLE)
    ts = datetime.now(timezone.utc).isoformat()
    signals_found = 0

    for commodity in COMMODITIES:
        try:
            data = _fetch_commodity_price(commodity)

            # Store raw
            S3.put_object(
                Bucket=RAW_BUCKET,
                Key=f"commodities/{commodity['symbol']}/{ts[:10]}.json",
                Body=json.dumps(data, default=str),
                ContentType="application/json",
            )

            # Check threshold
            change_pct = abs(data["change_pct"])
            if change_pct >= commodity["threshold_pct"]:
                direction = "surge" if data["change_pct"] > 0 else "drop"
                severity = "HIGH" if change_pct >= commodity["threshold_pct"] * 1.5 else "MEDIUM"

                signal_id = f"commodity-{commodity['symbol'].lower().replace('=', '')}-{ts[:10]}"
                signal = {
                    "signal_id": signal_id,
                    "timestamp": ts,
                    "signal_type": "COMMODITY_PRICE",
                    "source": f"commodity:{commodity['symbol']}",
                    "title": f"{commodity['name']} price {direction}: {data['change_pct']:.1f}%",
                    "summary": (
                        f"{commodity['name']} ({commodity['symbol']}) moved {data['change_pct']:.1f}% "
                        f"to {data['current_price']} {commodity['unit']}. "
                        f"Threshold: {commodity['threshold_pct']}%."
                    ),
                    "severity": severity,
                    "commodity_symbol": commodity["symbol"],
                    "commodity_name": commodity["name"],
                    "change_pct": Decimal(str(round(data["change_pct"], 2))),
                    "current_price": Decimal(str(round(data["current_price"], 4))),
                    "ttl": int(datetime.now(timezone.utc).timestamp()) + 86400,
                }
                table.put_item(Item=signal)
                signals_found += 1

        except Exception as e:
            logger.error("Commodity %s failed: %s", commodity["symbol"], str(e))

    logger.info("CommodityPriceCollector complete: %d signals", signals_found)
    return {"signals_found": signals_found, "source": "CommodityPriceCollector"}
