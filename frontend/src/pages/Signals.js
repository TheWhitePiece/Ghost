import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { format } from 'date-fns';

function Signals() {
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState({ type: '', severity: '' });
  const [nextToken, setNextToken] = useState(null);

  const loadSignals = useCallback(async (append = false) => {
    setLoading(true);
    try {
      const params = {};
      if (filter.type) params.type = filter.type;
      if (filter.severity) params.severity = filter.severity;

      const data = await api.getSignals(params);
      setSignals(prev => append ? [...prev, ...(data.signals || [])] : (data.signals || []));
      setNextToken(data.next_token || null);
    } catch (err) {
      console.error('Failed to load signals:', err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    loadSignals();
  }, [filter.type, filter.severity]); // eslint-disable-line

  const severityBadge = (severity) => {
    const classes = {
      critical: 'badge badge-critical',
      high: 'badge badge-high',
      medium: 'badge badge-medium',
      low: 'badge badge-low',
    };
    return <span className={classes[severity] || 'badge'}>{severity}</span>;
  };

  const signalTypeIcon = (type) => {
    const icons = {
      news: '📰', weather: '🌪️', port_congestion: '🚢',
      commodity_price: '📈', satellite: '🛰️', manual: '👤',
    };
    return icons[type] || '📡';
  };

  return (
    <div>
      <div className="page-header">
        <h2>Signal Intelligence</h2>
        <p>Real-time disruption signals from all collection sources</p>
      </div>

      {/* Filters */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
          <div>
            <label style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Signal Type</label>
            <select
              className="input"
              value={filter.type}
              onChange={e => setFilter(f => ({ ...f, type: e.target.value }))}
            >
              <option value="">All Types</option>
              <option value="news">News</option>
              <option value="weather">Weather</option>
              <option value="port_congestion">Port Congestion</option>
              <option value="commodity_price">Commodity Price</option>
              <option value="satellite">Satellite</option>
              <option value="manual">Manual</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Severity</label>
            <select
              className="input"
              value={filter.severity}
              onChange={e => setFilter(f => ({ ...f, severity: e.target.value }))}
            >
              <option value="">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
          <div style={{ marginLeft: 'auto' }}>
            <label style={{ fontSize: '12px', color: 'transparent', display: 'block', marginBottom: '4px' }}>_</label>
            <button className="btn btn-secondary" onClick={() => loadSignals()}>
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Signal Table */}
      <div className="card">
        <table className="signal-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Title</th>
              <th>Severity</th>
              <th>Source</th>
              <th>Region</th>
              <th>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {signals.length === 0 && !loading ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '48px', color: 'var(--text-muted)' }}>
                  No signals found. Collectors will populate data automatically.
                </td>
              </tr>
            ) : (
              signals.map((signal, i) => (
                <tr key={signal.signal_id || i}>
                  <td>
                    <span title={signal.signal_type}>
                      {signalTypeIcon(signal.signal_type)} {signal.signal_type?.replace('_', ' ')}
                    </span>
                  </td>
                  <td style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {signal.title || signal.description?.slice(0, 80) || '—'}
                  </td>
                  <td>{severityBadge(signal.severity)}</td>
                  <td style={{ color: 'var(--text-muted)' }}>{signal.source || '—'}</td>
                  <td>{signal.region || signal.affected_region || '—'}</td>
                  <td style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                    {signal.timestamp ? format(new Date(signal.timestamp), 'MMM d, HH:mm') : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {loading && (
          <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading signals...</div>
        )}

        {nextToken && !loading && (
          <div style={{ padding: '16px', textAlign: 'center' }}>
            <button className="btn btn-secondary" onClick={() => loadSignals(true)}>
              Load More
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default Signals;
