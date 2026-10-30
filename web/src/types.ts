// Types matching CONTRACT.md section 11 output shapes exactly.

// ── Error shape ──────────────────────────────────────────────
export interface ApiErrorShape {
  error_code: string;
  message: string;
  details: Record<string, unknown>;
}

// ── Health ───────────────────────────────────────────────────
export interface Health {
  status: string;
  database: string;
  reader: string;
  messaging: string;
  satellite: string;
  today: string;
  demo_clock: boolean;
  version: string;
  env?: 'development' | 'production';
  auth?: 'passcode' | 'accounts';
  reader_detail?: ReaderDetail;
}

export interface ReaderDetail {
  name: 'mock' | 'gemini_demo' | 'custom' | string;
  kind: string;
  provider: string | null;
  model: string | null;
  third_party: boolean;
  demo_only: boolean;
  probe: {
    status: 'not_run' | 'pending' | 'ok' | 'failed';
    latency_ms?: number;
    checked_at?: string;
    error?: string;
  };
}

// ── Auth (pilot v0.2) ────────────────────────────────────────
export interface LoginResult {
  token: string;
  token_type: 'bearer';
  expires_at: string;
  user: { username: string; role: 'operator' | 'officer' };
}

export interface MeResult {
  username: string | null;
  roles: string[];
  via: 'passcode' | 'session';
}

// ── RequestOut ───────────────────────────────────────────────
export interface RequestFarmer {
  name: string | null;
  phone: string;
}

export interface RequestExplanation {
  reason_code: string | null;
  reason: string | null;
  data_used: Record<string, unknown>;
  next_action: string | null;
  nearest_alternative: string | null;
  alternative_distance_km: number | null;
}

export interface RequestSlot {
  id: number;
  machine_id: number;
  machine_name: string;
  service_date: string;
  seq: number;
  status: string;
}

export interface RequestOut {
  id: number;
  status: string;
  source: string;
  farmer: RequestFarmer;
  village: string;
  acres: number;
  service_type: string;
  harvest_date: string | null;
  sow_by: string | null;
  deadline_date: string | null;
  explanation: RequestExplanation;
  slot: RequestSlot | null;
  badges: string[];
  created_at: string;
}

// ── MachineOut ───────────────────────────────────────────────
export interface MachineOut {
  id: number;
  name: string;
  type: string;
  service_types: string[];
  capacity_acres_per_day: number;
  status: string;
  active_from: string | null;
  active_to: string | null;
  driver_path: string;
  driver_link_status?: 'active' | 'expired' | 'revoked';
  driver_link_expires_at?: string | null;
}

export interface RecordLinkOut {
  slot_id: number;
  record_token: string;
  record_url: string;
  status: 'active' | 'expired' | 'revoked';
  expires_at: string | null;
}

// ── SlotOut ──────────────────────────────────────────────────
export interface SlotLocation {
  lat: number | null;
  lon: number | null;
  source: string;
}

export interface SlotMachine {
  id: number;
  name: string;
}

export interface SlotOut {
  id: number;
  seq: number;
  status: string;
  service_date: string;
  machine: SlotMachine;
  request_id: number;
  farmer_name: string | null;
  village: string;
  acres: number;
  deadline_date: string;
  location: SlotLocation;
  est_distance_km: number;
  link_token: string | null;
  needs_review: boolean;
  flags: string[];
  started_at: string | null;
  done_at: string | null;
  record_token: string | null;
}

// ── SlotEvidenceOut ──────────────────────────────────────────
export interface EvidenceDetail {
  kind: string;
  lat: number | null;
  lon: number | null;
  accuracy_m: number | null;
  distance_to_plot_m: number | null;
  plausible: boolean | null;
  position_state: string;
  photo: string;
  timestamp: string;
}

export interface SlotEvidenceOut {
  slot_id: number;
  status: string;
  evidence: EvidenceDetail;
  flags: string[];
  needs_review: boolean;
  record_url: string | null;
}

// ── RecordOut ────────────────────────────────────────────────
export interface RecordOut {
  request_id: string;
  village: string;
  machine: string;
  acres: number;
  service_type: string;
  scheduled: string;
  deadline_date: string;
  started_at: string | null;
  done_at: string | null;
  start_position: string;
  done_position: string;
  start_photo: string;
  done_photo: string;
  evidence_note: string | null;
  farmer_confirmed: boolean | null;
  outcome: string;
  on_time: boolean;
  flags: string[];
  needs_review: boolean;
  badges: string[];
  record_hash: string;
  hash_version: string;
}

export interface RecordVerify {
  stored: string;
  recomputed: string;
  match: boolean;
}

// ── Will-miss item ───────────────────────────────────────────
export interface AlternativeCentreItem {
  name: string;
  distance_km: number;
}

export interface WillMissItem {
  request_id: number;
  village: string;
  acres: number;
  service_type: string;
  deadline_date: string;
  status: string;
  reason_code: string;
  reason: string;
  data_used: Record<string, unknown>;
  next_action: string;
  nearest_alternative: string | null;
  alternative_distance_km: number | null;
  rescue_options?: AlternativeCentreItem[];
}

// ── Schedule day ─────────────────────────────────────────────
export interface ScheduleDay {
  machine_id: number;
  machine_name: string;
  date: string;
  capacity_acres: number;
  used_acres: number;
  slots: SlotOut[];
}

// ── Dashboard summary ────────────────────────────────────────
export interface FlaggedJobSummary {
  slot_id: number;
  request_id: string;
  village: string;
  machine: string;
  acres: number;
  service_date: string;
  flags: string[];
  record_token: string | null;
}

export interface DashboardSummary {
  total: number;
  needs_info: number;
  scheduled: number;
  in_progress: number;
  completed: number;
  will_miss: number;
  needs_review: number;
  capacity_used_pct: number;
  by_reason: Record<string, number>;
  by_village: Record<string, number>;
  today: string;
  flagged_jobs?: FlaggedJobSummary[];
}

// ── Slot message ─────────────────────────────────────────────
export interface SlotMessage {
  slot_id: number;
  language: string;
  body: string;
  body_en: string;
  wa_link: string;
  tel_link: string;
  service_code: string;
}

// ── Schedule run result ──────────────────────────────────────
export interface ScheduleRunResult {
  total: number;
  needs_info: number;
  open: number;
  scheduled: number;
  done: number;
  will_miss: number;
  cancelled: number;
  ran_in_ms: number;
  today: string;
}

// ── Driver page response ─────────────────────────────────────
export interface DriverResponse {
  machine: SlotMachine;
  date: string;
  slots: SlotOut[];
}

// ── Intake (Phase 3) ─────────────────────────────────────────
export interface IntakeRowFields {
  phone: string | null;
  name: string | null;
  village: string | null;
  acres: number | string | null;
  service_type: string | null;
  harvest_date: string | null;
  note?: string | null;
}

export interface IntakeRow {
  row: number;
  fields: IntakeRowFields;
  confidence: Record<string, number>;
  issues: string[];
}

export interface IntakeOut {
  intake_id: number;
  reader: string;
  reader_name?: string;
  third_party?: boolean;
  latency_ms: number | null;
  status: string;
  rows: IntakeRow[];
}

export interface IntakeConfirmRowIn {
  row: number;
  fields: Record<string, unknown>;
  skip?: boolean;
  consent_service?: boolean;
  consent_evidence?: boolean;
  consent_share?: boolean;
}

export interface IntakeConfirmError {
  row: number;
  field: string;
  issues?: string[];
  message: string;
}

export interface IntakeConfirmResult {
  created_request_ids: number[];
  skipped_rows: number[];
  errors: IntakeConfirmError[];
}

// ── Request body types ───────────────────────────────────────
export interface CreateRequestBody {
  phone: string;
  name?: string;
  village: string;
  lat?: number;
  lon?: number;
  acres: number;
  service_type: string;
  harvest_date?: string;
  deadline_date?: string;
  consent_service: boolean;
  consent_evidence: boolean;
  consent_share: boolean;
}

export interface PatchRequestBody {
  name?: string;
  village?: string;
  lat?: number;
  lon?: number;
  acres?: number;
  service_type?: string;
  harvest_date?: string;
  deadline_date?: string;
}
