#!/usr/bin/env python3
"""Cross-platform task runner for Vaari (Phase 1, 2, 3). Standard library only."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()


def get_venv_python() -> Path:
    """Return path to virtualenv python executable if .venv exists, else sys.executable."""
    if os.name == "nt":
        venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = ROOT / ".venv" / "bin" / "python"
    if venv_py.exists():
        return venv_py
    return Path(sys.executable)


def run_cmd(cmd: list[str], env: dict | None = None, cwd: Path = ROOT) -> int:
    """Run a subprocess command and return exit code."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    res = subprocess.run(cmd, cwd=cwd, env=merged_env)
    return res.returncode


def task_setup() -> int:
    """Create .venv if missing, install requirements.txt, web dependencies and playwright."""
    venv_dir = ROOT / ".venv"
    if not venv_dir.exists():
        print("Creating .venv...")
        import venv
        venv.create(venv_dir, with_pip=True)

    py = get_venv_python()
    print("Installing requirements.txt...")
    ret = run_cmd([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    if ret != 0:
        return ret
    ret = run_cmd([str(py), "-m", "pip", "install", "-r", "requirements.txt"])
    if ret != 0:
        return ret
    dev_req = ROOT / "requirements-dev.txt"
    if dev_req.exists():
        print("Installing requirements-dev.txt...")
        ret = run_cmd([str(py), "-m", "pip", "install", "-r", str(dev_req)])
        if ret != 0:
            return ret

    web_dir = ROOT / "web"
    if web_dir.exists() and (web_dir / "package.json").exists():
        print("Running npm install in web/...")
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        ret = run_cmd([npm_cmd, "install"], cwd=web_dir)
        if ret != 0:
            return ret
        print("Installing Playwright chromium...")
        npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
        run_cmd([npx_cmd, "playwright", "install", "chromium"], cwd=web_dir)
        print("Building web assets...")
        task_build_web()
    return 0


def task_build_web() -> int:
    """Run npm run build in web/."""
    web_dir = ROOT / "web"
    if not web_dir.exists():
        print("web/ directory does not exist")
        return 1
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    return run_cmd([npm_cmd, "run", "build"], cwd=web_dir)


def task_dev() -> int:
    """Run uvicorn with reload on 127.0.0.1:8000 and start Vite dev server."""
    py = get_venv_python()
    web_dir = ROOT / "web"
    if web_dir.exists() and (web_dir / "package.json").exists():
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        procs = []
        try:
            p_api = subprocess.Popen(
                [
                    str(py),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--reload",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                cwd=ROOT,
            )
            procs.append(p_api)
            p_web = subprocess.Popen(
                [npm_cmd, "run", "dev"],
                cwd=web_dir,
            )
            procs.append(p_web)
            for p in procs:
                p.wait()
        except KeyboardInterrupt:
            for p in procs:
                p.terminate()
        return 0
    return run_cmd(
        [str(py), "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"]
    )


def task_test(args: list[str]) -> int:
    """Run pytest -q (unit and API tests)."""
    py = get_venv_python()
    cmd = [str(py), "-m", "pytest", "-q"] + args
    return run_cmd(cmd)


def get_lan_ip() -> str:
    """Detect the local machine's primary LAN IP."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def get_driver_urls(base_url: str) -> list[tuple[str, str]]:
    """Retrieve machine names and driver URLs from the database."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from app.db import get_db
        from app.models import Machine
        with next(get_db()) as session:
            machines = (
                session.query(Machine)
                .filter(Machine.link_token.isnot(None))
                .order_by(Machine.id)
                .all()
            )
            return [(m.name, f"{base_url}/driver/{m.link_token}") for m in machines]
    except Exception:
        return []


def task_serve() -> int:
    """Build web assets and run uvicorn on 0.0.0.0:8000 serving API and frontend together."""
    task_build_web()

    lan_ip = get_lan_ip()
    local_url = "http://localhost:8000"
    lan_url = f"http://{lan_ip}:8000"

    print("\n" + "=" * 70, flush=True)
    print("  Vaari Operations Server (Serve Mode)", flush=True)
    print("=" * 70, flush=True)
    print(f"  Local URL:  {local_url}", flush=True)
    print(f"  LAN URL:    {lan_url}", flush=True)
    print("\n  Driver URLs (open on phone over LAN or HTTPS tunnel):", flush=True)

    driver_urls = get_driver_urls(lan_url)
    if driver_urls:
        for name, url in driver_urls:
            print(f"    - {name:<22}: {url}", flush=True)
    else:
        print("    (No machines found or database not initialized)", flush=True)
    print("=" * 70 + "\n", flush=True)
    sys.stdout.flush()

    py = get_venv_python()
    return run_cmd([str(py), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--log-config", "app/uvicorn_logging.json"])


def find_cloudflared() -> Path | None:
    """Find cloudflared executable in PATH, virtualenv, or standard directories."""
    import shutil
    cmd = shutil.which("cloudflared")
    if cmd:
        return Path(cmd)

    venv_cf = (
        ROOT
        / ".venv"
        / ("Scripts" if os.name == "nt" else "bin")
        / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    )
    if venv_cf.exists():
        return venv_cf

    if os.name == "nt":
        for pf in [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
        ]:
            candidate = Path(pf) / "cloudflared" / "cloudflared.exe"
            if candidate.exists():
                return candidate
    return None


def validate_tunnel_passcode(passcode: str | None) -> tuple[bool, str]:
    """Validate that VAARI_DEMO_PASSCODE is non-empty, not 'change-me', and at least 12 characters."""
    if not passcode or not passcode.strip():
        return False, "VAARI_DEMO_PASSCODE is empty. Set a strong passcode (at least 12 characters) in .env before running tunnel."
    val = passcode.strip()
    if val == "change-me":
        return False, "VAARI_DEMO_PASSCODE is still set to 'change-me'. Set a strong passcode (at least 12 characters) in .env before running tunnel."
    if len(val) < 12:
        return False, f"VAARI_DEMO_PASSCODE is too short ({len(val)} characters; minimum 12). Set a strong passcode in .env before running tunnel."
    return True, ""


def task_tunnel() -> int:
    """Run cloudflared tunnel to expose port 8000 over HTTPS, or print installation steps."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    passcode = os.environ.get("VAARI_DEMO_PASSCODE", "")
    valid, err_msg = validate_tunnel_passcode(passcode)
    if not valid:
        print("\n" + "=" * 70)
        print("  Tunnel Refused: Insecure Passcode")
        print("=" * 70)
        print(f"  {err_msg}")
        print("=" * 70 + "\n")
        return 1

    cf = find_cloudflared()
    if not cf:
        print("\n" + "=" * 70)
        print("  cloudflared is not installed")
        print("=" * 70)
        print("To install cloudflared:")
        print("  Windows: winget install --id Cloudflare.cloudflared")
        print("  macOS:   brew install cloudflared")
        print("  Linux:   curl -L --output cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64")
        print("=" * 70 + "\n")
        return 1

    print(f"Starting Cloudflare Quick Tunnel using: {cf}")
    import re
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    proc = subprocess.Popen(
        [str(cf), "tunnel", "--url", "http://localhost:8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    url_found = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if not url_found:
                match = url_pattern.search(line)
                if match:
                    url = match.group(0)
                    url_found = True
                    print("\n" + "=" * 70)
                    print("  Cloudflare Quick Tunnel Connected!")
                    print(f"  Public HTTPS URL: {url}")
                    print("=" * 70 + "\n")
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


def task_check_config() -> int:
    """Print every unsafe setting for the current VAARI_ENV and exit non-zero if any."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.config import settings
    from app.startup_checks import config_problems

    problems = config_problems(settings)
    if problems:
        print(f"Unsafe settings for VAARI_ENV={settings.env}:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"Settings are safe for VAARI_ENV={settings.env}.")
    return 0


def task_openapi() -> int:
    """Regenerate docs/openapi.json from the live app (LF line endings)."""
    import json
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.main import app

    out = ROOT / "docs" / "openapi.json"
    out.write_bytes((json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"Wrote {out.relative_to(ROOT)} ({len(app.openapi()['paths'])} paths)")
    return 0


def task_migrate(args: list[str]) -> int:
    """Upgrade the database to the newest migration, or show the current revision (--status)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.config import settings
    from app.migrate import current_revision, ensure_schema, head_revision

    if "--status" in args:
        print(f"Database: {settings.db_path}")
        print(f"Current revision: {current_revision()}  Head: {head_revision()}")
        return 0
    rev = ensure_schema()
    print(f"Database {settings.db_path} is at revision {rev}.")
    return 0


def task_db_revision(args: list[str]) -> int:
    """Autogenerate a new migration from model changes: python tasks.py db-revision "message"."""
    if not args:
        print('Usage: python tasks.py db-revision "short message"')
        return 1
    py = get_venv_python()
    return run_cmd([str(py), "-m", "alembic", "revision", "--autogenerate", "-m", " ".join(args)])


def task_backup(args: list[str]) -> int:
    """Online backup of the database and photos: python tasks.py backup [--out DIR] [--keep N]."""
    import argparse
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.backup import BackupError, create_backup, prune_backups
    from app.config import settings

    parser = argparse.ArgumentParser(prog="tasks.py backup")
    parser.add_argument("--out", default=settings.backup_dir)
    parser.add_argument("--keep", type=int, default=0, help="keep only the newest N backups")
    a = parser.parse_args(args)
    try:
        path = create_backup(Path(settings.db_path), Path(settings.data_dir), Path(a.out))
    except BackupError as exc:
        print(f"Backup failed: {exc}")
        return 1
    print(f"Backup written and verified: {path}")
    if a.keep:
        for old in prune_backups(Path(a.out), a.keep):
            print(f"Removed old backup: {old}")
    return 0


def task_restore(args: list[str]) -> int:
    """Restore a backup folder: python tasks.py restore BACKUP_DIR [--force]. Stop the server first."""
    import argparse
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.backup import BackupError, restore_backup, verify_backup
    from app.config import settings

    parser = argparse.ArgumentParser(prog="tasks.py restore")
    parser.add_argument("backup_dir")
    parser.add_argument("--force", action="store_true", help="replace an existing database")
    parser.add_argument("--verify-only", action="store_true", help="check the backup and change nothing")
    a = parser.parse_args(args)
    try:
        if a.verify_only:
            m = verify_backup(Path(a.backup_dir))
            print(f"Backup is complete and undamaged ({len(m['files'])} files, made {m['created_at']}).")
            return 0
        summary = restore_backup(Path(a.backup_dir), Path(settings.db_path), Path(settings.data_dir), force=a.force)
    except BackupError as exc:
        print(f"Restore refused: {exc}")
        return 1
    print(f"Restored {summary['restored_from']} (made {summary['backup_created_at']}).")
    print(f"Schema revision: {summary['schema_revision']}. Requests: {summary['row_counts'].get('request', 0)}.")
    for k in summary["kept_previous"]:
        print(f"Previous data kept at: {k}")
    return 0


def task_seed() -> int:
    """Load seed data into an existing database."""
    py = get_venv_python()
    return run_cmd([str(py), "-m", "app.seed.seed"])


def task_reset() -> int:
    """Delete database, photos, register pages, create tables, seed, run scheduler."""
    py = get_venv_python()
    return run_cmd([str(py), "-m", "app.seed.seed", "--reset"])


def task_smoke() -> int:
    """Run the smoke test."""
    py = get_venv_python()
    return run_cmd([str(py), "-m", "pytest", "-q", "tests/api/test_smoke.py"])


def task_reader_eval() -> int:
    """Run the configured reader on examples/register_pages/ and print counts."""
    py = get_venv_python()
    return run_cmd([str(py), "-m", "app.intake.eval"])


def task_purge_images(args: list[str]) -> int:
    """Delete register page images past image_delete_after."""
    dry_run = "--dry-run" in args
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.db import get_session_factory
    from app.migrate import ensure_schema
    from app.routes.intake import purge_expired_register_images

    ensure_schema()
    sf = get_session_factory()
    with sf() as session:
        deleted = purge_expired_register_images(session, dry_run=dry_run)
    prefix = "[DRY RUN] Would delete" if dry_run else "Deleted"
    if deleted:
        for p in deleted:
            print(f"{prefix}: {p}")
    else:
        print(f"{prefix}: 0 expired register images.")
    return 0


def task_screenshots() -> int:
    """Capture demo screenshots via Playwright into docs/screenshots/."""
    return task_e2e(["e2e/screenshots.spec.ts"])


E2E_PRODUCTION_SPEC = "e2e/production_login.spec.ts"
E2E_USERS = {
    # Synthetic test accounts, created only inside the temporary e2e database.
    "e2e-operator": ("operator", "e2e-operator-password-1"),
    "e2e-officer": ("officer", "e2e-officer-password-1"),
}


def _free_port(preferred: int = 8000) -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
        s2.bind(("127.0.0.1", 0))
        return s2.getsockname()[1]


def _stop(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _run_e2e_pass(mode: str, spec_args: list[str]) -> int:
    """Reset a temporary database, start the server in `mode`, run Playwright, stop the server."""
    import tempfile
    import time
    import urllib.request

    port = _free_port()
    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    data_dir = temp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["VAARI_DB_PATH"] = str(temp_path / "vaari_e2e.sqlite")
    env["VAARI_DATA_DIR"] = str(data_dir)
    env["VAARI_DEMO_PASSCODE"] = "change-me"
    env["VAARI_PUBLIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    env["VAARI_READER"] = "mock"
    env["VAARI_ALLOW_HOSTED_READER"] = "false"
    if mode == "production":
        import secrets

        env["VAARI_ENV"] = "production"
        env["VAARI_SECRET_KEY"] = secrets.token_urlsafe(48)
    else:
        env["VAARI_ENV"] = "development"

    py = get_venv_python()
    try:
        print(f"[{mode}] Initializing temporary database...")
        reset_cmd = [str(py), "-m", "app.seed.seed", "--reset"]
        if mode == "production":
            reset_cmd.append("--yes-delete-everything")  # a throwaway temporary database
        ret = run_cmd(reset_cmd, env=env)
        if ret != 0:
            print("Failed to initialize temporary database.")
            return ret
        if mode == "production":
            for username, (role, password) in E2E_USERS.items():
                res = subprocess.run(
                    [str(py), "tasks.py", "create-user", "--username", username, "--role", role, "--password-stdin"],
                    cwd=ROOT, env=env, input=password + "\n", text=True,
                )
                if res.returncode != 0:
                    return res.returncode

        print(f"[{mode}] Starting test server on http://127.0.0.1:{port}...")
        server_proc = subprocess.Popen(
            [str(py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            ready = False
            t0 = time.time()
            while time.time() - t0 < 20:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
                        if resp.status == 200:
                            ready = True
                            break
                except Exception:
                    time.sleep(0.2)
            if not ready:
                print("Test server failed to start within 20s.")
                return 1

            print(f"[{mode}] Server ready! Running Playwright tests...")
            playwright_env = env.copy()
            playwright_env["BASE_URL"] = f"http://127.0.0.1:{port}"
            playwright_env["VAARI_E2E_MODE"] = mode
            playwright_env["VAARI_PYTHON"] = str(py)  # specs that reset the database use this Python
            npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
            return run_cmd([npx_cmd, "playwright", "test"] + spec_args, env=playwright_env, cwd=ROOT / "web")
        finally:
            print(f"[{mode}] Stopping test server...")
            _stop(server_proc)
    finally:
        temp_dir.cleanup()


def task_e2e(args: list[str]) -> int:
    """Run Playwright end-to-end tests against freshly reset temporary databases.

    With no arguments: a development-mode pass (every spec) and then a
    production-mode pass (sign-in with accounts). With arguments, only a
    development pass with those Playwright arguments.
    """
    print("Building web application for serve mode...")
    task_build_web()

    fixtures_dir = ROOT / "tests" / "fixtures"
    start_fix = fixtures_dir / "start_field.jpg"
    done_fix = fixtures_dir / "done_field.jpg"
    reg_fix = fixtures_dir / "register_page.jpg"
    if not start_fix.exists() or not done_fix.exists() or not reg_fix.exists():
        from tests.fixtures.synthetic_photos import TINY_JPEG
        start_jpg = TINY_JPEG[:20] + b"\xff\xfe\x00\x07START" + TINY_JPEG[20:]
        done_jpg = TINY_JPEG[:20] + b"\xff\xfe\x00\x06DONE" + TINY_JPEG[20:]
        reg_jpg = TINY_JPEG[:20] + b"\xff\xfe\x00\x08REGISTER" + TINY_JPEG[20:]
        start_fix.write_bytes(start_jpg)
        done_fix.write_bytes(done_jpg)
        reg_fix.write_bytes(reg_jpg)

    dev_code = _run_e2e_pass("development", args)
    if args:
        return dev_code
    prod_code = _run_e2e_pass("production", [E2E_PRODUCTION_SPEC])
    print(f"e2e summary: development pass exit {dev_code}, production pass exit {prod_code}")
    return dev_code or prod_code


def main():
    if len(sys.argv) < 2:
        print("Usage: python tasks.py <task> [args]")
        print(
            "Available tasks: setup, dev, test, seed, reset, smoke, serve, tunnel, "
            "build-web, e2e, reader-eval, purge-images, screenshots, check-config, "
            "create-user, disable-user, list-users, openapi, migrate, db-revision, backup, restore"
        )
        sys.exit(1)

    task = sys.argv[1]
    extra_args = sys.argv[2:]

    if task == "setup":
        sys.exit(task_setup())
    elif task == "dev":
        sys.exit(task_dev())
    elif task == "test":
        sys.exit(task_test(extra_args))
    elif task == "serve":
        sys.exit(task_serve())
    elif task == "seed":
        sys.exit(task_seed())
    elif task == "reset":
        sys.exit(task_reset())
    elif task == "smoke":
        sys.exit(task_smoke())
    elif task == "build-web":
        sys.exit(task_build_web())
    elif task == "tunnel":
        sys.exit(task_tunnel())
    elif task == "e2e":
        sys.exit(task_e2e(extra_args))
    elif task == "reader-eval":
        sys.exit(task_reader_eval())
    elif task == "purge-images":
        sys.exit(task_purge_images(extra_args))
    elif task in ("create-user", "disable-user", "list-users"):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from app.cli_users import main as users_main
        sys.exit(users_main([task] + extra_args))
    elif task == "backup":
        sys.exit(task_backup(extra_args))
    elif task == "restore":
        sys.exit(task_restore(extra_args))
    elif task == "migrate":
        sys.exit(task_migrate(extra_args))
    elif task == "db-revision":
        sys.exit(task_db_revision(extra_args))
    elif task == "openapi":
        sys.exit(task_openapi())
    elif task == "check-config":
        sys.exit(task_check_config())
    elif task == "screenshots":
        sys.exit(task_screenshots())
    else:
        print(f"Unknown task: {task}")
        sys.exit(1)


if __name__ == "__main__":
    main()
