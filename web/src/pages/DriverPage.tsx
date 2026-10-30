import { useEffect, useState, useCallback, useRef, type ChangeEvent } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  getDriver,
  startSlot,
  doneSlot,
  notServedSlot,
  ApiError,
} from '../api';
import { friendlyError } from '../errors';
import { downscaleImage, getCurrentPosition, formatIST } from '../utils/image';
import Badge from '../components/Badge';
import type { DriverResponse, SlotOut, SlotEvidenceOut } from '../types';

const NOT_SERVED_REASONS = [
  { id: 'FIELD_NOT_READY', label: 'Field not ready' },
  { id: 'FARMER_ABSENT', label: 'Farmer not there / absent' },
  { id: 'MACHINE_BROKEN', label: 'Machine broken' },
  { id: 'WEATHER', label: 'Weather condition' },
  { id: 'OTHER', label: 'Other reason' },
];

export default function DriverPage() {
  const { machineToken } = useParams<{ machineToken: string }>();

  const [driverData, setDriverData] = useState<DriverResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [fetchErrorCode, setFetchErrorCode] = useState<string | null>(null);

  // Active opened job
  const [selectedSlot, setSelectedSlot] = useState<SlotOut | null>(null);

  // Action states for active slot
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [farmerCode, setFarmerCode] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitProgress, setSubmitProgress] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastEvidence, setLastEvidence] = useState<SlotEvidenceOut | null>(null);
  const [positionSelfReported, setPositionSelfReported] = useState(false);

  // Could not serve modal state
  const [showNotServed, setShowNotServed] = useState(false);
  const [notServedReason, setNotServedReason] = useState('FIELD_NOT_READY');
  const [notServedNote, setNotServedNote] = useState('');
  const [submittingNotServed, setSubmittingNotServed] = useState(false);
  const [notServedError, setNotServedError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDriverJobs = useCallback(async (token: string) => {
    setFetchError(null);
    setFetchErrorCode(null);
    try {
      const data = await getDriver(token);
      setDriverData(data);

      // Keep active slot updated
      setSelectedSlot((prev) => {
        if (!prev) return null;
        return data.slots.find((s) => s.id === prev.id) || null;
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setFetchErrorCode(err.error_code);
        setFetchError(
          err.error_code === 'NOT_FOUND'
            ? 'This driver link does not exist. Ask the centre for the current link.'
            : friendlyError(err.error_code) || err.message,
        );
      } else {
        setFetchError('Could not load jobs. Check network connection.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (machineToken) {
      loadDriverJobs(machineToken);
    } else {
      setFetchError('Machine token is missing.');
      setLoading(false);
    }
  }, [machineToken, loadDriverJobs]);

  // Open slot
  const handleSelectSlot = (slot: SlotOut) => {
    setSelectedSlot(slot);
    setPhotoFile(null);
    setPhotoPreview(null);
    setFarmerCode('');
    setActionError(null);
    setLastEvidence(null);
    setPositionSelfReported(false);
    setShowNotServed(false);
  };

  // Close active slot modal
  const handleCloseSlot = () => {
    setSelectedSlot(null);
    setPhotoFile(null);
    setPhotoPreview(null);
    setActionError(null);
    setShowNotServed(false);
  };

  // Handle photo selection
  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPhotoFile(file);
    setActionError(null);
    const objectUrl = URL.createObjectURL(file);
    setPhotoPreview(objectUrl);
  };

  // Execute START action
  const handleStartJob = async () => {
    if (!selectedSlot || !selectedSlot.link_token) {
      setActionError('Slot link token is missing.');
      return;
    }

    setSubmitting(true);
    setActionError(null);

    try {
      // 1. Process photo (if provided)
      let processedPhoto: File | undefined = undefined;
      if (photoFile) {
        setSubmitProgress('Optimizing photo for upload…');
        processedPhoto = await downscaleImage(photoFile, 1600);
      }

      // 2. Capture GPS (10s timeout, never blocks)
      setSubmitProgress('Checking GPS location…');
      const pos = await getCurrentPosition();
      const posReported = pos.lat == null;
      setPositionSelfReported(posReported);

      // 3. Upload evidence to /api/slots/{id}/start
      setSubmitProgress('Uploading start evidence…');
      const evidence = await startSlot(selectedSlot.id, selectedSlot.link_token, {
        photo: processedPhoto,
        lat: pos.lat,
        lon: pos.lon,
        accuracy_m: pos.accuracy_m,
      });

      setLastEvidence(evidence);
      setPhotoFile(null);
      setPhotoPreview(null);

      // Refresh jobs list
      if (machineToken) {
        await loadDriverJobs(machineToken);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.error_code === 'DUPLICATE_START') {
          setActionError('This job has already been started from another device.');
          if (machineToken) loadDriverJobs(machineToken);
        } else if (err.error_code === 'EVIDENCE_MISSING') {
          setActionError('Take a photo first.');
        } else if (err.error_code === 'NETWORK_DOWN') {
          setActionError('No signal. Your photo is still here. Try again.');
        } else {
          setActionError(friendlyError(err.error_code) || err.message);
        }
      } else {
        setActionError('Failed to start job. Please try again.');
      }
    } finally {
      setSubmitting(false);
      setSubmitProgress(null);
    }
  };

  // Execute DONE action
  const handleDoneJob = useCallback(async () => {
    if (!selectedSlot || !selectedSlot.link_token) {
      setActionError('Slot link token is missing.');
      return;
    }

    setSubmitting(true);
    setActionError(null);

    try {
      // 1. Process photo (if provided)
      let processedPhoto: File | undefined = undefined;
      if (photoFile) {
        setSubmitProgress('Optimizing photo for upload…');
        processedPhoto = await downscaleImage(photoFile, 1600);
      }

      // 2. Capture GPS
      setSubmitProgress('Checking GPS location…');
      const pos = await getCurrentPosition();
      const posReported = pos.lat == null;
      setPositionSelfReported(posReported);

      // 3. Submit done
      setSubmitProgress('Closing job & hashing record…');
      const evidence = await doneSlot(selectedSlot.id, selectedSlot.link_token, {
        photo: processedPhoto,
        lat: pos.lat,
        lon: pos.lon,
        accuracy_m: pos.accuracy_m,
        service_code: farmerCode.trim() || undefined,
      });

      setLastEvidence(evidence);
      setPhotoFile(null);
      setPhotoPreview(null);

      // Refresh jobs list
      if (machineToken) {
        await loadDriverJobs(machineToken);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.error_code === 'INVALID_TRANSITION') {
          setActionError('This action is not allowed in the current state.');
        } else if (err.error_code === 'EVIDENCE_MISSING') {
          setActionError('Take a photo first.');
        } else if (err.error_code === 'NETWORK_DOWN') {
          setActionError('No signal. Your photo is still here. Try again.');
        } else {
          setActionError(friendlyError(err.error_code) || err.message);
        }
      } else {
        setActionError('Failed to mark job complete.');
      }
    } finally {
      setSubmitting(false);
      setSubmitProgress(null);
    }
  }, [selectedSlot, photoFile, farmerCode, machineToken, loadDriverJobs]);

  useEffect(() => {
    (window as unknown as { __triggerDone?: () => Promise<void> }).__triggerDone = handleDoneJob;
    return () => {
      delete (window as unknown as { __triggerDone?: () => Promise<void> }).__triggerDone;
    };
  }, [handleDoneJob]);

  // Submit "Could not serve"
  const handleNotServedSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSlot || !selectedSlot.link_token) return;

    setSubmittingNotServed(true);
    setNotServedError(null);
    try {
      await notServedSlot(selectedSlot.id, selectedSlot.link_token, {
        reason: notServedReason,
        note: notServedNote.trim() || undefined,
      });
      setShowNotServed(false);
      setSelectedSlot(null);
      if (machineToken) {
        await loadDriverJobs(machineToken);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setNotServedError(friendlyError(err.error_code) || err.message);
      } else {
        setNotServedError('Failed to record unserved status.');
      }
    } finally {
      setSubmittingNotServed(false);
    }
  };

  // If initial load failed
  if (fetchError && !driverData) {
    return (
      <div className="driver-cab-container" id="driver-page">
        <div className="driver-error-card">
          <h2 id="driver-error-title">
            {fetchErrorCode === 'NOT_FOUND' || fetchErrorCode === 'LINK_EXPIRED'
              ? 'Link not working'
              : 'Connection Issue'}
          </h2>
          <p>{fetchError}</p>
          <button
            type="button"
            className="btn btn-primary btn-large mt-3"
            onClick={() => machineToken && loadDriverJobs(machineToken)}
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="driver-cab-container" id="driver-page">
      {/* Driver Cab Top Bar: High Contrast, Big Text */}
      <header className="driver-header" id="driver-header">
        <div className="driver-meta">
          <span className="driver-machine-name">
            🚜 {driverData?.machine?.name || 'Assigned Machine'}
          </span>
          <span className="driver-date-pill">{driverData?.date || 'Today'}</span>
        </div>
        <div className="driver-sun-badge">Tractor Cab View</div>
      </header>

      {/* Main Jobs List in Sequence Order */}
      <main className="driver-content">
        <div className="driver-list-header">
          <h2>Today's Jobs ({driverData?.slots.length ?? 0})</h2>
          <span className="cab-hint">Tap job to execute in order</span>
        </div>

        {loading ? (
          <div className="driver-loading">Loading daily job assignments…</div>
        ) : driverData?.slots.length === 0 ? (
          <div className="card text-center p-4">
            <p>No jobs allocated for this machine today.</p>
          </div>
        ) : (
          <div className="driver-jobs-list" id="driver-jobs-list">
            {driverData?.slots.map((s) => (
              <div
                key={s.id}
                id={`driver-job-${s.id}`}
                className={`driver-job-card card-status-${s.status}`}
                onClick={() => handleSelectSlot(s)}
              >
                <div className="job-card-top">
                  <div className="job-seq-badge">#{s.seq}</div>
                  <div className="job-main-info">
                    <span className="job-village">{s.village}</span>
                    <span className="job-acres">{s.acres} acres</span>
                  </div>
                  <div className={`status-pill pill-${s.status}`}>{s.status}</div>
                </div>

                <div className="job-card-footer">
                  <span className="job-deadline">
                    Sow Deadline: <strong>{s.deadline_date || '—'}</strong>
                  </span>
                  {s.link_token ? (
                    <span className="job-ready-indicator">Ready ➔</span>
                  ) : (
                    <span className="text-muted">Token required</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Active Job Action Modal / Full-Screen Cab Card */}
      {selectedSlot && (
        <div className="driver-modal-overlay" id="driver-action-modal">
          <div className="driver-action-card">
            <div className="action-card-header">
              <div>
                <span className="attr-label">Job #{selectedSlot.seq}</span>
                <h3>{selectedSlot.village} • {selectedSlot.acres} Acres</h3>
              </div>
              <button
                type="button"
                className="cab-close-btn"
                onClick={handleCloseSlot}
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            {/* Error Banner */}
            {actionError && (
              <div className="outcome-banner outcome-error" id="driver-action-error">
                {actionError}
              </div>
            )}

            {/* In Progress indicator */}
            {submitProgress && (
              <div className="outcome-banner outcome-info">
                {submitProgress}
              </div>
            )}

            {/* Evidence State (Three Ticks) upon completion */}
            {lastEvidence && (
              <div className="evidence-summary-card" id="evidence-summary-ticks">
                <h4>✓ Evidence Recorded</h4>
                <div className="ticks-grid">
                  <div className="tick-item">
                    <span className="tick-label">Position</span>
                    <strong className="tick-value">
                      {lastEvidence.evidence.lat != null
                        ? `✓ Plausible (${lastEvidence.evidence.lat.toFixed(4)}, ${lastEvidence.evidence.lon?.toFixed(4)})`
                        : 'not given'}
                    </strong>
                    {positionSelfReported && (
                      <Badge name="position self-reported" className="mt-1" />
                    )}
                  </div>

                  <div className="tick-item">
                    <span className="tick-label">Photo</span>
                    <strong className="tick-value">✓ Captured</strong>
                  </div>

                  <div className="tick-item">
                    <span className="tick-label">Server Timestamp</span>
                    <strong className="tick-value">
                      {formatIST(lastEvidence.evidence.timestamp)}
                    </strong>
                  </div>
                </div>

                {/* Flags in Plain Words */}
                {lastEvidence.flags && lastEvidence.flags.length > 0 && (
                  <div className="flags-list mt-2" id="driver-flags-list">
                    <span className="attr-label">Flags:</span>
                    {lastEvidence.flags.map((fl) => {
                      const plainText =
                        fl === 'too_fast'
                          ? 'Finished faster than a machine can work: a person will look'
                          : fl === 'exact_duplicate_photo'
                          ? "Photo exactly matches another job's photo"
                          : fl === 'code_missing'
                          ? "Farmer's code not entered"
                          : fl === 'code_wrong'
                          ? "Farmer's code did not match"
                          : fl === 'position_mismatch'
                          ? 'Position is outside the expected plot: a person will look'
                          : fl;
                      return (
                        <span key={fl} className="badge badge-warning ml-1">
                          {plainText}
                        </span>
                      );
                    })}
                  </div>
                )}

                {lastEvidence.record_url ? (
                  <div className="mt-3">
                    <Link
                      to={lastEvidence.record_url}
                      className="btn btn-secondary btn-large full-width"
                      id="btn-view-record-link"
                    >
                      View Service Record ➔
                    </Link>
                  </div>
                ) : (
                  <div className="mt-3">
                    <button
                      type="button"
                      id="btn-continue-job"
                      className="btn btn-primary btn-large full-width"
                      onClick={() => setLastEvidence(null)}
                    >
                      Continue to Completion / ਕੰਮ ਪੂਰਾ ਕਰੋ ➔
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* State 1: SCHEDULED -> Big START button */}
            {selectedSlot.status === 'scheduled' && !lastEvidence && (
              <div className="slot-action-body">
                <div className="camera-upload-section">
                  <label className="camera-label">
                    <span>📷 Photograph the field (Start)</span>
                    <small className="camera-hint">Photograph the field, not faces</small>
                    <input
                      ref={fileInputRef}
                      id="driver-camera-input"
                      type="file"
                      accept="image/*"
                      capture="environment"
                      onChange={handleFileChange}
                      className="hidden-file-input"
                    />
                  </label>
                  {photoPreview && (
                    <div className="photo-preview-box">
                      <img src={photoPreview} alt="Field preview" className="preview-img" />
                      <span className="preview-badge">✓ Photo ready</span>
                    </div>
                  )}
                </div>

                <button
                  id="btn-start-job"
                  type="button"
                  className="btn btn-cab-start"
                  onClick={handleStartJob}
                  disabled={submitting}
                >
                  {submitting ? 'Starting Job…' : 'START / ਸ਼ੁਰੂ'}
                </button>

                <div className="text-center mt-3">
                  <button
                    type="button"
                    className="link-btn text-muted"
                    id="btn-open-not-served"
                    onClick={() => setShowNotServed(true)}
                  >
                    Could not serve this request
                  </button>
                </div>
              </div>
            )}

            {/* State 2: IN_PROGRESS -> Big MARK DONE button */}
            {selectedSlot.status === 'in_progress' && !lastEvidence && (
              <div className="slot-action-body">
                <div className="camera-upload-section">
                  <label className="camera-label">
                    <span>📷 Photograph completed field (Done)</span>
                    <small className="camera-hint">Photograph the field, not faces</small>
                    <input
                      ref={fileInputRef}
                      id="driver-camera-input-done"
                      type="file"
                      accept="image/*"
                      capture="environment"
                      onChange={handleFileChange}
                      className="hidden-file-input"
                    />
                  </label>
                  {photoPreview && (
                    <div className="photo-preview-box">
                      <img src={photoPreview} alt="Field preview" className="preview-img" />
                      <span className="preview-badge">✓ Photo ready</span>
                    </div>
                  )}
                </div>

                <div className="form-group code-input-group">
                  <label htmlFor="farmer-code-input">Farmer's 4-Digit Code (optional)</label>
                  <input
                    id="farmer-code-input"
                    type="text"
                    inputMode="numeric"
                    maxLength={4}
                    placeholder="e.g. 4821"
                    value={farmerCode}
                    onChange={(e) => setFarmerCode(e.target.value.replace(/\D/g, ''))}
                    className="cab-code-input"
                  />
                  <small className="text-muted">Given in the farmer's slot message</small>
                </div>

                <button
                  id="btn-done-job"
                  type="button"
                  className="btn btn-cab-done"
                  onClick={handleDoneJob}
                  disabled={submitting}
                >
                  {submitting ? 'Marking Done…' : 'DONE / ਕੰਮ ਪੂਰਾ'}
                </button>

                <div className="text-center mt-3">
                  <button
                    type="button"
                    className="link-btn text-muted"
                    onClick={() => setShowNotServed(true)}
                  >
                    Could not serve this request
                  </button>
                </div>
              </div>
            )}

            {/* State 3: DONE -> Show Record Link and Summary */}
            {selectedSlot.status === 'done' && !lastEvidence && (
              <div className="slot-action-body">
                <div className="done-status-card">
                  <h3>✓ Job Completed</h3>
                  <p>Evidence and server hash have been secured.</p>
                  {selectedSlot.record_token && (
                    <Link
                      to={`/record/${selectedSlot.record_token}`}
                      className="btn btn-primary btn-large mt-3"
                    >
                      Open Completion Record ➔
                    </Link>
                  )}
                </div>
              </div>
            )}

            {/* "Could not serve" sub-modal */}
            {showNotServed && (
              <div className="not-served-modal" id="not-served-modal">
                <div className="not-served-card">
                  <h4>Reason Job Could Not Be Served</h4>
                  {notServedError && (
                    <div className="outcome-banner outcome-error mb-2">
                      {notServedError}
                    </div>
                  )}
                  <form onSubmit={handleNotServedSubmit}>
                    <div className="reasons-radio-list">
                      {NOT_SERVED_REASONS.map((r) => (
                        <label key={r.id} className="radio-label">
                          <input
                            type="radio"
                            name="not_served_reason"
                            value={r.id}
                            checked={notServedReason === r.id}
                            onChange={(e) => setNotServedReason(e.target.value)}
                          />
                          <span>{r.label}</span>
                        </label>
                      ))}
                    </div>

                    <div className="form-group mt-2">
                      <label htmlFor="not-served-note">Optional Note</label>
                      <input
                        id="not-served-note"
                        type="text"
                        placeholder="e.g. Field heavily flooded"
                        value={notServedNote}
                        onChange={(e) => setNotServedNote(e.target.value)}
                      />
                    </div>

                    <div className="action-row mt-3">
                      <button
                        id="btn-submit-not-served"
                        type="submit"
                        className="btn btn-danger btn-large"
                        disabled={submittingNotServed}
                      >
                        {submittingNotServed ? 'Recording…' : 'Confirm Could Not Serve'}
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => setShowNotServed(false)}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
