# Pilot build v0.2: verification log

Real output from the test run after each numbered item (summary lines pasted as printed). Environment: Linux, Python 3.13, Node 22.

| Item | Branch | Command | Result |
| --- | --- | --- | --- |
| Baseline (v0.1.0 + one later commit) | main | `python tasks.py test` / `e2e` / `smoke` | `137 passed` / `5 passed (18.9s)` / `1 passed` |
| A1 production mode | part-a-security | `python tasks.py test` | `152 passed, 1 warning in 6.84s` |
| A2 accounts and roles | part-a-security | `python tasks.py test` / `e2e` | `184 passed, 1 warning in 19.29s` / development pass `5 passed (19.0s)`, production pass `2 passed (3.3s)` |
| A3 rate limits and lockout | part-a-security | `python tasks.py test` | `192 passed, 1 warning in 24.83s` |
| A4 link expiry and revocation | part-a-security | `python tasks.py test` / `e2e` | `202 passed, 1 warning in 25.25s` / development `6 passed (20.1s)`, production `2 passed (3.3s)` |
| A5 CORS and security headers | part-a-security | `python tasks.py test` / `e2e` | `211 passed, 1 warning in 24.89s` / development `6 passed (20.7s)`, production `2 passed (3.5s)` |
| B6 Alembic migrations | part-b-data | `python tasks.py test` / `e2e` | `218 passed, 1 warning in 23.92s` / development `6 passed (20.8s)`, production `2 passed (3.5s)` |
| B7 photo storage and EXIF stripping | part-b-data | `python tasks.py test` / `e2e` | `235 passed, 1 warning in 27.04s` / development `6 passed (20.9s)`, production `2 passed (3.5s)` |
| B8 backup and restore | part-b-data | `python tasks.py test` | `245 passed, 1 warning in 28.13s` |
| C9 JSON logs, request IDs, /api/ready | part-c-ops | `python tasks.py test` / `e2e` | `254 passed, 1 warning in 28.63s` / development `6 passed (21.2s)`, production `2 passed (3.5s)` |
| C10 Docker deployment | part-c-ops | `python tasks.py test` + manual Docker run of DEPLOY.md steps 3-8 | `261 passed, 1 warning in 29.58s`; container `healthy`, `/api/ready` 200, uid 10001, restore round trip OK, refused with default secret |
| C11 CI (ruff, audits, e2e, Docker) | part-c-ops | `ruff check .` / `pytest` / `pip-audit` / `npm audit --audit-level=high` / `e2e` / Docker smoke | `All checks passed!` / `261 passed, 1 warning in 30.85s` / `No known vulnerabilities found` / exit 0 (2 moderate, assessed) / development `6 passed (21.8s)`, production `2 passed (3.6s)` / healthy, uid 10001, passcode 401 |
| R1 reader interface (mock, gemini_demo, custom stub) | part-5-reader | `python tasks.py test` | `278 passed, 1 warning in 30.35s` |
| R2 reader start-up probe in /api/health | part-5-reader | `python tasks.py test` | `283 passed, 1 warning in 31.04s` |
| R3 intake reader banner | part-5-reader | `python tasks.py test` / `e2e` | `284 passed, 1 warning in 32.16s` / development `8 passed (22.6s)`, production `2 passed (3.7s)` |
| R4 image preprocessing | part-5-reader | `python tasks.py test` / `e2e` | `296 passed, 1 warning in 30.02s` / development `8 passed (22.6s)`, production `2 passed (3.6s)` |
| R5 Gurmukhi digits and mixed entries | part-5-reader | `python tasks.py test` | `351 passed, 1 warning in 31.02s` |
| R6 strict JSON, per-field confidence | part-5-reader | `python tasks.py test` | `364 passed, 1 warning in 31.55s` |
| R7a reader pass bar + synthetic set (no eval run yet) | part-5-reader | `python tasks.py test` | `364 passed` (unchanged; docs and generator only) |
| R7b reader-eval per field, silent errors, READER_EVAL.md | part-5-reader | `python tasks.py test` / `reader-eval` (mock) | `372 passed, 1 warning in 31.44s` / mock: FAIL as expected (phone 0 of 48, silent phone 30 of 48; page1 5 of 6 phone) |
| R8 FUTURE_CUSTOM_READER.md | part-5-reader | `python tasks.py test` | `373 passed, 1 warning in 30.94s` |
| S1 FUTURE_SATELLITE.md | part-6-satellite-docs | `python tasks.py test` | `373 passed` (docs only) |
| S2 README/ROADMAP/ARCHITECTURE satellite status | part-6-satellite-docs | `python tasks.py test` | `376 passed, 1 warning in 30.89s` |
| Part 7 Definition of Done | part-7-handoff | `pytest` / `ruff` / web build / `smoke` / `e2e` / fresh-clone Docker per DEPLOY.md | `376 passed, 1 warning in 31.72s` / `All checks passed!` / `built` / `1 passed` / development `8 passed (22.4s)` + production `2 passed (3.7s)` / healthy, roles OK, passcode 401, EXIF stripped, backup+restore OK, refused with empty secret |
| Follow-ups: merge main 23aac6a, navbar Driver/Record pickers | part-8-followups | `pytest` / `e2e` | `380 passed` / development `11 passed`, production `2 passed` |
| CI e2e fix (VAARI_PYTHON for reset in specs) | part-9-ci-e2e-fix | `e2e` in a fresh clone, Python 3.12, no .venv, CI=true / `e2e` with .venv / `pytest` | before: `4 failed, 7 passed` (spawnSync .venv/bin/python ENOENT); after: development `11 passed`, production `2 passed`; with .venv same; `380 passed` |
