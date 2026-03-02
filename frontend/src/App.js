import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Authenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Signals from './pages/Signals';
import RiskAssessments from './pages/RiskAssessments';
import RiskDetail from './pages/RiskDetail';
import Workflow from './pages/Workflow';
import Chat from './pages/Chat';
import Simulate from './pages/Simulate';
import AuditTrail from './pages/AuditTrail';

function App() {
  return (
    <Authenticator>
      {({ signOut, user }) => (
        <BrowserRouter>
          <div className="app-container">
            <Sidebar user={user} onSignOut={signOut} />
            <main className="main-content">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/signals" element={<Signals />} />
                <Route path="/risks" element={<RiskAssessments />} />
                <Route path="/risks/:id" element={<RiskDetail />} />
                <Route path="/workflow" element={<Workflow />} />
                <Route path="/chat" element={<Chat />} />
                <Route path="/simulate" element={<Simulate />} />
                <Route path="/audit" element={<AuditTrail />} />
              </Routes>
            </main>
          </div>
        </BrowserRouter>
      )}
    </Authenticator>
  );
}

export default App;
