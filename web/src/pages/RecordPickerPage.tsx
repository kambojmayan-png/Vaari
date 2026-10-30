import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getSlots, ApiError } from '../api';
import { triggerReauth } from '../components/PasscodeGate';
import { friendlyError } from '../errors';
import type { SlotOut } from '../types';

/**
 * /record: lists completed jobs so an operator can open their service records.
 * A farmer gets the full link (/record/<token>). Before this page the navbar pointed at a
 * made-up token (/record/demo-token), which always showed "Service Record Not Found".
 */
export default function RecordPickerPage() {
  const [done, setDone] = useState<SlotOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSlots()
      .then(slots => setDone(slots.filter(s => s.status === 'done' && s.record_token)))
      .catch(err => {
        triggerReauth(err);
        setError(err instanceof ApiError ? friendlyError(err.error_code) : 'Could not load jobs.');
      });
  }, []);

  return (
    <div className="desk-container" id="record-picker-page">
      <div className="card">
        <h2>Service records</h2>
        <p className="card-subtitle">A record exists once a driver marks a job Done. Newest first.</p>
        {error && <div className="outcome-banner outcome-error">{error}</div>}
        {done && done.length === 0 && (
          <p id="record-picker-empty">No completed jobs yet. Finish a job from a driver view and its record appears here.</p>
        )}
        {done && done.length > 0 && (
          <table className="will-miss-table" id="record-picker-table">
            <thead>
              <tr>
                <th>Request</th>
                <th>Village</th>
                <th>Machine</th>
                <th>Done</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {[...done]
                .sort((a, b) => (b.done_at ?? '').localeCompare(a.done_at ?? ''))
                .map(s => (
                  <tr key={s.id}>
                    <td>VR-{s.request_id}</td>
                    <td>{s.village}</td>
                    <td>{s.machine.name}</td>
                    <td>{s.done_at?.slice(0, 16).replace('T', ' ')}</td>
                    <td>
                      <Link id={`open-record-${s.id}`} className="btn btn-secondary btn-sm" to={`/record/${s.record_token}`}>
                        Open record
                      </Link>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
