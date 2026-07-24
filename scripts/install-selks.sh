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

effective_uid() {
    id -u
}

check_root() {
    [[ "$(effective_uid)" == "0" ]] || die "run installer as root"
}

python_version_ok() {
    local version="$1"
    local major="${version%%.*}"
    local rest="${version#*.}"
    local minor="${rest%%.*}"

    [[ "${major}" =~ ^[0-9]+$ && "${minor}" =~ ^[0-9]+$ ]] ||
        die "invalid Python version: ${version}"
    ((major > 3 || (major == 3 && minor >= 11)))
}

has_command() {
    command -v "$1" >/dev/null 2>&1
}

collect_missing_commands() {
    local command_name
    local required=(
        df
        flock
        getent
        git
        groupadd
        install
        journalctl
        namei
        openssl
        ps
        python3
        runuser
        sha256sum
        stat
        systemctl
        systemd-analyze
        tar
        useradd
    )

    for command_name in "${required[@]}"; do
        has_command "${command_name}" ||
            printf '%s\n' "${command_name}"
    done
}

package_for_command() {
    case "$1" in
        python3) printf '%s\n' "python3 python3-venv python3-pip" ;;
        git) printf '%s\n' "git" ;;
        openssl) printf '%s\n' "openssl" ;;
        systemctl | systemd-analyze | journalctl) printf '%s\n' "systemd" ;;
        flock | runuser | namei) printf '%s\n' "util-linux" ;;
        groupadd | useradd) printf '%s\n' "passwd" ;;
        *) printf '%s\n' "coreutils" ;;
    esac
}

offer_apt_install() {
    local missing=("$@")
    local answer
    local command_name
    local package
    local packages=()

    has_command apt-get || die "apt-get is unavailable; install missing commands: ${missing[*]}"
    printf 'Install missing system dependencies with apt-get? [yes/no] ' >&2
    read -r answer
    [[ "${answer}" == "yes" ]] ||
        die "system package installation declined"

    for command_name in "${missing[@]}"; do
        for package in $(package_for_command "${command_name}"); do
            if [[ " ${packages[*]} " != *" ${package} "* ]]; then
                packages+=("${package}")
            fi
        done
    done

    apt-get update
    apt-get install -y "${packages[@]}"
}

available_kib() {
    local path="$1"
    df -k --output=avail "${path}" |
        tail -n 1 |
        tr -d '[:space:]'
}

check_available_space() {
    local path="$1"
    local minimum_kib="$2"
    local actual_kib

    actual_kib="$(available_kib "${path}")"
    [[ "${actual_kib}" =~ ^[0-9]+$ ]] ||
        die "cannot determine free space for ${path}"
    ((actual_kib >= minimum_kib)) ||
        die "insufficient free space at ${path}: ${actual_kib} KiB available, ${minimum_kib} KiB required"
}

check_python_runtime() {
    local version
    version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    python_version_ok "${version}" ||
        die "Python 3.11 or newer is required; found ${version}"
    python3 -c 'import ensurepip, venv' >/dev/null ||
        die "Python venv/pip support is unavailable"
}

repo_commit() {
    git -C "${REPO_ROOT}" rev-parse --verify HEAD
}

create_source_snapshot() {
    local destination="$1"

    mkdir -p "${destination}"
    git -C "${REPO_ROOT}" archive --format=tar HEAD |
        tar -x -C "${destination}"
}

build_candidate_wheel() {
    local snapshot="$1"
    local output_dir="$2"
    local build_venv="${output_dir}/build-venv"
    local wheels

    mkdir -p "${output_dir}"
    python3 -m venv "${build_venv}"
    "${build_venv}/bin/python" -m pip install "setuptools>=68" wheel
    "${build_venv}/bin/python" -m pip wheel \
        --no-deps \
        --no-build-isolation \
        --wheel-dir "${output_dir}" \
        "${snapshot}"

    wheels=("${output_dir}"/mikro_clear-*.whl)
    [[ "${#wheels[@]}" == "1" && -f "${wheels[0]}" ]] ||
        die "expected exactly one Mikro-Clear wheel"
    "${build_venv}/bin/python" \
        "${snapshot}/scripts/validate_wheel_artifact.py" \
        "${wheels[0]}"
    printf '%s\n' "${wheels[0]}"
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
