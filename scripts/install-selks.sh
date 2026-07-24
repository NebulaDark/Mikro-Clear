#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

INSTALL_MODE=""
START_ONLY=false
TEST_MODE="${MIKROCLEAR_INSTALLER_TEST_MODE:-0}"
TEST_ROOT="${MIKROCLEAR_INSTALLER_TEST_ROOT:-}"

die() {
    printf 'ERROR: %s\n' "$1" >&2
    return 1
}

usage() {
    printf '%s\n' \
        "Usage: $0 [--interactive|--config-template|--start|--help]"
}

parse_args() {
    INSTALL_MODE=""
    START_ONLY=false
    local selected=0

    while (($#)); do
        case "$1" in
            --interactive)
                INSTALL_MODE="interactive"
                ((selected += 1))
                ;;
            --config-template)
                INSTALL_MODE="template"
                ((selected += 1))
                ;;
            --start)
                INSTALL_MODE="existing"
                START_ONLY=true
                ((selected += 1))
                ;;
            --help)
                usage
                return 2
                ;;
            *)
                die "unknown argument: $1"
                return 1
                ;;
        esac
        shift
    done

    ((selected <= 1)) || die "choose exactly one install mode"
}

choose_install_mode() {
    local choice="${REPLY:-}"
    if [[ -z "${choice}" ]]; then
        printf '%s\n' \
            "1) Интерактивная настройка" \
            "2) Шаблон конфигурации" >&2
        read -r choice
    fi

    case "${choice}" in
        1) printf '%s\n' "interactive" ;;
        2) printf '%s\n' "template" ;;
        *) die "installation mode must be 1 or 2" ;;
    esac
}

init_paths() {
    if [[ -n "${TEST_ROOT}" ]]; then
        [[ "${TEST_MODE}" == "1" ]] || die "test root requires test mode"
        [[ "${TEST_ROOT}" == /tmp/* ]] || die "test root must be below /tmp"
        [[ -d "${TEST_ROOT}" && ! -L "${TEST_ROOT}" ]] || die "invalid test root"
    fi
}

target_path() {
    local absolute_path="$1"
    [[ "${absolute_path}" == /* ]] || die "target path must be absolute"
    printf '%s%s' "${TEST_ROOT}" "${absolute_path}"
}

main() {
    local parse_rc=0
    parse_args "$@" || parse_rc=$?
    ((parse_rc == 2)) && return 0
    ((parse_rc == 0)) || return "${parse_rc}"
    init_paths

    if [[ -z "${INSTALL_MODE}" ]]; then
        INSTALL_MODE="$(choose_install_mode)"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
