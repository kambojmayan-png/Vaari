import { useState } from 'react';
import { patchMachine, rotateDriverLink, revokeDriverLink, ApiError } from '../api';
import { friendlyError } from '../errors';
import type { MachineOut, ScheduleDay } from '../types';

interface Props {
  machines: MachineOut[];
  schedule: ScheduleDay[];
  todayDate: string;
  onRefreshAll: () => void;
}

export default function MachinesTab({ machines, schedule, todayDate, onRefreshAll }: Props) {
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleToggleStatus = async (machine: MachineOut) => {
    setTogglingId(machine.id);
    setActionError(null);
    const nextStatus = machine.status === 'active' ? 'inactive' : 'active';
    try {
      await patchMachine(machine.id, { status: nextStatus });
      onRefreshAll();
    } catch (err) {
      if (err instanceof ApiError) {
        setActionError(friendlyError(err.error_code) || err.message);
      } else {
        setActionError('Failed to toggle machine status.');
      }
    } finally {
      setTogglingId(null);
    }
  };

  const handleLinkAction = async (machine: MachineOut, action: 'rotate' | 'revoke') => {
    if (action === 'revoke' && !window.confirm(`Turn off the driver link for ${machine.name}? The phone holding it stops working at once.`)) {
      return;
    }
    setTogglingId(machine.id);
    setActionError(null);
    try {
      if (action === 'rotate') await rotateDriverLink(machine.id);
      else await revokeDriverLink(machine.id);
      onRefreshAll();
    } catch (err) {
      setActionError(err instanceof ApiError ? friendlyError(err.error_code) || err.message : 'Failed to change the driver link.');
    } finally {
      setTogglingId(null);
    }
  };

  const handleCopyDriverLink = async (machine: MachineOut) => {
    const fullUrl = `${window.location.origin}${machine.driver_path}`;
    try {
      await navigator.clipboard.writeText(fullUrl);
      setCopiedId(machine.id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      // Fallback
    }
  };

  return (
    <div className="machines-container" id="machines-tab">
      <div className="table-header-info">
        <h3>Machinery Fleet & Daily Allocations</h3>
        <p className="card-subtitle">
          Capacity tracking for {todayDate || 'today'}. Toggling an active machine to inactive automatically reflows slots.
        </p>
      </div>

      {actionError && (
        <div className="outcome-banner outcome-error mb-3">
          {actionError}
        </div>
      )}

      <div className="machines-grid">
        {machines.map(m => {
          const sched = schedule.find(s => s.machine_id === m.id);
          const usedAcres = sched ? sched.used_acres : 0;
          const capacity = m.capacity_acres_per_day;
          const availableAcres = Math.max(0, +(capacity - usedAcres).toFixed(2));
          const slots = sched?.slots || [];
          const fullDriverUrl = `${window.location.origin}${m.driver_path}`;

          return (
            <div key={m.id} className="card machine-card" id={`machine-card-${m.id}`}>
              <div className="machine-header">
                <div>
                  <div className="machine-title-row">
                    <h4>{m.name}</h4>
                    <span className={`status-pill pill-${m.status}`}>{m.status}</span>
                  </div>
                  <p className="text-muted">{m.type} • {capacity} acres/day capacity</p>
                </div>

                <button
                  id={`btn-toggle-machine-${m.id}`}
                  type="button"
                  className={`btn ${m.status === 'active' ? 'btn-secondary' : 'btn-primary'}`}
                  onClick={() => handleToggleStatus(m)}
                  disabled={togglingId === m.id}
                >
                  {togglingId === m.id
                    ? 'Updating…'
                    : m.status === 'active'
                    ? 'Mark Inactive'
                    : 'Mark Active'}
                </button>
              </div>

              {/* Capacity Progress Bar */}
              <div className="machine-capacity-section">
                <div className="capacity-labels">
                  <span>Today's Allocated Capacity</span>
                  <strong>{usedAcres} / {capacity} acres ({availableAcres} available)</strong>
                </div>
                <div className="capacity-bar-track">
                  <div
                    className="capacity-bar-fill"
                    style={{ width: `${Math.min(100, (usedAcres / capacity) * 100)}%` }}
                  />
                </div>
              </div>

              {/* Driver Link */}
              <div className="driver-link-box">
                <span className="attr-label">Driver Portal Link</span>
                <div className="driver-link-row">
                  <input
                    type="text"
                    readOnly
                    value={fullDriverUrl}
                    className="driver-url-input"
                  />
                  <button
                    id={`btn-copy-driver-${m.id}`}
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleCopyDriverLink(m)}
                  >
                    {copiedId === m.id ? '✓ Copied' : 'Copy'}
                  </button>
                  <a
                    href={m.driver_path}
                    target="_blank"
                    rel="noreferrer"
                    className="btn btn-secondary btn-sm"
                  >
                    Open
                  </a>
                </div>
                <div className="driver-link-row" id={`driver-link-state-${m.id}`}>
                  <span className={`status-pill ${m.driver_link_status === 'active' || !m.driver_link_status ? '' : 'pill-red'}`}>
                    {m.driver_link_status === 'revoked'
                      ? 'link turned off'
                      : m.driver_link_status === 'expired'
                      ? 'link expired'
                      : 'link active'}
                  </span>
                  {m.driver_link_expires_at && m.driver_link_status === 'active' && (
                    <span className="attr-label">until {m.driver_link_expires_at.slice(0, 10)}</span>
                  )}
                  <button
                    id={`btn-rotate-link-${m.id}`}
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={togglingId === m.id}
                    onClick={() => handleLinkAction(m, 'rotate')}
                  >
                    New link
                  </button>
                  {m.driver_link_status !== 'revoked' && (
                    <button
                      id={`btn-revoke-link-${m.id}`}
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={togglingId === m.id}
                      onClick={() => handleLinkAction(m, 'revoke')}
                    >
                      Turn off link
                    </button>
                  )}
                </div>
              </div>

              {/* Today's Jobs in Order */}
              <div className="machine-jobs-section">
                <h5>Today's Jobs ({slots.length})</h5>
                {slots.length === 0 ? (
                  <p className="text-muted text-sm">No slots assigned for today.</p>
                ) : (
                  <ol className="machine-slots-list">
                    {slots.map(s => (
                      <li key={s.id} className="slot-item">
                        <span className="slot-seq">#{s.seq}</span>
                        <span className="slot-village">{s.village}</span>
                        <span className="slot-acres">{s.acres} ac</span>
                        <span className={`status-pill pill-${s.status}`}>{s.status}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
