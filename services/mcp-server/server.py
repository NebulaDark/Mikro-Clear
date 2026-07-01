#!/usr/bin/env python3
import os
import shlex
import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mikroclear-selks")
SELKS_HOST = os.getenv("MIKROCATA_MCP_SSH_HOST", "selks")
SSH_COMMAND = shlex.split(
    os.getenv(
        "MIKROCATA_MCP_SSH_COMMAND",
        "ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new",
    )
)


def run_ssh(command: str, timeout: int = 30) -> str:
    result = subprocess.run(
        [*SSH_COMMAND, SELKS_HOST, command],
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
        "\"path='/usr/local/bin/mikrocataTZSP0.py'; "
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
        f"sudo tail -n {lines} "
        "/opt/SELKS/docker/containers-data/suricata/logs/eve.json",
        30,
    )


if __name__ == "__main__":
    mcp.run()
