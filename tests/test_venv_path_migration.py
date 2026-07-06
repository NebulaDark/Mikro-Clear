import subprocess
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
OLD_VENV = "/opt/" + "mikrocata" + "-venv"
NEW_VENV = "/opt/mikroclear-venv"


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


class VenvPathMigrationTests(TestCase):
    def test_old_mikrocata_venv_path_is_not_in_tracked_files(self):
        matches: list[str] = []
        for path in tracked_files():
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if OLD_VENV in text:
                matches.append(str(path.relative_to(ROOT)))

        self.assertEqual(matches, [])

    def test_systemd_units_use_mikroclear_venv(self):
        production = (ROOT / "systemd" / "mikroclear.service").read_text(encoding="utf-8")
        candidate = (ROOT / "deploy" / "systemd" / "mikroclear.service.candidate").read_text(encoding="utf-8")

        self.assertIn(f"ExecStart={NEW_VENV}/bin/python -m mikroclear", production)
        self.assertIn(f"ExecStart={NEW_VENV}/bin/python -m mikroclear", candidate)
