"""
Memory tools for the Strands Agent — DynamoDB-backed supplier memory.

Reads/writes from the SCG_Suppliers DynamoDB table so that supplier
reliability scores, event history, and notes persist across Lambda
cold starts and are shared across all pipeline components.

Env vars:
    SUPPLIERS_TABLE — DynamoDB table name (default: SCG_Suppliers)
"""
import os
import json
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from strands import tool

DDB = boto3.resource("dynamodb")
SUPPLIERS_TABLE = os.environ.get("SUPPLIERS_TABLE", "SCG_Suppliers")

# ── Seed data: written to DDB on first access if table is empty ────────
_DEFAULT_SUPPLIERS = {
    "Supplier A": {
        "supplier_id": "Supplier A",
        "name": "Shenzhen Electronics Co",
        "reliability_score": 62,
        "history": [
            {"event": "2025 Hurricane Florida", "delay_days": 12, "date": "2025-09-15"},
            {"event": "2025 Port strike", "delay_days": 9, "date": "2025-11-02"},
        ],
        "notes": "Frequent delays during storm season. Consider diversifying.",
    },
    "Supplier B": {
        "supplier_id": "Supplier B",
        "name": "Taiwan Semiconductor",
        "reliability_score": 85,
        "history": [
            {"event": "2025 Chip shortage", "delay_days": 5, "date": "2025-03-20"},
        ],
        "notes": "Generally reliable. Higher price but consistent quality.",
    },
    "Supplier C": {
        "supplier_id": "Supplier C",
        "name": "Rotterdam Logistics",
        "reliability_score": 78,
        "history": [
            {"event": "2025 Suez disruption", "delay_days": 15, "date": "2025-06-10"},
        ],
        "notes": "Good recovery speed. Strategic European hub.",
    },
    "Supplier D": {
        "supplier_id": "Supplier D",
        "name": "Vietnam Manufacturing",
        "reliability_score": 71,
        "history": [
            {"event": "2025 Monsoon season", "delay_days": 8, "date": "2025-07-25"},
        ],
        "notes": "Improving trend. Competitive pricing.",
    },
}


def _get_table():
    return DDB.Table(SUPPLIERS_TABLE)


def _seed_if_empty():
    """Seed default supplier data into DynamoDB if the table is empty."""
    table = _get_table()
    resp = table.scan(Limit=1)
    if resp.get("Count", 0) == 0:
        for key, data in _DEFAULT_SUPPLIERS.items():
            item = json.loads(json.dumps(data, default=str), parse_float=Decimal)
            table.put_item(Item=item)


def _load_all_suppliers() -> dict:
    """Load all suppliers from DynamoDB."""
    _seed_if_empty()
    table = _get_table()
    resp = table.scan()
    suppliers = {}
    for item in resp.get("Items", []):
        sid = item.get("supplier_id", "")
        # Convert Decimals → int/float for JSON
        suppliers[sid] = json.loads(json.dumps(item, default=str))
    return suppliers


def _load_supplier(supplier_name: str) -> dict | None:
    """Load one supplier from DynamoDB by partition key."""
    table = _get_table()
    resp = table.get_item(Key={"supplier_id": supplier_name})
    item = resp.get("Item")
    if item:
        return json.loads(json.dumps(item, default=str))
    return None


@tool
def get_supplier_memory(supplier_name: str = "") -> str:
    """
    Retrieve memory (historical performance) for a supplier or all suppliers.
    
    Args:
        supplier_name: Specific supplier name (e.g., "Supplier A"). Empty for all.
    
    Returns:
        Supplier reliability data, historical delays, and notes.
    """
    if supplier_name:
        # Exact match first
        item = _load_supplier(supplier_name)
        if item:
            return json.dumps({supplier_name: item}, default=str)
        # Fuzzy match
        all_suppliers = _load_all_suppliers()
        for key, data in all_suppliers.items():
            if (supplier_name.lower() in key.lower()
                    or supplier_name.lower() in data.get("name", "").lower()):
                return json.dumps({key: data}, default=str)
        return json.dumps({"error": f"Supplier '{supplier_name}' not found"})
    else:
        return json.dumps(_load_all_suppliers(), default=str)


@tool
def update_supplier_memory(supplier_name: str, event_description: str, delay_days: int, notes: str = "") -> str:
    """
    Update supplier memory with a new event (for learning from outcomes).
    Persists to DynamoDB so the update survives Lambda cold-starts.
    
    Args:
        supplier_name: Supplier name (e.g., "Supplier A")
        event_description: Description of the disruption event
        delay_days: Actual delay experienced in days
        notes: Additional notes
    
    Returns:
        Updated supplier memory entry.
    """
    table = _get_table()
    item = _load_supplier(supplier_name)
    if not item:
        return json.dumps({"error": f"Supplier '{supplier_name}' not found"})

    # Append new history event
    history = item.get("history", [])
    history.append({
        "event": event_description,
        "delay_days": delay_days,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    })

    # Recalculate reliability score: 100 - (avg_delay * 3), min 20
    delays = [h["delay_days"] for h in history if isinstance(h.get("delay_days"), (int, float))]
    avg_delay = sum(delays) / len(delays) if delays else 0
    new_score = max(20, int(100 - avg_delay * 3))

    update_notes = notes if notes else item.get("notes", "")

    # Persist to DynamoDB
    table.update_item(
        Key={"supplier_id": supplier_name},
        UpdateExpression=(
            "SET history = :h, reliability_score = :r, notes = :n, updated_at = :u"
        ),
        ExpressionAttributeValues={
            ":h": json.loads(json.dumps(history, default=str), parse_float=Decimal),
            ":r": new_score,
            ":n": update_notes,
            ":u": datetime.now(timezone.utc).isoformat(),
        },
    )

    return json.dumps({
        "updated": True,
        "supplier": supplier_name,
        "new_reliability_score": new_score,
        "total_events": len(history),
    }, default=str)
