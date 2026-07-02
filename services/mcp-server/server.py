#!/usr/bin/env python3
import difflib
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mikroclear-selks")
SELKS_HOST = os.getenv("MIKROCATA_MCP_SSH_HOST", "selks")
SSH_COMMAND = shlex.split(
    os.getenv(
        "MIKROCATA_MCP_SSH_COMMAND",
        "ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new",
    )
)
REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_SCRIPT = REPO_ROOT / "src" / "mikrocata" / "legacy.py"
LOCAL_UNIT = REPO_ROOT / "systemd" / "mikrocataTZSP0.service"
REMOTE_SCRIPT = "/usr/local/bin/mikrocataTZSP0.py"
CANDIDATE_SCRIPT = "/tmp/mikrocataTZSP0.py.codex-candidate"
REMOTE_UNIT = "/etc/systemd/system/mikrocataTZSP0.service"
CANDIDATE_UNIT = "/tmp/mikrocataTZSP0-codex.service"


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
def status_mikrocata() -> str:
    return run_ssh("systemctl status mikrocataTZSP0.service --no-pager", 20)


@mcp.tool()
def restart_mikrocata(confirm: bool = False) -> str:
    if not confirm:
        return "Refusing to restart service without confirm=True."
    return run_ssh(
        "sudo -n systemctl restart mikrocataTZSP0.service && "
        "sudo -n systemctl status mikrocataTZSP0.service --no-pager",
        40,
    )


@mcp.tool()
def tail_mikrocata_logs(lines: int = 100) -> str:
    lines = max(10, min(int(lines), 500))
    return run_ssh(f"sudo -n journalctl -u mikrocataTZSP0.service -n {lines} --no-pager", 30)


@mcp.tool()
def check_mikrocata_syntax() -> str:
    return run_ssh(
        "/opt/mikrocata-venv/bin/python -c "
        f"\"path='{REMOTE_SCRIPT}'; "
        "compile(open(path, encoding='utf-8').read(), path, 'exec'); "
        "print('OK')\"",
        30,
    )


@mcp.tool()
def read_mikrocata_env() -> str:
    return run_ssh(
        r"sudo -n sed -E 's/(TOKEN|PASSWORD|PASS|SECRET|KEY|AUTH|COOKIE)=.*/\1=***MASKED***/Ig' "
        r"/etc/mikrocata/mikrocataTZSP0.env",
        20,
    )


@mcp.tool()
def tail_suricata_eve(lines: int = 20) -> str:
    lines = max(5, min(int(lines), 100))
    return run_ssh(
        f"sudo -n tail -n {lines} "
        "/opt/SELKS/docker/containers-data/suricata/logs/eve.json",
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
        f"cat > {CANDIDATE_SCRIPT} && "
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
        f"sudo -n cp {REMOTE_SCRIPT} \"$backup\" && "
        f"sudo -n install -o root -g root -m 755 {CANDIDATE_SCRIPT} {REMOTE_SCRIPT} && "
        "/opt/mikrocata-venv/bin/python -c "
        f"\"path='{REMOTE_SCRIPT}'; compile(open(path, encoding='utf-8').read(), path, 'exec'); print('OK')\" && "
        "sudo -n systemctl restart mikrocataTZSP0.service && "
        "systemctl status mikrocataTZSP0.service --no-pager --lines=20 && "
        "printf '\\nBACKUP=%s\\n' \"$backup\"",
        60,
    )


@mcp.tool()
def upload_unit_candidate() -> str:
    unit_text = LOCAL_UNIT.read_text(encoding="utf-8")
    return run_ssh(
        f"cat > {CANDIDATE_UNIT} && /usr/bin/systemd-analyze verify {CANDIDATE_UNIT}",
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
        "sudo -n /usr/bin/systemctl restart mikrocataTZSP0.service && "
        "sudo -n /usr/bin/systemctl status mikrocataTZSP0.service --no-pager --lines=20",
        60,
    )


if __name__ == "__main__":
    mcp.run()
