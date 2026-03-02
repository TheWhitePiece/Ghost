"""
Supply Chain Ghost — Strands Agent Orchestrator.

The central "brain" that coordinates the four intelligence loops:
1. Perception (data collection)
2. Reasoning (Nova 2 Lite analysis)
3. Verification (Nova 2 Omni multimodal)
4. Execution (Nova Act ERP automation)

Uses Strands Agents SDK with custom tools.
"""
import os
import json
import logging
from datetime import datetime, timezone

import boto3
from strands import Agent
from strands.models.bedrock import BedrockModel

from tools.signal_tools import collect_signals, get_recent_signals
from tools.reasoning_tools import analyze_risk, get_assessment
from tools.verification_tools import verify_assessment
from tools.decision_tools import make_decision
from tools.execution_tools import execute_po, request_approval
from tools.memory_tools import get_supplier_memory, update_supplier_memory

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── AWS Clients ──
SFN = boto3.client("stepfunctions")
LAMBDA_CLIENT = boto3.client("lambda")

STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")


ORCHESTRATOR_SYSTEM_PROMPT = """You are the Supply Chain Ghost Orchestrator — an enterprise AI agent
that monitors, analyzes, and responds to supply chain disruptions.

Your workflow:
1. MONITOR: Collect signals from news, weather, ports, commodities, satellites
2. REASON: Analyze signals using historical context and memory
3. VERIFY: Cross-check high-risk findings with multimodal evidence
4. DECIDE: Calculate whether to act based on cost analysis
5. EXECUTE: Automate purchase order creation if approved
6. APPROVE: Coordinate human-in-the-loop approval

You have access to tools for each phase. Execute them in order.
Always explain your reasoning and cite evidence.
If confidence is low, escalate to humans.
If execution fails, retry with alternate strategies before escalating.

Be thorough, precise, and transparent in every action."""


def create_orchestrator_agent() -> Agent:
    """Create the main Strands orchestrator agent."""
    model = BedrockModel(
        model_id="amazon.nova-lite-v1:0",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )

    agent = Agent(
        model=model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[
            collect_signals,
            get_recent_signals,
            analyze_risk,
            get_assessment,
            verify_assessment,
            make_decision,
            execute_po,
            request_approval,
            get_supplier_memory,
            update_supplier_memory,
        ],
    )
    return agent


def run_full_pipeline(trigger_source: str = "scheduled", context: dict = None) -> dict:
    """
    Execute the complete Supply Chain Ghost pipeline.
    
    This can be triggered by:
    - Scheduled EventBridge (every 30 min)
    - Webhook alerts
    - Manual "Simulate Disruption" button
    - Direct API call
    """
    logger.info("Pipeline started: source=%s", trigger_source)
    pipeline_start = datetime.now(timezone.utc)

    results = {
        "pipeline_id": f"pipeline-{pipeline_start.strftime('%Y%m%d%H%M%S')}",
        "trigger_source": trigger_source,
        "started_at": pipeline_start.isoformat(),
        "phases": {},
    }

    try:
        # ═══════════════════════════════════
        # Phase 1: PERCEPTION — Collect Signals
        # ═══════════════════════════════════
        logger.info("Phase 1: Collecting signals...")
        signals = _invoke_lambda("SCG-NewsCollector", {"source": trigger_source})
        weather = _invoke_lambda("SCG-WeatherCollector", {"source": trigger_source})
        ports = _invoke_lambda("SCG-PortCongestionCollector", {"source": trigger_source})
        commodities = _invoke_lambda("SCG-CommodityPriceCollector", {"source": trigger_source})
        satellite = _invoke_lambda("SCG-SatelliteMetadataCollector", {"source": trigger_source})

        total_signals = sum([
            signals.get("signals_found", 0),
            weather.get("signals_found", 0),
            ports.get("signals_found", 0),
            commodities.get("signals_found", 0),
            satellite.get("signals_found", 0),
        ])

        results["phases"]["perception"] = {
            "status": "COMPLETED",
            "total_signals": total_signals,
            "breakdown": {
                "news": signals.get("signals_found", 0),
                "weather": weather.get("signals_found", 0),
                "ports": ports.get("signals_found", 0),
                "commodities": commodities.get("signals_found", 0),
                "satellite": satellite.get("signals_found", 0),
            },
        }

        if total_signals == 0:
            results["phases"]["perception"]["note"] = "No disruption signals detected"
            results["status"] = "MONITORING"
            results["completed_at"] = datetime.now(timezone.utc).isoformat()
            return results

        # ═══════════════════════════════════
        # Phase 2: REASONING — Analyze Risk
        # ═══════════════════════════════════
        logger.info("Phase 2: Reasoning...")
        assessment = _invoke_lambda("SCG-ReasoningEngine", {
            "source": trigger_source,
            "context": context or {},
        })

        results["phases"]["reasoning"] = {
            "status": "COMPLETED",
            "assessment_id": assessment.get("assessment_id"),
            "risk_score": assessment.get("risk_score"),
            "confidence_pct": assessment.get("confidence_pct"),
            "recommendation": assessment.get("action_recommendation"),
        }

        risk_score = float(assessment.get("risk_score", 0))

        # ═══════════════════════════════════
        # Phase 3: VERIFICATION (if risk > 60%)
        # ═══════════════════════════════════
        if risk_score > 60:
            logger.info("Phase 3: Verification (risk=%s > 60)...", risk_score)
            verification = _invoke_lambda("SCG-VerificationEngine", {
                "reasoning": assessment,
            })

            results["phases"]["verification"] = {
                "status": "COMPLETED",
                "original_score": risk_score,
                "verified_score": verification.get("verified_risk_score"),
                "visual_agrees": verification.get("visual_agrees_with_reasoning"),
                "self_correction": verification.get("self_correction_applied"),
            }

            # Use verified score going forward
            assessment["risk_score"] = verification.get("verified_risk_score", risk_score)
        else:
            results["phases"]["verification"] = {
                "status": "SKIPPED",
                "reason": f"Risk score {risk_score} <= 60",
            }

        # ═══════════════════════════════════
        # Phase 4: DECISION
        # ═══════════════════════════════════
        logger.info("Phase 4: Decision...")
        decision = _invoke_lambda("SCG-DecisionEngine", {
            "reasoning": assessment,
            "verification": results["phases"].get("verification", {}),
        })

        results["phases"]["decision"] = {
            "status": "COMPLETED",
            "action": decision.get("action"),
            "delay_cost": decision.get("cost_analysis", {}).get("expected_delay_cost_usd"),
            "switch_cost": decision.get("cost_analysis", {}).get("switch_cost_usd"),
            "net_savings": decision.get("cost_analysis", {}).get("net_savings_usd"),
        }

        # ═══════════════════════════════════
        # Phase 5: EXECUTION (if SWITCH_SUPPLIER)
        # ═══════════════════════════════════
        if decision.get("action") == "SWITCH_SUPPLIER":
            logger.info("Phase 5: Execution...")
            execution = _invoke_lambda("SCG-NovaActExecutor", {
                "decision": decision,
            })

            results["phases"]["execution"] = {
                "status": execution.get("status"),
                "method": execution.get("method"),
                "attempts": len(execution.get("attempts", [])),
                "po_details": execution.get("po_details"),
            }

            # Phase 6: AWAIT APPROVAL
            if execution.get("status") == "SUCCESS":
                results["phases"]["approval"] = {
                    "status": "AWAITING_APPROVAL",
                    "assessment_id": assessment.get("assessment_id"),
                }
            else:
                results["phases"]["approval"] = {
                    "status": "ESCALATED",
                    "reason": "Execution failed after retries",
                }
        elif decision.get("action") == "ESCALATE":
            results["phases"]["execution"] = {"status": "SKIPPED", "reason": "Escalated to human"}
        else:
            results["phases"]["execution"] = {"status": "SKIPPED", "reason": f"Action: {decision.get('action')}"}

        results["status"] = "COMPLETED"

    except Exception as e:
        logger.error("Pipeline failed: %s", str(e), exc_info=True)
        results["status"] = "ERROR"
        results["error"] = str(e)

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    elapsed = (datetime.now(timezone.utc) - pipeline_start).total_seconds()
    results["elapsed_seconds"] = round(elapsed, 2)

    logger.info("Pipeline complete: status=%s elapsed=%.1fs", results["status"], elapsed)
    return results


def run_via_step_functions(trigger_source: str = "scheduled", context: dict = None) -> str:
    """Start the pipeline via AWS Step Functions for visual orchestration."""
    execution = SFN.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=f"ghost-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
        input=json.dumps({
            "trigger_source": trigger_source,
            "context": context or {},
            "started_at": datetime.now(timezone.utc).isoformat(),
        }),
    )
    return execution["executionArn"]


def _invoke_lambda(function_name: str, payload: dict) -> dict:
    """Invoke a Lambda function synchronously."""
    try:
        response = LAMBDA_CLIENT.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload, default=str),
        )
        return json.loads(response["Payload"].read())
    except Exception as e:
        logger.error("Lambda invocation failed for %s: %s", function_name, str(e))
        return {"error": str(e)}


# ── Strands Agent Interactive Mode ──
def run_interactive(user_message: str) -> str:
    """
    Run the orchestrator in interactive "Ask the Ghost" mode.
    Uses Strands agent for conversational interaction.
    """
    agent = create_orchestrator_agent()
    response = agent(user_message)
    return str(response)


if __name__ == "__main__":
    # Run pipeline directly
    result = run_full_pipeline(trigger_source="manual")
    print(json.dumps(result, indent=2, default=str))
