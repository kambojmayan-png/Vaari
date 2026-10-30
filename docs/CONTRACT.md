# Build contract (v0.1)

This file is the single source of truth for the v0.1 build. Three people build Vaari in three phases, one after the other, and they do not share chats. This contract, the code in the repo, and `HANDOFF.md` are the only things passed between phases.

**If this file and any other doc disagree, this file wins.** The other docs explain *why*. This file says *exactly what*.

**Changing this contract.** Phase 1 may change anything until its handoff. After that, changes are additive only (a new field, a new route, a new enum value), and every change is written in `HANDOFF.md` under "Contract changes" and in `CHANGELOG.md`. Never rename or remove a field, a route or an enum value after phase 1 hands off.

---

## 1. Stack

| Part | Choice | Notes |
| --- | --- | --- |
| Language | Python 3.11 or newer | |
| API | FastAPI, Pydantic v2, uvicorn | |
| Database | SQLite in WAL mode, `busy_timeout = 5000`, via SQLAlchemy 2.x (sync) | Since pilot v0.2: Alembic migrations in `migrations/`, run at start-up (§15.7). `reset` deletes the file |
| Uploads | python-multipart | |
| Geometry | shapely 2 and pyproj | Phase 3 uses them. Phase 1 lists them in `requirements.txt` already |
| Config | python-dotenv | |
| Tests | pytest, FastAPI `TestClient` (httpx) | Playwright (Node) for browser tests from phase 2 |
| Frontend | React 18, Vite, TypeScript, React Router | Plain CSS. No UI library. Leaflet only in Tier 2 |
| Node | 20 or newer | |

Add no other library without writing it in `HANDOFF.md`. Everything must run on Windows, macOS and Linux: use `pathlib`, no bash-only scripts.

## 2. Repository layout

```
vaari/
  tasks.py                 cross-platform task runner (see section 3)
  Makefile                 thin wrapper: `make X` runs `python tasks.py X`
  requirements.txt
  .env.example             every variable from section 4, with safe defaults
  AGENTS.md  CLAUDE.md     rules for coding agents
  HANDOFF.md               one section per phase, written at the end of each phase
  app/
    main.py                FastAPI app; mounts /api; in serve mode also serves web/dist with SPA fallback
    config.py              settings read from the environment
    db.py                  engine, session, WAL and busy_timeout pragmas
    models.py              every table in section 6
    schemas.py             Pydantic input and output models
    errors.py              VaariError and the handlers that produce the error shape
    auth.py                passcode, machine-token and slot-token dependencies
    clock.py               today() and now_utc(). The ONLY place that reads the system clock
    tokens.py              token and service-code generators
    routes/                requests.py machines.py plots.py schedule.py slots.py driver.py
                           records.py dashboard.py health.py intake.py (phase 3)
    scheduler/             plan.py (pure function), service.py (loads, runs, saves), reasons.py, distance.py
    evidence/              lifecycle.py photos.py record.py checks.py; phase 3 adds position.py rules.py area.py
    messaging/             render.py templates.json
    intake/                phase 3: reader.py validate.py prompt.py hosted.py
    seed/                  seed.py villages.json
    optional/              Tier 2 only. Nothing outside this folder imports it
  web/                     phase 2
  scripts/                 load_plots.py (phase 3) and other one-off scripts
  tests/
    unit/  api/  e2e/      e2e holds Playwright tests (phase 2 and 3)
    fixtures/              tiny test images, a sample GeoJSON, a mock register draft
  data/                    gitignored: vaari.sqlite, photos/, register_pages/
  docs/
```

## 3. Task runner (`python tasks.py <task>`)

| Task | Does | Added in |
| --- | --- | --- |
| `setup` | Create `.venv` if missing, install `requirements.txt`, run `npm install` in `web/` if it exists, install Playwright browsers if `web/` exists | 1, extended in 2 |
| `dev` | uvicorn with reload on `127.0.0.1:8000`. Phase 2 adds: also start `npm run dev` in `web/` | 1, 2 |
| `test` | `pytest -q` (unit and API tests) | 1 |
| `seed` | Load seed data into an existing database | 1 |
| `reset` | Delete the database file and `data/photos/` and `data/register_pages/`, create tables, seed, run the scheduler once. Prints the time taken. Target under one minute | 1 |
| `smoke` | Run the end-to-end API scenario (`tests/api/test_smoke.py`) against a fresh temporary database | 1, extended in 3 |
| `build-web` | `npm run build` in `web/` | 2 |
| `serve` | `build-web`, then uvicorn on `0.0.0.0:8000` serving the API and the built frontend | 1 (API only), 2 |
| `e2e` | Start `serve` on a temporary database, run Playwright, stop the server | 2 |
| `tunnel` | Run `cloudflared tunnel --url http://localhost:8000` if cloudflared is installed, otherwise print how to install it | 2 |
| `reader-eval` | Run the configured reader on `examples/register_pages/` and print counts. *(Pilot v0.2: per-field k of N per page, silent errors, common errors, pass bar; writes `docs/READER_EVAL.md`.)* | 3 |
| `purge-images [--dry-run]` | Delete register page images past `image_delete_after` | 3 |

## 4. Configuration (`.env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `VAARI_DEMO_PASSCODE` | `change-me` | Shared demo passcode. DEMO ONLY |
| `VAARI_DB_PATH` | `data/vaari.sqlite` | |
| `VAARI_DATA_DIR` | `data` | Photos and register pages live under here |
| `VAARI_TZ` | `Asia/Kolkata` | The time zone for "today" |
| `VAARI_TODAY` | empty | If set (`YYYY-MM-DD`), overrides today. For tests and rehearsals only. When set, `/api/health` reports `demo_clock: true` and the UI shows a badge |
| `VAARI_WINDOW_DAYS` | `20` | `sow_by = harvest_date + window_days` |
| `VAARI_MAX_RADIUS_KM` | `25` | Estimated travel distance beyond which a field is `TRAVEL_INFEASIBLE` |
| `VAARI_ROAD_FACTOR` | `1.3` | Straight line × this = estimated travel distance |
| `VAARI_MAX_PHOTO_MB` | `8` | Larger uploads get 413 |
| `VAARI_TOO_FAST_MIN_PER_ACRE` | `25` | Phase 3 |
| `VAARI_SEED_PHONES` | empty | Comma-separated 10-digit numbers of the team, used for seeded farmers so `wa.me` links reach a real phone |
| `VAARI_DEMO_PLOT_LAT`, `VAARI_DEMO_PLOT_LON` | the centre's position | Where the live demo job's plot is. Set it to the hall on the day |
| `VAARI_CENTRE_LAT`, `VAARI_CENTRE_LON`, `VAARI_CENTRE_NAME`, `VAARI_CENTRE_PHONE` | a demo centre | The home centre for the seed |
| `VAARI_PUBLIC_BASE_URL` | empty | The tunnel URL, used to build full record and driver links |
| `VAARI_READER` | `mock` | Phase 3: `mock` or `hosted`. *(Pilot v0.2, §15.13: `mock`, `gemini_demo` or `custom`; `hosted` still means `gemini_demo`.)* |
| `VAARI_ALLOW_HOSTED_READER` | `false` | Phase 3: must be `true` before any image goes to a hosted model |
| `VAARI_VISION_PROVIDER` | `gemini` | Phase 3: `gemini` or `anthropic`. *(Pilot v0.2: `gemini` only.)* |
| `VAARI_VISION_MODEL` | empty | Phase 3: a current vision model name from the provider. *(Pilot v0.2: required when the hosted reader is on; no default in the code.)* |
| `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` | empty | Phase 3 |
| `VAARI_READER_TIMEOUT_S` | `20` | Phase 3 |

## 5. Units, time and identifiers

- **Acres.** The API uses a number with at most 2 decimals. The database stores an integer `acres_x100` (3.2 acres is 320). The scheduler compares integers only, so an exact capacity match (test C1) is exact. Valid range 0.25 to 200.
- **Today.** `clock.today()` returns `VAARI_TODAY` if set, else the current date in `VAARI_TZ`. Nothing else in the code may call `date.today()`, `datetime.now()` or `datetime.utcnow()`. A test greps for this.
- **Timestamps.** Server-set, UTC, ISO 8601 with `Z`.
- **On time.** A job is on time when the IST date of `done_at` is on or before `deadline_date`.
- **Phone.** Exactly 10 digits, first digit 6 to 9, stored without country code. `wa.me` and `tel:` links add `91`.
- **Tokens.** `secrets.token_urlsafe(16)` (128 bits). Service code: 4 random digits, `0000` to `9999`, as a string.
- **Date display in the UI and messages.** `23 Oct` in English, `23 ਅਕਤੂਬਰ` in Punjabi.

## 6. Data model

All tables are created by phase 1, including the ones only phase 3 fills. Column types: `int`, `str`, `bool`, `date`, `datetime` (UTC), `json` (stored as TEXT).

**village** — id int pk · name str unique · lat float · lon float

**centre** — id · name str · phone str · lat · lon · is_home bool · service_types json (list of service types it offers; used for "nearest alternative")

**machine** — id · centre_id fk · name str ("Super Seeder 01") · type str (display) · service_types json (list) · capacity_acres_x100 int (per day) · implement_width_m float null · active_from date null · active_to date null · status str (`active` | `inactive`) · link_token str unique

**farmer** — id · phone str unique · name str null · language str default `pa` · consent_service bool · consent_evidence bool · consent_share bool · consent_at datetime · consent_simulated bool default true

**plot** — id · farmer_id fk · village_name str · village_id fk null · pin_lat float null · pin_lon float null · geojson text null · acres_x100 int · centroid_lat float null · centroid_lon float null · location_source str (`pin` | `polygon` | `village` | `none`)

**intake_page** — id · centre_id fk · image_path str · image_sha256 str · image_delete_after datetime · reader str · prompt_version str · latency_ms int null · status str (`drafted` | `confirmed` | `failed`) · error str null · created_at

**register_draft** — id · intake_page_id fk · row_no int · row_json json · confidence_json json · issues_json json · edited bool · edited_fields_json json · skipped bool · confirmed_at datetime null · request_id fk null

**request** — id · centre_id fk · farmer_id fk · plot_id fk · service_type str · source str (`form` | `register` | `seed`) · acres_x100 int · harvest_date date null · sow_by date null · deadline_date date null · deadline_overridden bool · status str · reason_code str null · reason str null · next_action str null · data_used_json json null · nearest_alternative str null · alternative_distance_km float null · created_at · updated_at

**slot** — id · request_id fk · machine_id fk · service_date date · seq int · status str · link_token str unique · service_code str · est_distance_km float null · notified_at datetime null · started_at datetime null · done_at datetime null · not_served_reason str null · not_served_note str null · code_entered str null · farmer_confirmed bool null · flags_json json (list, default `[]`) · needs_review bool · created_at

**evidence** — id · slot_id fk · kind str (`start` | `done` | `extra`) · server_time datetime · lat float null · lon float null · accuracy_m float null · distance_to_plot_m float null · plausible bool null (null means not checked) · photo_path str null · photo_sha256 str null · photo_bytes int null. **Rows are never updated.**

**service_record** — id · slot_id fk unique · token str unique · outcome str (`COMPLETED`) · on_time bool · record_hash str · hash_version str (`v1`) · generated_at

**message_log** — id · slot_id fk · farmer_id fk · channel str (`screen` | `wa_link` | `tel`) · template str · body text · status str (`rendered` | `opened`) · created_at

**event_log** — id · actor str (`operator`, `driver:machine-3`, `system`) · entity str · entity_id int · event str · payload_json json · at. **Append-only.**

Tier 2 tables (`trace`, `orbit_check`, `review`) live in `app/optional/` and are created only by it.

## 7. Enums

| Enum | Values |
| --- | --- |
| `service_type` | `super_seeder`, `happy_seeder`, `baler`, `mulcher` |
| `buffer_days(service_type)` | `super_seeder` 0, `happy_seeder` 0, `baler` 2, `mulcher` 2 |
| `request.status` | `needs_info`, `open`, `scheduled`, `done`, `will_miss`, `cancelled` |
| `request.source` | `form`, `register`, `seed` |
| `slot.status` | `scheduled`, `in_progress`, `done`, `not_served`, `cancelled` |
| Will-miss `reason_code` | `INVALID_REQUEST`, `DEADLINE_PASSED`, `NO_COMPATIBLE_MACHINE`, `MACHINE_UNAVAILABLE`, `TRAVEL_INFEASIBLE`, `NO_CAPACITY` |
| `not_served_reason` | `FIELD_NOT_READY`, `FARMER_ABSENT`, `MACHINE_BROKEN`, `WEATHER`, `OTHER` |
| Evidence `flags` (phase 3) | `position_mismatch`, `too_fast`, `exact_duplicate_photo`, `code_missing`, `code_wrong` |
| Record position state | `plausible`, `mismatch`, `not_checked`, `not_given` |
| Badges (exact display text) | `seeded request`, `replayed real job`, `historical imagery`, `position self-reported`, `position not checked`, `consent simulated`, `reader: mock`, `exported by hand`, `demo clock` |

**`needs_info` and `needs_review` are different things.** `needs_info` is a request with no harvest date yet, so it cannot be planned. `needs_review` is a finished or running job whose evidence raised a flag. The Desk counts `needs_info`. The Officer counts `needs_review`.

### Request state rules

| Event | Effect |
| --- | --- |
| Create with no `harvest_date` | `needs_info` |
| Create with `harvest_date` | `open`; `sow_by` and `deadline_date` computed unless `deadline_date` was given (then `deadline_overridden = true`) |
| Scheduler run | Plans every request in `open` or `will_miss`. Result: `scheduled` (with a slot) or `will_miss` (with a reason). Requests that already have a `scheduled` or `in_progress` slot are left alone and their acres count against capacity |
| `PATCH` | Re-validate and recompute dates. Cancel the request's slot if it has not started. Status becomes `open` or `needs_info`. Run the scheduler for the centre |
| Machine set `inactive` | Cancel its slots that have not started; their requests become `open`; run the scheduler |
| Slot `not_served` | Slot `not_served`; request `open`; run the scheduler |
| Slot `done` | Request `done` |
| `DELETE` | Request `cancelled`; its slot `cancelled` if not started. A started slot cannot be cancelled (409 `INVALID_TRANSITION`) |

After every scheduler run each request is in exactly one status (test C11).

## 8. Scheduler (exact rules)

`plan(requests, machines, centres, existing_slots, today) -> Plan` is a pure function in `app/scheduler/plan.py`. No database access, no clock, no randomness. `service.py` loads the inputs, calls `plan`, and saves the result.

1. **Order:** requests in `open` or `will_miss`, sorted by `(deadline_date, created_at, id)`.
2. **Validity:** missing acres, acres outside 0.25 to 200, missing deadline, or `deadline_date < harvest_date` gives `INVALID_REQUEST`. The API rejects these at creation, so this is a defensive check.
3. `deadline_date < today` gives `DEADLINE_PASSED`.
4. `C` = home-centre machines whose `service_types` include the request's type, sorted by `id`. Empty gives `NO_COMPATIBLE_MACHINE`.
5. **Location** of a request: the plot centroid, else the pin, else the village's coordinates, else none. **Estimated distance** = haversine(centre, location) × `VAARI_ROAD_FACTOR`, rounded to 0.1 km. With no location, distance is 0 and the explanation says "location unknown".
6. For each `day` from `max(today, harvest_date)` to `deadline_date` **inclusive**, for each `m` in `C`:
   - skip if `m.status == inactive`, or `day < active_from`, or `day > active_to`;
   - skip if estimated distance > `VAARI_MAX_RADIUS_KM`;
   - skip if `free_acres_x100(m, day) < request.acres_x100`, where free = capacity − acres of slots on that machine-day with status `scheduled`, `in_progress` or `done`;
   - `cost` = the smallest estimated distance from the request to the centre or to any request already assigned to that machine-day;
   - keep the best `(day, cost, m.id)`; stop at the first day that has any candidate.
7. If found: create the slot with a new `link_token` and `service_code`. Then renumber `seq` for that machine-day by nearest neighbour from the centre (ties broken by request id).
8. If not found, the reason is chosen in this order: no machine in `C` is active on any day of the window gives `MACHINE_UNAVAILABLE`; else every active machine's centre is beyond the radius gives `TRAVEL_INFEASIBLE`; else `NO_CAPACITY`.
9. **Nearest alternative:** the nearest non-home centre whose `service_types` include the request's type, with its estimated distance from the request's location.

### Explanation text (stored on the request)

| Outcome | `reason` | `next_action` |
| --- | --- | --- |
| scheduled | Scheduled on {23 Oct} on {Super Seeder 01}: the earliest day with {3.2} free acres before the deadline of {24 Oct}. | null |
| `INVALID_REQUEST` | This request is incomplete or its dates conflict: {problem}. | Correct the request. |
| `DEADLINE_PASSED` | The deadline of {24 Oct} is before today ({26 Oct}). | Call the farmer and record the outcome. |
| `NO_COMPATIBLE_MACHINE` | This centre has no machine for {baler} work. | Refer to {Centre B}, {8.4} km away. |
| `MACHINE_UNAVAILABLE` | Every {baler} machine is inactive between {20 Oct} and {24 Oct}. | Check repairs, or ask {Centre B}, {8.4} km away. |
| `TRAVEL_INFEASIBLE` | The field is about {41.2} km away, beyond the {25} km service radius. | Refer to {Centre C}, {6.1} km away. |
| `NO_CAPACITY` | No compatible machine has {2.5} free acres on or before {24 Oct}. | Ask {Centre B}, {8.4} km away. |

If no alternative centre exists, the next action ends with "another centre" instead of a name. `data_used_json` holds the numbers the sentence used: acres, deadline_date, machines_checked, days_checked, distance_km.

## 9. Slots and evidence

| Action | Allowed from | Requires | Errors |
| --- | --- | --- | --- |
| `start` | `scheduled` | Auth (below). A photo if the farmer gave evidence consent. Position optional | 401, 403 `WRONG_SLOT`, 409 `DUPLICATE_START` (already `in_progress`), 409 `INVALID_TRANSITION` (any other status), 422 `EVIDENCE_MISSING`, 413, 422 `VALIDATION_ERROR` (not an image) |
| `done` | `in_progress` | Auth. A photo if evidence consent. Position optional. `service_code` optional | 409 `INVALID_TRANSITION` (Done before Start, or already done), 422 `EVIDENCE_MISSING`, 413 |
| `not-served` | `scheduled` or `in_progress` | Auth. A reason from the enum | 409 `INVALID_TRANSITION`, 422 |

- **Auth for slot actions:** header `X-Vaari-Slot-Token` equal to the slot's `link_token`, or the operator passcode header. A slot token that belongs to a different slot gives 403 `WRONG_SLOT`. Nothing at all gives 401.
- **Photos:** accept JPEG, PNG or WebP, checked by magic bytes, not only by content type. Save as `data/photos/{slot_id}_{kind}_{sha256[:12]}.{ext}`. SHA-256 of the raw uploaded bytes. *(Changed in pilot v0.2, §15.8: metadata is stripped and the image re-encoded as JPEG before saving; the name ends `.jpg` and the SHA-256 and size are of the stored file.)*
- **Without evidence consent** the job closes with times only, and the record says "times only: no evidence consent".
- **Checks.** At `done`, `evidence/checks.py: run_checks(session, slot) -> list[str]` returns flags. Phase 1 ships it returning `[]` and every position as `not_checked`. Phase 3 fills it in. `needs_review = len(flags) > 0`. Flags never change a status and never block.
- **At `done`:** create the `service_record` with a new token and the hash below; set the request to `done`; write `event_log` rows for start, done, record and every check.

### Record hash, version `v1`

`record_hash = "sha256:" + sha256(canonical_json(payload))`, where `canonical_json` is `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` and the payload is:

```json
{ "request_id": 1023, "slot_id": 42, "machine_id": 1, "acres_x100": 320,
  "service_date": "2026-10-23", "deadline_date": "2026-10-24",
  "started_at": "2026-10-23T03:34:00Z", "done_at": "2026-10-23T05:42:10Z",
  "code_entered": "4821",
  "evidence": [ { "kind": "start", "server_time": "...", "lat": 30.2451, "lon": 75.8412,
                  "accuracy_m": 18, "photo_sha256": "..." } ] }
```

Evidence is sorted by id. Flags and review state are **not** hashed, because a later review must not break the hash. `GET /api/records/{token}/verify` recomputes the hash and returns `{stored, recomputed, match}`.

## 10. Messages

`app/messaging/templates.json` holds the slot message in Punjabi (`pa`) and English (`en`). The Punjabi text must be checked by a native speaker before the demo.

```text
pa: ਸਤ ਸ੍ਰੀ ਅਕਾਲ ਜੀ। ਤੁਹਾਡੇ {village} ਵਾਲੇ {acres} ਏਕੜ ਖੇਤ ਲਈ {machine} {date} ਨੂੰ ਆਵੇਗੀ। ਕੰਮ ਪੂਰਾ ਹੋਣ 'ਤੇ ਡਰਾਈਵਰ ਨੂੰ ਇਹ ਕੋਡ ਦੱਸੋ: {code}। ਕੋਈ ਗੱਲ ਹੋਵੇ ਤਾਂ ਫ਼ੋਨ ਕਰੋ: {centre_phone}। - {centre_name}
en: Sat Sri Akal ji. {machine} will come on {date} for your {acres}-acre field in {village}. When the work is done, tell the driver this code: {code}. For any problem call {centre_phone}. - {centre_name}
```

Punjabi months: ਜਨਵਰੀ ਫ਼ਰਵਰੀ ਮਾਰਚ ਅਪ੍ਰੈਲ ਮਈ ਜੂਨ ਜੁਲਾਈ ਅਗਸਤ ਸਤੰਬਰ ਅਕਤੂਬਰ ਨਵੰਬਰ ਦਸੰਬਰ.

`wa_link = "https://wa.me/91{phone}?text=" + urlencode(body)`. `tel_link = "tel:+91{phone}"` (the farmer's phone, for the operator to call).

## 11. API

All routes are under `/api`. Every response is JSON except `usage.csv` and images. **Auth:** `P` = header `X-Vaari-Passcode`; `M` = header `X-Vaari-Machine-Token`; `S` = slot auth from section 9; `T` = the token in the path; `-` = public.

### Error shape

```json
{ "error_code": "VALIDATION_ERROR", "message": "Phone must be 10 digits.", "details": { "field": "phone" } }
```

FastAPI's own validation errors (`RequestValidationError`) must be converted into this shape with `error_code: VALIDATION_ERROR` and `details.field` set to the first failing field. Codes and HTTP status: `VALIDATION_ERROR` 422, `NOT_FOUND` 404, `UNAUTHORIZED` 401, `WRONG_SLOT` 403, `INVALID_TRANSITION` 409, `DUPLICATE_START` 409, `EVIDENCE_MISSING` 422, `DRAFT_NOT_FOUND` 404, `READER_UNAVAILABLE` 503, `PAYLOAD_TOO_LARGE` 413.

### Routes

| Method and path | Auth | Phase | Body or query → response |
| --- | --- | --- | --- |
| `GET /api/health` | - | 1 | → `{status, database, reader, messaging, satellite, today, demo_clock, version}`. `reader` is `not_built` until phase 3, then `mock`, `hosted` or `down` |
| `POST /api/requests` | P | 1 | `{phone, name?, village, lat?, lon?, acres, service_type, harvest_date?, deadline_date?, consent_service, consent_evidence, consent_share}` → 201 `RequestOut`. `consent_service` must be true. Runs the scheduler for the centre |
| `GET /api/requests` | P | 1 | `?status=&village=&date=&service_type=` (`date` filters on the slot's date) → `[RequestOut]`, sorted by `(deadline_date, id)` |
| `GET /api/requests/{id}` | P | 1 | → `RequestOut` |
| `PATCH /api/requests/{id}` | P | 1 | any of `name, village, lat, lon, acres, service_type, harvest_date, deadline_date` → `RequestOut` |
| `DELETE /api/requests/{id}` | P | 1 | → `RequestOut` (cancelled) |
| `POST /api/machines` | P | 1 | `{name, type, service_types, capacity_acres_per_day, implement_width_m?, active_from?, active_to?}` → 201 `MachineOut` |
| `GET /api/machines` | P | 1 | → `[MachineOut]` |
| `PATCH /api/machines/{id}` | P | 1 | any field, including `status` → `MachineOut`. Going `inactive` triggers the reflow |
| `POST /api/plots` | P | 1 | `{farmer_phone, village, pin_lat?, pin_lon?, acres, geojson?}` → 201 `PlotOut`. Phase 3 computes acres and centroid from `geojson` |
| `GET /api/plots`, `GET /api/plots/{id}` | P | 1 | → `PlotOut` |
| `POST /api/schedule/run` | P | 1 | → `{total, needs_info, open, scheduled, done, will_miss, cancelled, ran_in_ms, today}` |
| `GET /api/schedule` | P | 1 | `?date=&machine_id=` → `[{machine_id, machine_name, date, capacity_acres, used_acres, slots: [SlotOut]}]` |
| `GET /api/schedule/will-miss` | P | 1 | → `[{request_id, village, acres, service_type, deadline_date, status, reason_code, reason, data_used, next_action, nearest_alternative, alternative_distance_km}]`. No phone numbers |
| `GET /api/slots` | P or M | 1 | `?date=&machine_id=` → `[SlotOut]` in `seq` order. With M, only that machine's slots |
| `GET /api/driver/{machine_token}` | T | 1 | `?date=` (default today) → `{machine: {id, name}, date, slots: [SlotOut]}`. Each slot includes its `link_token` so the Driver page can act on it |
| `GET /api/slots/{id}/message` | P | 1 | → `{slot_id, language, body, body_en, wa_link, tel_link, service_code}`. Logs `rendered` |
| `POST /api/slots/{id}/message/opened` | P | 1 | `{channel: "wa_link" | "tel"}` → 204. Logs `opened`, sets `notified_at` |
| `POST /api/slots/{id}/start` | S | 1 | multipart: `photo?`, `lat?`, `lon?`, `accuracy_m?` → `SlotEvidenceOut` |
| `POST /api/slots/{id}/done` | S | 1 | multipart: `photo?`, `lat?`, `lon?`, `accuracy_m?`, `service_code?` → `SlotEvidenceOut` with `record_url` |
| `POST /api/slots/{id}/not-served` | S | 1 | `{reason, note?}` → `SlotOut` |
| `GET /api/records/{token}` | T | 1 | → `RecordOut` |
| `GET /api/records/{token}/verify` | T | 1 | → `{stored, recomputed, match}` |
| `GET /api/dashboard/summary` | P | 1 | `?village=&date=&machine_id=&status=` → `{total, needs_info, scheduled, in_progress, completed, will_miss, needs_review, capacity_used_pct, by_reason, by_village, today}` |
| `GET /api/dashboard/usage.csv` | P | 3 (Tier 2) | CSV: `date, machine, jobs, acres` |
| `POST /api/intake/register-photo` | P | 3 | multipart `photo` → 200 `IntakeOut`, or 503 `READER_UNAVAILABLE` with `details.intake_id` so the client can show the photo beside the form |
| `GET /api/intake/{id}` | P | 3 | → `IntakeOut` |
| `GET /api/intake/{id}/image` | P | 3 | → the page image |
| `POST /api/intake/{id}/confirm` | P | 3 | `{rows: [{row, fields, skip?}]}` → 201 `{created_request_ids, skipped_rows, errors}` |

`capacity_used_pct` = scheduled-or-done acres ÷ active machine capacity, over the 7 days starting today, rounded to a whole number.

### Output shapes

```json
// RequestOut
{ "id": 1023, "status": "scheduled", "source": "form",
  "farmer": { "name": null, "phone": "98XXXXXX12" },
  "village": "Pind Kalan", "acres": 3.2, "service_type": "super_seeder",
  "harvest_date": "2026-10-18", "sow_by": "2026-11-07", "deadline_date": "2026-11-07",
  "explanation": { "reason_code": null, "reason": "Scheduled on 23 Oct on ...", "data_used": {},
                   "next_action": null, "nearest_alternative": null, "alternative_distance_km": null },
  "slot": { "id": 42, "machine_id": 1, "machine_name": "Super Seeder 01",
            "service_date": "2026-10-23", "seq": 1, "status": "scheduled" },
  "badges": ["seeded request"], "created_at": "..." }

// MachineOut
{ "id": 1, "name": "Super Seeder 01", "type": "Super Seeder", "service_types": ["super_seeder"],
  "capacity_acres_per_day": 8.0, "status": "active", "active_from": null, "active_to": null,
  "driver_path": "/driver/<link_token>" }

// SlotOut
{ "id": 42, "seq": 1, "status": "scheduled", "service_date": "2026-10-23",
  "machine": { "id": 1, "name": "Super Seeder 01" }, "request_id": 1023,
  "farmer_name": null, "village": "Pind Kalan", "acres": 3.2, "deadline_date": "2026-10-24",
  "location": { "lat": 30.77, "lon": 76.57, "source": "pin" }, "est_distance_km": 4.2,
  "link_token": "only in driver and operator responses", "needs_review": false, "flags": [],
  "started_at": null, "done_at": null, "record_token": null }

// SlotEvidenceOut
{ "slot_id": 42, "status": "done",
  "evidence": { "kind": "done", "lat": 30.2451, "lon": 75.8412, "accuracy_m": 18,
                "distance_to_plot_m": null, "plausible": null, "position_state": "not_checked",
                "photo": "present", "timestamp": "2026-10-23T05:42:10Z" },
  "flags": [], "needs_review": false, "record_url": "/record/<token>" }

// RecordOut. Never contains a farmer's name or phone.
{ "request_id": "VR-1023", "village": "Pind Kalan", "machine": "Super Seeder 01", "acres": 3.2,
  "service_type": "super_seeder", "scheduled": "2026-10-23", "deadline_date": "2026-10-24",
  "started_at": "...", "done_at": "...",
  "start_position": "not_checked", "done_position": "not_checked",
  "start_photo": "present", "done_photo": "present", "evidence_note": null,
  "farmer_confirmed": null, "outcome": "COMPLETED", "on_time": true,
  "flags": [], "needs_review": false, "badges": ["seeded request", "consent simulated"],
  "record_hash": "sha256:...", "hash_version": "v1" }

// IntakeOut (phase 3)
{ "intake_id": 7, "reader": "mock", "latency_ms": 40, "status": "drafted",
  "rows": [ { "row": 1, "fields": { "phone": "...", "name": "...", "village": "...", "acres": 4.5,
              "service_type": "super_seeder", "harvest_date": "2026-10-18" },
              "confidence": { "phone": 0.96, "name": 0.41 }, "issues": [] } ] }
```

## 12. Seed data (`python tasks.py reset`)

All seeded data is fictional and every seeded request carries the `seeded request` badge. Dates are **relative to `clock.today()`**, never hard-coded, so the demo works on any day.

- **Centres:** the home centre (from `.env`), Centre B about 8 km away (offers `super_seeder`, `mulcher`), Centre C about 15 km away (offers `baler`, `super_seeder`).
- **Villages:** 8 fictional village names, placed 2 to 12 km from the home centre, plus one far village about 40 km away.
- **Machines (home centre):** Super Seeder 01 and Super Seeder 02, 8 acres a day each; Baler 01, 15 acres a day, `active_from = today + 10` (in repair).
- **40 requests** that, after one scheduler run, give exactly: **28 scheduled, 7 will miss, 5 needs info.** The 7 will-miss requests cover: `DEADLINE_PASSED` 1, `NO_COMPATIBLE_MACHINE` 2 (mulcher), `MACHINE_UNAVAILABLE` 1 (baler, deadline before the baler returns), `TRAVEL_INFEASIBLE` 1 (far village), `NO_CAPACITY` 2 (deadline today, after today's machine-days are full).
- **The demo request:** 3.2 acres, `super_seeder`, deadline today, the earliest `created_at` of all seeded requests, pin at `VAARI_DEMO_PLOT_LAT/LON` (default: the centre's own position, so it is nearest and gets `seq = 1`). It must come out scheduled today on Super Seeder 01 with `seq = 1`. The two `NO_CAPACITY` requests are created after it, so they lose today's remaining space.
- Farmers use `VAARI_SEED_PHONES` in rotation, else made-up numbers like `9000000001`. Farmers' names are made up; 10 of them have no name.
- A test asserts every number above. If the counts drift, fix the seed, not the test.

## 13. Frontend contract (phase 2)

- Routes: `/` redirects to `/desk`; `/desk`; `/driver/:machineToken`; `/officer`; `/record/:token`; `/intake` (phase 3). *(Pilot v0.2 adds `/driver` and `/record`: operator pickers that open a real driver view or record.)*
- The API base is `/api`. In dev, Vite proxies `/api` to `127.0.0.1:8000`. In serve mode, FastAPI serves `web/dist` at `/` with an SPA fallback for every path not under `/api`. One origin, so no CORS and one tunnel.
- The passcode is entered once on Desk or Officer and kept in `sessionStorage`. Driver and Record pages never ask for it.
- `web/src/api.ts` is the only file that calls `fetch`. It turns every error into `{error_code, message, details}` and the UI switches on `error_code`.
- A status strip on Desk and Officer polls `/api/health` every 15 seconds and shows each dependency. A fallback that hides itself is a bug.
- Every badge from the enum is shown wherever its data appears.

## 14. Phase ownership

| Phase | Owner and tool | Builds | Leaves for later |
| --- | --- | --- | --- |
| 1 | Claude Code (VS Code) | Everything in sections 1 to 12 that is marked phase 1: backend, scheduler, lifecycle, records, dashboard, messages, seed, task runner | Checks stub, intake routes, frontend |
| 2 | Antigravity | `web/`: Desk, Driver, Officer, Record; serve mode; tunnel; Playwright end-to-end for the Tier 0 loop | Intake screen, evidence checks |
| 3 | Antigravity | Intake (reader, routes, confirmation screen), polygons and position checks, evidence flags, fallback tests, full end-to-end, demo readiness, then Tier 2 if time allows | — |

Each phase ends by writing its section of `HANDOFF.md`, running every test, and pushing a git tag: `phase-1-done`, `phase-2-done`, `phase-3-done`.

## 15. Pilot hardening (v0.2): additive changes

This section records every change made for the one-centre pilot. Each one is additive unless it says otherwise, and each is also listed in `HANDOFF.md` under "Pilot build (v0.2) / Contract changes".

### 15.1 Configuration added

| Variable | Default | Meaning |
| --- | --- | --- |
| `VAARI_ENV` | `development` | `development` or `production`. Production refuses to start with unsafe settings (see 15.2) |
| `VAARI_ALLOW_HOSTED_READER_IN_PRODUCTION` | `false` | Explicit override. Without it, production refuses to start while any hosted reader is enabled |
| `VAARI_SECRET_KEY` | empty | Signs login sessions. Required in production, at least 32 characters. In development an empty value means a random key per process |
| `VAARI_SESSION_HOURS` | `12` | How long a sign-in lasts |
| `VAARI_LOGIN_RATE_PER_MIN` | `10` | Sign-in attempts per client address per minute |
| `VAARI_LOGIN_LOCKOUT_FAILURES` | `5` | Wrong passwords for one username (within the lockout window) before it is locked |
| `VAARI_LOGIN_LOCKOUT_MINUTES` | `15` | Lockout window and length |
| `VAARI_UPLOAD_RATE_PER_MIN` | `30` | Photo uploads (`register-photo`, slot `start`, slot `done`) per client address per minute |
| `VAARI_DRIVER_LINK_DAYS` | `30` | Lifetime of a new driver link (machine token) |
| `VAARI_RECORD_LINK_DAYS` | `365` | Lifetime of a new service-record link |
| `VAARI_PHOTO_STORE` | `local` | Where photos are kept. Only `local` is built; any other value is refused at start-up |
| `VAARI_BACKUP_DIR` | `backups` | Where `python tasks.py backup` writes |
| `VAARI_CORS_ORIGINS` | empty | Exact origins allowed to call the API cross-origin. Empty = no CORS headers at all. Production refuses `*` and non-`https://` entries |
| `VAARI_TRUST_PROXY` | `false` | Take the client address from the first `X-Forwarded-For` value. Turn on only behind your own reverse proxy |

### 15.2 Production start-up checks

With `VAARI_ENV=production` the app refuses to start, and lists every problem, when:

- `VAARI_SECRET_KEY` is empty, a default value (`change-me` and similar), or shorter than 32 characters. (Item A1 first checked `VAARI_DEMO_PASSCODE` with a 16-character minimum. Item A2 switches the shared passcode off in production, so the check moved to the secret that now guards every sign-in. The passcode's value no longer matters in production);
- a hosted reader is enabled (`VAARI_READER` other than `mock`, or `VAARI_ALLOW_HOSTED_READER=true`) and `VAARI_ALLOW_HOSTED_READER_IN_PRODUCTION` is not `true`.

`python tasks.py check-config` prints the same list without starting the server. Any other `VAARI_ENV` value is refused in every mode.

### 15.3 Accounts, roles and sessions (A2)

- **Tables.** `user_account` — id · username str unique (stored lower-case) · password_hash str (argon2id) · role str (`operator` | `officer`) · active bool · created_at · last_login_at null. `auth_session` — id · sid_sha256 str unique · user_id fk · created_at · expires_at · revoked_at null. Only a SHA-256 of the session id is stored.
- **Session token.** `v1.<sid>.<expires_unix>.<hmac>`, HMAC-SHA256 with `VAARI_SECRET_KEY`. Sent as `Authorization: Bearer <token>`. Valid only if the signature matches, it has not expired, the session row is not revoked, and the account is active.
- **Shared passcode.** `X-Vaari-Passcode` works in development only, where it acts with both roles. In production it is always refused with 401.
- **Roles.**

| Routes | operator | officer |
| --- | --- | --- |
| Requests, plots, intake, schedule run, `GET /api/schedule`, `GET /api/slots`, slot messages, slot actions, machine create and patch | yes | no (403 `FORBIDDEN`) |
| `GET /api/dashboard/summary`, `GET /api/dashboard/usage.csv`, `GET /api/schedule/will-miss`, `GET /api/machines` | yes | yes. Officers get `driver_path: ""` |

- **New routes.** `POST /api/auth/login` `{username, password}` → `{token, token_type: "bearer", expires_at, user: {username, role}}`, or 401 `UNAUTHORIZED` "Wrong username or password." (same answer for an unknown user, a wrong password and a disabled account). `POST /api/auth/logout` (Bearer) → 204 and the session is revoked. `GET /api/auth/me` → `{username, roles, via}`.
- **New error code.** `FORBIDDEN` 403: signed in, but the role cannot use the route.
- **Health.** `GET /api/health` adds `env` (`development` | `production`) and `auth` (`passcode` | `accounts`).
- **Slot actions.** `start`, `done` and `not-served` answer 401 before looking up the slot when the caller sent no credential at all (it used to be 404 for an unknown slot id).
- **event_log.** Rows written by a signed-in account name it: `operator:asha`. Passcode actions stay `operator`.
- **Commands.** `python tasks.py create-user --username NAME --role operator|officer [--password-stdin]` (passwords at least 12 characters), `disable-user --username NAME` (also signs out every session), `list-users`, `openapi` (regenerates `docs/openapi.json`).
- **Frontend.** When `health.auth` is `accounts`, Desk, Intake and Officer show a username and password form, keep the session token in `sessionStorage`, and show "Sign out". Officer opens for `officer` or `operator`; Desk and Intake for `operator`. In development the screens open with the demo passcode as before.

### 15.4 Rate limits and lockout (A3)

- **New error code.** `RATE_LIMITED` 429, with a `Retry-After` header and `details.retry_after_s`.
- **Per address.** `POST /api/auth/login` and the three photo uploads are counted per client address in a 60-second sliding window, checked in middleware before the body is read.
- **Per username.** After `VAARI_LOGIN_LOCKOUT_FAILURES` wrong passwords within the window, the username is locked for `VAARI_LOGIN_LOCKOUT_MINUTES`, even for the right password. Unknown usernames get the same answer, so the response does not reveal which accounts exist. A successful sign-in clears the count. Locking a real account writes `event_log` `login_locked`.
- **Scope.** Counts live in memory in one server process and reset on restart. That fits one server at one centre.

### 15.5 Link expiry and revocation (A4)

- **Columns.** `machine.link_expires_at`, `machine.link_revoked_at`, `service_record.token_expires_at`, `service_record.token_revoked_at` (all datetime, null). A null expiry means "does not expire", so rows made before v0.2 keep working until rotated. New machines and new records always get an expiry.
- **New error code.** `LINK_EXPIRED` 410 with `details.reason` `expired` or `revoked`. Returned by `GET /api/driver/{machine_token}`, `GET /api/slots` with `X-Vaari-Machine-Token`, slot actions made with a slot token whose machine link is expired or off, `GET /api/records/{token}` and `.../verify`. Operators can still act on any slot.
- **New routes (operator).** `POST /api/machines/{id}/link/rotate` → `MachineOut` with a new token and expiry; the old link and every slot token it handed out for `scheduled` or `in_progress` slots stop working. `POST /api/machines/{id}/link/revoke` → `MachineOut`, link off now. `POST /api/slots/{id}/record/revoke` and `POST /api/slots/{id}/record/reissue` → `{slot_id, record_token, record_url, status, expires_at}`. Turning off or reissuing a record link never changes the record or its hash (the token is not hashed).
- **MachineOut** adds `driver_link_status` (`active` | `expired` | `revoked`) and `driver_link_expires_at`.
- **event_log.** `driver_link_rotated`, `driver_link_revoked`, `link_revoked`, `link_reissued`.

### 15.6 CORS and security headers (A5)

- **CORS.** Off unless `VAARI_CORS_ORIGINS` lists origins; then only those exact origins get `Access-Control-Allow-Origin`, without credentials (sessions use the `Authorization` header). Preflights from other origins get 400. Section 13's "one origin, so no CORS" stays the normal set-up.
- **Headers on every response.** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` (driver and record tokens are in URLs), `Permissions-Policy: camera=(self), geolocation=(self), microphone=(), payment=(), usb=()`, `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin`, and `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tile.openstreetmap.org; connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`. `/api` responses add `Cache-Control: no-store`. Production adds `Strict-Transport-Security: max-age=31536000; includeSubDomains`.

### 15.7 Migrations (B6)

- `migrations/versions/0001_baseline.py` is exactly the v0.1.0 schema. `0002_pilot_accounts_links.py` adds Part A's tables and columns. New schema changes get a new revision (`python tasks.py db-revision "message"`), never an edit to an old one.
- Start-up, `reset`, `seed`, `purge-images`, `create-user` and `migrate` all call `app.migrate.ensure_schema()`, which upgrades to head. A database made by `create_all` (no `alembic_version` table) is stamped with the revision its tables match (`0001` for v0.1.0, `0002` for a Part A build) and then upgraded, keeping its data.
- `python tasks.py migrate` upgrades; `migrate --status` prints the current and head revisions.
- A test checks that a fresh migration matches the models exactly (`alembic.autogenerate.compare_metadata` finds no difference), and the test suite's databases are built by the migrations.
- `reset` and `seed` refuse to run when `VAARI_ENV=production` unless given `--yes-delete-everything`.

### 15.8 Photo storage and metadata stripping (B7)

- **Interface.** `app/storage.PhotoStore` (`put`, `get`, `exists`, `delete`). `LocalDiskStore` keeps files under `VAARI_DATA_DIR/photos/` and `VAARI_DATA_DIR/register_pages/`, written atomically. `S3CompatibleStore` is a named placeholder that raises "not built"; `VAARI_PHOTO_STORE=s3` makes start-up refuse in every mode. Nothing outside `app/storage/` touches photo files.
- **Clean before saving.** Every uploaded image (start, done and register pages) is decoded, turned upright from its EXIF orientation, flattened to RGB and saved again as JPEG (quality 88) with no EXIF, GPS, XMP, ICC profile or comments. Images over 40 million pixels, and files that cannot be decoded, get 422 `VALIDATION_ERROR`. The same input always gives the same bytes.
- **Not additive (asked for by the brief).** `evidence.photo_sha256`, `evidence.photo_bytes` and `intake_page.image_sha256` are now of the *stored, cleaned* file, not the raw upload, so the stored file can always be checked against the record hash. Exact-duplicate detection (`exact_duplicate_photo`) compares these hashes, so it still catches the same photo sent twice. Stored names end in `.jpg`. `GET /api/intake/{id}/image` always returns `image/jpeg`. Response shapes are unchanged.

### 15.9 Backup and restore (B8)

- `python tasks.py backup [--out DIR] [--keep N]` writes `vaari-backup-<UTC time>/` with `vaari.sqlite` (SQLite online backup API, so it is safe while the server runs and includes writes still in the WAL), `photos/`, `register_pages/` and `manifest.json` (SHA-256 of every file, row counts, schema revision). The copy must pass `PRAGMA integrity_check` or the backup fails. `--keep N` removes all but the newest N.
- `python tasks.py restore DIR [--force] [--verify-only]` checks every hash, refuses extra or missing files, checks integrity, and only then moves the current database (and `-wal`/`-shm`) and photo folders aside as `*.pre-restore-<time>`, copies the backup in, and upgrades the schema to head. Without `--force` it refuses when a database already exists. Stop the server first.

### 15.10 Logs, request IDs and readiness (C9)

- **Logs.** One JSON object per line on stdout: `ts`, `level`, `logger`, `msg`, `request_id` (inside a request) and a fixed allow-list of fields (`event`, `method`, `route`, `status`, `duration_ms`, `env`, `auth`, `reader`, `revision`, `latency_ms`, `rows`, `ok`, `error_type`, `where`, ...). One `request` line per request with the **route template** (`/api/records/{token}`), never the real path or query string. Never logged: names, phone numbers, images, bodies, reader output. A filter masks anything shaped like a mobile number, a link token or a Bearer value. uvicorn's access log is off (it prints raw paths); `app/uvicorn_logging.json` makes uvicorn's own lines JSON too. `httpx` is held at WARNING because a hosted reader's URL can carry its key.
- **Request IDs.** Every response has `X-Request-ID`. A well-formed incoming one (8 to 64 of `A-Z a-z 0-9 . _ -`) is kept; anything else is replaced.
- **Unhandled errors** give 500 `{error_code: "INTERNAL_ERROR", message, details: {request_id}}` (new error code) and log only the exception type and code location, because database errors can quote personal values.
- **`GET /api/ready`** (public): 200 `{status: "ready", checks: {database, migrations, storage, reader}}` when the database answers, the schema is at head and the data folder is writable; otherwise 503 `NOT_READY` (new error code) with `details.checks`. A reader that is down does not make the server unready, because typing rows is the visible fallback.

### 15.11 Docker deployment (C10)

- `Dockerfile`: two stages (Node 22 builds `web/dist`; Python 3.12 runs it), user `vaari` (uid 10001), `VAARI_ENV=production`, data in `/data` (`VAARI_DB_PATH=/data/vaari.sqlite`, `VAARI_DATA_DIR=/data`, `VAARI_BACKUP_DIR=/data/backups`), `HEALTHCHECK` on `/api/ready`, uvicorn with `--no-access-log --log-config app/uvicorn_logging.json`. Base images can be swapped with `--build-arg PYTHON_IMAGE=... NODE_IMAGE=...`.
- `docker-compose.yml`: volume `vaari-data:/data`, `env_file: .env`, port bound to `127.0.0.1:8000`, read-only root filesystem, `no-new-privileges`, all capabilities dropped. `.env.production.example` is the starting `.env`.
- `docs/DEPLOY.md`: fresh clone to running server, accounts, HTTPS, links, backups, restore and upgrades.
- **Mock reader in production.** `MockRegisterReader` refuses when `VAARI_ENV=production`, because it returns the same invented rows for any photo. Register upload then gives 503 `READER_UNAVAILABLE` and keeps the photo, so staff type the rows beside it. `/api/health` reports `reader: "down"` in that case (an existing enum value).
- A start-up refusal is logged as one JSON line, `event: "refused_to_start"`, listing every problem.

### 15.12 CI (C11)

`.github/workflows/ci.yml` runs on every push and pull request: `ruff check .` (rules in `ruff.toml`: pycodestyle, pyflakes, bugbear, import order), pytest plus a check that unsafe production settings are refused, `pip-audit -r requirements.txt`, `npm audit --audit-level=high` (the two moderate react-router advisories are assessed in `notes/npm-audit.md`), the web build, the Playwright suite through `python tasks.py e2e` (both passes), and a Docker build with a smoke test (refuses without a secret, becomes healthy, runs as non-root, refuses the passcode). `web/playwright.config.ts` takes an optional `PLAYWRIGHT_CHROMIUM_EXECUTABLE` for machines with a preinstalled Chromium.

### 15.13 Register reader interface (Part 5)

- `app/intake/reader.py` defines `RegisterReader.read(image, media_type) -> RegisterDraft` and `get_reader()`. Nothing else in the app imports a concrete reader.
- **Implementations.** `mock` (default; refuses in production), `gemini_demo` (`app/intake/hosted.py`, Google Gemini, DEMO ONLY, off unless `VAARI_ALLOW_HOSTED_READER=true`), and `custom` (`app/intake/custom.py`, a stub client for a future model at `VAARI_CUSTOM_READER_URL`, optional `VAARI_CUSTOM_READER_TOKEN`). `VAARI_READER=hosted` is kept as an alias of `gemini_demo`.
- **No hard-coded model names.** The Gemini reader has no default model; `VAARI_VISION_MODEL` is required when it is on, and start-up refuses (any mode) without it or without `GEMINI_API_KEY`. The key is sent in the `x-goog-api-key` header, never in the URL. Error text keeps the HTTP status only, never the provider's body.
- **Anthropic provider removed** (the brief names Gemini for the demo). `VAARI_VISION_PROVIDER` accepts `gemini` only; `ANTHROPIC_API_KEY` is gone from `.env.example`.
- **Custom reader contract.** `POST` JSON `{image_base64, media_type, prompt_version, fields}` → the same `{rows: [{row, fields, confidence}]}` JSON as the hosted reader. `VAARI_READER=custom` needs the URL; production refuses a plain-`http://` URL unless it is on this machine or a private network. It is not treated as a third party.
- **Health.** `reader` may also be `custom` (additive enum value).
- **Start-up probe.** With `gemini_demo` switched on, or `custom`, start-up sends one synthetic 320×96 "VAARI PROBE" image through the reader in a background thread (`VAARI_READER_PROBE`, default `true`). `GET /api/health` adds `reader_detail` `{name, kind, provider, model, third_party, demo_only, probe: {status: not_run | pending | ok | failed, provider, model, latency_ms, checked_at, rows | error}}`. A failed probe makes `reader` report `down` until a real call succeeds.
- **Intake banner.** `/intake` always shows `#intake-privacy-banner`, naming the reader in use (`#intake-reader-name`) and where photos go (`#intake-reader-destination`): for `gemini_demo`, "Photos you upload here are sent to Google, a third party. Use synthetic pages only." (red); for `custom`, the host; for `mock`, "No photo leaves this server." When the reader is `down` it adds the type-the-rows fallback. `IntakeOut` adds `reader_name` and `third_party` (additive).
- **Preprocessing** (`app/intake/preprocess.py`) runs before every reader: EXIF orientation (applied when the upload is cleaned), an optional operator turn (`POST /api/intake/register-photo` adds form field `rotate`: 0, 90, 180 or 270 clockwise, else 422; applied to the stored page too), long side brought to 1000-2000 px (under 400 px left alone), greyscale and a 1% autocontrast stretch. The stored page keeps its colours; only the reader's copy is changed. The intake screen has a "Turn the photo before reading" choice (`#intake-rotate`).
- **Gurmukhi digits and mixed entries** (`app/intake/normalize.py`, used by `validate_row` for every reader and for typed rows). Gurmukhi (੦–੯) and Devanagari digits become 0–9 in phones, acres and dates. Phones: labels (ਫ਼ੋਨ:, Mob.), spaces, dashes, brackets and the danda are dropped; a leading +91, 91 or 0 is removed. Acres: unit words ਏਕੜ, ਕਿੱਲੇ/ਕਿੱਲਾ, acre(s), killa/kille are dropped; ½ ¼ ¾ and "2 1/2" are read; **kanal is converted at 8 kanal = 1 acre with a warning that highlights the cell but does not block** (new non-blocking issue text "acres: converted from N kanal (8 kanal = 1 acre), check the register"). Service: Gurmukhi and English words in any mix (ਸੁਪਰ seeder, Super ਸੀਡਰ, ਸੁਪਰਸੀਡਰ, ਬੇਲਰ (baler), S.S.). Dates: Punjabi and English month names ("੧੮ ਅਕਤੂਬਰ", "18 Oct", "Oct 18"). Names and villages are kept as written. Nothing is guessed: unreadable cells stay as written and are flagged.
