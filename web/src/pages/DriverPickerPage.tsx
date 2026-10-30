import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getMachines, ApiError } from '../api';
import { triggerReauth } from '../components/PasscodeGate';
import { friendlyError } from '../errors';
import type { MachineOut } from '../types';

/**
 * /driver: lets an operator open a machine's driver view.
 * A driver's own phone gets the full link (/driver/<token>) from the Desk; this page is
 * for staff checking what a driver sees. Before this page the navbar pointed at a
 * made-up token (/driver/demo-machine), which always showed "not found".
 */
export default function DriverPickerPage() {
  const [machines, setMachines] = useState<MachineOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMachines()
      .then(setMachines)
      .catch(err => {
        triggerReauth(err);
        setError(err instanceof ApiError ? friendlyError(err.error_code) : 'Could not load machines.');
      });
  }, []);

  return (
    <div className="desk-container" id="driver-picker-page">
      <div className="card">
        <h2>Driver view</h2>
        <p className="card-subtitle">
          Open what a machine's driver sees today. To give a driver their link, copy it from Desk → Machines.
        </p>
        {error && <div className="outcome-banner outcome-error">{error}</div>}
        {machines && machines.length === 0 && <p id="driver-picker-empty">No machines yet. Add one on the Desk.</p>}
        {machines && machines.length > 0 && (
          <ul className="driver-picker-list" style={{ listStyle: 'none', padding: 0 }}>
            {machines.map(m => {
              const usable = m.driver_path && (m.driver_link_status ?? 'active') === 'active';
              return (
                <li key={m.id} className="driver-link-row" style={{ margin: '0.5rem 0' }}>
                  <strong style={{ minWidth: '12rem', display: 'inline-block' }}>{m.name}</strong>{' '}
                  {usable ? (
                    <Link id={`open-driver-${m.id}`} className="btn btn-secondary btn-sm" to={m.driver_path}>
                      Open driver view
                    </Link>
                  ) : (
                    <span className="attr-label">
                      Link {m.driver_link_status === 'revoked' ? 'turned off' : 'expired'}: issue a new one on Desk → Machines
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
