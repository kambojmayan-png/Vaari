import { BrowserRouter, Routes, Route, Navigate, NavLink } from 'react-router-dom';
import PasscodeGate from './components/PasscodeGate';
import SignOutButton from './components/SignOutButton';
import DeskPage from './pages/DeskPage';
import DriverPage from './pages/DriverPage';
import OfficerPage from './pages/OfficerPage';
import RecordPage from './pages/RecordPage';
import DriverPickerPage from './pages/DriverPickerPage';
import RecordPickerPage from './pages/RecordPickerPage';
import IntakePage from './pages/IntakePage';

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <header className="app-navbar">
          <div className="navbar-container">
            <div className="brand-group">
              <span className="brand-leaf">🌾</span>
              <span className="brand-name">Vaari</span>
              <span className="brand-phase">v0.1</span>
            </div>
            <nav className="nav-links">
              <NavLink
                to="/desk"
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                id="nav-desk"
              >
                Desk
              </NavLink>
              <NavLink
                to="/intake"
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                id="nav-intake"
              >
                Register Intake
              </NavLink>
              <NavLink
                to="/officer"
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                id="nav-officer"
              >
                Officer
              </NavLink>
              <NavLink
                to="/driver"
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                id="nav-driver"
              >
                Driver View
              </NavLink>
              <NavLink
                to="/record"
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                id="nav-record"
              >
                Record View
              </NavLink>
              <SignOutButton />
            </nav>
          </div>
        </header>

        <div className="app-content">
          <Routes>
            <Route path="/" element={<Navigate to="/desk" replace />} />
            <Route
              path="/desk"
              element={
                <PasscodeGate>
                  <DeskPage />
                </PasscodeGate>
              }
            />
            <Route
              path="/intake"
              element={
                <PasscodeGate>
                  <IntakePage />
                </PasscodeGate>
              }
            />
            <Route
              path="/driver"
              element={
                <PasscodeGate>
                  <DriverPickerPage />
                </PasscodeGate>
              }
            />
            <Route path="/driver/:machineToken" element={<DriverPage />} />
            <Route
              path="/officer"
              element={
                <PasscodeGate roles={['officer', 'operator']}>
                  <OfficerPage />
                </PasscodeGate>
              }
            />
            <Route
              path="/record"
              element={
                <PasscodeGate>
                  <RecordPickerPage />
                </PasscodeGate>
              }
            />
            <Route path="/record/:token" element={<RecordPage />} />
            <Route path="*" element={<Navigate to="/desk" replace />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
