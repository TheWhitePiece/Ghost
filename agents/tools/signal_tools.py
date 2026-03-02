"""
Signal collection tools for the Strands Agent.
"""
import json
import boto3
from datetime import datetime, timezone, timedelta
from strands import tool

LAMBDA_CLIENT = boto3.client("lambda")
DDB = boto3.resource("dynamodb")


@tool
def collect_signals(source: str = "all") -> str:
    """
    Trigger signal collection from all data sources.
    
    Args:
        source: Which collectors to trigger. Options: "all", "news", "weather", "ports", "commodities", "satellite"
    
    Returns:
        Summary of signals collected from each source.
    """
    collectors = {
        "news": "SCG-NewsCollector",
        "weather": "SCG-WeatherCollector",
        "ports": "SCG-PortCongestionCollector",
        "commodities": "SCG-CommodityPriceCollector",
        "satellite": "SCG-SatelliteMetadataCollector",
    }

    if source != "all":
        collectors = {source: collectors.get(source, "")}

    results = {}
    for name, fn_name in collectors.items():
        if not fn_name:
            results[name] = {"error": f"Unknown source: {name}"}
            continue
        try:
            response = LAMBDA_CLIENT.invoke(
                FunctionName=fn_name,
                InvocationType="RequestResponse",
                Payload=json.dumps({"source": "agent"}),
            )
            results[name] = json.loads(response["Payload"].read())
        except Exception as e:
            results[name] = {"error": str(e)}

    total = sum(r.get("signals_found", 0) for r in results.values() if isinstance(r, dict))
    return json.dumps({
        "total_signals": total,
        "by_source": results,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }, default=str)


@tool
def get_recent_signals(hours: int = 6, signal_type: str = "") -> str:
    """
    Retrieve recent signals from the database.
    
    Args:
        hours: How many hours back to look (default: 6)
        signal_type: Filter by type (NEWS, WEATHER, PORT_CONGESTION, COMMODITY_PRICE, SATELLITE). Empty for all.
    
    Returns:
        List of recent signals with their details.
    """
    import os
    table = DDB.Table(os.environ.get("SIGNALS_TABLE", "SCG_Signals"))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    if signal_type:
        response = table.query(
            IndexName="by-type",
            KeyConditionExpression="signal_type = :t AND #ts >= :cutoff",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":t": signal_type,
                ":cutoff": cutoff,
            },
            ScanIndexForward=False,
            Limit=20,
        )
    else:
        response = table.scan(
            FilterExpression="#ts >= :cutoff",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={":cutoff": cutoff},
            Limit=50,
        )

    items = response.get("Items", [])
    return json.dumps({
        "signals": items,
        "count": len(items),
        "filter": {"hours": hours, "type": signal_type},
    }, default=str)
