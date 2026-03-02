import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { format } from 'date-fns';

function RiskAssessments() {
  const [risks, setRisks] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    loadRisks();
  }, []);

  async function loadRisks() {
    setLoading(true);
    try {
      const data = await api.getRisks();
      setRisks(data.assessments || []);
    } catch (err) {
      console.error('Failed to load risks:', err);
    } finally {
      setLoading(false);
    }
  }

  const riskColor = (score) => {
    if (score >= 75) return 'var(--accent-red)';
    if (score >= 50) return 'var(--accent-yellow)';
    if (score >= 25) return 'var(--accent-blue)';
    return 'var(--accent-green)';
  };

  const statusBadge = (status) => {
    const normalized = status?.toLowerCase().replace(/ /g, '_');
    const map = {
      new: 'badge badge-medium',
      analyzing: 'badge badge-high',
      assessed: 'badge badge-medium',
      pending_verification: 'badge badge-high',
      verified: 'badge badge-critical',
      decided: 'badge badge-low',
      executing: 'badge badge-high',
      pending_approval: 'badge badge-critical',
      awaiting_approval: 'badge badge-critical',
      approved: 'badge badge-low',
      rejected: 'badge badge-critical',
      closed: 'badge',
    };
    return <span className={map[normalized] || 'badge'}>{status?.replace(/_/g, ' ')}</span>;
  };

  return (
    <div>
      <div className="page-header">
        <h2>Risk Assessments</h2>
        <p>Active risk evaluations with AI-driven scoring and recommendations</p>
      </div>

      {loading ? (
        <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading assessments...</div>
      ) : risks.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '64px' }}>
          <h3 style={{ color: 'var(--text-muted)', marginBottom: '8px' }}>No Active Risks</h3>
          <p style={{ color: 'var(--text-muted)' }}>Risk assessments will appear when disruption signals are analyzed.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '16px' }}>
          {risks.map((risk, i) => (
            <div
              key={risk.assessment_id || i}
              className="card"
              style={{ cursor: 'pointer', transition: 'border-color 0.2s' }}
              onClick={() => navigate(`/risks/${risk.assessment_id}`)}
              onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--accent-cyan)'}
              onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border-color)'}
            >
              <div style={{ display: 'flex', gap: '24px', alignItems: 'flex-start' }}>
                {/* Risk Score Gauge */}
                <div style={{
                  minWidth: '80px', textAlign: 'center', padding: '12px',
                  background: 'var(--bg-primary)', borderRadius: '12px',
                }}>
                  <div style={{
                    fontSize: '32px', fontWeight: 700, color: riskColor(risk.risk_score || 0),
                    lineHeight: 1
                  }}>
                    {risk.risk_score || 0}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>Risk Score</div>
                  <div className="risk-meter" style={{ marginTop: '8px' }}>
                    <div className="risk-meter-fill" style={{
                      width: `${risk.risk_score || 0}%`,
                      background: riskColor(risk.risk_score || 0),
                    }} />
                  </div>
                </div>

                {/* Details */}
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                    <h3 style={{ margin: 0, fontSize: '16px' }}>{risk.title || risk.signal_type || 'Risk Assessment'}</h3>
                    {statusBadge(risk.status)}
                  </div>
                  <p style={{ color: 'var(--text-muted)', margin: '0 0 12px', fontSize: '14px', lineHeight: 1.5 }}>
                    {risk.summary || risk.description || 'Awaiting detailed analysis...'}
                  </p>
                  <div style={{ display: 'flex', gap: '24px', fontSize: '13px', color: 'var(--text-muted)' }}>
                    {risk.confidence && (
                      <span>Confidence: <strong style={{ color: 'var(--text-primary)' }}>{risk.confidence}%</strong></span>
                    )}
                    {risk.estimated_delay_days && (
                      <span>Est. Delay: <strong style={{ color: 'var(--accent-yellow)' }}>{risk.estimated_delay_days}d</strong></span>
                    )}
                    {risk.financial_impact_usd && (
                      <span>Impact: <strong style={{ color: 'var(--accent-red)' }}>${(risk.financial_impact_usd / 1000).toFixed(0)}K</strong></span>
                    )}
                    {risk.created_at && (
                      <span>Created: {format(new Date(risk.created_at), 'MMM d, HH:mm')}</span>
                    )}
                  </div>
                </div>

                {/* Arrow */}
                <div style={{ color: 'var(--text-muted)', fontSize: '20px', padding: '12px' }}>→</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default RiskAssessments;
