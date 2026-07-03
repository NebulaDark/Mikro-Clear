#!/usr/bin/env python3
import difflib
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mikroclear-selks")
SERVICE_NAME = "mikroclear.service"
LEGACY_SERVICE_NAME = "mikrocataTZSP0.service"
SELKS_HOST = os.getenv("MIKROCLEAR_MCP_SSH_HOST") or os.getenv("MIKROCATA_MCP_SSH_HOST", "selks")
SSH_COMMAND = shlex.split(
    os.getenv("MIKROCLEAR_MCP_SSH_COMMAND")
    or os.getenv(
        "MIKROCATA_MCP_SSH_COMMAND",
        "ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new",
    )
)
REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_SCRIPT = REPO_ROOT / "src" / "mikroclear" / "legacy.py"
LOCAL_UNIT = REPO_ROOT / "systemd" / "mikroclear.service"
REMOTE_SCRIPT = "/usr/local/bin/mikroclear.py"
LEGACY_REMOTE_SCRIPT = "/usr/local/bin/mikrocataTZSP0.py"
CANDIDATE_DIR = "/var/tmp/mikroclear-deploy"
CANDIDATE_SCRIPT = f"{CANDIDATE_DIR}/mikroclear.py.codex-candidate"
REMOTE_UNIT = "/etc/systemd/system/mikroclear.service"
CANDIDATE_UNIT = f"{CANDIDATE_DIR}/mikroclear-codex.service"
MASK_ENV_HELPER = "/usr/local/sbin/mikroclear-mask-env"
SURICATA_EVE_JSON = "/opt/SELKS/docker/containers-data/suricata/logs/eve.json"


def _fixed_size(value: int, allowed: tuple[int, ...]) -> int:
    requested = int(value)
    for size in allowed:
        if requested <= size:
            return size
    return allowed[-1]


def run_ssh(command: str, timeout: int = 30, stdin: str | None = None) -> str:
    result = subprocess.run(
        [*SSH_COMMAND, SELKS_HOST, command],
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    output = result.stdout or ""

    if result.stderr:
        output += "\nSTDERR:\n" + result.stderr

    if result.returncode != 0:
        output += f"\nRETURN_CODE: {result.returncode}"

    return output.strip()


@mcp.tool()
def status_mikroclear() -> str:
    return run_ssh(f"systemctl status {SERVICE_NAME} --no-pager", 20)


@mcp.tool()
def status_mikrocata() -> str:
    return status_mikroclear()


@mcp.tool()
def restart_mikroclear(confirm: bool = False) -> str:
    if not confirm:
        return "Refusing to restart service without confirm=True."
    return run_ssh(
        f"sudo -n /usr/bin/systemctl restart {SERVICE_NAME} && "
        f"sudo -n /usr/bin/systemctl status {SERVICE_NAME} --no-pager",
        40,
    )


@mcp.tool()
def restart_mikrocata(confirm: bool = False) -> str:
    return restart_mikroclear(confirm)


@mcp.tool()
def tail_mikroclear_logs(lines: int = 100) -> str:
    lines = _fixed_size(lines, (100, 300, 500))
    return run_ssh(f"sudo -n journalctl -u {SERVICE_NAME} -n {lines} --no-pager", 30)


@mcp.tool()
def tail_mikrocata_logs(lines: int = 100) -> str:
    return tail_mikroclear_logs(lines)


@mcp.tool()
def check_mikroclear_syntax() -> str:
    return run_ssh(
        "/opt/mikrocata-venv/bin/python -c "
        f"\"path='{REMOTE_SCRIPT}'; "
        "compile(open(path, encoding='utf-8').read(), path, 'exec'); "
        "print('OK')\"",
        30,
    )


@mcp.tool()
def check_mikrocata_syntax() -> str:
    return check_mikroclear_syntax()


@mcp.tool()
def read_mikroclear_env() -> str:
    return run_ssh(
        r"if [ -f /etc/mikroclear/mikroclear.env ]; then "
        rf"sudo -n {MASK_ENV_HELPER} /etc/mikroclear/mikroclear.env; "
        r"else "
        rf"sudo -n {MASK_ENV_HELPER} /etc/mikrocata/mikrocataTZSP0.env; "
        r"fi",
        20,
    )


@mcp.tool()
def read_mikrocata_env() -> str:
    return read_mikroclear_env()


@mcp.tool()
def tail_suricata_eve(lines: int = 20) -> str:
    lines = _fixed_size(lines, (20, 50, 100))
    return run_ssh(
        f"sudo -n tail -n {lines} {SURICATA_EVE_JSON}",
        30,
    )


@mcp.tool()
def compare_production_script() -> dict[str, Any]:
    local_text = LOCAL_SCRIPT.read_text(encoding="utf-8")
    remote_text = run_ssh(f"cat {REMOTE_SCRIPT}", 30)
    diff = "\n".join(
        difflib.unified_diff(
            remote_text.splitlines(),
            local_text.splitlines(),
            fromfile=REMOTE_SCRIPT,
            tofile=str(LOCAL_SCRIPT),
            lineterm="",
        )
    )
    return {"matches": local_text.strip() == remote_text.strip(), "diff": diff}


@mcp.tool()
def upload_candidate_script() -> str:
    local_text = LOCAL_SCRIPT.read_text(encoding="utf-8")
    return run_ssh(
        f"/usr/bin/install -d -m 700 {CANDIDATE_DIR} && "
        f"cat > {CANDIDATE_SCRIPT} && "
        f"chmod 600 {CANDIDATE_SCRIPT} && "
        f"/opt/mikrocata-venv/bin/python -c \"path='{CANDIDATE_SCRIPT}'; "
        "compile(open(path, encoding='utf-8').read(), path, 'exec'); print('OK')\" && "
        f"stat -c '%U:%G %a %s %y %n' {CANDIDATE_SCRIPT}",
        30,
        stdin=local_text,
    )


@mcp.tool()
def deploy_candidate_script(confirm: bool = False) -> str:
    if not confirm:
        return "Refusing to deploy candidate without confirm=True."
    return run_ssh(
        f"backup={REMOTE_SCRIPT}.bak-$(date +%Y%m%d-%H%M%S) && "
        f"legacy_backup={LEGACY_REMOTE_SCRIPT}.bak-mikroclear-$(date +%Y%m%d-%H%M%S) && "
        f"if [ -f {REMOTE_SCRIPT} ]; then "
        f"sudo -n cp {REMOTE_SCRIPT} \"$backup\"; "
        f"elif [ -f {LEGACY_REMOTE_SCRIPT} ]; then "
        f"sudo -n cp {LEGACY_REMOTE_SCRIPT} \"$legacy_backup\"; "
        "fi && "
        f"sudo -n install -o root -g root -m 755 {CANDIDATE_SCRIPT} {REMOTE_SCRIPT} && "
        "/opt/mikrocata-venv/bin/python -c "
        f"\"path='{REMOTE_SCRIPT}'; compile(open(path, encoding='utf-8').read(), path, 'exec'); print('OK')\" && "
        f"sudo -n systemctl restart {SERVICE_NAME} && "
        f"systemctl status {SERVICE_NAME} --no-pager --lines=20 && "
        "printf '\\nBACKUP=%s\\nLEGACY_BACKUP=%s\\n' \"$backup\" \"$legacy_backup\"",
        60,
    )


@mcp.tool()
def upload_unit_candidate() -> str:
    unit_text = LOCAL_UNIT.read_text(encoding="utf-8")
    return run_ssh(
        f"/usr/bin/install -d -m 700 {CANDIDATE_DIR} && "
        f"cat > {CANDIDATE_UNIT} && "
        f"chmod 600 {CANDIDATE_UNIT} && "
        f"stat -c '%U:%G %a %s %y %n' {CANDIDATE_UNIT} && "
        f"/usr/bin/systemd-analyze verify {CANDIDATE_UNIT}",
        30,
        stdin=unit_text,
    )


@mcp.tool()
def verify_systemd_unit() -> str:
    return run_ssh(f"sudo -n /usr/bin/systemd-analyze verify {REMOTE_UNIT}", 30)


@mcp.tool()
def daemon_reload(confirm: bool = False) -> str:
    if not confirm:
        return "Refusing to run daemon-reload without confirm=True."
    return run_ssh("sudo -n /usr/bin/systemctl daemon-reload", 20)


@mcp.tool()
def deploy_unit_candidate(confirm: bool = False) -> str:
    if not confirm:
        return "Refusing to deploy unit candidate without confirm=True."
    return run_ssh(
        f"sudo -n /usr/bin/install -o root -g root -m 644 {CANDIDATE_UNIT} {REMOTE_UNIT} && "
        "sudo -n /usr/bin/systemctl daemon-reload && "
        f"sudo -n /usr/bin/systemd-analyze verify {REMOTE_UNIT} && "
        f"(sudo -n /usr/bin/systemctl stop {LEGACY_SERVICE_NAME} || true) && "
        f"(sudo -n /usr/bin/systemctl disable {LEGACY_SERVICE_NAME} || true) && "
        f"sudo -n /usr/bin/systemctl enable {SERVICE_NAME} && "
        f"sudo -n /usr/bin/systemctl restart {SERVICE_NAME} && "
        f"sudo -n /usr/bin/systemctl status {SERVICE_NAME} --no-pager --lines=20",
        60,
    )


@mcp.tool()
def status_legacy_mikrocata() -> str:
    return run_ssh(f"systemctl status {LEGACY_SERVICE_NAME} --no-pager", 20)


if __name__ == "__main__":
    mcp.run()
