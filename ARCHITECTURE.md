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
│  │  │  Lite)  │  │ Premier)│  │  Math)  │  │  Act)   │ │                 │
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
  - `weather_collector` — NWS API (US) + Open-Meteo API (worldwide) for 8 monitored regions
  - `port_congestion_collector` — 10 major ports via BarentsWatch AIS / MarineTraffic
  - `commodity_price_collector` — 10 commodities via Alpha Vantage + Yahoo Finance
  - `satellite_metadata_collector` — 5 port AOIs via Sentinel Hub (ESA Copernicus) with actual imagery stored to S3
- **Output**: Signals stored in DynamoDB (`SCG_Signals`) and S3 (`scg-raw-signals`)

### Loop 2: Reasoning (Risk Assessment)

- **Model**: Amazon Nova Lite (`amazon.nova-lite-v1:0`) with extended thinking (4096 token budget)
- **RAG**: Bedrock Knowledge Base retrieval for supplier history and playbooks
- **Memory Context**: Supplier reliability scores from DynamoDB (`SCG_Suppliers`), inventory status, revenue sensitivity
- **Output**: Structured risk assessment (score 0-100, confidence, delay estimate, financial impact, mitigation options)

### Loop 3: Verification (Multimodal Cross-Check)

- **Model**: Amazon Nova Premier (`amazon.nova-premier-v1:0`)
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
  - Supplier data loaded from DynamoDB (`SCG_Suppliers`) at runtime
- **Nova Act**: Browser automation for ERP purchase order creation (Docker container mode)
  - 8-step workflow with self-healing retry (3 attempts)
  - ERP REST API fallback mode for standard Lambda deployment
  - Set `ERP_URL` to your real ERP endpoint; set `EXECUTION_MODE` to `nova_act` or `api`
  - Screenshots saved to S3 for audit trail
- **Human-in-the-Loop**: Step Functions `WAIT_FOR_TASK_TOKEN` for approval
  - Required for all actions with financial impact > threshold
  - APPROVE continues execution, REJECT cancels with audit record

## AWS Services Used

| Service                       | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Amazon Bedrock (Nova Lite)    | Risk reasoning with extended thinking    |
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
2. **Multimodal Understanding** — Nova Premier analyzing satellite imagery + documents
3. **UI Automation** — Nova Act automating ERP purchase order workflow

## Security Architecture

- **VPC Isolation**: 4 subnet tiers (Public, Private, Nova Act Sandbox, Isolated)
- **Nova Act Sandbox**: Dedicated subnet with HTTPS-only egress (port 443)
- **S3 Audit Trail**: Object Lock in GOVERNANCE mode for immutable audit records
- **Cognito MFA**: Multi-factor authentication required for all users
- **WAF**: AWS Managed Rules + Rate Limiting (1000 req/5min) on CloudFront
- **Secrets Manager**: Encrypted ERP credentials with rotation support
- **VPC Endpoints**: Private connectivity to S3, DynamoDB, Secrets Manager, Bedrock

## Environment Variables

The following external API keys / secrets must be set (via Lambda environment or Secrets Manager) for full functionality:

| Variable                     | Used By                                         | Required | Notes                                             |
| ---------------------------- | ----------------------------------------------- | -------- | ------------------------------------------------- |
| `BARENTSWATCH_CLIENT_ID`     | port_congestion_collector                       | Yes      | Free — register at developer.barentswatch.no      |
| `BARENTSWATCH_CLIENT_SECRET` | port_congestion_collector                       | Yes      | Free — same registration                          |
| `MARINETRAFFIC_API_KEY`      | port_congestion_collector                       | No       | PS07 endpoint; fallback if BarentsWatch fails     |
| `ALPHA_VANTAGE_API_KEY`      | commodity_price_collector                       | Yes      | Free tier — 25 requests/day at alphavantage.co    |
| `SENTINEL_HUB_CLIENT_ID`     | satellite_metadata_collector                    | Yes      | Free trial at apps.sentinel-hub.com               |
| `SENTINEL_HUB_CLIENT_SECRET` | satellite_metadata_collector                    | Yes      | Free trial — same registration                    |
| `OPENWEATHERMAP_API_KEY`     | weather_collector                               | No       | Optional enhanced fallback; Open-Meteo is primary |
| `ERP_URL`                    | nova_act_executor                               | Yes\*    | Your real ERP base URL; required if executing POs |
| `EXECUTION_MODE`             | nova_act_executor                               | No       | `api` (default) or `nova_act` (Docker + Chromium) |
| `KNOWLEDGE_BASE_ID`          | reasoning_engine                                | No       | Bedrock Knowledge Base ID; RAG disabled if empty  |
| `SUPPLIERS_TABLE`            | decision_engine, reasoning_engine, memory_tools | No       | Defaults to `SCG_Suppliers`                       |

## Deployment

```bash
# One-command deployment
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

See [README.md](README.md) for detailed deployment instructions.
