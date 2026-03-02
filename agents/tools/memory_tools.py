"""
Memory tools for the Strands Agent — Bedrock Memory integration.
"""
import json
import boto3
from datetime import datetime, timezone
from strands import tool

DDB = boto3.resource("dynamodb")


# In production, integrate with Bedrock Memory API.
# For now, use DynamoDB as memory store.

SUPPLIER_MEMORY = {
    "Supplier A": {
        "name": "Shenzhen Electronics Co",
        "reliability_score": 62,
        "history": [
            {"event": "2025 Hurricane Florida", "delay_days": 12, "date": "2025-09-15"},
            {"event": "2025 Port strike", "delay_days": 9, "date": "2025-11-02"},
        ],
        "notes": "Frequent delays during storm season. Consider diversifying.",
    },
    "Supplier B": {
        "name": "Taiwan Semiconductor",
        "reliability_score": 85,
        "history": [
            {"event": "2025 Chip shortage", "delay_days": 5, "date": "2025-03-20"},
        ],
        "notes": "Generally reliable. Higher price but consistent quality.",
    },
    "Supplier C": {
        "name": "Rotterdam Logistics",
        "reliability_score": 78,
        "history": [
            {"event": "2025 Suez disruption", "delay_days": 15, "date": "2025-06-10"},
        ],
        "notes": "Good recovery speed. Strategic European hub.",
    },
    "Supplier D": {
        "name": "Vietnam Manufacturing",
        "reliability_score": 71,
        "history": [
            {"event": "2025 Monsoon season", "delay_days": 8, "date": "2025-07-25"},
        ],
        "notes": "Improving trend. Competitive pricing.",
    },
}


@tool
def get_supplier_memory(supplier_name: str = "") -> str:
    """
    Retrieve memory (historical performance) for a supplier or all suppliers.
    
    Args:
        supplier_name: Specific supplier name (e.g., "Supplier A"). Empty for all.
    
    Returns:
        Supplier reliability data, historical delays, and notes.
    """
    if supplier_name and supplier_name in SUPPLIER_MEMORY:
        return json.dumps({supplier_name: SUPPLIER_MEMORY[supplier_name]}, default=str)
    elif supplier_name:
        # Search by fuzzy match
        for key, data in SUPPLIER_MEMORY.items():
            if supplier_name.lower() in key.lower() or supplier_name.lower() in data["name"].lower():
                return json.dumps({key: data}, default=str)
        return json.dumps({"error": f"Supplier '{supplier_name}' not found"})
    else:
        return json.dumps(SUPPLIER_MEMORY, default=str)


@tool
def update_supplier_memory(supplier_name: str, event_description: str, delay_days: int, notes: str = "") -> str:
    """
    Update supplier memory with a new event (for learning from outcomes).
    
    Args:
        supplier_name: Supplier name (e.g., "Supplier A")
        event_description: Description of the disruption event
        delay_days: Actual delay experienced in days
        notes: Additional notes
    
    Returns:
        Updated supplier memory entry.
    """
    if supplier_name not in SUPPLIER_MEMORY:
        return json.dumps({"error": f"Supplier '{supplier_name}' not found"})

    SUPPLIER_MEMORY[supplier_name]["history"].append({
        "event": event_description,
        "delay_days": delay_days,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    })

    if notes:
        SUPPLIER_MEMORY[supplier_name]["notes"] = notes

    # Recalculate reliability score
    delays = [h["delay_days"] for h in SUPPLIER_MEMORY[supplier_name]["history"]]
    avg_delay = sum(delays) / len(delays)
    # Simple reliability formula: 100 - (avg_delay * 3), min 20
    new_score = max(20, int(100 - avg_delay * 3))
    SUPPLIER_MEMORY[supplier_name]["reliability_score"] = new_score

    return json.dumps({
        "updated": True,
        "supplier": supplier_name,
        "new_reliability_score": new_score,
        "total_events": len(SUPPLIER_MEMORY[supplier_name]["history"]),
    }, default=str)
