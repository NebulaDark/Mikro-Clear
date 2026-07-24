#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

INSTALL_MODE=""
START_ONLY=false
TEST_MODE="${MIKROCLEAR_INSTALLER_TEST_MODE:-0}"
TEST_ROOT="${MIKROCLEAR_INSTALLER_TEST_ROOT:-}"

SERVICE_USER="mikroclear"
SERVICE_GROUP="mikroclear"
CANONICAL_CONFIG_DIR="/etc/mikroclear"
CANONICAL_CERT_DIR="/etc/mikroclear/certs"
CANONICAL_ENV_FILE="/etc/mikroclear/mikroclear.env"
CANONICAL_CA_FILE="/etc/mikroclear/certs/mikrotik-ca.crt"
CANONICAL_STATE_DIR="/var/lib/mikroclear"
CANONICAL_BACKUP_ROOT="/var/backups/mikroclear"
CANONICAL_VENV_DIR="/opt/mikroclear-venv"
CANONICAL_UNIT_FILE="/etc/systemd/system/mikroclear.service"
CANONICAL_EVE_PATH="/opt/SELKS/docker/containers-data/suricata/logs/eve.json"

CONFIG_DIR="${CANONICAL_CONFIG_DIR}"
CERT_DIR="${CANONICAL_CERT_DIR}"
ENV_FILE="${CANONICAL_ENV_FILE}"
CA_FILE="${CANONICAL_CA_FILE}"
STATE_DIR="${CANONICAL_STATE_DIR}"
BACKUP_ROOT="${CANONICAL_BACKUP_ROOT}"
VENV_DIR="${CANONICAL_VENV_DIR}"
UNIT_FILE="${CANONICAL_UNIT_FILE}"
EVE_PATH="${CANONICAL_EVE_PATH}"

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

    CONFIG_DIR="$(target_path "${CANONICAL_CONFIG_DIR}")"
    CERT_DIR="$(target_path "${CANONICAL_CERT_DIR}")"
    ENV_FILE="$(target_path "${CANONICAL_ENV_FILE}")"
    CA_FILE="$(target_path "${CANONICAL_CA_FILE}")"
    STATE_DIR="$(target_path "${CANONICAL_STATE_DIR}")"
    BACKUP_ROOT="$(target_path "${CANONICAL_BACKUP_ROOT}")"
    VENV_DIR="$(target_path "${CANONICAL_VENV_DIR}")"
    UNIT_FILE="$(target_path "${CANONICAL_UNIT_FILE}")"
    EVE_PATH="$(target_path "${CANONICAL_EVE_PATH}")"
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

validate_target_paths() {
    local path
    local directory_paths=(
        "${CONFIG_DIR}"
        "${CERT_DIR}"
        "${STATE_DIR}"
        "${BACKUP_ROOT}"
        "${VENV_DIR}"
    )
    local file_paths=(
        "${ENV_FILE}"
        "${CA_FILE}"
        "${UNIT_FILE}"
    )

    for path in "${directory_paths[@]}"; do
        [[ ! -L "${path}" ]] || die "unexpected symlink at ${path}"
        [[ ! -e "${path}" || -d "${path}" ]] ||
            die "expected directory at ${path}"
    done
    for path in "${file_paths[@]}"; do
        [[ ! -L "${path}" ]] || die "unexpected symlink at ${path}"
        [[ ! -e "${path}" || -f "${path}" ]] ||
            die "expected regular file at ${path}"
    done
}

ensure_service_identity() {
    if [[ "${TEST_MODE}" == "1" ]]; then
        return 0
    fi

    getent group "${SERVICE_GROUP}" >/dev/null ||
        groupadd --system "${SERVICE_GROUP}"
    id -u "${SERVICE_USER}" >/dev/null 2>&1 ||
        useradd \
            --system \
            --gid "${SERVICE_GROUP}" \
            --no-create-home \
            --home-dir /nonexistent \
            --shell /usr/sbin/nologin \
            "${SERVICE_USER}"
    [[ "$(id -gn "${SERVICE_USER}")" == "${SERVICE_GROUP}" ]] ||
        die "existing ${SERVICE_USER} user has unexpected primary group"
}

install_owned_dir() {
    local owner="$1"
    local group="$2"
    local mode="$3"
    local path="$4"

    if [[ "${TEST_MODE}" == "1" ]]; then
        install -d -m "${mode}" "${path}"
    else
        install -d -o "${owner}" -g "${group}" -m "${mode}" "${path}"
    fi
}

install_layout() {
    validate_target_paths
    ensure_service_identity
    install_owned_dir root "${SERVICE_GROUP}" 0750 "${CONFIG_DIR}"
    install_owned_dir root "${SERVICE_GROUP}" 0750 "${CERT_DIR}"
    install_owned_dir "${SERVICE_USER}" "${SERVICE_GROUP}" 0700 "${STATE_DIR}"
    install_owned_dir root root 0700 "${BACKUP_ROOT}"
}

write_template_config() {
    local temporary

    [[ ! -e "${ENV_FILE}" ]] ||
        die "configuration already exists: ${ENV_FILE}"
    temporary="$(mktemp "${CONFIG_DIR}/.mikroclear.env.XXXXXX")"
    if ! install -m 0640 \
        "${REPO_ROOT}/config/mikroclear.env.example" \
        "${temporary}"; then
        rm -f "${temporary}"
        return 1
    fi
    if [[ "${TEST_MODE}" != "1" ]]; then
        chown root:"${SERVICE_GROUP}" "${temporary}"
    fi
    mv -T "${temporary}" "${ENV_FILE}"
}

run_as_service_user() {
    if [[ "${TEST_MODE}" == "1" ]]; then
        "$@"
    else
        runuser -u "${SERVICE_USER}" -- "$@"
    fi
}

print_eve_remediation() {
    local eve_group

    eve_group="$(stat -c '%G' "${EVE_PATH}" 2>/dev/null || true)"
    if [[ -n "${eve_group}" &&
        "${eve_group}" != "UNKNOWN" &&
        "${eve_group}" != "root" &&
        "${eve_group}" != "nogroup" ]]; then
        printf 'Suggested operator command:\n' >&2
        printf '  sudo usermod -a -G %q %q\n' \
            "${eve_group}" "${SERVICE_USER}" >&2
        printf '  sudo systemctl restart mikroclear.service\n' >&2
    else
        printf 'Suggested operator commands if ACL is supported:\n' >&2
        printf '%s\n' \
            "  sudo setfacl -m u:${SERVICE_USER}:rx /opt /opt/SELKS /opt/SELKS/docker" \
            "  sudo setfacl -m u:${SERVICE_USER}:rx /opt/SELKS/docker/containers-data" \
            "  sudo setfacl -m u:${SERVICE_USER}:rx /opt/SELKS/docker/containers-data/suricata" \
            "  sudo setfacl -m u:${SERVICE_USER}:rx /opt/SELKS/docker/containers-data/suricata/logs" \
            "  sudo setfacl -m u:${SERVICE_USER}:r ${CANONICAL_EVE_PATH}" >&2
    fi
    printf 'Repeat check:\n  sudo -u %q test -r %q\n' \
        "${SERVICE_USER}" "${CANONICAL_EVE_PATH}" >&2
}

verify_eve_access() {
    if run_as_service_user test -r "${EVE_PATH}"; then
        return 0
    fi

    printf 'eve.json is not readable by %s\n' "${SERVICE_USER}" >&2
    namei -l "${EVE_PATH}" >&2 || true
    stat -c '%U:%G %a %n' "${EVE_PATH}" >&2 || true
    print_eve_remediation
    die "eve.json is not readable by ${SERVICE_USER}"
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
