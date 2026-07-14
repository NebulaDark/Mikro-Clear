#!/usr/bin/env bash
set -euo pipefail

EXPECTED_USER="${1:-mcp-selks}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SUDOERS_SOURCE="${REPO_ROOT}/deploy/sudoers.d/mikroclear-mcp-selks"
SUDOERS_TARGET="/etc/sudoers.d/mikroclear-mcp-selks"

install_helper() {
    local source_path="$1"
    local target_path="$2"
    install -o root -g root -m 755 "${source_path}" "${target_path}"
}

main() {
    if [[ "$(id -u)" -ne 0 ]]; then
        echo "run as root: sudo $0 [ssh-user]" >&2
        exit 1
    fi

    if [[ ! -f "${SUDOERS_SOURCE}" ]]; then
        echo "missing sudoers source: ${SUDOERS_SOURCE}" >&2
        exit 1
    fi

    install_helper "${REPO_ROOT}/deploy/bin/mikroclear-mask-env" "/usr/local/sbin/mikroclear-mask-env"
    install_helper "${REPO_ROOT}/deploy/bin/mikroclear-service-env" "/usr/local/sbin/mikroclear-service-env"
    install_helper "${REPO_ROOT}/deploy/bin/mikroclear-telegram-getupdates-probe" "/usr/local/sbin/mikroclear-telegram-getupdates-probe"

    local tmp_sudoers
    tmp_sudoers="$(mktemp /tmp/mikroclear-codex-sudoers.XXXXXX)"
    trap 'rm -f "${tmp_sudoers}"' EXIT

    sed "1s/^mcp-selks /${EXPECTED_USER} /" "${SUDOERS_SOURCE}" > "${tmp_sudoers}"
    chmod 0440 "${tmp_sudoers}"
    visudo -cf "${tmp_sudoers}"
    install -o root -g root -m 440 "${tmp_sudoers}" "${SUDOERS_TARGET}"

    echo "Installed helpers:"
    echo "  /usr/local/sbin/mikroclear-mask-env"
    echo "  /usr/local/sbin/mikroclear-service-env"
    echo "  /usr/local/sbin/mikroclear-telegram-getupdates-probe"
    echo "Installed sudoers policy:"
    echo "  ${SUDOERS_TARGET}"
    echo
    echo "Validate as ${EXPECTED_USER}:"
    echo "  sudo -n -u ${EXPECTED_USER} sudo -n systemctl status mikroclear.service --no-pager --lines=20"
    echo "  sudo -n -u ${EXPECTED_USER} sudo -n journalctl -u mikroclear.service -n 100 --no-pager"
}

main "$@"
