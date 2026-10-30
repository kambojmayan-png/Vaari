# Roadmap

Eight small releases instead of one broad v1.0. Every release closes the loop; later ones make it more robust, not wider. Features taken from other open projects are credited in brackets, and the survey is in [PRIOR_ART.md](PRIOR_ART.md).

Status words: **Designed** (specified, not built), **Built**, **Measured** (built, with published numbers). Nothing on this page is Built yet.

| Release | Theme | One-line goal |
| --- | --- | --- |
| v0.1 | Hackathon MVP | Register intake, deterministic scheduling and field evidence, end to end |
| v0.2 | Pilot hardening | Validation, retention jobs, CI, exports, an offline demo mode |
| v0.3 | Offline and mobile | Start and Done work with no signal |
| v0.4 | Scheduling optimisation | A routing solver behind the same interface, with road distances |
| v0.5 | Messaging | WhatsApp Business flows, reminders, consent from the farmer's phone |
| v0.6 | Security and privacy | Authentication, roles, audit chain, a compliant register reader |
| v0.7 | Satellite intelligence: future (v0.7), not built | Harvest sensing and coverage, validated before it is trusted ([design](FUTURE_SATELLITE.md)) |
| v1.0 | Pilot production | A stable deployment with one district's integrations |

## Validation before code

The weeks before the first build fall on the harvest, so the riskiest assumptions are tested on real behaviour first. The best test is a concierge pilot: run the loop by hand for one cooperative for 5 to 14 evenings, with a notebook, a spreadsheet and a personal WhatsApp account.

| # | Assumption that kills the product if wrong | Behaviour observed | Invalidated when |
| --- | --- | --- | --- |
| 1 | An operator will hand over his requests if it costs him almost nothing | Evenings on which the register photo arrives unprompted, with the phone column covered | Fewer than half the evenings |
| 2 | Some unserved requests are avoidable through better scheduling and communication | For each unserved request: was a machine free, reachable and willing, and the field ready? | Fewer than 1 in 5 avoidable. One centre is an anecdote, and the write-up says so |
| 3 | Farmers act on a slot message | Call-backs to re-confirm; fields not ready on arrival | Over half call back, or over 30% not ready |
| 4 | A vision model reads register pages well enough to beat typing | Rows usable without edits, on pages with no real personal data | Fewer than half the rows |
| 5 | A driver will tap twice and take two photos | Jobs with both photos and a location | Fewer than 6 of 10 |
| 6 | Someone with authority wants the output | One written sentence of interest | Nobody will write one |

## v0.1 — Hackathon MVP

Scope, hours, kill order and the readiness checklist are in [BUILD_PLAN.md](BUILD_PLAN.md). The build itself is split into three sequential phases, described in [PHASES.md](PHASES.md), with [CONTRACT.md](CONTRACT.md) as the single source of truth between them.

- **Tier 0:** requests, machines, deterministic scheduler with inclusive deadlines and reason codes, slot lifecycle enforced by the backend, service records, four basic views, on-screen Punjabi message.
- **Tier 1:** register photo → draft → human confirmation; prefilled `wa.me` and `tel:` links [agri_rent]; photo and position evidence with plausibility, too-fast and exact-duplicate checks; the farmer's service code [delivery-code practice in proof-of-delivery tools].
- **Tier 2, only if stable:** map panel, officer analytics, nearest-centre list, coverage trace, satellite module (future (v0.7), not built), review step.

## v0.2 — Pilot hardening

- A daily retention job that deletes register images and anonymises old requests, as [PRIVACY.md](PRIVACY.md) specifies.
- CI on every pull request; an auto-generated typed frontend client; Docker Compose for one-command start [full-stack-fastapi-template].
- An offline demo mode: a synthetic season and a replayed trace, with no network [harvest_time_estimate, AgOpenGPS simulator].
- i18n with Punjabi, Hindi and English [Agrirent Platform].
- Exports: usage CSV, PDF receipt with a QR code, GeoJSON layers for QGIS [CropCore].
- One retry when the reader's JSON breaks the schema, and deterministic validation of every field [DocExtract, Nutrient's extraction guide].
- A published reality ledger per release: production-grade, shortcut, seed or mock. A README status table that never lies [Agri-Share].

## v0.3 — Offline and mobile

- **An offline capture queue for Start and Done**, stored on the phone and synced when a signal returns, with the server acknowledging each item before it leaves the queue [ODK Collect, the offline-first logistics platform, GUARD].
- Battery-aware position sampling for long jobs [offline-first logistics platform].
- An installable web app for the Driver view. SMS as a fallback for the slot message.

## v0.4 — Scheduling optimisation

- A routing solver behind `Scheduler.plan()`: time windows from harvest to deadline, skills for machine types, priorities for fairness rules, working hours and breaks [VROOM, pyvroom]. Greedy stays the default and the fallback.
- Road distances from an open routing engine in place of straight-line × 1.3.
- A benchmark: first-come-first-served, greedy and the solver on the same requests, including a pilot centre's real register if it is shared. A simulation explains the algorithm; it is not field evidence.
- Two-step baler jobs and rain-aware reflow. Rescue options across centres, where "no spare capacity nearby" is recorded as a shortage signal.
- Reliability scores for centres. Never ratings of farmers.

## v0.5 — Messaging

- WhatsApp Business flows through an open platform: reminders, reschedule replies, and **consent captured from the farmer's own phone** [Glific].
- Voice notes in Punjabi, then IVR, because voice is the true incumbent.

## v0.6 — Security and privacy

- Authentication, role-based authorisation, secure sessions, rate limiting, CORS and CSRF controls, upload re-encoding and scanning [full-stack-fastapi-template for the auth baseline; the logistics platform's middleware list].
- The access matrix in [PRIVACY.md](PRIVACY.md) enforced, not just designed.
- A hash-chained event log, so tampering with history is evident and not only with one record [GUARD's Merkle chain; Evidential's custody log].
- Perceptual hashing beside SHA-256, to catch resized or re-encoded photos.
- A provider-agnostic reader router, and an India-hosted or on-device reader so real pages never leave the country or the phone [handwriting-json's provider routing].
- Source grounding: show the cropped region of the page beside each drafted field [Nutrient's extraction guide].
- A review of the whole design against India's data-protection rules.

## v0.7 — Satellite intelligence (future (v0.7), not built)

Validated before it is trusted, and never allowed to decide anything. The design, data sources, limits and validation plan are in [FUTURE_SATELLITE.md](FUTURE_SATELLITE.md). No satellite code exists in the repository.

- Harvest sensing per registered plot: an interval, never a day; the stated date wins; reported as "k of N intervals held" with mean error and bias [harvest_time_estimate].
- Orbit rules as code and as tests: same-MGRS-tile pairing, 10 m bands resampled down to 20 m, index and area invariants [savanna-burn-mapper]. Post-harvest baselines only [Digital Earth Africa's caveat].
- Coverage painted from the phone's path by implement width, overlaps unioned [idea: AgOpenGPS].
- Candidates to evaluate, not promises: Sentinel-1 VV/VH for hazy weeks [Ndvi2Gif]; Harmonized Landsat Sentinel-2 for denser series on larger plots [burn-scar-recovery].
- A research track only: weak labels from fire-point proximity plus optical change, with district-held-out evaluation [weak-supervision-burned-cropland].

## v1.0 — Pilot production

- Postgres and object storage; backups; monitoring.
- An export shaped like the state's usage report, so a job recorded in Vaari never has to be typed again. A farm-records export for interoperability [farmOS].
- A small driver app with background location and signed photos [geotagcamera's device-signed hashes].
- One district, one season, with the agriculture office as the operator of record.

## Not planned

Marketplace listings, payments or commissions, ratings of farmers, real-time chat, hardware trackers, an automated burn verdict, and any collection of Aadhaar or land records. Reasons are in [PRIOR_ART.md](PRIOR_ART.md#10-deliberately-not-adopted).

## Good first issues, once v0.1 lands

1. A test that every request is in exactly one state after any scheduler run.
2. The trace simulator: replay a GPX file into `POST /api/slots/{id}/trace`.
3. A Hindi message template, reviewed by a native speaker.
4. `make reset` in under a minute on a cold laptop.
5. The retention job, with a dry-run flag.
