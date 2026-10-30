# Changelog

All notable changes are recorded here. The format follows Keep a Changelog, and versions follow semantic versioning.

## [Unreleased]

### Pilot build v0.2 (30 Oct 2026)
- **A1 Production mode**: `VAARI_ENV=production` refuses to start with unsafe settings; new `python tasks.py check-config`.
- **A2 Accounts and roles**: operator and officer accounts (argon2id), signed expiring sessions, role checks on every protected route, `create-user` / `disable-user` / `list-users`, sign-in screen in production, production-mode Playwright pass.
- **A3 Rate limits and lockout**: per-address limits on sign-in and photo uploads (checked before the body is read), per-username lockout after repeated wrong passwords, 429 `RATE_LIMITED`.
- **A4 Link expiry and revocation**: driver and record links expire; operators rotate or turn off driver links and turn off or reissue record links; 410 `LINK_EXPIRED`.
- **A5 CORS and security headers**: CORS only for configured origins; CSP, no-referrer, nosniff, frame DENY, Permissions-Policy, COOP/CORP, HSTS in production, `no-store` on the API.
- **B6 Alembic migrations**: v0.1.0 baseline plus pilot revision; start-up upgrades instead of `create_all`; legacy databases are stamped and upgraded; model-vs-migration test.
- **B7 Photo storage**: storage interface (local disk; S3 placeholder refused); every image re-encoded with EXIF/GPS stripped; hashes are of the stored file.
- **B8 Backup and restore**: online SQLite backup plus photos with a SHA-256 manifest; verified restore that keeps the previous data.
- **C9 Logs and readiness**: JSON logs with request IDs and route templates, PII redaction, safe 500s, `/api/ready`.
- **C10 Docker**: non-root image, compose with a data volume, production `.env` example, `docs/DEPLOY.md`; mock reader refuses in production.
- **C11 CI**: ruff, pip-audit, npm audit, Playwright e2e and a Docker build-and-smoke job; fixed a scheduler NameError ruff found.
- **R1 Reader interface**: `mock`, `gemini_demo` and a `custom` stub behind `RegisterReader`; no hard-coded model names; key in a header; Anthropic path removed.
- **R2 Reader probe**: synthetic start-up probe of a remote reader; provider, model and latency in `/api/health`.
- **R3 Intake banner**: always names the reader in use and says when photos go to a third party.
- **R4 Preprocessing**: rotation (EXIF and an operator turn), resize to 1000-2000 px, greyscale contrast stretch before any reader.
- **R5 Gurmukhi and mixed entries**: Gurmukhi digits, phone labels and prefixes, acre/killa/kanal units and fractions, mixed-script service names, Punjabi and English month names.

### Polish & Hardening Pass (29 Oct 2026)
- **OpenAPI & Freshness Enforcement**: Regenerated `docs/openapi.json` from live application (`app.openapi()`) with LF line endings containing all 25 API paths (including `/api/intake/*` and `/api/dashboard/usage.csv`), and added an automated drift test `tests/api/test_openapi_freshness.py` that fails if committed schema is out of date.
- **Handoff Links & Dependencies**: Updated `HANDOFF.md` to replace absolute `file:///` URLs with repo-relative paths, and documented `shapely` and `pyproj` additions for geodesic polygon and coordinate transformations.
- **Continuous Integration**: Added `.github/workflows/ci.yml` running pytest across Python 3.12 and web build on Node 22 for all pushes and PRs; added CI status badge to `README.md`.
- **Git Hygiene**: Narrowed blanket `*.txt` rule in `.gitignore` to specific dump/scratch files (`pipreqs*.txt`, `dump*.txt`, etc.) ensuring requirement files remain tracked.
- **Dependency Split**: Separated test dependencies (`pytest`, `httpx`) into `requirements-dev.txt`, updating `tasks.py setup`, `CONTRIBUTING.md`, and CI workflow.
- **Coordinate Transformation Modernization**: Replaced deprecated `shapely.ops.transform` in `app/evidence/position.py` and test suites with modern `pyproj.Transformer` and `shapely.transform`, eliminating deprecation warnings while preserving exact geodesic checks.
- **Web Dependency Audit**: Audited `web/` dependencies (`npm audit`) for `react-router` vulnerabilities, documented that SSR-hydration and open-redirect paths are unreachable in static SPA, and noted non-breaking deferral of React Router v7 breaking upgrade in `notes/npm-audit.md`.
- **Clean Documentation**: Removed obsolete `docs/PHASE1_MASTER_PROMPT.md` and verified zero broken links.
- **Passcode Safety**: Enforced passcode validation in `python tasks.py tunnel` to refuse execution if `VAARI_DEMO_PASSCODE` is empty, `change-me`, or shorter than 12 characters; added unit tests (`tests/unit/test_tunnel_passcode.py`) and setup notes in `docs/DEMO_SETUP.md`.
- **Reader Evaluation Guide**: Added `examples/register_pages/README.md` documenting synthetic register page creation, evaluation execution with mock and hosted models, and PII prevention; verified `.gitignore` blocks all register image files.
- **Playwright Demo Screenshots**: Implemented automated screenshot capture (`web/e2e/screenshots.spec.ts` and `python tasks.py screenshots`) capturing Desk, Driver, Record, Officer, and Intake screens into `docs/screenshots/` and embedded visual walkthrough in `README.md`.

## [0.1.0] - 2026-10-26

### Added (Phase 3 Intelligence, Evidence & Hardening)
- Register extraction pipeline (`app/intake/`): `RegisterReader` protocol, deterministic 6-row `MockRegisterReader`, `HostedVisionReader` behind `VAARI_ALLOW_HOSTED_READER=true` privacy gate with 20s timeout and 1-retry JSON self-correction, and `validate_row` supporting Gurmukhi service names and flexible dates.
- Reader evaluation harness (`python tasks.py reader-eval`) writing count-based evaluation metrics to `examples/register_pages/EVAL.md`.
- Register intake API (`app/routes/intake.py`): `POST /api/intake/register-photo`, `GET /api/intake/{id}`, `GET /api/intake/{id}/image`, `POST /api/intake/{id}/confirm`, and retention cleanup task (`python tasks.py purge-images [--dry-run]`).
- Register Confirmation Screen (`/intake`, `web/src/pages/IntakePage.tsx`) with persistent privacy warning banner, side-by-side page preview and editable table, <0.8 amber confidence cells, red issue cells, URL `?id=` reload survival, and 503 fallback reusing `NewRequestForm` beside the stored photo.
- Pure geodesic polygon area (`pyproj.Geod`) and UTM Zone 43N (`EPSG:32643`) position checks (`app/evidence/area.py`, `position.py`, `rules.py`) wired into `POST /api/plots`, `start_slot`, `done_slot`, and `run_checks` (`position_mismatch`, `too_fast`, `exact_duplicate_photo`, `code_missing`, `code_wrong`).
- Bulk plot loader `scripts/load_plots.py`, venue demo polygon `examples/demo_plot.geojson`, and setup guide `docs/DEMO_PLOT.md`.
- Officer flagged-jobs review table and Tier 2 `GET /api/dashboard/usage.csv` export with one-click download button on `/officer`, spatial map panel (`web/src/optional/DeskMapPanel.tsx`), plus `rescue_options` on `/api/schedule/will-miss`.
- Complete fallback test suite (`tests/api/test_step08_fallbacks.py`, `web/e2e/fallbacks.spec.ts`, `docs/FALLBACK_RESULTS.md`) and full 8-step Playwright E2E scenario (`web/e2e/full_loop.spec.ts`, `docs/READINESS.md`).

### Added (Phase 2 Frontend & Tier 0 Loop - 25 Oct 2026)
- Modern, accessible React 18 + TypeScript + Vite frontend under `web/` with plain CSS design system.
- Operator Desk (`/desk`) with summary counters, 15s intake form, request reflow panel, machines tab, and copyable WhatsApp message.
- Tractor-cab Driver View (`/driver/{token}`) with 56px touch targets, camera input, client-side downscaling to 1600px JPEG, GPS capture, 3-tick evidence summary, and "Could not serve" flow.
- Public Proof of Service Record (`/record/{token}`) with vertical 5-step timeline, status badges, print/PDF layout, and interactive SHA-256 hash verification.
- Officer Oversight Dashboard (`/officer`) with 8 metric cards, multi-dimensional filters, reason proportion bars, village table, and 15s auto-refresh ticker.
- Universal dependency health status strip (`StatusStrip.tsx`) and contract badges component (`Badge.tsx`).
- Production SPA fallback serving compiled `web/dist` alongside `/api` routes on `0.0.0.0:8000`.
- Cloudflare Quick Tunnel command (`python tasks.py tunnel`) for HTTPS mobile access to camera and GPS.
- Playwright Chromium end-to-end test runner (`python tasks.py e2e`) proving full Tier 0 loop against a fresh temporary database in offline mode.
- Demo setup and venue fallback guide in `docs/DEMO_SETUP.md`.

### Added (Phase 1 Backend Core - 25 Oct 2026)
- Complete backend API and core engine matching `docs/CONTRACT.md`.
- Cross-platform task runner `tasks.py` supporting `setup`, `dev`, `test`, `seed`, `reset`, `smoke`, `serve`.
- Centralized timezone-aware clock `app/clock.py` (Asia/Kolkata) with `VAARI_TODAY` simulation support.
- Full SQLite data model with 13 tables in WAL mode (`busy_timeout=5000`) and integer hundredths acres.
- Pure deterministic deadline-first scheduler in `app/scheduler/plan.py` with boundary tests (B1-B6), rules (C1-C13), and byte-for-byte reproducibility.
- Enforced slot lifecycle (`start`, `done`, `not-served`) and tamper-evident service records with v1 canonical JSON hash and verification endpoint.
- Photo upload pipeline with size limits, magic bytes validation (JPEG, PNG, WebP), and SHA-256 integrity storage.
- Bilingual slot notification rendering (Punjabi and English) with native month names and `wa.me` link generation.
- Dynamic relative-date seed generator and sub-second database reset (`python tasks.py reset` -> 28 scheduled, 7 will miss, 5 needs info).
- OpenAPI specification exported to `docs/openapi.json`.
- Comprehensive test suite of 71 unit and API tests with 100% pass rate.

### Added (1 Oct 2026)
- `docs/CONTRACT.md`: the single source of truth for the build: stack, layout, task runner, settings, full schema, enums, exact scheduler rules, lifecycle, record hash, messages, every route and output shape, seed spec, frontend rules, phase ownership.
- `docs/PHASES.md`: three sequential phases for three builders, with handoff rules.
- Decision records 13 to 16: one IST clock and relative seed dates; acres as integer hundredths; `TRAVEL_INFEASIBLE` as a service radius in v0.1; `needs_info` separated from `needs_review`.
- Tests B7, T1–T4, C12, C13, S4b, S10, S11.
- `AGENTS.md` and `CLAUDE.md`: rules for coding agents.

### Changed (1 Oct 2026)
- Test B3: an invalid request is rejected at creation with `VALIDATION_ERROR`; `INVALID_REQUEST` stays as a defensive scheduler reason.
- A photo is required only when the farmer gave evidence consent, matching PRIVACY.md.
- `not-served` is allowed from `in_progress` too, for a machine that breaks mid-job.
- The intake 503 now carries `details.intake_id`, so the form can show the stored photo.
- The build plan now assumes three people, not four, and a cross-platform `tasks.py` beside the Makefile.
- Rs. used instead of the rupee symbol.


### Added
- `docs/API.md`: grouped routes under `/api`, structured errors, worked examples.
- `docs/TESTING.md`: deadline boundary tests first, then state machines, the end-to-end scenario and every fallback path.
- `docs/PRIVACY.md`: data inventory, retention and deletion, access by role, the register-image lifecycle.
- `docs/BUILD_PLAN.md`: four tiers with hours, a fixed kill order, team allocation, the demo story, a readiness checklist and a reset procedure.
- README: a 30-second demo, what the demo proves and does not prove, fallback behaviour, known limitations, demo credentials.
- Decision records 9 to 12: inclusive deadlines, draft-then-confirm intake, the farmer's service code, satellite sensing as an optional layer.
- Prior art: handwriting extraction, field evidence and custody, project scaffolding.

### Changed
- **Scheduler pseudocode: the deadline day is now tried.** The earlier loop used an exclusive end and would have dropped the most urgent requests.
- Date semantics defined: `harvest_date`, `sow_by`, `deadline_date` (inclusive), `service_date`, `done_at`.
- Will-miss reasons are machine-readable codes with a sentence, the data used and a next action.
- The slot lifecycle is a state machine enforced by the backend.
- Evidence is described as plausibility, not proof. SHA-256 is named exact duplicate detection.
- Access control in v0.1 is labelled DEMO ONLY, with a checklist of what a pilot needs.
- The product claim is narrowed to coordination friction in the harvest-to-sowing window.
- The roadmap is split into eight smaller releases.
- Satellite sensing moved out of the core into an optional layer.

### Notes
- No product code exists yet. The first build is planned for 30–31 Oct 2026 under a no-pre-built-code rule, and the first product commit will land at hour 0.
