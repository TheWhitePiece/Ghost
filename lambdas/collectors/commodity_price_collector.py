"""
CommodityPriceCollector Lambda — Tracks raw material and commodity price changes.

Uses Alpha Vantage (free tier, 25 req/day) as primary source and Yahoo Finance
(yfinance-style scraping) as fallback.

Env vars:
    RAW_BUCKET               — S3 bucket for raw data
    SIGNALS_TABLE            — DynamoDB signals table
    ALPHA_VANTAGE_API_KEY    — Alpha Vantage API key (free: https://www.alphavantage.co/support/)
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

ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")

# Commodities critical to supply chain — with Alpha Vantage function/symbol mapping
COMMODITIES = [
    {"symbol": "CL=F", "av_function": "WTI", "av_symbol": "WTI", "name": "Crude Oil WTI", "unit": "USD/barrel", "threshold_pct": 5.0},
    {"symbol": "NG=F", "av_function": "NATURAL_GAS", "av_symbol": "NATURAL_GAS", "name": "Natural Gas", "unit": "USD/MMBtu", "threshold_pct": 8.0},
    {"symbol": "HG=F", "av_function": "COPPER", "av_symbol": "COPPER", "name": "Copper", "unit": "USD/lb", "threshold_pct": 4.0},
    {"symbol": "ALI=F", "av_function": "ALUMINUM", "av_symbol": "ALUMINUM", "name": "Aluminum", "unit": "USD/ton", "threshold_pct": 5.0},
    {"symbol": "SI=F", "av_function": "GLOBAL_QUOTE", "av_symbol": "SLV", "name": "Silver", "unit": "USD/oz", "threshold_pct": 5.0},
    {"symbol": "LBR", "av_function": "GLOBAL_QUOTE", "av_symbol": "WOOD", "name": "Lumber", "unit": "USD/board foot", "threshold_pct": 7.0},
    {"symbol": "CT=F", "av_function": "COTTON", "av_symbol": "COTTON", "name": "Cotton", "unit": "USD/lb", "threshold_pct": 6.0},
    {"symbol": "ZS=F", "av_function": "GLOBAL_QUOTE", "av_symbol": "SOYB", "name": "Soybeans", "unit": "USD/bushel", "threshold_pct": 5.0},
    {"symbol": "SEMI", "av_function": "GLOBAL_QUOTE", "av_symbol": "SOXX", "name": "Semiconductor Index", "unit": "index", "threshold_pct": 3.0},
    {"symbol": "BDI", "av_function": "GLOBAL_QUOTE", "av_symbol": "BDRY", "name": "Baltic Dry Index", "unit": "index", "threshold_pct": 10.0},
]


# ── Price data providers ─────────────────────────────────────────────────

def _fetch_alpha_vantage_commodity(commodity: dict) -> dict | None:
    """Fetch price from Alpha Vantage commodity endpoint or GLOBAL_QUOTE."""
    if not ALPHA_VANTAGE_KEY:
        return None

    try:
        av_fn = commodity.get("av_function", "GLOBAL_QUOTE")
        av_sym = commodity.get("av_symbol", commodity["symbol"])

        if av_fn in ("WTI", "NATURAL_GAS", "COPPER", "ALUMINUM", "COTTON"):
            # Alpha Vantage commodity-specific endpoints
            resp = requests.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": av_fn,
                    "interval": "daily",
                    "apikey": ALPHA_VANTAGE_KEY,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            # Parse time-series data (key varies: "data" list)
            series = data.get("data", [])
            if len(series) >= 2:
                current = float(series[0].get("value", 0))
                previous = float(series[1].get("value", 0))
                if previous > 0:
                    change_pct = ((current - previous) / previous) * 100
                    return {
                        "current_price": round(current, 4),
                        "previous_close": round(previous, 4),
                        "change_pct": round(change_pct, 2),
                        "day_high": round(current * 1.005, 4),
                        "day_low": round(current * 0.995, 4),
                        "volume": 0,
                        "data_source": "alpha_vantage",
                    }
        else:
            # GLOBAL_QUOTE for ETF/index proxies
            resp = requests.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol": av_sym,
                    "apikey": ALPHA_VANTAGE_KEY,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            quote = data.get("Global Quote", {})
            current = float(quote.get("05. price", 0))
            previous = float(quote.get("08. previous close", 0))
            if previous > 0 and current > 0:
                change_pct = ((current - previous) / previous) * 100
                return {
                    "current_price": round(current, 4),
                    "previous_close": round(previous, 4),
                    "change_pct": round(change_pct, 2),
                    "day_high": round(float(quote.get("03. high", current)), 4),
                    "day_low": round(float(quote.get("04. low", current)), 4),
                    "volume": int(quote.get("06. volume", 0)),
                    "data_source": "alpha_vantage",
                }
    except Exception as e:
        logger.warning("Alpha Vantage failed for %s: %s", commodity["symbol"], e)
    return None


def _fetch_yahoo_finance(commodity: dict) -> dict | None:
    """Fallback: scrape Yahoo Finance v8 quote API."""
    yf_symbol = commodity["symbol"]
    # Map our symbols to Yahoo Finance tickers
    yf_map = {
        "SEMI": "SOXX", "BDI": "BDRY", "LBR": "WOOD",
    }
    yf_symbol = yf_map.get(yf_symbol, yf_symbol)

    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}",
            params={"range": "2d", "interval": "1d"},
            headers={"User-Agent": "SupplyChainGhost/1.0"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if len(closes) >= 2 and closes[-1] and closes[-2]:
            current = float(closes[-1])
            previous = float(closes[-2])
            change_pct = ((current - previous) / previous) * 100 if previous else 0
            return {
                "current_price": round(current, 4),
                "previous_close": round(previous, 4),
                "change_pct": round(change_pct, 2),
                "day_high": round(current * 1.005, 4),
                "day_low": round(current * 0.995, 4),
                "volume": 0,
                "data_source": "yahoo_finance",
            }
    except Exception as e:
        logger.warning("Yahoo Finance failed for %s: %s", commodity["symbol"], e)
    return None


def _fetch_commodity_price(commodity: dict) -> dict:
    """
    Fetch latest price data for a commodity.
    Primary: Alpha Vantage.  Fallback: Yahoo Finance.
    """
    result = _fetch_alpha_vantage_commodity(commodity)
    if not result:
        result = _fetch_yahoo_finance(commodity)
    if not result:
        logger.warning("No price data for %s — all providers failed", commodity["symbol"])
        result = {
            "current_price": 0.0, "previous_close": 0.0, "change_pct": 0.0,
            "day_high": 0.0, "day_low": 0.0, "volume": 0,
            "data_source": "unavailable",
        }

    return {
        "symbol": commodity["symbol"],
        "name": commodity["name"],
        "unit": commodity["unit"],
        **result,
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
