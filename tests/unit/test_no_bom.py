"""Test that no tracked files start with a UTF-8 BOM (Item 3)."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_no_tracked_files_have_utf8_bom():
    """Verify that every tracked file in git does not begin with the UTF-8 BOM."""
    res = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    assert tracked_files, "git ls-files returned no tracked files"

    bom_files = []
    for rel_path in tracked_files:
        full_path = ROOT / rel_path
        if not full_path.is_file():
            continue
        try:
            with open(full_path, "rb") as f:
                header = f.read(3)
                if header == b"\xef\xbb\xbf":
                    bom_files.append(rel_path)
        except OSError:
            pass

    assert not bom_files, (
        f"Found {len(bom_files)} tracked file(s) with UTF-8 BOM (\\xef\\xbb\\xbf):\n"
        + "\n".join(f"  - {f}" for f in bom_files)
    )
