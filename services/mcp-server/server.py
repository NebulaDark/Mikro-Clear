#!/usr/bin/env python3
import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mikroclear-selks")
SELKS_HOST = "selks"


def run_ssh(command: str, timeout: int = 30) -> str:
    result = subprocess.run(
        ["ssh", SELKS_HOST, command],
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
    return run_ssh("sudo systemctl status mikrocataTZSP0.service --no-pager", 20)


@mcp.tool()
def restart_mikrocata() -> str:
    return run_ssh(
        "sudo systemctl restart mikrocataTZSP0.service && "
        "sudo systemctl status mikrocataTZSP0.service --no-pager",
        40,
    )


@mcp.tool()
def tail_mikrocata_logs(lines: int = 100) -> str:
    lines = max(10, min(int(lines), 500))
    return run_ssh(f"sudo journalctl -u mikrocataTZSP0.service -n {lines} --no-pager", 30)


@mcp.tool()
def check_mikrocata_syntax() -> str:
    return run_ssh(
        "sudo /opt/mikrocata-venv/bin/python -m py_compile "
        "/usr/local/bin/mikrocataTZSP0.py && echo OK",
        30,
    )


@mcp.tool()
def read_mikrocata_env() -> str:
    return run_ssh(
        r"sudo sed -E 's/(TOKEN|PASSWORD|PASS|SECRET|KEY)=.*/\1=***MASKED***/g' "
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
