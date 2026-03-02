"""
DecisionEngine Lambda — Cost-based decision logic.

Implements the decision formula:
  Expected Delay Cost = (Estimated Delay Days × Revenue Loss Per Day) × Reliability Risk Multiplier
  Switch Cost = (New Supplier Price - Old Supplier Price) × Quantity + Expedited Freight
  If Delay Cost > Switch Cost → Act.
"""
import os
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DDB = boto3.resource("dynamodb")
RISK_TABLE = os.environ["RISK_TABLE"]

# ── Supplier Database (in production: from DynamoDB/Aurora) ──
SUPPLIERS = {
    "Supplier A": {
        "name": "Shenzhen Electronics Co",
        "reliability_score": 0.62,
        "unit_price": 45.00,
        "lead_time_days": 14,
        "region": "Asia-Pacific",
        "port": "CNSZN",
    },
    "Supplier B": {
        "name": "Taiwan Semiconductor",
        "reliability_score": 0.85,
        "unit_price": 52.00,
        "lead_time_days": 10,
        "region": "Asia-Pacific",
        "port": "TWKHH",
    },
    "Supplier C": {
        "name": "Rotterdam Logistics",
        "reliability_score": 0.78,
        "unit_price": 48.00,
        "lead_time_days": 7,
        "region": "Europe",
        "port": "NLRTM",
    },
    "Supplier D": {
        "name": "Vietnam Manufacturing",
        "reliability_score": 0.71,
        "unit_price": 40.00,
        "lead_time_days": 16,
        "region": "Asia-Pacific",
        "port": "VNSGN",
    },
}

# Revenue sensitivity per product line
REVENUE_PER_DAY = {
    "Product Line Alpha": 125000,
    "Product Line Beta": 85000,
    "Product Line Gamma": 45000,
}

# Default parameters
DEFAULT_QUANTITY = 5000
EXPEDITED_FREIGHT_BASE = 15000
CONFIDENCE_THRESHOLD = 50
RISK_SCORE_ACT_THRESHOLD = 40


def _calculate_delay_cost(delay_days: int, revenue_per_day: float, reliability_multiplier: float) -> float:
    """
    Expected Delay Cost = (Estimated Delay Days × Revenue Loss Per Day) × Reliability Risk Multiplier
    """
    return delay_days * revenue_per_day * reliability_multiplier


def _calculate_switch_cost(
    old_price: float, new_price: float, quantity: int, expedited: bool = True
) -> float:
    """
    Switch Cost = (New Supplier Price - Old Supplier Price) × Quantity + Expedited Freight
    """
    price_diff_cost = (new_price - old_price) * quantity
    freight = EXPEDITED_FREIGHT_BASE if expedited else 0
    return max(0, price_diff_cost + freight)


def _find_best_alternative(affected_suppliers: list, assessment: dict) -> dict:
    """Find the best alternative supplier based on cost and reliability."""
    affected_names = [s.lower() for s in affected_suppliers]
    alternatives = []

    for name, info in SUPPLIERS.items():
        if name.lower() not in affected_names:
            alternatives.append({
                "supplier_name": name,
                **info,
                "score": info["reliability_score"] * 100 - info["lead_time_days"] * 2,
            })

    alternatives.sort(key=lambda x: x["score"], reverse=True)
    return alternatives[0] if alternatives else None


def handler(event, context):
    """
    Decision engine handler.
    
    Takes reasoning + verification output and makes a cost-based decision.
    """
    logger.info("DecisionEngine invoked")

    # Get assessment data (from Step Functions or direct)
    assessment = event.get("verification", event.get("reasoning", event))
    risk_score = float(assessment.get("verified_risk_score", assessment.get("risk_score", 0)))
    confidence = float(assessment.get("confidence_pct", 0))
    delay_days = int(assessment.get("estimated_delay_days", 0))
    affected_suppliers = assessment.get("affected_suppliers", [])
    recommendation = assessment.get("action_recommendation", "MONITOR")

    # ── Confidence Gate ──
    if confidence < CONFIDENCE_THRESHOLD:
        decision = {
            "action": "ESCALATE",
            "reason": f"Model confidence ({confidence}%) below threshold ({CONFIDENCE_THRESHOLD}%)",
            "risk_score": risk_score,
            "confidence_pct": confidence,
            "requires_human": True,
        }
        logger.info("Decision: ESCALATE (low confidence)")
        return decision

    # ── Low Risk — Monitor ──
    if risk_score < RISK_SCORE_ACT_THRESHOLD:
        decision = {
            "action": "MONITOR",
            "reason": f"Risk score ({risk_score}) below action threshold ({RISK_SCORE_ACT_THRESHOLD})",
            "risk_score": risk_score,
            "confidence_pct": confidence,
            "requires_human": False,
        }
        logger.info("Decision: MONITOR")
        return decision

    # ── Cost Analysis ──
    # Find affected supplier details
    primary_supplier = None
    for name in affected_suppliers:
        if name in SUPPLIERS:
            primary_supplier = SUPPLIERS[name]
            primary_supplier["supplier_key"] = name
            break

    if not primary_supplier:
        primary_supplier = SUPPLIERS.get("Supplier A", {})
        primary_supplier["supplier_key"] = "Supplier A"

    # Find best alternative
    alternative = _find_best_alternative(affected_suppliers, assessment)

    if not alternative:
        decision = {
            "action": "ESCALATE",
            "reason": "No alternative suppliers available",
            "risk_score": risk_score,
            "requires_human": True,
        }
        return decision

    # Calculate costs
    reliability_multiplier = 1 + (1 - primary_supplier.get("reliability_score", 0.5))
    avg_revenue_per_day = sum(REVENUE_PER_DAY.values()) / len(REVENUE_PER_DAY)

    delay_cost = _calculate_delay_cost(delay_days, avg_revenue_per_day, reliability_multiplier)
    switch_cost = _calculate_switch_cost(
        primary_supplier.get("unit_price", 0),
        alternative.get("unit_price", 0),
        DEFAULT_QUANTITY,
        expedited=True,
    )

    # ── Decision Logic ──
    should_switch = delay_cost > switch_cost

    decision = {
        "action": "SWITCH_SUPPLIER" if should_switch else "ALERT",
        "risk_score": risk_score,
        "confidence_pct": confidence,
        "estimated_delay_days": delay_days,
        "requires_human": should_switch,  # Switching always needs approval

        # Cost breakdown
        "cost_analysis": {
            "expected_delay_cost_usd": round(delay_cost, 2),
            "switch_cost_usd": round(switch_cost, 2),
            "net_savings_usd": round(delay_cost - switch_cost, 2),
            "delay_cost_per_day_usd": round(avg_revenue_per_day * reliability_multiplier, 2),
            "reliability_multiplier": round(reliability_multiplier, 3),
        },

        # Supplier comparison
        "current_supplier": {
            "name": primary_supplier["supplier_key"],
            "full_name": primary_supplier.get("name", ""),
            "reliability_score": primary_supplier.get("reliability_score", 0),
            "unit_price": primary_supplier.get("unit_price", 0),
            "lead_time_days": primary_supplier.get("lead_time_days", 0),
        },
        "recommended_supplier": {
            "name": alternative["supplier_name"],
            "full_name": alternative.get("name", ""),
            "reliability_score": alternative.get("reliability_score", 0),
            "unit_price": alternative.get("unit_price", 0),
            "lead_time_days": alternative.get("lead_time_days", 0),
        },

        # Order details
        "proposed_order": {
            "quantity": DEFAULT_QUANTITY,
            "unit_price": alternative.get("unit_price", 0),
            "total_cost": alternative.get("unit_price", 0) * DEFAULT_QUANTITY,
            "expected_delivery_days": alternative.get("lead_time_days", 0),
            "expedited": True,
        },

        "reason": (
            f"Delay cost (${delay_cost:,.0f}) {'>' if should_switch else '<='} "
            f"Switch cost (${switch_cost:,.0f}). "
            f"Net {'savings' if should_switch else 'loss'}: ${abs(delay_cost - switch_cost):,.0f}. "
            f"Recommend {'switching to' if should_switch else 'monitoring'} "
            f"{alternative['supplier_name']}."
        ),

        "decided_at": datetime.now(timezone.utc).isoformat(),
        "assessment_id": assessment.get("assessment_id", ""),
    }

    # Update risk table
    if assessment.get("assessment_id"):
        risk_table = DDB.Table(RISK_TABLE)
        try:
            risk_table.update_item(
                Key={
                    "assessment_id": assessment["assessment_id"],
                    "created_at": assessment.get("created_at", ""),
                },
                UpdateExpression="SET decision = :d, #st = :status",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":d": json.loads(json.dumps(decision, default=str), parse_float=Decimal),
                    ":status": "DECIDED",
                },
            )
        except Exception as e:
            logger.error("Failed to update risk table: %s", str(e))

    logger.info("Decision: %s (delay=$%s switch=$%s)", decision["action"], delay_cost, switch_cost)
    return decision
