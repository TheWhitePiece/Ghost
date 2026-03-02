import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { format } from 'date-fns';

function AuditTrail() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    loadAudit();
  }, []);

  async function loadAudit() {
    setLoading(true);
    try {
      const data = await api.getAuditTrail();
      setEvents(data.events || data.audit_entries || []);
    } catch (err) {
      console.error('Failed to load audit trail:', err);
    } finally {
      setLoading(false);
    }
  }

  const actionIcon = (action) => {
    const icons = {
      signal_collected: '📡',
      risk_assessed: '🧠',
      risk_verified: '🛰️',
      decision_made: '⚡',
      po_created: '🤖',
      po_executed: '🤖',
      approval_requested: '🔐',
      approved: '✅',
      rejected: '❌',
      escalated: '⚠️',
      pipeline_started: '▶️',
      pipeline_completed: '🏁',
    };
    return icons[action] || '📋';
  };

  const filteredEvents = filter
    ? events.filter(e =>
        e.action?.toLowerCase().includes(filter.toLowerCase()) ||
        e.details?.toLowerCase().includes(filter.toLowerCase()) ||
        e.actor?.toLowerCase().includes(filter.toLowerCase())
      )
    : events;

  return (
    <div>
      <div className="page-header">
        <h2>Audit Trail</h2>
        <p>Immutable record of all Ghost pipeline actions — stored in S3 with Object Lock</p>
      </div>

      {/* Filter */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
          <input
            className="input"
            type="text"
            placeholder="Filter by action, details, or actor..."
            value={filter}
            onChange={e => setFilter(e.target.value)}
            style={{ flex: 1 }}
          />
          <button className="btn btn-secondary" onClick={loadAudit}>Refresh</button>
        </div>
      </div>

      {/* Audit Events */}
      <div className="card">
        {loading ? (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading audit trail...</div>
        ) : filteredEvents.length === 0 ? (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
            {filter ? 'No matching audit events.' : 'No audit events recorded yet.'}
          </div>
        ) : (
          <div>
            {filteredEvents.map((event, i) => (
              <div
                key={event.event_id || i}
                style={{
                  display: 'flex', gap: '16px', padding: '16px',
                  borderBottom: i < filteredEvents.length - 1 ? '1px solid var(--border-color)' : 'none',
                  alignItems: 'flex-start',
                }}
              >
                {/* Timeline Line */}
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: '40px' }}>
                  <div style={{
                    width: '36px', height: '36px', borderRadius: '50%',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    background: 'var(--bg-primary)', fontSize: '18px',
                  }}>
                    {actionIcon(event.action)}
                  </div>
                  {i < filteredEvents.length - 1 && (
                    <div style={{
                      width: '2px', flex: 1, minHeight: '20px',
                      background: 'var(--border-color)', marginTop: '4px',
                    }} />
                  )}
                </div>

                {/* Content */}
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '4px' }}>
                    <div>
                      <strong style={{ textTransform: 'capitalize' }}>
                        {event.action?.replace(/_/g, ' ') || 'Unknown Action'}
                      </strong>
                      {event.actor && (
                        <span style={{ marginLeft: '8px', fontSize: '13px', color: 'var(--accent-cyan)' }}>
                          by {event.actor}
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      {event.timestamp ? format(new Date(event.timestamp), 'MMM d, HH:mm:ss') : '—'}
                    </span>
                  </div>

                  {event.details && (
                    <p style={{ margin: '4px 0 0', fontSize: '14px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                      {event.details}
                    </p>
                  )}

                  {/* Metadata Tags */}
                  <div style={{ display: 'flex', gap: '8px', marginTop: '8px', flexWrap: 'wrap' }}>
                    {event.assessment_id && (
                      <span style={{
                        fontSize: '11px', padding: '2px 8px', borderRadius: '4px',
                        background: 'var(--bg-primary)', color: 'var(--text-muted)',
                      }}>
                        Risk: {event.assessment_id.slice(0, 8)}
                      </span>
                    )}
                    {event.signal_id && (
                      <span style={{
                        fontSize: '11px', padding: '2px 8px', borderRadius: '4px',
                        background: 'var(--bg-primary)', color: 'var(--text-muted)',
                      }}>
                        Signal: {event.signal_id.slice(0, 8)}
                      </span>
                    )}
                    {event.execution_id && (
                      <span style={{
                        fontSize: '11px', padding: '2px 8px', borderRadius: '4px',
                        background: 'var(--bg-primary)', color: 'var(--text-muted)',
                      }}>
                        Exec: {event.execution_id.slice(0, 8)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Stats Footer */}
      <div style={{
        marginTop: '16px', padding: '12px 16px', display: 'flex', justifyContent: 'space-between',
        color: 'var(--text-muted)', fontSize: '13px',
      }}>
        <span>Total events: {events.length}</span>
        {filter && <span>Showing: {filteredEvents.length}</span>}
        <span>Storage: Amazon S3 with Object Lock (GOVERNANCE mode)</span>
      </div>
    </div>
  );
}

export default AuditTrail;
