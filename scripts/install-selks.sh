#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

INSTALL_MODE=""
# Exposed for source-based CLI contract tests and operator wrappers.
# shellcheck disable=SC2034
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
CANONICAL_MANIFEST_FILE="/var/lib/mikroclear/install-manifest"
CANONICAL_BACKUP_ROOT="/var/backups/mikroclear"
CANONICAL_VENV_DIR="/opt/mikroclear-venv"
CANONICAL_UNIT_FILE="/etc/systemd/system/mikroclear.service"
CANONICAL_EVE_PATH="/opt/SELKS/docker/containers-data/suricata/logs/eve.json"
CANONICAL_LOCK_FILE="/run/lock/mikroclear-install.lock"

CONFIG_DIR="${CANONICAL_CONFIG_DIR}"
CERT_DIR="${CANONICAL_CERT_DIR}"
ENV_FILE="${CANONICAL_ENV_FILE}"
CA_FILE="${CANONICAL_CA_FILE}"
STATE_DIR="${CANONICAL_STATE_DIR}"
MANIFEST_FILE="${CANONICAL_MANIFEST_FILE}"
BACKUP_ROOT="${CANONICAL_BACKUP_ROOT}"
VENV_DIR="${CANONICAL_VENV_DIR}"
UNIT_FILE="${CANONICAL_UNIT_FILE}"
EVE_PATH="${CANONICAL_EVE_PATH}"
LOCK_FILE="${CANONICAL_LOCK_FILE}"

BACKUP_DIR=""
CANDIDATE_VENV=""
ROLLBACK_VENV=""
HAD_PREVIOUS_INSTALL=false
WHEEL_PATH=""
WORK_DIR=""
ACTIVATION_EPOCH=""

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
                # Exported state for callers that source this script.
                # shellcheck disable=SC2034
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
    MANIFEST_FILE="$(target_path "${CANONICAL_MANIFEST_FILE}")"
    BACKUP_ROOT="$(target_path "${CANONICAL_BACKUP_ROOT}")"
    VENV_DIR="$(target_path "${CANONICAL_VENV_DIR}")"
    UNIT_FILE="$(target_path "${CANONICAL_UNIT_FILE}")"
    EVE_PATH="$(target_path "${CANONICAL_EVE_PATH}")"
    LOCK_FILE="$(target_path "${CANONICAL_LOCK_FILE}")"
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
        awk
        chmod
        chown
        cp
        date
        df
        dirname
        du
        flock
        getent
        git
        grep
        groupadd
        install
        journalctl
        mkdir
        mktemp
        mv
        namei
        openssl
        ps
        python3
        rm
        runuser
        sed
        sha256sum
        sleep
        stat
        systemctl
        systemd-analyze
        tail
        tar
        tr
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
        find) printf '%s\n' "findutils" ;;
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
    "${build_venv}/bin/python" -m pip install "setuptools>=68" wheel >&2
    "${build_venv}/bin/python" -m pip wheel \
        --no-deps \
        --no-build-isolation \
        --wheel-dir "${output_dir}" \
        "${snapshot}" >&2

    wheels=("${output_dir}"/mikro_clear-*.whl)
    [[ "${#wheels[@]}" == "1" && -f "${wheels[0]}" ]] ||
        die "expected exactly one Mikro-Clear wheel"
    "${build_venv}/bin/python" \
        "${snapshot}/scripts/validate_wheel_artifact.py" \
        "${wheels[0]}" >&2
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

normalize_existing_runtime_permissions() {
    python3 "${REPO_ROOT}/scripts/normalize_runtime_permissions.py" \
        --env-file "${ENV_FILE}" \
        --ca-file "${CA_FILE}" \
        --state-dir "${STATE_DIR}" \
        --config-user root \
        --service-user "${SERVICE_USER}" \
        --service-group "${SERVICE_GROUP}"
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

env_line() {
    local key="$1"
    local value="$2"
    local escaped

    [[ "${key}" =~ ^[A-Z][A-Z0-9_]*$ ]] ||
        die "invalid environment key: ${key}"
    if [[ "${value}" == *$'\n'* || "${value}" == *$'\r'* ]]; then
        die "newline is not allowed in environment value"
    fi
    escaped="${value//\\/\\\\}"
    escaped="${escaped//\"/\\\"}"
    printf '%s="%s"\n' "${key}" "${escaped}"
}

render_config() {
    local router_username="${ROUTER_USERNAME:-}"
    local router_password="${ROUTER_PASSWORD:-}"
    local router_ip="${ROUTER_IP:-}"
    local use_ssl="${USE_SSL:-true}"
    local router_port="${ROUTER_PORT:-8729}"
    local tls_server_name="${TLS_SERVER_NAME:-${router_ip}}"
    local allow_self_signed="${ALLOW_SELF_SIGNED:-false}"
    local telegram_enable="${TELEGRAM_ENABLE:-false}"
    local telegram_token="${TELEGRAM_TOKEN:-}"
    local telegram_chatid="${TELEGRAM_CHATID:-}"
    local mangle_enable="${MANGLE_CONTROL_ENABLE:-false}"

    env_line MIKROCLEAR_ROUTER_USERNAME "${router_username}"
    env_line MIKROCLEAR_ROUTER_PASSWORD "${router_password}"
    env_line MIKROCLEAR_ROUTER_IP "${router_ip}"
    printf '%s\n' \
        "MIKROCLEAR_USE_SSL=${use_ssl}" \
        "MIKROCLEAR_ROUTER_PORT=${router_port}" \
        "MIKROCLEAR_ROUTER_CONNECT_NOTIFY_ENABLE=false" \
        "MIKROCLEAR_ALLOW_SELF_SIGNED_CERTS=${allow_self_signed}" \
        "MIKROCLEAR_CA_FILE=${CANONICAL_CA_FILE}"
    env_line MIKROCLEAR_ROUTER_TLS_SERVER_NAME "${tls_server_name}"
    printf '%s\n' \
        "MIKROCLEAR_BLOCK_LIST_NAME=Suricata" \
        "MIKROCLEAR_BLOCK_TIMEOUT=1d" \
        "MIKROCLEAR_MONITOR_ONLY=false" \
        "MIKROCLEAR_TELEGRAM_ENABLE=${telegram_enable}"
    env_line MIKROCLEAR_TELEGRAM_TOKEN "${telegram_token}"
    env_line MIKROCLEAR_TELEGRAM_CHATID "${telegram_chatid}"
    printf '%s\n' \
        "MIKROCLEAR_TELEGRAM_UNBLOCK_ENABLE=true" \
        "MIKROCLEAR_TELEGRAM_UNBLOCK_TTL_SECONDS=86400" \
        "MIKROCLEAR_TELEGRAM_LONG_POLL_SECONDS=25" \
        "MIKROCLEAR_MANGLE_CONTROL_ENABLE=${mangle_enable}" \
        "MIKROCLEAR_MANGLE_COMMENT_PREFIX=MC:" \
        "MIKROCLEAR_MANGLE_ALLOWED_CHAINS=prerouting" \
        "MIKROCLEAR_MANGLE_ALLOWED_ACTIONS=mark-routing" \
        "MIKROCLEAR_MANGLE_REQUIRE_CONFIRMATION=true" \
        "MIKROCLEAR_BOT_ENABLE=${telegram_enable}" \
        "MIKROCLEAR_BOT_DRY_RUN=true"
    env_line MIKROCLEAR_BOT_ADMIN_CHAT_IDS "${telegram_chatid}"
    env_line MIKROCLEAR_BOT_ALLOWED_CHAT_IDS "${telegram_chatid}"
    printf '%s\n' \
        "MIKROCLEAR_BOT_MODULES=status,asset_resolver,mangle_control,parental_control" \
        "MIKROCLEAR_BOT_AUDIT_LOG=/var/lib/mikroclear/bot-audit.log" \
        "MIKROCLEAR_SURICATA_LOG_DIR=/opt/SELKS/docker/containers-data/suricata/logs/" \
        "MIKROCLEAR_EVE_JSON=${CANONICAL_EVE_PATH}" \
        "MIKROCLEAR_STATE_DIR=${CANONICAL_STATE_DIR}" \
        "MIKROCLEAR_SEVERITY=1,2" \
        "MIKROCLEAR_LISTEN_INTERFACES=tzsp0" \
        "MIKROCLEAR_ADD_ON_START=false" \
        "MIKROCLEAR_DEBUG=false"
}

print_masked_summary() {
    printf '%s\n' \
        "RouterOS user: ${ROUTER_USERNAME:-}" \
        "RouterOS password: ***" \
        "RouterOS address: ${ROUTER_IP:-}:${ROUTER_PORT:-}" \
        "RouterOS TLS: ${USE_SSL:-true}" \
        "Telegram enabled: ${TELEGRAM_ENABLE:-false}" \
        "Telegram token: ***" \
        "Telegram chat ID: ${TELEGRAM_CHATID:-}" \
        "Mangle control: ${MANGLE_CONTROL_ENABLE:-false}"
}

validate_config_text() {
    local config_path="$1"
    local key
    local line
    local required=(
        MIKROCLEAR_ROUTER_USERNAME
        MIKROCLEAR_ROUTER_PASSWORD
        MIKROCLEAR_ROUTER_IP
        MIKROCLEAR_ROUTER_PORT
        MIKROCLEAR_STATE_DIR
        MIKROCLEAR_EVE_JSON
    )

    for key in "${required[@]}"; do
        line="$(grep -m 1 "^${key}=" "${config_path}" || true)"
        [[ -n "${line}" && "${line#*=}" != '""' ]] ||
            return 1
    done
}

write_config_atomic() {
    local content="$1"
    local temporary

    temporary="$(mktemp "${CONFIG_DIR}/.mikroclear.env.XXXXXX")"
    printf '%s\n' "${content}" >"${temporary}"
    if ! validate_config_text "${temporary}"; then
        rm -f "${temporary}"
        die "configuration validation failed"
        return 1
    fi
    chmod 0640 "${temporary}"
    if [[ "${TEST_MODE}" != "1" ]]; then
        chown root:"${SERVICE_GROUP}" "${temporary}"
    fi
    mv -T "${temporary}" "${ENV_FILE}"
}

validate_ca_source() {
    local source="$1"

    [[ -f "${source}" ]] ||
        die "invalid CA certificate: file not found"
    openssl x509 -in "${source}" -noout >/dev/null 2>&1 ||
        die "invalid CA certificate: ${source}"
}

install_ca() {
    local source="$1"
    local temporary

    validate_ca_source "${source}"
    temporary="$(mktemp "${CERT_DIR}/.mikrotik-ca.crt.XXXXXX")"
    if ! install -m 0640 "${source}" "${temporary}"; then
        rm -f "${temporary}"
        return 1
    fi
    if [[ "${TEST_MODE}" != "1" ]]; then
        chown root:"${SERVICE_GROUP}" "${temporary}"
    fi
    mv -T "${temporary}" "${CA_FILE}"
}

validate_router_port() {
    local port="$1"

    if [[ ! "${port}" =~ ^[0-9]+$ ]] ||
        ((port < 1 || port > 65535)); then
        die "RouterOS port must be between 1 and 65535"
    fi
}

read_yes_no() {
    local prompt="$1"
    local default="$2"
    local answer

    printf '%s [%s]: ' "${prompt}" "${default}" >&2
    read -r answer
    answer="${answer:-${default}}"
    case "${answer,,}" in
        yes | y | true) printf '%s\n' "true" ;;
        no | n | false) printf '%s\n' "false" ;;
        *) die "answer yes or no" ;;
    esac
}

collect_interactive_config() {
    local confirmation

    printf 'RouterOS username: ' >&2
    read -r ROUTER_USERNAME
    printf 'RouterOS password: ' >&2
    read -r -s ROUTER_PASSWORD
    printf '\nRouterOS address: ' >&2
    read -r ROUTER_IP
    [[ -n "${ROUTER_USERNAME}" &&
        -n "${ROUTER_PASSWORD}" &&
        -n "${ROUTER_IP}" ]] ||
        die "RouterOS username, password and address are required"

    USE_SSL="$(read_yes_no "Use RouterOS TLS" "yes")"
    if [[ "${USE_SSL}" == "true" ]]; then
        printf 'RouterOS API port [8729]: ' >&2
        read -r ROUTER_PORT
        ROUTER_PORT="${ROUTER_PORT:-8729}"
        printf 'TLS server name [%s]: ' "${ROUTER_IP}" >&2
        read -r TLS_SERVER_NAME
        TLS_SERVER_NAME="${TLS_SERVER_NAME:-${ROUTER_IP}}"
        ALLOW_SELF_SIGNED="$(
            read_yes_no "Disable certificate verification (unsafe)" "no"
        )"
        CA_SOURCE=""
        if [[ "${ALLOW_SELF_SIGNED}" == "false" ]]; then
            printf 'Source CA certificate path: ' >&2
            read -r CA_SOURCE
            [[ -n "${CA_SOURCE}" ]] ||
                die "CA certificate path is required for verified TLS"
            validate_ca_source "${CA_SOURCE}"
        fi
    else
        printf 'RouterOS API port [8728]: ' >&2
        read -r ROUTER_PORT
        ROUTER_PORT="${ROUTER_PORT:-8728}"
        TLS_SERVER_NAME="${ROUTER_IP}"
        ALLOW_SELF_SIGNED=false
        CA_SOURCE=""
    fi
    validate_router_port "${ROUTER_PORT}"

    TELEGRAM_ENABLE="$(read_yes_no "Enable Telegram" "no")"
    TELEGRAM_TOKEN=""
    TELEGRAM_CHATID=""
    if [[ "${TELEGRAM_ENABLE}" == "true" ]]; then
        printf 'Telegram token: ' >&2
        read -r -s TELEGRAM_TOKEN
        printf '\nTelegram chat ID: ' >&2
        read -r TELEGRAM_CHATID
        [[ -n "${TELEGRAM_TOKEN}" && -n "${TELEGRAM_CHATID}" ]] ||
            die "Telegram token and chat ID are required"
    fi

    MANGLE_CONTROL_ENABLE="$(
        read_yes_no "Enable Telegram mangle control" "no"
    )"
    print_masked_summary
    confirmation="$(read_yes_no "Write this configuration" "no")"
    [[ "${confirmation}" == "true" ]] ||
        die "configuration was not confirmed"
}

configure_interactively() {
    local content

    collect_interactive_config || return 1
    if [[ "${USE_SSL}" == "true" &&
        "${ALLOW_SELF_SIGNED}" == "false" ]]; then
        install_ca "${CA_SOURCE}" || return 1
    fi
    content="$(render_config)" || return 1
    write_config_atomic "${content}" || return 1
}

acquire_install_lock() {
    local lock_dir

    lock_dir="$(dirname "${LOCK_FILE}")"
    if [[ ! -d "${lock_dir}" ]]; then
        install -d -m 0755 "${lock_dir}"
    fi
    exec 9>"${LOCK_FILE}"
    flock -n 9 || die "another installer is running: ${LOCK_FILE}"
}

prepare_candidate_paths() {
    local timestamp

    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    if [[ -z "${CANDIDATE_VENV}" ]]; then
        CANDIDATE_VENV="$(
            target_path "/opt/.mikroclear-venv.candidate.$$"
        )"
    fi
    if [[ -z "${ROLLBACK_VENV}" ]]; then
        ROLLBACK_VENV="$(
            target_path "/opt/.mikroclear-venv.rollback.${timestamp}"
        )"
    fi
}

prepare_candidate_venv() {
    local wheel="$1"
    local import_path

    prepare_candidate_paths || return 1
    if [[ -e "${CANDIDATE_VENV}" ]]; then
        die "candidate venv already exists: ${CANDIDATE_VENV}"
        return 1
    fi
    python3 -m venv "${CANDIDATE_VENV}" || return 1
    "${CANDIDATE_VENV}/bin/python" -m pip install "${wheel}" ||
        return 1
    if "${CANDIDATE_VENV}/bin/python" -m pip show mcp >/dev/null 2>&1; then
        die "candidate runtime unexpectedly contains mcp"
        return 1
    fi
    import_path="$(
        cd /
        "${CANDIDATE_VENV}/bin/python" -c \
            'import pathlib, mikroclear; print(pathlib.Path(mikroclear.__file__).resolve())'
    )" || return 1
    if [[ "${import_path}" != \
        "${CANDIDATE_VENV}"/lib/python*/site-packages/mikroclear/* ]]; then
        die "candidate import is outside candidate site-packages: ${import_path}"
        return 1
    fi
}

backup_file_if_present() {
    local source="$1"
    local backup_name="$2"

    if [[ -f "${source}" ]]; then
        cp -a -- "${source}" "${BACKUP_DIR}/${backup_name}"
        printf '%s\n' "${backup_name}" >>"${BACKUP_DIR}/backup-inventory"
    fi
}

create_backup() {
    local timestamp

    if [[ -z "${BACKUP_DIR}" ]]; then
        timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
        BACKUP_DIR="${BACKUP_ROOT}/${timestamp}"
    fi
    [[ ! -e "${BACKUP_DIR}" ]] ||
        die "backup directory already exists: ${BACKUP_DIR}"
    install_owned_dir root root 0700 "${BACKUP_DIR}"
    : >"${BACKUP_DIR}/backup-inventory"
    chmod 0600 "${BACKUP_DIR}/backup-inventory"
    backup_file_if_present "${UNIT_FILE}" "mikroclear.service"
    backup_file_if_present "${ENV_FILE}" "mikroclear.env"
    backup_file_if_present "${CA_FILE}" "mikrotik-ca.crt"
    backup_file_if_present "${MANIFEST_FILE}" "install-manifest"
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        "${VENV_DIR}/bin/python" -m pip freeze \
            >"${BACKUP_DIR}/pip-freeze.txt"
        chmod 0600 "${BACKUP_DIR}/pip-freeze.txt"
    fi
}

switch_candidate_venv() {
    if [[ ! -d "${CANDIDATE_VENV}" ]]; then
        die "candidate venv is missing: ${CANDIDATE_VENV}"
        return 1
    fi

    if [[ -d "${VENV_DIR}" ]]; then
        HAD_PREVIOUS_INSTALL=true
        if [[ -e "${ROLLBACK_VENV}" ]]; then
            die "rollback venv path already exists: ${ROLLBACK_VENV}"
            return 1
        fi
        mv -- "${VENV_DIR}" "${ROLLBACK_VENV}" || return 1
    else
        HAD_PREVIOUS_INSTALL=false
    fi

    if ! mv -- "${CANDIDATE_VENV}" "${VENV_DIR}"; then
        if [[ "${HAD_PREVIOUS_INSTALL}" == "true" &&
            -d "${ROLLBACK_VENV}" ]]; then
            mv -- "${ROLLBACK_VENV}" "${VENV_DIR}" || true
        fi
        return 1
    fi
}

restore_previous_venv() {
    local failed_venv

    [[ -d "${ROLLBACK_VENV}" ]] ||
        die "rollback venv is missing: ${ROLLBACK_VENV}"
    if [[ -n "${BACKUP_DIR}" ]]; then
        failed_venv="${BACKUP_DIR}/failed-venv"
    else
        failed_venv="$(target_path "/opt/.mikroclear-venv.failed.$$")"
    fi
    [[ ! -e "${failed_venv}" ]] ||
        die "failed venv archive already exists: ${failed_venv}"
    if [[ -d "${VENV_DIR}" ]]; then
        mv -- "${VENV_DIR}" "${failed_venv}"
    fi
    mv -- "${ROLLBACK_VENV}" "${VENV_DIR}"
}

finalize_successful_update() {
    if [[ ! -d "${ROLLBACK_VENV}" ]]; then
        return 0
    fi
    [[ -n "${BACKUP_DIR}" && -d "${BACKUP_DIR}" ]] ||
        die "backup directory is unavailable for previous venv"
    [[ ! -e "${BACKUP_DIR}/venv" ]] ||
        die "backup venv already exists: ${BACKUP_DIR}/venv"
    mv -- "${ROLLBACK_VENV}" "${BACKUP_DIR}/venv"
}

install_unit_candidate() {
    local temporary

    temporary="$(
        mktemp "$(dirname "${UNIT_FILE}")/.mikroclear.XXXXXX.service"
    )" || return 1
    if ! install -m 0644 \
        "${REPO_ROOT}/systemd/mikroclear.service" \
        "${temporary}"; then
        rm -f -- "${temporary}"
        return 1
    fi
    if [[ "${TEST_MODE}" != "1" ]]; then
        if ! chown root:root "${temporary}" ||
            ! systemd-analyze verify "${temporary}"; then
            rm -f -- "${temporary}"
            return 1
        fi
    fi
    if ! mv -T "${temporary}" "${UNIT_FILE}"; then
        rm -f -- "${temporary}"
        return 1
    fi
}

write_manifest() {
    local status="$1"
    local commit
    local wheel_sha=""
    local temporary
    local python_version

    commit="$(repo_commit)" || return 1
    if [[ -n "${WHEEL_PATH}" && -f "${WHEEL_PATH}" ]]; then
        wheel_sha="$(
            sha256sum "${WHEEL_PATH}" | awk '{print $1}'
        )" || return 1
    fi
    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
        die "runtime Python is missing: ${VENV_DIR}/bin/python"
        return 1
    fi
    python_version="$("${VENV_DIR}/bin/python" --version 2>&1)" ||
        return 1
    temporary="$(mktemp "${STATE_DIR}/.install-manifest.XXXXXX")" ||
        return 1
    if ! printf '%s\n' \
        "status=${status}" \
        "commit=${commit}" \
        "wheel_sha256=${wheel_sha}" \
        "python=${python_version}" \
        "installed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        >"${temporary}"; then
        rm -f -- "${temporary}"
        return 1
    fi
    if ! chmod 0600 "${temporary}"; then
        rm -f -- "${temporary}"
        return 1
    fi
    if [[ "${TEST_MODE}" != "1" ]]; then
        if ! chown "${SERVICE_USER}:${SERVICE_GROUP}" "${temporary}"; then
            rm -f -- "${temporary}"
            return 1
        fi
    fi
    if ! mv -T "${temporary}" "${MANIFEST_FILE}"; then
        rm -f -- "${temporary}"
        return 1
    fi
}

read_env_value() {
    local key="$1"
    local line
    local value

    [[ "${key}" =~ ^[A-Z][A-Z0-9_]*$ ]] ||
        die "invalid environment key: ${key}"
    line="$(grep -m 1 "^${key}=" "${ENV_FILE}" || true)"
    [[ -n "${line}" ]] || return 1
    value="${line#*=}"
    if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
        value="${value:1:${#value}-2}"
        value="${value//\\\"/\"}"
        value="${value//\\\\/\\}"
    fi
    printf '%s\n' "${value}"
}

validate_existing_config() {
    local use_ssl
    local allow_self_signed

    [[ -f "${ENV_FILE}" ]] ||
        die "existing configuration is missing: ${ENV_FILE}"
    validate_config_text "${ENV_FILE}" ||
        die "existing configuration is incomplete: ${ENV_FILE}"
    use_ssl="$(read_env_value MIKROCLEAR_USE_SSL || printf 'true\n')"
    allow_self_signed="$(
        read_env_value MIKROCLEAR_ALLOW_SELF_SIGNED_CERTS ||
            printf 'false\n'
    )"
    if [[ "${use_ssl}" == "true" &&
        "${allow_self_signed}" != "true" ]]; then
        validate_ca_source "${CA_FILE}"
    fi
}

existing_install() {
    [[ -d "${VENV_DIR}" && -f "${ENV_FILE}" && -f "${UNIT_FILE}" ]]
}

stop_service() {
    systemctl stop mikroclear.service >/dev/null 2>&1 || true
}

start_service() {
    systemctl enable --now mikroclear.service
}

reload_service_manager() {
    systemctl daemon-reload
}

service_properties() {
    systemctl show mikroclear.service \
        --property=ActiveState,SubState,NRestarts,TasksCurrent,User,Group,WorkingDirectory,MainPID \
        --no-pager
}

service_journal() {
    journalctl -u mikroclear.service \
        --since "@${ACTIVATION_EPOCH}" \
        --no-pager
}

property_value() {
    local properties="$1"
    local key="$2"

    awk -F= -v key="${key}" '$1 == key {print substr($0, index($0, "=") + 1); exit}' \
        <<<"${properties}"
}

acceptance_probe() {
    local properties
    local journal
    local main_pid
    local process_user
    local tasks_current
    local telegram_enable
    local import_path

    properties="$(service_properties)" || return 1
    [[ "$(property_value "${properties}" ActiveState)" == "active" ]] || return 1
    [[ "$(property_value "${properties}" SubState)" == "running" ]] || return 1
    [[ "$(property_value "${properties}" NRestarts)" == "0" ]] || return 1
    [[ "$(property_value "${properties}" User)" == "${SERVICE_USER}" ]] || return 1
    [[ "$(property_value "${properties}" Group)" == "${SERVICE_GROUP}" ]] || return 1
    [[ "$(property_value "${properties}" WorkingDirectory)" == "/" ]] || return 1

    main_pid="$(property_value "${properties}" MainPID)"
    [[ "${main_pid}" =~ ^[1-9][0-9]*$ ]] || return 1
    process_user="$(ps -o user= -p "${main_pid}" | tr -d '[:space:]')"
    [[ "${process_user}" == "${SERVICE_USER}" ]] || return 1

    import_path="$(
        cd /
        "${VENV_DIR}/bin/python" -c \
            'import pathlib, mikroclear; print(pathlib.Path(mikroclear.__file__).resolve())'
    )" || return 1
    [[ "${import_path}" == "${VENV_DIR}"/lib/python*/site-packages/mikroclear/* ]] ||
        return 1
    verify_eve_access || return 1
    run_as_service_user test -w "${STATE_DIR}" || return 1

    journal="$(service_journal)" || return 1
    grep -Fq "Connected to MikroTik" <<<"${journal}" || return 1
    if grep -Eq "Traceback|Fatal Telegram polling worker error" <<<"${journal}"; then
        return 1
    fi

    telegram_enable="$(
        read_env_value MIKROCLEAR_TELEGRAM_ENABLE ||
            printf 'false\n'
    )"
    if [[ "${telegram_enable}" == "true" ]]; then
        grep -Fq "Telegram polling worker started" <<<"${journal}" || return 1
        tasks_current="$(property_value "${properties}" TasksCurrent)"
        [[ "${tasks_current}" =~ ^[0-9]+$ && "${tasks_current}" -ge 2 ]] ||
            return 1
    fi
}

show_diagnostics() {
    {
        systemctl status mikroclear.service --no-pager --lines=30 || true
        journalctl -u mikroclear.service -n 100 --no-pager || true
    } 2>&1 |
        sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g' >&2
}

accept_install() {
    local timeout="${1:-90}"
    local deadline

    ACTIVATION_EPOCH="$(date +%s)"
    start_service || return 1
    deadline=$((ACTIVATION_EPOCH + timeout))
    while (("$(date +%s)" <= deadline)); do
        if acceptance_probe; then
            return 0
        fi
        sleep 2
    done
    show_diagnostics
    return 1
}

restore_backup_file() {
    local backup_name="$1"
    local destination="$2"

    if [[ -f "${BACKUP_DIR}/${backup_name}" ]]; then
        cp -a -- "${BACKUP_DIR}/${backup_name}" "${destination}"
    elif [[ -f "${BACKUP_DIR}/backup-inventory" ]] &&
        ! grep -Fxq "${backup_name}" "${BACKUP_DIR}/backup-inventory"; then
        rm -f -- "${destination}"
    fi
}

restore_backup_files() {
    restore_backup_file "mikroclear.service" "${UNIT_FILE}"
    restore_backup_file "mikroclear.env" "${ENV_FILE}"
    restore_backup_file "mikrotik-ca.crt" "${CA_FILE}"
    restore_backup_file "install-manifest" "${MANIFEST_FILE}"
}

verify_rollback_health() {
    local properties

    properties="$(service_properties)" || return 1
    [[ "$(property_value "${properties}" ActiveState)" == "active" ]] &&
        [[ "$(property_value "${properties}" SubState)" == "running" ]] &&
        [[ "$(property_value "${properties}" NRestarts)" == "0" ]]
}

rollback_update() {
    stop_service || {
        printf 'ROLLBACK FAILED; backup: %s\n' "${BACKUP_DIR}" >&2
        return 2
    }
    restore_previous_venv || {
        printf 'ROLLBACK FAILED; backup: %s\n' "${BACKUP_DIR}" >&2
        return 2
    }
    restore_backup_files || {
        printf 'ROLLBACK FAILED; backup: %s\n' "${BACKUP_DIR}" >&2
        return 2
    }
    reload_service_manager || {
        printf 'ROLLBACK FAILED; backup: %s\n' "${BACKUP_DIR}" >&2
        return 2
    }
    start_service || {
        printf 'ROLLBACK FAILED; backup: %s\n' "${BACKUP_DIR}" >&2
        return 2
    }
    if ! verify_rollback_health; then
        printf 'ROLLBACK FAILED; backup: %s\n' "${BACKUP_DIR}" >&2
        return 2
    fi
    printf 'Update failed; previous installation restored from %s\n' \
        "${BACKUP_DIR}" >&2
}

install_or_update() {
    if [[ "${HAD_PREVIOUS_INSTALL}" == "true" &&
        -z "${BACKUP_DIR}" ]]; then
        create_backup
    fi
    if ! prepare_candidate_venv "${WHEEL_PATH}"; then
        if [[ "${HAD_PREVIOUS_INSTALL}" == "true" ]]; then
            restore_backup_files
        fi
        return 1
    fi
    if [[ "${HAD_PREVIOUS_INSTALL}" == "true" ]]; then
        stop_service
    fi
    if ! normalize_existing_runtime_permissions; then
        if [[ "${HAD_PREVIOUS_INSTALL}" == "true" ]]; then
            restore_backup_files || return 1
            start_service || return 1
        fi
        return 1
    fi
    if ! switch_candidate_venv; then
        return 1
    fi
    if ! install_unit_candidate ||
        ! reload_service_manager ||
        ! accept_install 90; then
        if [[ "${HAD_PREVIOUS_INSTALL}" == "true" ]]; then
            rollback_update || return $?
        else
            stop_service
        fi
        return 1
    fi
    if ! write_manifest active ||
        ! finalize_successful_update; then
        if [[ "${HAD_PREVIOUS_INSTALL}" == "true" ]]; then
            rollback_update || return $?
        else
            stop_service
        fi
        return 1
    fi
}

prepare_install_artifact() {
    local timestamp
    local snapshot
    local build_output

    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    WORK_DIR="$(target_path "/var/tmp/mikroclear-install.${timestamp}.$$")"
    install -d -m 0700 "${WORK_DIR}"
    snapshot="${WORK_DIR}/source"
    build_output="${WORK_DIR}/build"
    create_source_snapshot "${snapshot}"
    WHEEL_PATH="$(build_candidate_wheel "${snapshot}" "${build_output}")"
}

run_preflight() {
    local missing=()
    local required_kib=524288
    local current_kib

    check_root
    mapfile -t missing < <(collect_missing_commands)
    if (("${#missing[@]}" > 0)); then
        printf 'Missing commands: %s\n' "${missing[*]}" >&2
        offer_apt_install "${missing[@]}"
        mapfile -t missing < <(collect_missing_commands)
        (("${#missing[@]}" == 0)) ||
            die "system dependencies are still missing: ${missing[*]}"
    fi
    [[ -d /run/systemd/system ]] ||
        die "systemd is not the active init system"
    check_python_runtime
    repo_commit >/dev/null ||
        die "current directory has no committed Git HEAD"
    if [[ -d "${VENV_DIR}" ]]; then
        current_kib="$(du -sk "${VENV_DIR}" | awk '{print $1}')"
        required_kib=$((required_kib + current_kib))
    fi
    check_available_space /opt "${required_kib}"
}

install_template_mode() {
    if existing_install; then
        die "existing installation found; template mode will not modify it"
        return 1
    fi
    install_layout
    write_template_config
    verify_eve_access
    prepare_install_artifact
    HAD_PREVIOUS_INSTALL=false
    prepare_candidate_venv "${WHEEL_PATH}"
    switch_candidate_venv
    install_unit_candidate
    reload_service_manager
    write_manifest template
    printf '%s\n' \
        "Template installed. Fill ${CANONICAL_ENV_FILE}, then run:" \
        "  sudo ./scripts/install-selks.sh --start"
}

install_interactive_mode() {
    if existing_install; then
        HAD_PREVIOUS_INSTALL=true
    else
        HAD_PREVIOUS_INSTALL=false
    fi
    install_layout
    prepare_install_artifact
    if [[ "${HAD_PREVIOUS_INSTALL}" == "true" ]]; then
        create_backup
    fi
    if ! configure_interactively; then
        if [[ "${HAD_PREVIOUS_INSTALL}" == "true" ]]; then
            restore_backup_files
        fi
        return 1
    fi
    if ! validate_existing_config ||
        ! verify_eve_access; then
        if [[ "${HAD_PREVIOUS_INSTALL}" == "true" ]]; then
            restore_backup_files
        fi
        return 1
    fi
    install_or_update
}

install_update_mode() {
    existing_install ||
        die "existing installation is incomplete; use an explicit clean-install mode"
    HAD_PREVIOUS_INSTALL=true
    install_layout
    validate_existing_config
    verify_eve_access
    prepare_install_artifact
    install_or_update
}

start_existing_install() {
    existing_install ||
        die "existing installation is incomplete"
    validate_existing_config
    verify_eve_access
    reload_service_manager
    if ! accept_install 90; then
        stop_service
        return 1
    fi
    write_manifest active
}

main() {
    local parse_rc=0
    parse_args "$@" || parse_rc=$?
    ((parse_rc == 2)) && return 0
    ((parse_rc == 0)) || return "${parse_rc}"
    init_paths
    acquire_install_lock
    run_preflight

    if [[ -z "${INSTALL_MODE}" ]]; then
        if existing_install; then
            INSTALL_MODE="update"
        else
            INSTALL_MODE="$(choose_install_mode)"
        fi
    fi

    case "${INSTALL_MODE}" in
        template) install_template_mode ;;
        interactive) install_interactive_mode ;;
        existing) start_existing_install ;;
        update) install_update_mode ;;
        *) die "unsupported install mode: ${INSTALL_MODE}" ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
