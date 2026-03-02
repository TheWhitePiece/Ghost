import React from 'react';
import { NavLink } from 'react-router-dom';

const navItems = [
  { path: '/', icon: '📊', label: 'Dashboard' },
  { path: '/signals', icon: '📡', label: 'Signals' },
  { path: '/risks', icon: '⚠️', label: 'Risk Assessments' },
  { path: '/workflow', icon: '🔄', label: 'Workflow' },
  { path: '/chat', icon: '🧠', label: 'Ask the Ghost' },
  { path: '/simulate', icon: '🎯', label: 'Simulate' },
  { path: '/audit', icon: '📋', label: 'Audit Trail' },
];

function Sidebar({ user, onSignOut }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <span className="ghost-icon">🚢</span>
        <h1>
          GHOST
          <span>Supply Chain Intelligence</span>
        </h1>
      </div>

      <ul className="nav-items">
        {navItems.map(({ path, icon, label }) => (
          <li key={path} className="nav-item">
            <NavLink
              to={path}
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
              end={path === '/'}
            >
              <span>{icon}</span>
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '16px' }}>
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px', padding: '0 8px' }}>
          {user?.signInDetails?.loginId || 'User'}
        </div>
        <button onClick={onSignOut} className="btn btn-ghost" style={{ width: '100%', justifyContent: 'center' }}>
          Sign Out
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
