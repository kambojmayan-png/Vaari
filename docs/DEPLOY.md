# Deploying Vaari for one hiring centre (pilot v0.2)

This guide takes a fresh clone to a running server with Docker. It is written for one server at one centre. Every command is run from the repository folder unless it says otherwise.

What you get: one container that serves the API and the web app on port 8000, runs as a non-root user with a read-only filesystem, keeps the database and photos in a Docker volume, refuses to start with unsafe settings, and reports its health at `/api/ready`.

## 1. What you need

- A Linux machine (2 GB RAM, 10 GB disk is plenty) with Docker Engine 24 or newer and the Compose plugin (`docker compose version`).
- A domain name pointing at the machine, for HTTPS (step 6). Phones only allow the camera and GPS on HTTPS pages.
- `git`.

## 2. Get the code

```bash
git clone https://github.com/kambojmayan-png/Vaari.git vaari
cd vaari
```

## 3. Write the settings

```bash
cp .env.production.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste the output as VAARI_SECRET_KEY
```

Edit `.env`: set `VAARI_SECRET_KEY`, the centre's name, phone and position, and `VAARI_PUBLIC_BASE_URL` (the `https://` address people will open). Keep `.env` private: it is in `.gitignore` and `.dockerignore`.

The server **refuses to start** in production mode if:

- `VAARI_SECRET_KEY` is empty, a default, or shorter than 32 characters;
- a hosted register reader is turned on without `VAARI_ALLOW_HOSTED_READER_IN_PRODUCTION=true` (the hosted reader sends register photos to a third party and is for demonstration only);
- `VAARI_CORS_ORIGINS` contains `*` or a plain `http://` origin;
- `VAARI_PHOTO_STORE` is anything but `local`.

It prints every problem at once, as one log line with `"event": "refused_to_start"`; with `restart: unless-stopped` the container then keeps restarting and never becomes healthy until the setting is fixed. You can check without starting anything:

```bash
docker compose run --rm vaari python tasks.py check-config
```

In production the shared demo passcode is switched off. Staff sign in with their own accounts (step 5).

## 4. Build and start

```bash
docker compose build
docker compose up -d
docker compose ps            # STATUS should become "healthy" within about 30 seconds
curl -s http://127.0.0.1:8000/api/ready
```

`/api/ready` answers `{"status": "ready", "checks": {"database": "ok", "migrations": "ok", "storage": "ok", "reader": ...}}`. On first start the database is created by the migrations. On later starts, and after upgrades, the migrations bring it up to date on their own.

Logs are JSON, one line per event, with a `request_id` that matches the `X-Request-ID` response header:

```bash
docker compose logs -f vaari
```

They never contain names, phone numbers, tokens, photos or reader output.

## 5. Create the staff accounts

There are two roles. **operator**: the Desk, register intake, machines, driver links and records. **officer**: the Officer dashboard, usage export and will-miss list, with no phone numbers and no driver links.

```bash
docker compose exec vaari python tasks.py create-user --username asha --role operator
docker compose exec vaari python tasks.py create-user --username ravi --role officer
docker compose exec vaari python tasks.py list-users
```

You are asked for the password twice (at least 12 characters). From a script, pipe it in with `--password-stdin`. When someone leaves:

```bash
docker compose exec vaari python tasks.py disable-user --username ravi   # also signs out every session
```

After 5 wrong passwords a username is locked for 15 minutes, and each address may try 10 sign-ins a minute.

## 6. Put HTTPS in front

The container listens only on `127.0.0.1:8000`. Put a reverse proxy with a certificate in front of it. With [Caddy](https://caddyserver.com/) installed on the machine, this whole `Caddyfile` gets and renews a certificate for you:

```
vaari.example.org {
    reverse_proxy 127.0.0.1:8000
}
```

Then set `VAARI_TRUST_PROXY=true` in `.env` (so rate limits see each phone's address, not the proxy's) and `docker compose up -d` again. Without a domain, `python tasks.py tunnel` (a Cloudflare quick tunnel) works for a trial, but its address changes every time.

The app already sends HSTS, a Content-Security-Policy, `Referrer-Policy: no-referrer` and the other standard headers. It needs no CORS: the web app and API share one origin.

## 7. Driver and record links

Each machine's driver link is on the Desk, under Machines. Links last 30 days (`VAARI_DRIVER_LINK_DAYS`). If a phone is lost or a driver leaves, press **Turn off link**. **New link** issues a fresh one, and the old link and its job links stop working at once. A farmer's record link lasts 365 days (`VAARI_RECORD_LINK_DAYS`). It can be turned off or reissued from the request's panel. That never changes the record or its hash.

## 8. Backups

Make a backup while the server runs (SQLite's online backup, plus every photo, with a SHA-256 manifest):

```bash
docker compose exec vaari python tasks.py backup --keep 14
docker compose cp vaari:/data/backups ./backups-copy      # then copy this OFF the machine
```

A backup in the same volume does not survive a disk failure, so copy it somewhere else every day. A cron line on the host:

```cron
15 2 * * * cd /srv/vaari && docker compose exec -T vaari python tasks.py backup --keep 14 && docker compose cp vaari:/data/backups /srv/vaari-backups
```

Backups hold personal data (phone numbers, photos). Store them encrypted, or on a disk only the centre can reach.

To **restore**, stop the server first, check the backup, then restore it:

```bash
docker compose stop vaari
docker compose run --rm vaari python tasks.py restore /data/backups/vaari-backup-20261030T021500Z --verify-only
docker compose run --rm vaari python tasks.py restore /data/backups/vaari-backup-20261030T021500Z --force
docker compose up -d
```

Restore refuses a damaged backup (any hash mismatch, missing or extra file, or failed integrity check) and changes nothing. Otherwise it keeps the current database and photos beside the originals as `*.pre-restore-<time>` and upgrades an older backup to the current schema. To restore a backup copied from elsewhere, copy it into the volume first: `docker compose cp ./vaari-backup-... vaari:/data/backups/`.

## 9. Upgrading

```bash
docker compose exec vaari python tasks.py backup
git pull
docker compose build
docker compose up -d          # migrations run at start-up
docker compose exec vaari python tasks.py migrate --status
```

## 10. Register reader

In production, leave `VAARI_READER=mock`. The mock reader refuses to run in production, because it would invent rows. So the intake screen keeps the photo and staff type the rows beside it: that is the visible fallback. The Gemini reader is for demonstrations on synthetic pages only (see `docs/READER_EVAL.md`). A custom reader that runs on infrastructure you control is planned (`docs/FUTURE_CUSTOM_READER.md`).

## 11. Limits of this set-up

- One container, one SQLite file. Rate-limit and lockout counts are in memory and reset on restart; with more than one server process each would keep its own counts.
- Photos are on local disk in the Docker volume. An S3-compatible store is designed for (`app/storage`), not built.
- No error-tracking service. Alert on log lines with `"event": "unhandled_error"`.
- WhatsApp Business API, an offline driver queue and Postgres are not built.
