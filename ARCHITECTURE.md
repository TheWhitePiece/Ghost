# Supply Chain Ghost — Architecture Document

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SUPPLY CHAIN GHOST (Enterprise)                      │
│              AI-Powered Supply Chain Disruption Detection & Response         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐               │
│  │   CloudFront   │───▶│    React      │    │   Cognito     │               │
│  │   + WAF        │    │   Dashboard   │───▶│   Auth        │               │
│  └───────────────┘    └───────────────┘    └───────────────┘               │
│          │                                          │                       │
│          ▼                                          ▼                       │
│  ┌───────────────────────────────────────────────────────┐                 │
│  │              API Gateway (REST + Cognito Auth)         │                 │
│  └──────────┬──────────┬──────────┬──────────┬───────────┘                 │
│             │          │          │          │                               │
│  ┌──────────▼──────────▼──────────▼──────────▼───────────┐                 │
│  │                 LAMBDA FUNCTIONS                        │                 │
│  │  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌─────────────┐ │                 │
│  │  │ API     │ │ Chat     │ │ Approv │ │ Collectors  │ │                 │
│  │  │ Handler │ │ Handler  │ │ Handler│ │ (5 types)   │ │                 │
│  │  └─────────┘ └──────────┘ └────────┘ └─────────────┘ │                 │
│  └───────────────────────────────────────────────────────┘                 │
│                              │                                              │
│  ┌───────────────────────────▼───────────────────────────┐                 │
│  │            AWS STEP FUNCTIONS (Orchestrator)           │                 │
│  │                                                        │                 │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐ │                 │
│  │  │ Reason  │─▶│ Verify? │─▶│ Decide  │─▶│ Execute │ │                 │
│  │  │ (Nova   │  │ (Nova   │  │ (Cost   │  │ (Nova   │ │                 │
│  │  │  Lite)  │  │  Omni)  │  │  Math)  │  │  Act)   │ │                 │
│  │  └─────────┘  └─────────┘  └─────────┘  └────┬────┘ │                 │
│  │                                                │      │                 │
│  │                                          ┌─────▼────┐ │                 │
│  │                                          │ Approval │ │                 │
│  │                                          │ (HITL)   │ │                 │
│  │                                          └──────────┘ │                 │
│  └───────────────────────────────────────────────────────┘                 │
│                              │                                              │
│  ┌───────────────────────────▼───────────────────────────┐                 │
│  │                    DATA LAYER                          │                 │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐│                 │
│  │  │ DynamoDB │ │ Aurora   │ │ S3       │ │ Bedrock  ││                 │
│  │  │ (Signals │ │ Postgres │ │ (Raw +   │ │ Knowledge││                 │
│  │  │  + Risks)│ │ (History)│ │  Audit)  │ │ Base     ││                 │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘│                 │
│  └───────────────────────────────────────────────────────┘                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 4-Loop Pipeline Architecture

### Loop 1: Perception (Signal Collection)

- **5 Collectors** running every 30 minutes via EventBridge:
  - `news_collector` — RSS feeds with NLP keyword matching (25 supply chain keywords)
  - `weather_collector` — NWS API severe weather alerts for 8 monitored regions
  - `port_congestion_collector` — 10 major ports, congestion threshold analysis
  - `commodity_price_collector` — 10 commodities with threshold-based alerting
  - `satellite_metadata_collector` — 5 port AOIs with change detection
- **Output**: Signals stored in DynamoDB (`SCG_Signals`) and S3 (`scg-raw-signals`)

### Loop 2: Reasoning (Risk Assessment)

- **Model**: Amazon Nova 2 Lite (`amazon.nova-lite-v2:0`) with extended thinking (4096 token budget)
- **RAG**: Bedrock Knowledge Base retrieval for supplier history and playbooks
- **Memory Context**: Supplier reliability scores, inventory status, revenue sensitivity
- **Output**: Structured risk assessment (score 0-100, confidence, delay estimate, financial impact, mitigation options)

### Loop 3: Verification (Multimodal Cross-Check)

- **Model**: Amazon Nova 2 Omni / Premier (`amazon.nova-premier-v1:0`)
- **Conditional**: Only triggered when risk score ≥ 60
- **Capabilities**:
  - Port satellite image analysis (vessel clustering, dock occupancy, movement density)
  - Bill of Lading OCR validation (date mismatches, anomalies, fraud indicators)
- **Self-Correction**: ±15 risk score adjustment when visual evidence contradicts reasoning

### Loop 4: Execution (Autonomous Response)

- **Decision Engine**: Cost-based analysis
  - `Delay Cost = (Delay Days × Revenue/Day) × Reliability Multiplier`
  - `Switch Cost = (Price Diff × Qty) + Expedited Freight`
  - Confidence gating: actions only when confidence ≥ 70%
- **Nova Act**: Browser automation for ERP purchase order creation
  - 8-step workflow with self-healing retry (3 attempts)
  - API fallback mode if browser automation fails
  - Screenshots saved to S3 for audit trail
- **Human-in-the-Loop**: Step Functions `WAIT_FOR_TASK_TOKEN` for approval
  - Required for all actions with financial impact > threshold
  - APPROVE continues execution, REJECT cancels with audit record

## AWS Services Used

| Service                       | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Amazon Bedrock (Nova 2 Lite)  | Risk reasoning with extended thinking    |
| Amazon Bedrock (Nova Premier) | Multimodal verification (satellite, BOL) |
| Amazon Nova Act               | Browser automation for ERP operations    |
| AWS Step Functions            | Visual pipeline orchestration            |
| AWS Lambda                    | Serverless compute for all functions     |
| Amazon DynamoDB               | Signal and risk assessment storage       |
| Amazon Aurora Serverless v2   | Historical analytics (PostgreSQL)        |
| Amazon S3                     | Raw signals, knowledge base, audit trail |
| Amazon Cognito                | User authentication with MFA             |
| Amazon CloudFront             | CDN for React dashboard                  |
| AWS WAF                       | Web application firewall                 |
| Amazon EventBridge            | Scheduled collection + event routing     |
| Amazon API Gateway            | REST API with Cognito auth               |
| AWS Secrets Manager           | ERP credential management                |
| Amazon CloudWatch             | Metrics, dashboards, alarms              |
| AWS X-Ray                     | Distributed tracing                      |

## Competition Categories

1. **Agentic AI** — Strands Agents SDK orchestrating multi-step supply chain reasoning
2. **Multimodal Understanding** — Nova 2 Omni analyzing satellite imagery + documents
3. **UI Automation** — Nova Act automating ERP purchase order workflow

## Security Architecture

- **VPC Isolation**: 4 subnet tiers (Public, Private, Nova Act Sandbox, Isolated)
- **Nova Act Sandbox**: Dedicated subnet with HTTPS-only egress (port 443)
- **S3 Audit Trail**: Object Lock in GOVERNANCE mode for immutable audit records
- **Cognito MFA**: Multi-factor authentication required for all users
- **WAF**: AWS Managed Rules + Rate Limiting (1000 req/5min) on CloudFront
- **Secrets Manager**: Encrypted ERP credentials with rotation support
- **VPC Endpoints**: Private connectivity to S3, DynamoDB, Secrets Manager, Bedrock

## Deployment

```bash
# One-command deployment
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

See [README.md](README.md) for detailed deployment instructions.
