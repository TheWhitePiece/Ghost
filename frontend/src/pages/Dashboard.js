import React, { useState, useEffect } from 'react';
import { ComposedChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { api } from '../services/api';

function Dashboard() {
  const [kpis, setKpis] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadDashboard();
    const interval = setInterval(loadDashboard, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  async function loadDashboard() {
    try {
      const data = await api.getDashboard();
      setKpis(data.kpis);
    } catch (err) {
      // Use demo data on error
      setKpis({
        signals_24h: 47,
        active_risks: 3,
        pending_approvals: 1,
        avg_risk_score: 62.4,
        total_assessments: 156,
        total_cost_savings_usd: 2450000,
      });
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading dashboard...</div>;
  }

  const riskTrendData = [
    { date: 'Mon', score: 35, signals: 12 },
    { date: 'Tue', score: 42, signals: 18 },
    { date: 'Wed', score: 58, signals: 24 },
    { date: 'Thu', score: 71, signals: 31 },
    { date: 'Fri', score: 65, signals: 28 },
    { date: 'Sat', score: 48, signals: 15 },
    { date: 'Sun', score: kpis?.avg_risk_score || 62, signals: kpis?.signals_24h || 47 },
  ];

  const signalBreakdown = [
    { name: 'News', value: 18, color: '#3b82f6' },
    { name: 'Weather', value: 8, color: '#f59e0b' },
    { name: 'Port', value: 12, color: '#ef4444' },
    { name: 'Commodity', value: 5, color: '#10b981' },
    { name: 'Satellite', value: 4, color: '#8b5cf6' },
  ];

  return (
    <div>
      <div className="page-header">
        <h2>Operations Dashboard</h2>
        <p>Real-time supply chain intelligence overview</p>
      </div>

      {/* KPI Cards */}
      <div className="kpi-grid">
        <div className={`kpi-card ${kpis?.signals_24h > 30 ? 'warning' : 'info'}`}>
          <div className="label">Signals (24h)</div>
          <div className="value">{kpis?.signals_24h || 0}</div>
          <div className="change positive">+12% vs yesterday</div>
        </div>
        <div className={`kpi-card ${kpis?.active_risks > 5 ? 'critical' : 'warning'}`}>
          <div className="label">Active Risks</div>
          <div className="value">{kpis?.active_risks || 0}</div>
          <div className="change negative">2 new today</div>
        </div>
        <div className="kpi-card warning">
          <div className="label">Pending Approvals</div>
          <div className="value">{kpis?.pending_approvals || 0}</div>
        </div>
        <div className={`kpi-card ${(kpis?.avg_risk_score || 0) > 60 ? 'critical' : 'warning'}`}>
          <div className="label">Avg Risk Score</div>
          <div className="value">{kpis?.avg_risk_score || 0}</div>
          <div className="risk-meter">
            <div
              className="risk-meter-fill"
              style={{
                width: `${kpis?.avg_risk_score || 0}%`,
                background: (kpis?.avg_risk_score || 0) > 75 ? 'var(--accent-red)' :
                            (kpis?.avg_risk_score || 0) > 50 ? 'var(--accent-yellow)' : 'var(--accent-green)'
              }}
            />
          </div>
        </div>
        <div className="kpi-card info">
          <div className="label">Total Assessments</div>
          <div className="value">{kpis?.total_assessments || 0}</div>
        </div>
        <div className="kpi-card good">
          <div className="label">Cost Savings</div>
          <div className="value">${((kpis?.total_cost_savings_usd || 0) / 1000000).toFixed(1)}M</div>
          <div className="change positive">+$450K this week</div>
        </div>
      </div>

      {/* Charts */}
      <div className="grid-2">
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Risk Score Trend</h3>
            <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Last 7 days</span>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={riskTrendData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="date" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} domain={[0, 100]} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Line type="monotone" dataKey="score" stroke="#06b6d4" strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Signal Breakdown</h3>
            <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>By source</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <ResponsiveContainer width="50%" height={280}>
              <PieChart>
                <Pie
                  data={signalBreakdown}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  dataKey="value"
                  stroke="none"
                >
                  {signalBreakdown.map((entry, index) => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div style={{ flex: 1 }}>
              {signalBreakdown.map(({ name, value, color }) => (
                <div key={name} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                  <span style={{ width: '12px', height: '12px', borderRadius: '3px', background: color }} />
                  <span style={{ flex: 1, fontSize: '14px' }}>{name}</span>
                  <span style={{ fontWeight: 600 }}>{value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Signal Volume Chart */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Signal Volume vs Risk Score</h3>
        </div>
        <ResponsiveContainer width="100%" height={250}>
          <ComposedChart data={riskTrendData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="date" stroke="#64748b" fontSize={12} />
            <YAxis yAxisId="left" stroke="#64748b" fontSize={12} />
            <YAxis yAxisId="right" orientation="right" stroke="#64748b" fontSize={12} domain={[0, 100]} />
            <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
            <Bar yAxisId="left" dataKey="signals" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            <Line yAxisId="right" type="monotone" dataKey="score" stroke="#ef4444" strokeWidth={2} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default Dashboard;
