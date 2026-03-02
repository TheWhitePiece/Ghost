import React, { useState } from 'react';
import { api } from '../services/api';

const DISRUPTION_TEMPLATES = [
  {
    name: 'Port Closure — Shanghai',
    description: 'Typhoon causes 5-day closure at Shanghai port affecting container shipments',
    params: {
      disruption_type: 'port_closure',
      region: 'Shanghai',
      severity: 'critical',
      details: 'Typhoon Gaemi forces complete closure of Shanghai port. All container operations suspended. 127 vessels anchored offshore awaiting port reopening.',
    },
  },
  {
    name: 'Supplier Bankruptcy',
    description: 'Key tier-1 supplier files for bankruptcy, affecting 3 product lines',
    params: {
      disruption_type: 'supplier_failure',
      region: 'Global',
      severity: 'critical',
      details: 'Primary component supplier MegaParts Inc. files Chapter 11. Affects premium electronics, industrial sensors, and automotive modules. 45-day supply remaining.',
    },
  },
  {
    name: 'Commodity Price Spike',
    description: 'Copper prices surge 30% due to mining strikes in Chile',
    params: {
      disruption_type: 'commodity_price',
      region: 'South America',
      severity: 'high',
      details: 'Copper futures spike 30% to $12,450/ton following nationwide mining strikes in Chile. Expected duration 2-4 weeks. Affects industrial electronics and automotive wiring.',
    },
  },
  {
    name: 'Suez Canal Blockage',
    description: 'Container ship grounding blocks Suez Canal transit for 7+ days',
    params: {
      disruption_type: 'route_disruption',
      region: 'Suez Canal',
      severity: 'critical',
      details: 'Ultra-large container ship Ever Forward runs aground in Suez Canal. Salvage operations underway. 400+ vessels queued. Alternative Cape of Good Hope route adds 14 days transit.',
    },
  },
  {
    name: 'Severe Weather — Gulf Coast',
    description: 'Hurricane warning disrupts Gulf Coast logistics and petrochemical supply',
    params: {
      disruption_type: 'weather',
      region: 'Gulf Coast',
      severity: 'high',
      details: 'Category 3 hurricane approaching Gulf Coast. Port of Houston and Port of New Orleans preemptively closed. Petrochemical plants shutting down. Expected impact: 3-7 days.',
    },
  },
];

function Simulate() {
  const [selected, setSelected] = useState(null);
  const [customMode, setCustomMode] = useState(false);
  const [customParams, setCustomParams] = useState({
    disruption_type: '',
    region: '',
    severity: 'medium',
    details: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  async function runSimulation() {
    setSubmitting(true);
    setResult(null);
    try {
      const params = customMode ? customParams : DISRUPTION_TEMPLATES[selected].params;
      const data = await api.simulate(params);
      setResult(data);
    } catch (err) {
      setResult({ error: 'Simulation failed: ' + (err.message || 'Unknown error') });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <h2>Disruption Simulator</h2>
        <p>Trigger simulated supply chain disruptions to test the full Ghost pipeline</p>
      </div>

      {/* Template Selection */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="card-header">
          <h3 className="card-title">Scenario Templates</h3>
          <button
            className={`btn ${customMode ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => { setCustomMode(!customMode); setSelected(null); }}
          >
            {customMode ? 'Use Templates' : 'Custom Scenario'}
          </button>
        </div>

        {!customMode ? (
          <div style={{ display: 'grid', gap: '12px', marginTop: '16px' }}>
            {DISRUPTION_TEMPLATES.map((template, i) => (
              <div
                key={i}
                onClick={() => setSelected(i)}
                style={{
                  padding: '16px', borderRadius: '8px', cursor: 'pointer',
                  background: selected === i ? 'rgba(6, 182, 212, 0.1)' : 'var(--bg-primary)',
                  border: selected === i ? '1px solid var(--accent-cyan)' : '1px solid var(--border-color)',
                  transition: 'all 0.2s',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <strong>{template.name}</strong>
                  <span className={`badge badge-${template.params.severity === 'critical' ? 'critical' : 'high'}`}>
                    {template.params.severity}
                  </span>
                </div>
                <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '14px' }}>
                  {template.description}
                </p>
                {selected === i && (
                  <div style={{
                    marginTop: '12px', padding: '12px', background: 'var(--bg-secondary)',
                    borderRadius: '6px', fontSize: '13px', lineHeight: 1.6,
                    borderLeft: '3px solid var(--accent-cyan)',
                  }}>
                    {template.params.details}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div style={{ marginTop: '16px', display: 'grid', gap: '16px' }}>
            <div className="grid-2">
              <div>
                <label style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Disruption Type</label>
                <select
                  className="input"
                  value={customParams.disruption_type}
                  onChange={e => setCustomParams(p => ({ ...p, disruption_type: e.target.value }))}
                >
                  <option value="">Select type...</option>
                  <option value="port_closure">Port Closure</option>
                  <option value="weather">Severe Weather</option>
                  <option value="supplier_failure">Supplier Failure</option>
                  <option value="commodity_price">Commodity Price Spike</option>
                  <option value="route_disruption">Route Disruption</option>
                  <option value="geopolitical">Geopolitical Event</option>
                  <option value="cyber_attack">Cyber Attack</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Region</label>
                <input
                  className="input"
                  type="text"
                  value={customParams.region}
                  onChange={e => setCustomParams(p => ({ ...p, region: e.target.value }))}
                  placeholder="e.g., Shanghai, Gulf Coast, Suez Canal"
                />
              </div>
            </div>
            <div>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Severity</label>
              <div style={{ display: 'flex', gap: '8px' }}>
                {['low', 'medium', 'high', 'critical'].map(sev => (
                  <button
                    key={sev}
                    className={`btn ${customParams.severity === sev ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => setCustomParams(p => ({ ...p, severity: sev }))}
                    style={{ textTransform: 'capitalize' }}
                  >
                    {sev}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Details</label>
              <textarea
                className="input"
                value={customParams.details}
                onChange={e => setCustomParams(p => ({ ...p, details: e.target.value }))}
                placeholder="Describe the disruption scenario in detail..."
                rows={4}
                style={{ width: '100%', resize: 'vertical' }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Launch Button */}
      <div style={{ marginBottom: '24px' }}>
        <button
          className="btn btn-primary"
          onClick={runSimulation}
          disabled={submitting || (!customMode && selected === null) || (customMode && !customParams.disruption_type)}
          style={{ width: '100%', padding: '16px', fontSize: '16px' }}
        >
          {submitting ? 'Running Simulation...' : '🚀 Launch Disruption Simulation'}
        </button>
      </div>

      {/* Results */}
      {result && (
        <div className="card" style={{ borderColor: result.error ? 'var(--accent-red)' : 'var(--accent-green)' }}>
          <h3 className="card-title">{result.error ? '❌ Simulation Error' : '✅ Simulation Triggered'}</h3>
          {result.error ? (
            <p style={{ color: 'var(--accent-red)' }}>{result.error}</p>
          ) : (
            <div>
              <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                Disruption event has been published to the event bus. The full Ghost pipeline will now process this signal:
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px', marginTop: '16px' }}>
                {result.type && (
                  <div style={{ padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Type</div>
                    <div style={{ fontWeight: 600, textTransform: 'capitalize' }}>{result.type?.replace(/_/g, ' ')}</div>
                  </div>
                )}
                {result.region && (
                  <div style={{ padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Region</div>
                    <div style={{ fontWeight: 600 }}>{result.region}</div>
                  </div>
                )}
                {result.severity && (
                  <div style={{ padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Severity</div>
                    <span className={`badge badge-${result.severity === 'critical' ? 'critical' : result.severity === 'high' ? 'high' : 'medium'}`}>
                      {result.severity}
                    </span>
                  </div>
                )}
                <div style={{ padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Status</div>
                  <div style={{ fontWeight: 600, color: 'var(--accent-green)' }}>{result.status || 'Triggered'}</div>
                </div>
              </div>
              <div className="workflow-steps" style={{ marginTop: '16px' }}>
                <div className="workflow-step active">📡 Perception</div>
                <span style={{ color: 'var(--accent-cyan)' }}>→</span>
                <div className="workflow-step">🧠 Reasoning</div>
                <span style={{ color: 'var(--text-muted)' }}>→</span>
                <div className="workflow-step">🛰️ Verification</div>
                <span style={{ color: 'var(--text-muted)' }}>→</span>
                <div className="workflow-step">⚡ Decision</div>
                <span style={{ color: 'var(--text-muted)' }}>→</span>
                <div className="workflow-step">🤖 Execution</div>
              </div>
              <p style={{ marginTop: '16px', fontSize: '13px', color: 'var(--text-muted)' }}>
                Check the <strong>Workflow</strong> page to monitor pipeline progress, or <strong>Risk Assessments</strong> once analysis completes.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default Simulate;
