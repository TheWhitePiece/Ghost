# 🚢 Supply Chain Ghost — Enterprise Edition

**An AI-powered supply chain disruption detection, analysis, and autonomous response system built entirely on AWS using Amazon Nova foundation models.**

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    SUPPLY CHAIN GHOST                            │
├────────────┬────────────┬──────────────┬───────────────────────┤
│ PERCEPTION │  REASONING │ VERIFICATION │     EXECUTION          │
│   Loop     │    Loop    │    Loop      │       Loop             │
├────────────┼────────────┼──────────────┼───────────────────────┤
│ EventBridge│ Nova 2 Lite│ Nova 2 Omni  │ Nova Act              │
│ Lambda     │ Extended   │ Multimodal   │ Browser Automation    │
│ Collectors │ Thinking   │ Cross-Check  │ ERP Integration       │
├────────────┴────────────┴──────────────┴───────────────────────┤
│              Strands Agents + AWS Step Functions                 │
├─────────────────────────────────────────────────────────────────┤
│              Amazon Bedrock (Nova Models)                        │
├─────────────────────────────────────────────────────────────────┤
│  S3 │ DynamoDB │ Aurora Serverless │ Bedrock KB │ CloudWatch    │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Technology |
|---|---|
| Infrastructure | AWS CDK (Python) |
| AI Models | Amazon Nova 2 Lite, Nova 2 Omni, Nova Act |
| Orchestration | Strands Agents SDK, AWS Step Functions |
| Data Collection | AWS Lambda, EventBridge |
| Knowledge Base | Bedrock Knowledge Bases (RAG) |
| Memory | Bedrock Memory |
| Database | DynamoDB, Aurora Serverless v2 |
| Storage | Amazon S3 |
| Auth | Amazon Cognito |
| Frontend | React + CloudFront |
| Security | VPC, WAF, Secrets Manager, IAM |
| Observability | CloudWatch, X-Ray |

## Project Structure

```
SupplyChain/
├── infra/                    # AWS CDK Infrastructure
│   ├── app.py
│   ├── stacks/
│   │   ├── vpc_stack.py
│   │   ├── storage_stack.py
│   │   ├── auth_stack.py
│   │   ├── perception_stack.py
│   │   ├── reasoning_stack.py
│   │   ├── execution_stack.py
│   │   ├── api_stack.py
│   │   ├── dashboard_stack.py
│   │   └── observability_stack.py
│   └── cdk.json
├── lambdas/                  # Lambda Functions
│   ├── collectors/
│   ├── reasoning/
│   ├── verification/
│   ├── execution/
│   ├── decision/
│   └── api/
├── agents/                   # Strands Agent Definitions
│   ├── orchestrator.py
│   ├── tools/
│   └── prompts/
├── stepfunctions/            # Step Functions Definitions
│   └── workflow.json
├── frontend/                 # React Dashboard
│   ├── src/
│   └── package.json
├── scripts/                  # Deployment & Utility Scripts
├── tests/                    # Tests
└── requirements.txt
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure AWS credentials
aws configure

# 3. Bootstrap CDK
cd infra && cdk bootstrap

# 4. Deploy all stacks
cdk deploy --all

# 5. Deploy frontend
cd ../frontend && npm install && npm run build
aws s3 sync build/ s3://<dashboard-bucket>/

# 6. Seed knowledge base
cd ../scripts && python seed_knowledge_base.py
```

## Key Features

- **Real-time Disruption Detection** — Monitors news, weather, ports, commodities, satellites
- **Memory-Informed Reasoning** — Nova 2 Lite with extended thinking + historical memory
- **Multimodal Verification** — Nova 2 Omni cross-checks with satellite imagery & documents
- **Autonomous ERP Execution** — Nova Act automates purchase order creation
- **Human-in-the-Loop** — Conversational approval with "Ask the Ghost" chat
- **Enterprise Audit Trail** — Immutable logging of every decision and action
- **Self-Healing** — Automatic retry, fallback strategies, human escalation
