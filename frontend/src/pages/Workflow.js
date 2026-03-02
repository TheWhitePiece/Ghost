import React, { useState, useEffect } from 'react';
import { api } from '../services/api';

const PIPELINE_STEPS = [
  { key: 'perception', label: 'Perception', icon: '📡', description: 'Signal collection from news, weather, ports, satellites' },
  { key: 'reasoning', label: 'Reasoning', icon: '🧠', description: 'Nova 2 Lite risk analysis with extended thinking' },
  { key: 'verification', label: 'Verification', icon: '🛰️', description: 'Nova 2 Omni multimodal visual cross-check' },
  { key: 'decision', label: 'Decision', icon: '⚡', description: 'Cost-benefit analysis and action recommendation' },
  { key: 'execution', label: 'Execution', icon: '🤖', description: 'Nova Act browser automation for ERP operations' },
  { key: 'approval', label: 'Approval', icon: '🔐', description: 'Human-in-the-loop verification and sign-off' },
];

function Workflow() {
  const [activeStep, setActiveStep] = useState(null);
  const [risks, setRisks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadActiveWorkflows();
  }, []);

  async function loadActiveWorkflows() {
    try {
      const data = await api.getRisks();
      setRisks(data.assessments || []);
    } catch (err) {
      console.error('Failed to load workflows:', err);
    } finally {
      setLoading(false);
    }
  }

  function getStepStatus(risk, stepKey) {
    const normalized = risk.status?.toLowerCase().replace(/ /g, '_');
    const statusMap = {
      new: 'perception',
      analyzing: 'reasoning',
      assessed: 'reasoning',
      pending_verification: 'verification',
      verified: 'verification',
      decided: 'decision',
      executing: 'execution',
      pending_approval: 'approval',
      awaiting_approval: 'approval',
      approved: 'completed',
      rejected: 'completed',
      closed: 'completed',
    };
    const currentStep = statusMap[normalized] || 'perception';
    const stepIndex = PIPELINE_STEPS.findIndex(s => s.key === stepKey);
    const currentIndex = PIPELINE_STEPS.findIndex(s => s.key === currentStep);

    if (currentStep === 'completed') return 'completed';
    if (stepIndex < currentIndex) return 'completed';
    if (stepIndex === currentIndex) return 'active';
    return 'pending';
  }

  return (
    <div>
      <div className="page-header">
        <h2>Pipeline Workflows</h2>
        <p>Step Functions visual orchestration — Perception → Reasoning → Verification → Decision → Execution → Approval</p>
      </div>

      {/* Architecture Diagram */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <h3 className="card-title">4-Loop Architecture</h3>
        <div className="workflow-steps">
          {PIPELINE_STEPS.map((step, i) => (
            <React.Fragment key={step.key}>
              <div
                className={`workflow-step ${activeStep === step.key ? 'active' : ''}`}
                onClick={() => setActiveStep(activeStep === step.key ? null : step.key)}
                style={{ cursor: 'pointer' }}
              >
                <div style={{ fontSize: '28px', marginBottom: '8px' }}>{step.icon}</div>
                <div style={{ fontWeight: 600, marginBottom: '4px' }}>{step.label}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                  {step.description}
                </div>
              </div>
              {i < PIPELINE_STEPS.length - 1 && (
                <div style={{
                  display: 'flex', alignItems: 'center', color: 'var(--accent-cyan)',
                  fontSize: '24px', margin: '0 4px',
                }}>
                  →
                </div>
              )}
            </React.Fragment>
          ))}
        </div>

        {/* Step Detail Panel */}
        {activeStep && (
          <div style={{
            marginTop: '16px', padding: '16px', background: 'var(--bg-primary)',
            borderRadius: '8px', borderLeft: '3px solid var(--accent-cyan)',
          }}>
            <h4 style={{ margin: '0 0 8px' }}>
              {PIPELINE_STEPS.find(s => s.key === activeStep)?.icon}{' '}
              {PIPELINE_STEPS.find(s => s.key === activeStep)?.label} Loop
            </h4>
            {activeStep === 'perception' && (
              <div>
                <p>Collects disruption signals every 30 minutes from 5 sources:</p>
                <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                  <li>📰 News — RSS feeds with NLP keyword matching</li>
                  <li>🌪️ Weather — NWS severe weather alerts</li>
                  <li>🚢 Port Congestion — Vessel counts and wait times</li>
                  <li>📈 Commodity Prices — Threshold-based alerting</li>
                  <li>🛰️ Satellite — Change detection on port imagery</li>
                </ul>
                <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                  AWS Services: Lambda, EventBridge (30min cron), DynamoDB, S3
                </p>
              </div>
            )}
            {activeStep === 'reasoning' && (
              <div>
                <p>Amazon Nova 2 Lite analyzes signals with extended thinking enabled:</p>
                <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                  <li>RAG retrieval from Bedrock Knowledge Base (supplier history)</li>
                  <li>Risk score (0-100), confidence, delay estimation</li>
                  <li>Financial impact calculation</li>
                  <li>Mitigation options with cost analysis</li>
                </ul>
                <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                  Model: amazon.nova-lite-v2:0 | Thinking budget: 4096 tokens
                </p>
              </div>
            )}
            {activeStep === 'verification' && (
              <div>
                <p>Nova 2 Omni/Premier performs multimodal cross-verification:</p>
                <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                  <li>Port satellite image analysis (vessel clustering, dock occupancy)</li>
                  <li>Bill of Lading OCR validation (date mismatches, fraud indicators)</li>
                  <li>Self-correction: ±15 score adjustment when visual contradicts reasoning</li>
                </ul>
                <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                  Model: amazon.nova-premier-v1:0 | Conditional: only when risk ≥ 60
                </p>
              </div>
            )}
            {activeStep === 'decision' && (
              <div>
                <p>Cost-based decision engine evaluates action vs inaction:</p>
                <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                  <li>Delay Cost = (Delay Days × Revenue/Day) × Reliability Multiplier</li>
                  <li>Switch Cost = (Price Diff × Qty) + Expedited Freight</li>
                  <li>Alternative supplier selection by reliability score</li>
                  <li>Confidence gating: actions only when confidence ≥ 70%</li>
                </ul>
              </div>
            )}
            {activeStep === 'execution' && (
              <div>
                <p>Nova Act automates ERP purchase order creation:</p>
                <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                  <li>8-step browser workflow with self-healing retry (3 attempts)</li>
                  <li>Login → Procurement → New PO → Supplier → Items → Delivery → Screenshot → Save</li>
                  <li>API fallback mode if browser automation fails</li>
                  <li>Screenshot saved to S3 for audit trail</li>
                </ul>
                <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                  SDK: nova-act | Sandbox: Isolated VPC subnet with HTTPS-only egress
                </p>
              </div>
            )}
            {activeStep === 'approval' && (
              <div>
                <p>Human-in-the-loop approval for high-value actions:</p>
                <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                  <li>Step Functions WAIT_FOR_TASK_TOKEN pattern</li>
                  <li>Approval request sent to authorized approvers</li>
                  <li>APPROVE continues execution, REJECT cancels</li>
                  <li>Full audit trail with approver identity and notes</li>
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Active Workflows */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Active Workflows</h3>
          <button className="btn btn-secondary" onClick={loadActiveWorkflows}>Refresh</button>
        </div>

        {loading ? (
          <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading...</div>
        ) : risks.length === 0 ? (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
            No active workflows. Trigger a simulation to see the pipeline in action.
          </div>
        ) : (
          risks.map((risk, i) => (
            <div key={risk.assessment_id || i} style={{
              padding: '16px', borderBottom: i < risks.length - 1 ? '1px solid var(--border)' : 'none',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                <strong>{risk.title || `Assessment ${risk.assessment_id?.slice(0, 8)}`}</strong>
                <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                  Score: <strong style={{ color: risk.risk_score >= 60 ? 'var(--accent-red)' : 'var(--accent-yellow)' }}>
                    {risk.risk_score}
                  </strong>
                </span>
              </div>
              <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                {PIPELINE_STEPS.map((step, si) => {
                  const status = getStepStatus(risk, step.key);
                  return (
                    <React.Fragment key={step.key}>
                      <div style={{
                        padding: '6px 12px', borderRadius: '6px', fontSize: '12px',
                        display: 'flex', alignItems: 'center', gap: '4px',
                        background: status === 'active' ? 'rgba(6, 182, 212, 0.2)' :
                                    status === 'completed' ? 'rgba(16, 185, 129, 0.2)' : 'var(--bg-primary)',
                        color: status === 'active' ? 'var(--accent-cyan)' :
                               status === 'completed' ? 'var(--accent-green)' : 'var(--text-muted)',
                        border: status === 'active' ? '1px solid var(--accent-cyan)' : '1px solid transparent',
                      }}>
                        {status === 'completed' ? '✓' : step.icon} {step.label}
                      </div>
                      {si < PIPELINE_STEPS.length - 1 && (
                        <span style={{
                          color: status === 'completed' ? 'var(--accent-green)' : 'var(--border)',
                          fontSize: '14px',
                        }}>→</span>
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default Workflow;
