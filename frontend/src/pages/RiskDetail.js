import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { format } from 'date-fns';

function RiskDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [risk, setRisk] = useState(null);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(false);
  const [notes, setNotes] = useState('');

  useEffect(() => {
    loadRisk();
  }, [id]); // eslint-disable-line

  async function loadRisk() {
    setLoading(true);
    try {
      const data = await api.getRiskDetail(id);
      setRisk(data);
    } catch (err) {
      console.error('Failed to load risk detail:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleApproval(action) {
    setApproving(true);
    try {
      await api.approveRisk(id, { action, comments: notes });
      await loadRisk();
    } catch (err) {
      console.error('Approval failed:', err);
    } finally {
      setApproving(false);
    }
  }

  const riskColor = (score) => {
    if (score >= 75) return 'var(--accent-red)';
    if (score >= 50) return 'var(--accent-yellow)';
    if (score >= 25) return 'var(--accent-blue)';
    return 'var(--accent-green)';
  };

  if (loading) {
    return <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading risk detail...</div>;
  }

  if (!risk) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '64px' }}>
        <h3 style={{ color: 'var(--text-muted)' }}>Risk assessment not found</h3>
        <button className="btn btn-secondary" onClick={() => navigate('/risks')} style={{ marginTop: '16px' }}>
          Back to Risks
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <button className="btn btn-secondary" onClick={() => navigate('/risks')} style={{ marginBottom: '8px' }}>
          ← Back
        </button>
        <h2>{risk.title || 'Risk Assessment'}</h2>
        <p>Assessment ID: {id}</p>
      </div>

      <div className="grid-2">
        {/* Risk Score Panel */}
        <div className="card">
          <h3 className="card-title">Risk Analysis</h3>
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <div style={{
              fontSize: '64px', fontWeight: 700,
              color: riskColor(risk.risk_score || 0), lineHeight: 1,
            }}>
              {risk.risk_score || 0}
            </div>
            <div style={{ color: 'var(--text-muted)', marginTop: '8px' }}>Risk Score</div>
            <div className="risk-meter" style={{ marginTop: '16px', maxWidth: '300px', margin: '16px auto 0' }}>
              <div className="risk-meter-fill" style={{
                width: `${risk.risk_score || 0}%`,
                background: riskColor(risk.risk_score || 0),
              }} />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginTop: '24px' }}>
            <div style={{ padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Confidence</div>
              <div style={{ fontSize: '24px', fontWeight: 600 }}>{risk.confidence || 0}%</div>
            </div>
            <div style={{ padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Est. Delay</div>
              <div style={{ fontSize: '24px', fontWeight: 600 }}>{risk.estimated_delay_days || 0}d</div>
            </div>
            <div style={{ padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Financial Impact</div>
              <div style={{ fontSize: '24px', fontWeight: 600, color: 'var(--accent-red)' }}>
                ${((risk.financial_impact_usd || 0) / 1000).toFixed(0)}K
              </div>
            </div>
            <div style={{ padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Status</div>
              <div style={{ fontSize: '18px', fontWeight: 600, textTransform: 'capitalize' }}>
                {risk.status?.replace(/_/g, ' ') || 'Unknown'}
              </div>
            </div>
          </div>
        </div>

        {/* Assessment Details */}
        <div className="card">
          <h3 className="card-title">Assessment Details</h3>
          {risk.summary && (
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>Summary</div>
              <p style={{ lineHeight: 1.6 }}>{risk.summary}</p>
            </div>
          )}
          {risk.risk_factors && risk.risk_factors.length > 0 && (
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Risk Factors</div>
              <ul style={{ margin: 0, paddingLeft: '20px' }}>
                {risk.risk_factors.map((factor, i) => (
                  <li key={i} style={{ marginBottom: '4px', color: 'var(--text-secondary)' }}>{factor}</li>
                ))}
              </ul>
            </div>
          )}
          {risk.mitigation_options && risk.mitigation_options.length > 0 && (
            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Mitigation Options</div>
              {risk.mitigation_options.map((opt, i) => (
                <div key={i} style={{
                  padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px',
                  marginBottom: '8px', borderLeft: '3px solid var(--accent-cyan)'
                }}>
                  {typeof opt === 'string' ? opt : (
                    <>
                      <strong>{opt.action}</strong>
                      {opt.cost && <span style={{ color: 'var(--text-muted)' }}> — ${opt.cost?.toLocaleString()}</span>}
                      {opt.description && <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-secondary)' }}>{opt.description}</p>}
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Verification Section */}
      {risk.verification && (
        <div className="card" style={{ marginTop: '16px' }}>
          <h3 className="card-title">🛰️ Multimodal Verification</h3>
          <div className="grid-2">
            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Verification Result</div>
              <p style={{ lineHeight: 1.6 }}>{risk.verification.summary || 'Pending verification...'}</p>
              {risk.verification.adjustments && (
                <div style={{ marginTop: '12px', padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
                  <strong>Score Adjustment:</strong> {risk.verification.adjustments}
                </div>
              )}
            </div>
            {risk.verification.screenshot_url && (
              <div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Visual Evidence</div>
                <img
                  src={risk.verification.screenshot_url}
                  alt="Satellite verification"
                  style={{ width: '100%', borderRadius: '8px', border: '1px solid var(--border-color)' }}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Decision & Execution */}
      {risk.decision && (
        <div className="card" style={{ marginTop: '16px' }}>
          <h3 className="card-title">⚡ Decision & Action</h3>
          <div style={{ padding: '16px', background: 'var(--bg-primary)', borderRadius: '8px', marginBottom: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ color: 'var(--text-muted)' }}>Recommended Action</span>
              <strong style={{ textTransform: 'capitalize' }}>{risk.decision.action || 'None'}</strong>
            </div>
            {risk.decision.alternative_supplier && (
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Alternative Supplier</span>
                <strong>{risk.decision.alternative_supplier}</strong>
              </div>
            )}
            {risk.decision.cost_analysis && (
              <div style={{ marginTop: '12px', fontSize: '13px', color: 'var(--text-secondary)' }}>
                {risk.decision.cost_analysis}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Approval Panel */}
      {(risk.status?.toLowerCase() === 'pending_approval' || risk.status === 'AWAITING_APPROVAL') && (
        <div className="card" style={{ marginTop: '16px', borderColor: 'var(--accent-yellow)' }}>
          <h3 className="card-title">🔐 Approval Required</h3>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '16px' }}>
            This action requires human approval before execution. Review the assessment and provide your decision.
          </p>
          <textarea
            className="input"
            placeholder="Add approval notes (optional)..."
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={3}
            style={{ width: '100%', marginBottom: '16px', resize: 'vertical' }}
          />
          <div style={{ display: 'flex', gap: '12px' }}>
            <button
              className="btn btn-primary"
              onClick={() => handleApproval('APPROVE')}
              disabled={approving}
              style={{ background: 'var(--accent-green)' }}
            >
              {approving ? 'Processing...' : '✓ Approve Action'}
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => handleApproval('REJECT')}
              disabled={approving}
              style={{ borderColor: 'var(--accent-red)', color: 'var(--accent-red)' }}
            >
              ✕ Reject
            </button>
          </div>
        </div>
      )}

      {/* Timeline */}
      {risk.timeline && risk.timeline.length > 0 && (
        <div className="card" style={{ marginTop: '16px' }}>
          <h3 className="card-title">Timeline</h3>
          {risk.timeline.map((event, i) => (
            <div key={i} style={{
              display: 'flex', gap: '16px', padding: '12px 0',
              borderBottom: i < risk.timeline.length - 1 ? '1px solid var(--border-color)' : 'none',
            }}>
              <div style={{
                width: '12px', height: '12px', borderRadius: '50%', marginTop: '4px',
                background: i === 0 ? 'var(--accent-cyan)' : 'var(--border-color)',
              }} />
              <div>
                <div style={{ fontWeight: 500 }}>{event.action || event.event}</div>
                <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                  {event.timestamp ? format(new Date(event.timestamp), 'MMM d, HH:mm:ss') : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default RiskDetail;
