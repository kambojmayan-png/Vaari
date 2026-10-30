import { useState, useEffect, useCallback, type ChangeEvent } from 'react';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import StatusStrip from '../components/StatusStrip';
import Badge from '../components/Badge';
import NewRequestForm from '../components/NewRequestForm';
import {
  uploadRegisterPhoto,
  getIntakeDraft,
  getIntakeImageBlobUrl,
  confirmIntakeDraft,
  getRequests,
  getHealth,
  ApiError,
} from '../api';
import { triggerReauth } from '../components/PasscodeGate';
import { friendlyError } from '../errors';
import type { Health, IntakeOut, IntakeConfirmError } from '../types';
import ReaderBanner from '../components/ReaderBanner';

const LOW_CONF_THRESHOLD = 0.8;

interface EditableRowState {
  row: number;
  phone: string;
  name: string;
  village: string;
  acres: string;
  service_type: string;
  harvest_date: string;
  confidence: Record<string, number>;
  issues: string[];
  editedFields: Record<string, boolean>;
  consentAgreed: boolean;
  skip: boolean;
  confirmedRequestId?: number;
}

function normalizeDateStr(d: string): { date: string; wasExpanded: boolean } {
  if (!d) return { date: '', wasExpanded: false };
  const s = d.trim();
  // Match DD-MM-YY, DD/MM/YY, DD.MM.YY
  const match2Digit = s.match(/^(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{2})$/);
  if (match2Digit) {
    const p1 = parseInt(match2Digit[1], 10);
    const p2 = parseInt(match2Digit[2], 10);
    const p3 = parseInt(match2Digit[3], 10);
    // If year is in front (YY-MM-DD e.g. 26-10-22)
    if (p1 >= 24 && p1 <= 30 && p3 <= 31) {
      const year = `20${String(p1).padStart(2, '0')}`;
      const month = String(p2).padStart(2, '0');
      const day = String(p3).padStart(2, '0');
      return { date: `${year}-${month}-${day}`, wasExpanded: true };
    }
    // Standard DD-MM-YY (e.g. 22-10-26)
    const year = `20${String(p3).padStart(2, '0')}`;
    const month = String(p2).padStart(2, '0');
    const day = String(p1).padStart(2, '0');
    return { date: `${year}-${month}-${day}`, wasExpanded: true };
  }
  return { date: s, wasExpanded: false };
}

function buildEditableRows(draft: IntakeOut): EditableRowState[] {
  return draft.rows.map((r) => {
    const rawDate = r.fields.harvest_date != null ? String(r.fields.harvest_date) : '';
    const norm = normalizeDateStr(rawDate);
    const filteredIssues = norm.wasExpanded
      ? (r.issues || []).filter((iss) => !iss.toLowerCase().startsWith('harvest_date:'))
      : r.issues || [];
    return {
      row: r.row,
      phone: r.fields.phone != null ? String(r.fields.phone) : '',
      name: r.fields.name != null ? String(r.fields.name) : '',
      village: r.fields.village != null ? String(r.fields.village) : '',
      acres: r.fields.acres != null ? String(r.fields.acres) : '',
      service_type: r.fields.service_type != null ? String(r.fields.service_type) : 'super_seeder',
      harvest_date: norm.date,
      confidence: r.confidence || {},
      issues: filteredIssues,
      editedFields: {},
      consentAgreed: true,
      skip: false,
    };
  });
}

export default function IntakePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [, setReaderMode] = useState<string>('mock');
  // Pilot Part 5: turn a page photographed sideways before it is stored and read
  const [rotate, setRotate] = useState<0 | 90 | 180 | 270>(0);
  const [health, setHealth] = useState<Health | null>(null);
  const [villages, setVillages] = useState<string[]>([
    'Pind Kalan',
    'Bhucho Khurd',
    'Rampura Phul',
    'Kot Shamir',
    'Maur Mandi',
    'Sangat Kalan',
    'Talwandi Sabo',
    'Goniana Mandi',
  ]);

  const [uploading, setUploading] = useState(false);
  const [draft, setDraft] = useState<IntakeOut | null>(null);
  const [rows, setRows] = useState<EditableRowState[]>([]);
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);

  // Fallback state (503 READER_UNAVAILABLE)
  const [readerFailed, setReaderFailed] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Confirmation state
  const [confirming, setConfirming] = useState(false);
  const [confirmSummary, setConfirmSummary] = useState<{
    createdCount: number;
    skippedCount: number;
    createdIds: number[];
  } | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<number, IntakeConfirmError>>({});

  // Load initial health & villages
  useEffect(() => {
    getHealth()
      .then((h) => {
        setReaderMode(h.reader);
        setHealth(h);
      })
      .catch(() => {});
    getRequests()
      .then((reqs) => {
        const s = new Set<string>(villages);
        reqs.forEach((r) => {
          if (r.village) s.add(r.village);
        });
        setVillages(Array.from(s).sort());
      })
      .catch((err) => triggerReauth(err));
  }, []);

  // Reload draft from URL ?id=7 so a draft survives a page reload
  const loadDraftById = useCallback(async (id: number) => {
    setErrorBanner(null);
    try {
      const [loadedDraft, blobUrl] = await Promise.all([
        getIntakeDraft(id),
        getIntakeImageBlobUrl(id).catch(() => null),
      ]);
      setDraft(loadedDraft);
      setReaderMode(loadedDraft.reader);
      setRows(buildEditableRows(loadedDraft));
      if (blobUrl) setPhotoUrl(blobUrl);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          triggerReauth(err);
          return;
        }
        setErrorBanner(friendlyError(err.error_code) || err.message);
      }
    }
  }, []);

  useEffect(() => {
    const idParam = searchParams.get('id');
    if (idParam && !draft && !uploading && !readerFailed) {
      const parsedId = parseInt(idParam, 10);
      if (!isNaN(parsedId)) {
        loadDraftById(parsedId);
      }
    }
  }, [searchParams, draft, uploading, readerFailed, loadDraftById]);

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setErrorBanner(null);
    setReaderFailed(false);
    setConfirmSummary(null);
    setRowErrors({});
    setDraft(null);

    const localObjUrl = URL.createObjectURL(file);
    setPhotoUrl(localObjUrl);

    try {
      const uploadedDraft = await uploadRegisterPhoto(file, rotate);
      setDraft(uploadedDraft);
      setReaderMode(uploadedDraft.reader);
      setRows(buildEditableRows(uploadedDraft));
      setSearchParams({ id: String(uploadedDraft.intake_id) });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          triggerReauth(err);
          return;
        }
        if (err.error_code === 'READER_UNAVAILABLE') {
          setReaderFailed(true);
          setErrorBanner('Reader unavailable: type the rows');
          const intakeId = err.details?.intake_id ? Number(err.details.intake_id) : null;
          if (intakeId) {
            getIntakeImageBlobUrl(intakeId)
              .then((serverBlobUrl) => setPhotoUrl(serverBlobUrl))
              .catch(() => {});
          }
        } else {
          setErrorBanner(friendlyError(err.error_code) || err.message);
        }
      } else {
        setErrorBanner('Failed to upload register photo.');
      }
    } finally {
      setUploading(false);
    }
  };

  const updateCell = (
    rowIndex: number,
    field: 'phone' | 'name' | 'village' | 'acres' | 'service_type' | 'harvest_date',
    value: string,
  ) => {
    setRows((prev) =>
      prev.map((r, idx) => {
        if (idx !== rowIndex) return r;
        // Remove field-specific issue once operator edits the cell
        const filteredIssues = r.issues.filter(
          (iss) => !iss.toLowerCase().startsWith(`${field}:`),
        );
        return {
          ...r,
          [field]: value,
          issues: filteredIssues,
          editedFields: { ...r.editedFields, [field]: true },
        };
      }),
    );
    const targetRowNo = rows[rowIndex]?.row;
    if (targetRowNo && rowErrors[targetRowNo]) {
      setRowErrors((prev) => {
        const copy = { ...prev };
        delete copy[targetRowNo];
        return copy;
      });
    }
  };

  const toggleSkip = (rowIndex: number) => {
    setRows((prev) =>
      prev.map((r, idx) => (idx === rowIndex ? { ...r, skip: !r.skip } : r)),
    );
  };

  const toggleConsent = (rowIndex: number) => {
    setRows((prev) =>
      prev.map((r, idx) =>
        idx === rowIndex ? { ...r, consentAgreed: !r.consentAgreed } : r,
      ),
    );
  };

  const getFieldIssues = (r: EditableRowState, field: string): string[] => {
    const list = r.issues.filter((iss) =>
      iss.toLowerCase().startsWith(`${field}:`),
    );
    const apiErr = rowErrors[r.row];
    if (apiErr && apiErr.field === field && !list.includes(apiErr.message)) {
      list.push(apiErr.message);
    }
    return list;
  };

  const getCellStyle = (r: EditableRowState, field: string) => {
    if (r. editedFields[field]) {
      return {
        backgroundColor: '#f1f5f9',
        borderColor: '#64748b',
      };
    }
    const fieldIssues = getFieldIssues(r, field);
    if (fieldIssues.length > 0) {
      return {
        backgroundColor: '#fef2f2',
        borderColor: '#dc2626',
      };
    }
    const conf = r.confidence[field];
    if (conf !== undefined && conf < LOW_CONF_THRESHOLD) {
      return {
        backgroundColor: '#fef3c7',
        borderColor: '#d97706',
      };
    }
    return {};
  };

  const getCellClass = (r: EditableRowState, field: string): string => {
    if (r.editedFields[field]) return 'cell-edited';
    if (getFieldIssues(r, field).length > 0) return 'cell-issue input-error';
    const conf = r.confidence[field];
    if (conf !== undefined && conf < LOW_CONF_THRESHOLD) return 'cell-low-confidence';
    return '';
  };

  const handleConfirm = async () => {
    if (!draft) return;
    setConfirming(true);
    setErrorBanner(null);

    try {
      const payloadRows = rows.map((r) => ({
        row: r.row,
        skip: r.skip,
        consent_service: r.consentAgreed,
        consent_evidence: r.consentAgreed,
        consent_share: r.consentAgreed,
        fields: {
          phone: r.phone.trim(),
          name: r.name.trim() || null,
          village: r.village.trim(),
          acres: r.acres.trim() !== '' ? Number(r.acres) : null,
          service_type: r.service_type,
          harvest_date: r.harvest_date.trim() || null,
        },
      }));

      const res = await confirmIntakeDraft(draft.intake_id, payloadRows);

      setConfirmSummary({
        createdCount: res.created_request_ids.length,
        skippedCount: res.skipped_rows.length,
        createdIds: res.created_request_ids,
      });

      const errMap: Record<number, IntakeConfirmError> = {};
      for (const e of res.errors || []) {
        errMap[e.row] = e;
      }
      setRowErrors(errMap);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorBanner(friendlyError(err.error_code) || err.message);
      } else {
        setErrorBanner('Failed to confirm register rows.');
      }
    } finally {
      setConfirming(false);
    }
  };

  const allConfirmedCleanly =
    confirmSummary !== null && Object.keys(rowErrors).length === 0;

  return (
    <div className="desk-container" id="intake-page">
      <StatusStrip />

      <div className="desk-header">
        <div className="desk-title-group">
          <h1>Register Photo Intake</h1>
          <p className="page-subtitle">
            Photograph the booking register, review every drafted row, and confirm
          </p>
        </div>
        <div className="desk-header-actions">
          <Link to="/desk" className="btn btn-secondary" id="btn-back-desk">
            ← Back to Desk
          </Link>
        </div>
      </div>

      {/* 1. Always-visible banner: which reader, and where photos go */}
      <ReaderBanner health={health} draftReader={draft?.reader ?? null} />

      {/* 2. File / Camera Upload Input */}
      <div className="card new-request-card" id="intake-upload-box">
        <div className="card-header">
          <div>
            <h2>Upload Register Page Photo</h2>
            <span className="card-subtitle">
              Select a photo or capture from camera. A draft is never a request until confirmed.
            </span>
          </div>
        </div>
        <div className="mt-2">
          <label className="attr-label" htmlFor="intake-rotate">
            Turn the photo before reading{' '}
            <select
              id="intake-rotate"
              value={rotate}
              onChange={e => setRotate(Number(e.target.value) as 0 | 90 | 180 | 270)}
              disabled={uploading}
            >
              <option value={0}>No turn (upright)</option>
              <option value={90}>Turn right (90°)</option>
              <option value={180}>Upside down (180°)</option>
              <option value={270}>Turn left (90°)</option>
            </select>
          </label>
        </div>
        <div className="mt-2">
          <input
            id="intake-file-input"
            type="file"
            accept="image/*"
            capture="environment"
            onChange={handleFileChange}
            disabled={uploading}
          />
          {uploading && <span className="ml-2 text-muted">Reading register page…</span>}
        </div>
      </div>

      {/* Error or Fallback Notice */}
      {errorBanner && (
        <div
          className={`outcome-banner ${readerFailed ? 'outcome-warning' : 'outcome-error'}`}
          id="intake-error-banner"
        >
          {errorBanner}
        </div>
      )}

      {/* Confirmation Summary Banner */}
      {confirmSummary && (
        <div
          className={`outcome-banner ${
            allConfirmedCleanly ? 'outcome-success' : 'outcome-warning'
          }`}
          id="intake-confirm-banner"
          style={{ justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}
        >
          <span>
            Created {confirmSummary.createdCount} requests, skipped {confirmSummary.skippedCount}
            {Object.keys(rowErrors).length > 0 &&
              ` (${Object.keys(rowErrors).length} row needs correction below)`}
          </span>
          <button
            id="btn-return-desk-after-confirm"
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => navigate('/desk')}
          >
            Open Desk ➔
          </button>
        </div>
      )}

      {/* 5. Fallback Mode: 503 READER_UNAVAILABLE -> Stored photo on left + Desk NewRequestForm on right */}
      {readerFailed && (
        <div className="officer-middle-grid" id="intake-fallback-layout">
          <div className="card">
            <h3>Register Page Photo</h3>
            <p className="card-subtitle mb-2">
              Reader unavailable: type the rows using the form beside this photo.
            </p>
            {photoUrl && (
              <img
                id="intake-fallback-photo"
                src={photoUrl}
                alt="Uploaded register page"
                style={{ width: '100%', borderRadius: '8px', border: '1px solid #cbd5e1' }}
              />
            )}
          </div>
          <div>
            <NewRequestForm
              villages={villages}
              onSuccess={() => {
                // Operator can enter multiple rows from the photo
              }}
            />
          </div>
        </div>
      )}

      {/* 3 & 4. Draft Review & Human Confirmation Layout: Photo Large on Left, Editable Table on Right */}
      {draft && !readerFailed && (
        <div
          className="officer-middle-grid"
          id="intake-review-layout"
          style={{ gridTemplateColumns: '1fr 2fr', alignItems: 'start' }}
        >
          {/* Left: Large Register Photo */}
          <div className="card" id="intake-photo-panel">
            <div className="card-header mb-2">
              <h3>Register Page #{draft.intake_id}</h3>
              <span className="card-subtitle">
                Reader: {draft.reader} • {draft.latency_ms ?? 0} ms
              </span>
            </div>
            {photoUrl ? (
              <img
                id="intake-register-photo"
                src={photoUrl}
                alt="Register page"
                style={{ width: '100%', borderRadius: '8px', border: '1px solid #cbd5e1' }}
              />
            ) : (
              <img
                id="intake-register-photo"
                src={`/api/intake/${draft.intake_id}/image`}
                alt="Register page"
                style={{ width: '100%', borderRadius: '8px', border: '1px solid #cbd5e1' }}
              />
            )}
          </div>

          {/* Right: Editable Draft Table */}
          <div className="card" id="intake-table-panel">
            <div className="card-header mb-2">
              <div>
                <h3>Drafted Rows ({rows.length})</h3>
                <p className="card-subtitle">
                  Amber cells have confidence below 80%. Red cells have validation issues. Edit any cell before confirming.
                </p>
              </div>
            </div>

            <div className="table-responsive">
              <table className="data-table" id="intake-draft-table">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Phone *</th>
                    <th>Name</th>
                    <th>Village *</th>
                    <th>Acres *</th>
                    <th>Service Type *</th>
                    <th>Harvest Date</th>
                    <th>Consent</th>
                    <th>Skip</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, idx) => {
                    const rowErr = rowErrors[r.row];
                    return (
                      <tr
                        key={r.row}
                        id={`intake-row-${r.row}`}
                        style={{ opacity: r.skip ? 0.55 : 1 }}
                      >
                        <td>
                          <strong>#{r.row}</strong>
                        </td>

                        {/* Phone */}
                        <td>
                          <input
                            id={`intake-phone-${r.row}`}
                            type="text"
                            value={r.phone}
                            disabled={r.skip || allConfirmedCleanly}
                            onChange={(e) => updateCell(idx, 'phone', e.target.value)}
                            className={getCellClass(r, 'phone')}
                            style={{ width: '120px', ...getCellStyle(r, 'phone') }}
                          />
                          {r.editedFields.phone && (
                            <div className="text-xs text-muted">Edited</div>
                          )}
                          {getFieldIssues(r, 'phone').map((iss) => (
                            <div key={iss} className="field-error-msg">
                              {iss}
                            </div>
                          ))}
                        </td>

                        {/* Name */}
                        <td>
                          <input
                            id={`intake-name-${r.row}`}
                            type="text"
                            value={r.name}
                            disabled={r.skip || allConfirmedCleanly}
                            onChange={(e) => updateCell(idx, 'name', e.target.value)}
                            className={getCellClass(r, 'name')}
                            style={{ width: '125px', ...getCellStyle(r, 'name') }}
                          />
                          {r.editedFields.name && (
                            <div className="text-xs text-muted">Edited</div>
                          )}
                        </td>

                        {/* Village */}
                        <td>
                          <input
                            id={`intake-village-${r.row}`}
                            type="text"
                            list="intake-villages-datalist"
                            value={r.village}
                            disabled={r.skip || allConfirmedCleanly}
                            onChange={(e) => updateCell(idx, 'village', e.target.value)}
                            className={getCellClass(r, 'village')}
                            style={{ width: '125px', ...getCellStyle(r, 'village') }}
                          />
                          {r.editedFields.village && (
                            <div className="text-xs text-muted">Edited</div>
                          )}
                          {getFieldIssues(r, 'village').map((iss) => (
                            <div key={iss} className="field-error-msg">
                              {iss}
                            </div>
                          ))}
                        </td>

                        {/* Acres */}
                        <td>
                          <input
                            id={`intake-acres-${r.row}`}
                            type="number"
                            step="0.1"
                            min="0.25"
                            max="200"
                            value={r.acres}
                            disabled={r.skip || allConfirmedCleanly}
                            onChange={(e) => updateCell(idx, 'acres', e.target.value)}
                            className={getCellClass(r, 'acres')}
                            style={{ width: '80px', ...getCellStyle(r, 'acres') }}
                          />
                          {r.editedFields.acres && (
                            <div className="text-xs text-muted">Edited</div>
                          )}
                          {getFieldIssues(r, 'acres').map((iss) => (
                            <div key={iss} className="field-error-msg">
                              {iss}
                            </div>
                          ))}
                        </td>

                        {/* Service Type */}
                        <td>
                          <select
                            id={`intake-service-${r.row}`}
                            value={r.service_type}
                            disabled={r.skip || allConfirmedCleanly}
                            onChange={(e) =>
                              updateCell(idx, 'service_type', e.target.value)
                            }
                            className={getCellClass(r, 'service_type')}
                            style={getCellStyle(r, 'service_type')}
                          >
                            <option value="super_seeder">Super Seeder</option>
                            <option value="happy_seeder">Happy Seeder</option>
                            <option value="baler">Baler</option>
                            <option value="mulcher">Mulcher</option>
                          </select>
                          {r.editedFields.service_type && (
                            <div className="text-xs text-muted">Edited</div>
                          )}
                          {getFieldIssues(r, 'service_type').map((iss) => (
                            <div key={iss} className="field-error-msg">
                              {iss}
                            </div>
                          ))}
                        </td>

                        {/* Harvest Date */}
                        <td>
                          <input
                            id={`intake-harvest-${r.row}`}
                            type="date"
                            value={r.harvest_date}
                            disabled={r.skip || allConfirmedCleanly}
                            onChange={(e) =>
                              updateCell(idx, 'harvest_date', e.target.value)
                            }
                            className={getCellClass(r, 'harvest_date')}
                            style={getCellStyle(r, 'harvest_date')}
                          />
                          {r.editedFields.harvest_date && (
                            <div className="text-xs text-muted">Edited</div>
                          )}
                          {getFieldIssues(r, 'harvest_date').map((iss) => (
                            <div key={iss} className="field-error-msg">
                              {iss}
                            </div>
                          ))}
                        </td>

                        {/* Per-row Consent Checkbox + Simulated Badge */}
                        <td>
                          <label className="checkbox-label">
                            <input
                              id={`intake-consent-${r.row}`}
                              type="checkbox"
                              checked={r.consentAgreed}
                              disabled={r.skip || allConfirmedCleanly}
                              onChange={() => toggleConsent(idx)}
                            />
                            <span>Farmer agreed by phone</span>
                          </label>
                          <div className="mt-1">
                            <Badge name="consent simulated" />
                          </div>
                        </td>

                        {/* Skip Checkbox */}
                        <td>
                          <label className="checkbox-label">
                            <input
                              id={`intake-skip-${r.row}`}
                              type="checkbox"
                              checked={r.skip}
                              disabled={allConfirmedCleanly}
                              onChange={() => toggleSkip(idx)}
                            />
                            <span>Skip</span>
                          </label>
                          {rowErr && (
                            <div className="field-error-msg mt-1" id={`intake-row-error-${r.row}`}>
                              {rowErr.message}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <datalist id="intake-villages-datalist">
                {villages.map((v) => (
                  <option key={v} value={v} />
                ))}
              </datalist>
            </div>

            {!allConfirmedCleanly && (
              <div className="form-actions mt-3">
                <button
                  id="btn-confirm-rows"
                  type="button"
                  className="btn btn-primary btn-large"
                  onClick={handleConfirm}
                  disabled={confirming}
                >
                  {confirming ? 'Confirming…' : 'Confirm rows'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
