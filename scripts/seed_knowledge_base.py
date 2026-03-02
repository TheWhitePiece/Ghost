"""
Supply Chain Ghost — Seed Bedrock Knowledge Base
Uploads supplier data, historical disruptions, and SOP documents to S3
for RAG retrieval by the reasoning engine.
"""
import json
import boto3
import os
from datetime import datetime

s3 = boto3.client("s3")
KB_BUCKET = os.environ.get("SCG_KB_BUCKET", "scg-knowledge-base")


def upload_document(key: str, content: str, metadata: dict = None):
    """Upload a document to the knowledge base S3 bucket."""
    s3.put_object(
        Bucket=KB_BUCKET,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/plain",
        Metadata=metadata or {},
    )
    print(f"  Uploaded: {key}")


def seed_supplier_profiles():
    """Seed supplier reliability profiles."""
    suppliers = [
        {
            "supplier_id": "SUP-001",
            "name": "Shanghai Components Ltd",
            "region": "East China",
            "products": ["electronic_components", "semiconductors"],
            "reliability_score": 0.92,
            "avg_lead_time_days": 21,
            "annual_volume_usd": 12_000_000,
            "risk_factors": [
                "Typhoon-prone coastal location",
                "Single port dependency (Shanghai)",
                "High geopolitical exposure",
            ],
            "historical_disruptions": [
                {"date": "2024-09-15", "type": "port_closure", "duration_days": 4, "impact_usd": 340_000},
                {"date": "2024-03-22", "type": "covid_lockdown", "duration_days": 14, "impact_usd": 1_200_000},
            ],
        },
        {
            "supplier_id": "SUP-002",
            "name": "Rotterdam Industrial BV",
            "region": "Western Europe",
            "products": ["industrial_sensors", "control_modules"],
            "reliability_score": 0.96,
            "avg_lead_time_days": 14,
            "annual_volume_usd": 8_500_000,
            "risk_factors": [
                "Rhine River water level dependency",
                "EU regulatory exposure",
            ],
            "historical_disruptions": [
                {"date": "2024-07-10", "type": "heatwave", "duration_days": 3, "impact_usd": 85_000},
            ],
        },
        {
            "supplier_id": "SUP-003",
            "name": "Gulf Coast Petrochemicals Inc",
            "region": "US Gulf Coast",
            "products": ["specialty_plastics", "chemical_compounds"],
            "reliability_score": 0.88,
            "avg_lead_time_days": 7,
            "annual_volume_usd": 5_200_000,
            "risk_factors": [
                "Hurricane season (Jun-Nov)",
                "Petrochemical dependency chain",
                "Port of Houston congestion",
            ],
            "historical_disruptions": [
                {"date": "2024-08-28", "type": "hurricane", "duration_days": 8, "impact_usd": 620_000},
                {"date": "2023-09-05", "type": "hurricane", "duration_days": 5, "impact_usd": 410_000},
            ],
        },
        {
            "supplier_id": "SUP-004",
            "name": "Singapore Precision Pte Ltd",
            "region": "Southeast Asia",
            "products": ["precision_machined_parts", "optical_components"],
            "reliability_score": 0.94,
            "avg_lead_time_days": 18,
            "annual_volume_usd": 6_800_000,
            "risk_factors": [
                "Malacca Strait transit dependency",
                "Regional haze season disruptions",
            ],
            "historical_disruptions": [
                {"date": "2024-06-12", "type": "shipping_delay", "duration_days": 2, "impact_usd": 42_000},
            ],
        },
    ]

    for supplier in suppliers:
        key = f"suppliers/{supplier['supplier_id']}.json"
        upload_document(key, json.dumps(supplier, indent=2, default=str))

        # Also upload a text summary for better RAG retrieval
        summary = f"""
Supplier Profile: {supplier['name']}
ID: {supplier['supplier_id']}
Region: {supplier['region']}
Products: {', '.join(supplier['products'])}
Reliability Score: {supplier['reliability_score']}
Average Lead Time: {supplier['avg_lead_time_days']} days
Annual Volume: ${supplier['annual_volume_usd']:,}

Risk Factors:
{chr(10).join('- ' + r for r in supplier['risk_factors'])}

Historical Disruptions:
{chr(10).join(f"- {d['date']}: {d['type']} ({d['duration_days']} days, ${d['impact_usd']:,} impact)" for d in supplier['historical_disruptions'])}
""".strip()
        upload_document(f"suppliers/{supplier['supplier_id']}_summary.txt", summary)

    print(f"  Seeded {len(suppliers)} supplier profiles")


def seed_disruption_playbooks():
    """Seed standard operating procedures for disruption response."""
    playbooks = {
        "port_closure": """
DISRUPTION PLAYBOOK: Port Closure

Trigger: Port closure lasting >48 hours affecting active shipments.

Immediate Actions (0-4 hours):
1. Identify all in-transit shipments through affected port
2. Assess current inventory levels for affected product lines
3. Contact affected suppliers for ETA updates
4. Evaluate alternative ports and routing options

Short-term Mitigation (4-48 hours):
1. Activate backup suppliers if inventory < 14 days
2. Reroute shipments to alternative ports where feasible
3. Expedite existing orders from unaffected suppliers
4. Notify downstream customers of potential delays

Decision Criteria for Supplier Switch:
- Switch if: delay_cost > switch_cost AND backup_reliability > 0.85
- Delay Cost = (Delay Days × Daily Revenue Impact) × (1 + Risk Premium)
- Switch Cost = (Price Premium × Quantity) + Expedited Shipping

Escalation: Notify VP Supply Chain if estimated impact > $500K
""",
        "supplier_failure": """
DISRUPTION PLAYBOOK: Supplier Failure

Trigger: Supplier unable to fulfill orders (bankruptcy, force majeure, quality failure).

Immediate Actions (0-4 hours):
1. Assess remaining inventory and burn rate
2. Activate pre-qualified backup suppliers
3. Evaluate spot market options for critical components
4. Assess impact on production schedule

Short-term Mitigation (4-72 hours):
1. Issue emergency POs to backup suppliers
2. Negotiate expedited delivery terms
3. Evaluate component substitution options
4. Adjust production schedule to prioritize high-revenue products

Decision Matrix:
- Critical (inventory < 7 days): Emergency PO + air freight
- Urgent (inventory 7-21 days): Standard PO + expedited sea freight
- Planned (inventory > 21 days): Standard PO, optimize for cost

Cost Thresholds:
- Auto-approve: single PO < $50,000
- Manager approval: $50,000 - $250,000
- VP approval: > $250,000
""",
        "weather_event": """
DISRUPTION PLAYBOOK: Severe Weather Event

Trigger: Hurricane/typhoon/flood warning for region with active suppliers or shipping routes.

Pre-Event Actions (>48 hours before impact):
1. Accelerate any pending shipments from affected region
2. Increase safety stock for vulnerable product lines
3. Pre-position backup logistics providers
4. Confirm supplier disaster recovery plans

During Event:
1. Monitor real-time updates from NWS/NOAA
2. Track vessel positions for in-transit shipments
3. Assess satellite imagery for port/facility damage
4. Update risk scores based on actual conditions

Post-Event (0-72 hours after):
1. Contact suppliers for damage assessment
2. Evaluate infrastructure damage using satellite imagery
3. Activate recovery procedures based on damage severity
4. Adjust forecasts and communicate to customers

Severity Mapping:
- Category 1-2: Monitor, pre-position alternatives
- Category 3: Activate backup suppliers
- Category 4-5: Emergency procurement, consider dual-sourcing permanently
""",
    }

    for name, content in playbooks.items():
        upload_document(f"playbooks/{name}.txt", content.strip())

    print(f"  Seeded {len(playbooks)} disruption playbooks")


def seed_product_lines():
    """Seed product line configuration."""
    products = [
        {
            "product_line": "Premium Electronics",
            "daily_revenue_usd": 145_000,
            "key_components": ["semiconductors", "electronic_components", "optical_components"],
            "safety_stock_days": 14,
            "primary_suppliers": ["SUP-001", "SUP-004"],
            "backup_suppliers": ["SUP-002"],
        },
        {
            "product_line": "Industrial Sensors",
            "daily_revenue_usd": 89_000,
            "key_components": ["industrial_sensors", "precision_machined_parts"],
            "safety_stock_days": 21,
            "primary_suppliers": ["SUP-002", "SUP-004"],
            "backup_suppliers": ["SUP-001"],
        },
        {
            "product_line": "Automotive Modules",
            "daily_revenue_usd": 210_000,
            "key_components": ["control_modules", "specialty_plastics", "electronic_components"],
            "safety_stock_days": 10,
            "primary_suppliers": ["SUP-001", "SUP-002", "SUP-003"],
            "backup_suppliers": ["SUP-004"],
        },
    ]

    for product in products:
        key = f"products/{product['product_line'].lower().replace(' ', '_')}.json"
        upload_document(key, json.dumps(product, indent=2))

    print(f"  Seeded {len(products)} product line configurations")


def main():
    print("=" * 60)
    print("  Supply Chain Ghost — Knowledge Base Seeding")
    print("=" * 60)
    print(f"  Bucket: {KB_BUCKET}")
    print(f"  Time:   {datetime.utcnow().isoformat()}Z")
    print()

    try:
        # Verify bucket exists
        s3.head_bucket(Bucket=KB_BUCKET)
    except Exception:
        print(f"[!] Bucket '{KB_BUCKET}' not found. Creating...")
        try:
            s3.create_bucket(Bucket=KB_BUCKET)
        except Exception as e:
            print(f"[✗] Cannot create bucket: {e}")
            print("    Set SCG_KB_BUCKET env var or deploy CDK stacks first.")
            return

    print("[1/3] Seeding supplier profiles...")
    seed_supplier_profiles()

    print("[2/3] Seeding disruption playbooks...")
    seed_disruption_playbooks()

    print("[3/3] Seeding product line configurations...")
    seed_product_lines()

    print()
    print("[✓] Knowledge base seeding complete!")
    print("    Run Bedrock KB sync to index these documents.")


if __name__ == "__main__":
    main()
