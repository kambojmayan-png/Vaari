import { useState, useEffect } from 'react';
import { getSlotMessage, markMessageOpened, patchRequest, deleteRequest, revokeRecordLink, reissueRecordLink, ApiError } from '../api';
import { friendlyError } from '../errors';
import Badge from './Badge';
import type { RequestOut, SlotMessage } from '../types';

interface Props {
  request: RequestOut | null;
  onClose: () => void;
  onUpdate: () => void;
}

export default function RequestDetailPanel({ request, onClose, onUpdate }: Props) {
  // Message state
  const [showMessage, setShowMessage] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState(false);
  const [messageData, setMessageData] = useState<SlotMessage | null>(null);
  const [messageError, setMessageError] = useState<string | null>(null);
  const [isCopied, setIsCopied] = useState(false);

  // Edit state
  const [isEditing, setIsEditing] = useState(false);
  const [editHarvestDate, setEditHarvestDate] = useState('');
  const [editAcres, setEditAcres] = useState('');
  const [editServiceType, setEditServiceType] = useState('');
  const [editError, setEditError] = useState<string | null>(null);
  const [editSuccess, setEditSuccess] = useState<string | null>(null);
  const [submittingEdit, setSubmittingEdit] = useState(false);

  // Cancel state
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  // Record link (pilot v0.2): turn off or reissue the farmer's record link
  const [recordLinkNote, setRecordLinkNote] = useState<string | null>(null);
  const handleRecordLink = async (action: 'revoke' | 'reissue') => {
    const slotId = request?.slot?.id;
    if (!slotId) return;
    setRecordLinkNote(null);
    try {
      const res = action === 'revoke' ? await revokeRecordLink(slotId) : await reissueRecordLink(slotId);
      setRecordLinkNote(
        action === 'revoke'
          ? 'Record link turned off. The record and its hash are unchanged.'
          : `New record link: ${res.record_url}`,
      );
    } catch (err) {
      setRecordLinkNote(err instanceof ApiError ? friendlyError(err.error_code) || err.message : 'Failed to change the record link.');
    }
  };

  useEffect(() => {
    if (request) {
      setEditHarvestDate(request.harvest_date || '');
      setEditAcres(String(request.acres));
      setEditServiceType(request.service_type);
      setShowMessage(false);
      setMessageData(null);
      setMessageError(null);
      setIsEditing(false);
      setConfirmCancel(false);
      setEditError(null);
      setEditSuccess(null);
    }
  }, [request]);

  if (!request) return null;

  // Load slot message
  const handleLoadMessage = async () => {
    if (!request.slot) return;
    setShowMessage(true);
    setLoadingMessage(true);
    setMessageError(null);
    try {
      const data = await getSlotMessage(request.slot.id);
      setMessageData(data);
    } catch (err) {
      if (err instanceof ApiError && err.error_code === 'NETWORK_DOWN') {
        setMessageError('Not sent: copy or call');
        // Render from last response if present, else fallback Punjabi template
        setMessageData(prev => prev ?? {
          slot_id: request.slot!.id,
          language: 'pa',
          body: `ਸਤ ਸ੍ਰੀ ਅਕਾਲ ਜੀ। ਤੁਹਾਡੇ ${request.village} ਵਾਲੇ ${request.acres} ਏਕੜ ਖੇਤ ਲਈ ${request.slot!.machine_name} ${request.slot!.service_date} ਨੂੰ ਆਵੇਗੀ। ਕੋਈ ਗੱਲ ਹੋਵੇ ਤਾਂ ਫ਼ੋਨ ਕਰੋ।`,
          body_en: `Sat Sri Akal ji. ${request.slot!.machine_name} will come on ${request.slot!.service_date} for your ${request.acres}-acre field in ${request.village}.`,
          wa_link: `https://wa.me/91${request.farmer.phone}`,
          tel_link: `tel:+91${request.farmer.phone}`,
          service_code: '----',
        });
      } else {
        setMessageError('Failed to load message.');
      }
    } finally {
      setLoadingMessage(false);
    }
  };

  const handleCopyMessage = async () => {
    if (!messageData) return;
    try {
      await navigator.clipboard.writeText(messageData.body);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const handleOpenWhatsApp = async () => {
    if (!messageData || !request.slot) return;
    try {
      await markMessageOpened(request.slot.id, 'wa_link');
    } catch {
      // If network fails, still proceed to open link
    }
    window.open(messageData.wa_link, '_blank');
  };

  const handleSaveEdit = async () => {
    setSubmittingEdit(true);
    setEditError(null);
    setEditSuccess(null);
    try {
      const updated = await patchRequest(request.id, {
        harvest_date: editHarvestDate || undefined,
        acres: parseFloat(editAcres),
        service_type: editServiceType,
      });

      let outcome = `Updated! Status: ${updated.status}`;
      if (updated.status === 'scheduled' && updated.slot) {
        outcome = `Scheduled on ${updated.slot.service_date} (${updated.slot.machine_name})`;
      } else if (updated.status === 'will_miss') {
        outcome = `Will miss: ${updated.explanation?.reason || 'Capacity limit'}`;
      } else if (updated.status === 'needs_info') {
        outcome = 'Need info: no harvest date yet';
      }
      setEditSuccess(outcome);
      setIsEditing(false);
      onUpdate();
    } catch (err) {
      if (err instanceof ApiError) {
        setEditError(friendlyError(err.error_code) || err.message);
      } else {
        setEditError('Failed to update request.');
      }
    } finally {
      setSubmittingEdit(false);
    }
  };

  const handleCancelRequest = async () => {
    setCancelling(true);
    setCancelError(null);
    try {
      await deleteRequest(request.id);
      onUpdate();
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        setCancelError(friendlyError(err.error_code) || err.message);
      } else {
        setCancelError('Failed to cancel request.');
      }
      setCancelling(false);
    }
  };

  return (
    <div className="side-panel-overlay" onClick={onClose} id="request-detail-panel">
      <div className="side-panel" onClick={e => e.stopPropagation()}>
        <div className="side-panel-header">
          <div>
            <div className="id-badge-row">
              <span className="request-id-large">VR-{request.id}</span>
              <span className={`status-pill pill-${request.status}`}>{request.status}</span>
            </div>
            <p className="side-panel-farmer">
              {request.farmer.name ? `${request.farmer.name} • ` : ''}
              <strong>{request.farmer.phone}</strong>
            </p>
          </div>
          <button className="panel-close-btn" onClick={onClose} aria-label="Close panel">
            ✕
          </button>
        </div>

        <div className="side-panel-body">
          {/* Badges */}
          {request.badges && request.badges.length > 0 && (
            <div className="panel-badges">
              {request.badges.map(b => (
                <Badge key={b} name={b} />
              ))}
            </div>
          )}

          {/* Outcome Alert if recently edited */}
          {editSuccess && (
            <div className="outcome-banner outcome-success">
              {editSuccess}
            </div>
          )}

          {/* Key Attributes */}
          <div className="panel-attributes">
            <div className="attribute-item">
              <span className="attr-label">Village</span>
              <span className="attr-val">{request.village}</span>
            </div>
            <div className="attribute-item">
              <span className="attr-label">Acreage</span>
              <span className="attr-val">{request.acres} acres</span>
            </div>
            <div className="attribute-item">
              <span className="attr-label">Service Type</span>
              <span className="attr-val text-capitalize">{request.service_type.replace('_', ' ')}</span>
            </div>
            <div className="attribute-item">
              <span className="attr-label">Harvest Date</span>
              <span className="attr-val">{request.harvest_date || 'Not cut yet'}</span>
            </div>
            <div className="attribute-item">
              <span className="attr-label">Sow By</span>
              <span className="attr-val">{request.sow_by || '—'}</span>
            </div>
            <div className="attribute-item">
              <span className="attr-label">Deadline</span>
              <span className="attr-val">{request.deadline_date || '—'}</span>
            </div>
          </div>

          {/* Slot Info (if scheduled) */}
          {request.slot && (
            <div className="panel-card slot-card">
              <h3>Assigned Slot</h3>
              <div className="slot-details-grid">
                <div>
                  <span className="attr-label">Machine</span>
                  <p><strong>{request.slot.machine_name}</strong></p>
                </div>
                <div>
                  <span className="attr-label">Service Date</span>
                  <p><strong>{request.slot.service_date}</strong></p>
                </div>
                <div>
                  <span className="attr-label">Sequence</span>
                  <p>Job #{request.slot.seq}</p>
                </div>
                <div>
                  <span className="attr-label">Slot Status</span>
                  <span className={`status-pill pill-${request.slot.status}`}>{request.slot.status}</span>
                </div>
              </div>
              {request.slot.status === 'done' && (
                <div className="driver-link-row" id="record-link-actions">
                  <button id="btn-record-link-reissue" type="button" className="btn btn-secondary btn-sm" onClick={() => handleRecordLink('reissue')}>
                    New record link
                  </button>
                  <button id="btn-record-link-revoke" type="button" className="btn btn-secondary btn-sm" onClick={() => handleRecordLink('revoke')}>
                    Turn off record link
                  </button>
                </div>
              )}
              {recordLinkNote && <p className="attr-label" id="record-link-note">{recordLinkNote}</p>}
            </div>
          )}

          {/* Explanation Section */}
          <div className="panel-card explanation-card">
            <h3>Scheduling Explanation</h3>
            {request.explanation ? (
              <>
                <p className="explanation-sentence">{request.explanation.reason}</p>
                {request.explanation.next_action && (
                  <p className="next-action-row">
                    <strong>Next Action: </strong>
                    <span>{request.explanation.next_action}</span>
                  </p>
                )}
                {request.explanation.nearest_alternative && (
                  <p className="nearest-alt-row">
                    <span>Nearest Alternative: </span>
                    <strong>{request.explanation.nearest_alternative}</strong>
                    {request.explanation.alternative_distance_km && (
                      <span> ({request.explanation.alternative_distance_km} km)</span>
                    )}
                  </p>
                )}
              </>
            ) : (
              <p className="placeholder-text">No explanation recorded.</p>
            )}
          </div>

          {/* Message Modal / Expander */}
          {showMessage && (
            <div className="panel-card message-card" id="slot-message-container">
              <h3>Farmer Notification Message</h3>
              {loadingMessage ? (
                <p>Generating slot message…</p>
              ) : messageData ? (
                <>
                  {messageError && (
                    <div className="outcome-banner outcome-warning mb-2">
                      {messageError}
                    </div>
                  )}
                  <div className="punjabi-message-box">
                    <p className="message-punjabi">{messageData.body}</p>
                  </div>
                  <div className="english-message-box">
                    <span className="attr-label">English Translation:</span>
                    <p className="message-english">{messageData.body_en}</p>
                  </div>
                  <div className="message-actions">
                    <button
                      id="btn-copy-msg"
                      type="button"
                      className="btn btn-secondary"
                      onClick={handleCopyMessage}
                    >
                      {isCopied ? '✓ Copied' : 'Copy Text'}
                    </button>
                    <a
                      id="btn-whatsapp-msg"
                      href={messageData.wa_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-primary"
                      onClick={handleOpenWhatsApp}
                    >
                      Open WhatsApp
                    </a>
                    <a
                      id="btn-call-farmer"
                      href={messageData.tel_link}
                      className="btn btn-secondary"
                    >
                      Call
                    </a>
                  </div>
                </>
              ) : null}
            </div>
          )}

          {/* Edit Form Drawer */}
          {isEditing && (
            <div className="panel-card edit-card" id="edit-request-section">
              <h3>Edit Request</h3>
              {editError && <div className="outcome-banner outcome-error">{editError}</div>}
              <div className="form-group mb-2">
                <label>Harvest Date</label>
                <input
                  type="date"
                  value={editHarvestDate}
                  onChange={e => setEditHarvestDate(e.target.value)}
                />
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => setEditHarvestDate('')}
                >
                  Clear (Mark not cut yet)
                </button>
              </div>
              <div className="form-group mb-2">
                <label>Acres</label>
                <input
                  type="number"
                  step="0.1"
                  min="0.25"
                  value={editAcres}
                  onChange={e => setEditAcres(e.target.value)}
                />
              </div>
              <div className="form-group mb-2">
                <label>Service Type</label>
                <select
                  value={editServiceType}
                  onChange={e => setEditServiceType(e.target.value)}
                >
                  <option value="super_seeder">Super Seeder</option>
                  <option value="happy_seeder">Happy Seeder</option>
                  <option value="baler">Baler</option>
                  <option value="mulcher">Mulcher</option>
                </select>
              </div>
              <div className="action-row">
                <button
                  id="btn-save-edit"
                  type="button"
                  className="btn btn-primary"
                  onClick={handleSaveEdit}
                  disabled={submittingEdit}
                >
                  {submittingEdit ? 'Saving…' : 'Save & Reflow'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setIsEditing(false)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Cancellation Confirmation */}
          {confirmCancel && (
            <div className="panel-card cancel-card" id="cancel-confirm-box">
              <h3>Confirm Cancellation</h3>
              <p>Are you sure you want to cancel request VR-{request.id}? Any unstarted slot will be cancelled.</p>
              {cancelError && <div className="outcome-banner outcome-error">{cancelError}</div>}
              <div className="action-row mt-2">
                <button
                  id="btn-confirm-cancel"
                  type="button"
                  className="btn btn-danger"
                  onClick={handleCancelRequest}
                  disabled={cancelling}
                >
                  {cancelling ? 'Cancelling…' : 'Yes, Cancel Request'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setConfirmCancel(false)}
                >
                  Keep Request
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Action Toolbar */}
        <div className="side-panel-footer">
          {request.slot && (
            <button
              id="btn-panel-message"
              type="button"
              className="btn btn-secondary"
              onClick={handleLoadMessage}
            >
              💬 Message
            </button>
          )}

          {!isEditing && (
            <button
              id="btn-panel-edit"
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsEditing(true)}
            >
              ✏️ Edit
            </button>
          )}

          {!confirmCancel && request.status !== 'cancelled' && (
            <button
              id="btn-panel-cancel"
              type="button"
              className="btn btn-danger-outline"
              onClick={() => setConfirmCancel(true)}
            >
              Cancel Request
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
