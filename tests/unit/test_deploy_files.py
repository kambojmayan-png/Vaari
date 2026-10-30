"""Static checks on the Docker deployment files (pilot item C10)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_dockerfile_runs_as_non_root_with_a_healthcheck():
    d = read("Dockerfile")
    user_lines = [ln for ln in d.splitlines() if ln.startswith("USER ")]
    assert user_lines and user_lines[-1].split()[1].split(":")[0] not in ("root", "0")
    assert "HEALTHCHECK" in d and "/api/ready" in d
    assert "VAARI_ENV=production" in d
    assert "--no-access-log" in d  # uvicorn's access log prints raw paths with tokens
    assert "COPY . " not in d and "COPY .env" not in d


def test_dockerignore_keeps_secrets_and_personal_data_out():
    ignored = set(read(".dockerignore").split())
    for must in (".env", "data/", "backups/", "*.sqlite", ".git", "tests/"):
        assert must in ignored, must


def test_compose_uses_a_volume_and_a_locked_down_container():
    c = read("docker-compose.yml")
    assert "vaari-data:/data" in c
    assert "read_only: true" in c and "no-new-privileges:true" in c and "- ALL" in c
    assert "127.0.0.1:8000:8000" in c
    assert "env_file: .env" in c


def test_production_example_has_no_secret_and_is_safe_by_default():
    env = dict(
        line.split("=", 1)
        for line in read(".env.production.example").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert env["VAARI_ENV"] == "production"
    assert env["VAARI_SECRET_KEY"] == ""
    assert env["VAARI_ALLOW_HOSTED_READER"] == "false"


def test_deploy_guide_covers_the_steps():
    g = read("docs/DEPLOY.md")
    for step in ("docker compose build", "docker compose up -d", "create-user", "/api/ready", "tasks.py backup", "tasks.py restore", "HTTPS"):
        assert step in g, step
