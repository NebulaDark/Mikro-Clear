# SELKS Standalone Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать автономную установку и безопасное обновление Mikro-Clear непосредственно из committed Git checkout на SELKS с non-root runtime, двумя режимами конфигурации, acceptance и rollback.

**Architecture:** Один операторский entrypoint `scripts/install-selks.sh` содержит sourceable Bash-функции и guard прямого запуска. Он строит wheel из `git archive HEAD`, готовит отдельный candidate venv, атомарно переключает runtime после backup и откатывает весь venv/unit/config при неуспешном acceptance. Python `unittest` проверяет функции через Bash subprocess и временный test root; production root prefix через CLI не поддерживается.

**Tech Stack:** Bash 5, Python 3.11+, `unittest`, setuptools/wheel, Git, systemd, OpenSSL, coreutils, util-linux.

## Global Constraints

- Официально тестируются Debian 12 и Debian 13; жёсткого ограничения по имени дистрибутива нет.
- Python должен быть версии 3.11 или новее.
- Установщик запускается непосредственно на SELKS из локального Git checkout и не выполняет SSH-оркестрацию.
- Устанавливается точный committed `HEAD`; `git pull`, `git fetch` и checkout внутри установщика запрещены.
- Production runtime не устанавливает `requirements.txt`, optional extras или пакет `mcp`.
- Единственный операторский entrypoint — `scripts/install-selks.sh`.
- Поддерживаются режимы `--interactive`, `--config-template` и последующий `--start`.
- Runtime запускается от системных `User=mikroclear` и `Group=mikroclear`.
- Новый CA path — только `/etc/mikroclear/certs/mikrotik-ca.crt`.
- Установщик не меняет владельца, группу, ACL или режимы SELKS/Docker для доступа к `eve.json`.
- Live RouterOS, Telegram и production SELKS не вызываются автоматическими тестами.
- Любая production SELKS mutation или restart требует отдельного разрешения пользователя.
- Существующие пользовательские изменения `requirements.txt` и `docs/ru/.telegram-bot-incident-2026-07-14.md.swp` не добавлять в коммиты.
- `pyproject.toml` уже изменён пользователем; Task 1 намеренно меняет только размещение `mcp`, сохраняя его как optional tooling dependency.
- Перед каждым коммитом выполнять `git diff --cached --name-only` и проверять точный список файлов.

---

### Task 1: Зафиксировать runtime dependency и CA contract

**Files:**
- Create: `tests/test_standalone_install_contract.py`
- Modify: `tests/test_settings.py:SettingsTests`
- Modify: `src/mikroclear/settings.py:Settings.ca_file,Settings.from_env`
- Modify: `config/mikroclear.env.example:MIKROCLEAR_CA_FILE`
- Modify: `pyproject.toml:[project].dependencies`
- Modify: `scripts/validate_wheel_artifact.py:validate_wheel`
- Modify: `tests/test_wheel_artifact_validation.py:WheelArtifactValidationTests`

**Interfaces:**
- Consumes: существующий `Settings.from_env()` и wheel validator.
- Produces: canonical CA constant value `/etc/mikroclear/certs/mikrotik-ca.crt`; optional dependency group `mcp-tools`; wheel validation error `forbidden runtime dependency: mcp`.

- [ ] **Step 1: Write failing settings and metadata tests**

Добавить:

```python
# tests/test_settings.py
def test_default_ca_file_uses_mikroclear_config_tree(self):
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings.from_env()

    self.assertEqual(
        settings.ca_file,
        "/etc/mikroclear/certs/mikrotik-ca.crt",
    )
```

Создать:

```python
# tests/test_standalone_install_contract.py
from pathlib import Path
import tomllib
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class StandaloneInstallContractTests(TestCase):
    def test_mcp_is_optional_not_runtime_dependency(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime = data["project"]["dependencies"]
        optional = data["project"]["optional-dependencies"]["mcp-tools"]

        self.assertFalse(any(item.split("=", 1)[0].lower() == "mcp" for item in runtime))
        self.assertIn("mcp==1.28.1", optional)

    def test_new_runtime_files_use_canonical_ca_path(self):
        paths = (
            ROOT / "src/mikroclear/settings.py",
            ROOT / "config/mikroclear.env.example",
        )
        for path in paths:
            with self.subTest(path=str(path)):
                text = path.read_text(encoding="utf-8")
                self.assertIn("/etc/mikroclear/certs/mikrotik-ca.crt", text)
                self.assertNotIn("/etc/mikrocata/certs", text)
```

В `tests/test_wheel_artifact_validation.py` добавить fixture wheel с
`Requires-Dist: mcp==1.28.1` и ожидание:

```python
self.assertIn("forbidden runtime dependency: mcp", result.errors)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_settings \
  tests.test_standalone_install_contract \
  tests.test_wheel_artifact_validation
```

Expected: FAIL на старом CA path, отсутствии `mcp-tools` и отсутствии проверки wheel metadata.

- [ ] **Step 3: Implement the runtime contract**

В `pyproject.toml` удалить `mcp==1.28.1` из `[project].dependencies` и добавить:

```toml
[project.optional-dependencies]
mcp-tools = [
    "mcp==1.28.1",
]
```

В обоих местах `src/mikroclear/settings.py` и в
`config/mikroclear.env.example` использовать:

```text
/etc/mikroclear/certs/mikrotik-ca.crt
```

В wheel validator прочитать единственный `*.dist-info/METADATA`, разобрать
строки `Requires-Dist:` и добавить ошибку:

```python
for line in metadata.splitlines():
    if not line.lower().startswith("requires-dist:"):
        continue
    dependency = line.split(":", 1)[1].strip().split(";", 1)[0].strip()
    normalized = dependency.split("[", 1)[0].split("=", 1)[0].strip().lower()
    if normalized == "mcp":
        errors.append("forbidden runtime dependency: mcp")
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command.

Expected: `OK`.

- [ ] **Step 5: Commit only Task 1 files**

```bash
git add pyproject.toml config/mikroclear.env.example \
  src/mikroclear/settings.py scripts/validate_wheel_artifact.py \
  tests/test_settings.py tests/test_standalone_install_contract.py \
  tests/test_wheel_artifact_validation.py
git diff --cached --name-only
git commit -m "Separate installer runtime dependencies"
```

Expected staged list: exactly the seven files above; `requirements.txt` is not staged.

---

### Task 2: Перевести systemd unit на non-root runtime

**Files:**
- Modify: `systemd/mikroclear.service:[Service]`
- Modify: `deploy/systemd/mikroclear.service.candidate:[Service]`
- Modify: `tests/test_systemd_unit.py:SystemdUnitTests`
- Modify: `tests/test_systemd_candidate_unit.py:SystemdCandidateUnitTests`

**Interfaces:**
- Consumes: paths `/opt/mikroclear-venv`, `/etc/mikroclear`, `/var/lib/mikroclear`.
- Produces: одинаковый production/candidate unit contract с обязательным env и пользователем `mikroclear`.

- [ ] **Step 1: Write failing unit tests**

Заменить root-ожидания и добавить обязательный env:

```python
def test_service_runs_as_dedicated_user_with_required_env(self):
    service_lines = section_lines("Service")

    self.assertIn("User=mikroclear", service_lines)
    self.assertIn("Group=mikroclear", service_lines)
    self.assertIn("EnvironmentFile=/etc/mikroclear/mikroclear.env", service_lines)
    self.assertNotIn("EnvironmentFile=-/etc/mikroclear/mikroclear.env", service_lines)
```

Для candidate unit выполнить те же assertions внутри цикла по обоим unit-файлам.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_systemd_unit \
  tests.test_systemd_candidate_unit
```

Expected: FAIL с отсутствующими `User=mikroclear`, `Group=mikroclear` и strict `EnvironmentFile`.

- [ ] **Step 3: Update both unit files**

В обоих unit-файлах установить:

```ini
EnvironmentFile=/etc/mikroclear/mikroclear.env
User=mikroclear
Group=mikroclear
WorkingDirectory=/
```

Сохранить `ExecStart`, hardening, `ReadWritePaths` и `ReadOnlyPaths` без
ослабления.

- [ ] **Step 4: Verify unit tests and syntax**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_systemd_unit \
  tests.test_systemd_candidate_unit
systemd-analyze verify systemd/mikroclear.service
systemd-analyze verify deploy/systemd/mikroclear.service.candidate
```

Expected: unittest `OK`; systemd verification exits `0` without syntax errors.

- [ ] **Step 5: Commit**

```bash
git add systemd/mikroclear.service deploy/systemd/mikroclear.service.candidate \
  tests/test_systemd_unit.py tests/test_systemd_candidate_unit.py
git diff --cached --name-only
git commit -m "Run Mikro-Clear as dedicated service user"
```

---

### Task 3: Создать sourceable CLI-каркас установщика

**Files:**
- Create: `scripts/install-selks.sh`
- Create: `tests/test_selks_standalone_installer.py`

**Interfaces:**
- Produces Bash functions: `usage()`, `die(message)`, `parse_args(arguments)`,
  `choose_install_mode()`, `init_paths()`, `target_path(path)`,
  `main(arguments)`.
- Produces globals: `INSTALL_MODE`, `START_ONLY`, `TEST_MODE`, `TEST_ROOT`.
- Test contract: `source scripts/install-selks.sh` не запускает `main`.

- [ ] **Step 1: Write failing CLI tests**

Создать Python helper и тесты:

```python
from pathlib import Path
import os
import subprocess
import tempfile
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install-selks.sh"


def run_bash(body: str, *, env: dict[str, str] | None = None):
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"\n{body}'],
        cwd=ROOT,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
    )


class SelksStandaloneInstallerTests(TestCase):
    def test_source_does_not_execute_main(self):
        result = run_bash('printf "sourced\\n"')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "sourced\n")

    def test_parse_supported_modes(self):
        interactive = run_bash('parse_args --interactive; printf "%s:%s\\n" "$INSTALL_MODE" "$START_ONLY"')
        template = run_bash('parse_args --config-template; printf "%s:%s\\n" "$INSTALL_MODE" "$START_ONLY"')
        start = run_bash('parse_args --start; printf "%s:%s\\n" "$INSTALL_MODE" "$START_ONLY"')

        self.assertEqual(interactive.stdout, "interactive:false\n")
        self.assertEqual(template.stdout, "template:false\n")
        self.assertEqual(start.stdout, "existing:true\n")

    def test_unknown_argument_fails(self):
        result = run_bash("parse_args --unknown")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown argument: --unknown", result.stderr)

    def test_modes_are_mutually_exclusive(self):
        result = run_bash("parse_args --interactive --config-template")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("choose exactly one install mode", result.stderr)

    def test_menu_selects_one_of_two_install_modes(self):
        interactive = run_bash("choose_install_mode", env={"REPLY": "1"})
        template = run_bash("choose_install_mode", env={"REPLY": "2"})

        self.assertEqual(interactive.returncode, 0, interactive.stderr)
        self.assertEqual(interactive.stdout, "interactive\n")
        self.assertEqual(template.returncode, 0, template.stderr)
        self.assertEqual(template.stdout, "template\n")

    def test_test_root_requires_explicit_test_mode_and_tmp_path(self):
        with tempfile.TemporaryDirectory() as root:
            accepted = run_bash(
                'init_paths; target_path "/etc/mikroclear"',
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )
        rejected = run_bash(
            'init_paths',
            env={"MIKROCLEAR_INSTALLER_TEST_ROOT": "/tmp/not-authorized"},
        )

        self.assertEqual(accepted.returncode, 0)
        self.assertTrue(accepted.stdout.endswith("/etc/mikroclear"))
        self.assertNotEqual(rejected.returncode, 0)
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: ERROR/FAIL because `scripts/install-selks.sh` does not exist.

- [ ] **Step 3: Implement minimal guarded CLI**

Создать executable Bash script со следующими обязательными частями:

```bash
#!/usr/bin/env bash
set -euo pipefail

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
            --interactive) INSTALL_MODE="interactive"; ((selected += 1)) ;;
            --config-template) INSTALL_MODE="template"; ((selected += 1)) ;;
            --start) INSTALL_MODE="existing"; START_ONLY=true; ((selected += 1)) ;;
            --help) usage; return 2 ;;
            *) die "unknown argument: $1"; return 1 ;;
        esac
        shift
    done
    ((selected <= 1)) || die "choose exactly one install mode"
}

choose_install_mode() {
    local choice="${REPLY:-}"
    if [[ -z "${choice}" ]]; then
        printf '%s\n' "1) Интерактивная настройка" "2) Шаблон конфигурации" >&2
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
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
```

Сделать файл executable.

- [ ] **Step 4: Verify GREEN and Bash syntax**

Run:

```bash
chmod +x scripts/install-selks.sh
bash -n scripts/install-selks.sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: syntax exit `0`, unittest `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-selks.sh tests/test_selks_standalone_installer.py
git diff --cached --name-only
git commit -m "Add standalone installer CLI"
```

---

### Task 4: Добавить capability preflight и сборку committed HEAD

**Files:**
- Modify: `scripts/install-selks.sh`
- Modify: `tests/test_selks_standalone_installer.py`

**Interfaces:**
- Produces: `check_root()`, `python_version_ok()`,
  `collect_missing_commands()`, `offer_apt_install()`,
  `check_available_space(path,minimum_kib)`, `repo_commit()`,
  `create_source_snapshot(destination)`, `build_candidate_wheel(snapshot,out)`.
- `create_source_snapshot` всегда использует `git archive HEAD`, не копирование worktree.

- [ ] **Step 1: Add failing preflight and archive tests**

Добавить тесты:

```python
def test_python_floor_is_311(self):
    old = run_bash('python_version_ok "3.10"')
    current = run_bash('python_version_ok "3.11"')
    newer = run_bash('python_version_ok "3.13"')
    self.assertNotEqual(old.returncode, 0)
    self.assertEqual(current.returncode, 0)
    self.assertEqual(newer.returncode, 0)

def test_snapshot_uses_committed_head_only(self):
    with tempfile.TemporaryDirectory() as temp:
        repo = Path(temp) / "repo"
        snapshot = Path(temp) / "snapshot"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", repo], check=True)
        (repo / "tracked.txt").write_text("committed\n", encoding="utf-8")
        subprocess.run(["git", "-C", repo, "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", repo, "-c", "user.name=Test", "-c",
             "user.email=test@example.invalid", "commit", "-qm", "fixture"],
            check=True,
        )
        (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        result = run_bash(
            f'REPO_ROOT="{repo}"; create_source_snapshot "{snapshot}"'
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((snapshot / "tracked.txt").read_text(), "committed\n")
        self.assertFalse((snapshot / "untracked.txt").exists())

def test_installer_source_has_no_git_network_mutation(self):
    text = SCRIPT.read_text(encoding="utf-8")
    self.assertNotIn("git pull", text)
    self.assertNotIn("git fetch", text)
    self.assertNotIn("git checkout", text)

def test_dependency_install_uses_only_apt_after_confirmation(self):
    declined = run_bash(
        'apt-get(){ printf "APT_CALLED\\n"; }; '
        'printf "no\\n" | offer_apt_install git'
    )
    source = SCRIPT.read_text(encoding="utf-8")

    self.assertNotIn("APT_CALLED", declined.stdout)
    self.assertNotIn("dnf ", source)
    self.assertNotIn("yum ", source)
    self.assertNotIn("apk ", source)

def test_disk_space_check_fails_below_required_kib(self):
    result = run_bash(
        'available_kib(){ printf "100\\n"; }; '
        'check_available_space /opt 101'
    )
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("insufficient free space", result.stderr)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: FAIL because preflight/archive functions are undefined.

- [ ] **Step 3: Implement capability and source functions**

Добавить:

```bash
python_version_ok() {
    local version="$1"
    local major="${version%%.*}"
    local rest="${version#*.}"
    local minor="${rest%%.*}"
    ((major > 3 || (major == 3 && minor >= 11)))
}

collect_missing_commands() {
    local command_name
    for command_name in git install sha256sum openssl flock runuser systemctl \
        systemd-analyze python3; do
        command -v "${command_name}" >/dev/null 2>&1 ||
            printf '%s\n' "${command_name}"
    done
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
```

`offer_apt_install()` сопоставляет отсутствующие capability с пакетами
`python3`, `python3-venv`, `python3-pip`, `git`, `coreutils`, `openssl`,
`util-linux`, `systemd` и вызывает `apt-get update`/`apt-get install` только
после ответа `yes`. При отсутствии `apt-get` функция возвращает ошибку со
списком capability.

`available_kib(path)` читает `df -Pk --output=avail`, а
`check_available_space(path,minimum_kib)` завершается до mutation, если
доступно меньше запрошенного. Production preflight проверяет место для source
snapshot, candidate venv и полной копии текущего venv.

`build_candidate_wheel()` создаёт временный build venv, устанавливает
`setuptools>=68` и `wheel`, выполняет:

```bash
"${build_venv}/bin/python" -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "${output_dir}" "${snapshot}"
"${build_venv}/bin/python" \
    "${snapshot}/scripts/validate_wheel_artifact.py" "${output_dir}"/mikro_clear-*.whl
```

- [ ] **Step 4: Verify preflight tests**

Run:

```bash
bash -n scripts/install-selks.sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-selks.sh tests/test_selks_standalone_installer.py
git diff --cached --name-only
git commit -m "Build installer artifact from committed HEAD"
```

---

### Task 5: Реализовать service identity, каталоги, template и EVE preflight

**Files:**
- Modify: `scripts/install-selks.sh`
- Modify: `tests/test_selks_standalone_installer.py`

**Interfaces:**
- Produces: `ensure_service_identity()`, `install_layout()`,
  `write_template_config()`, `run_as_service_user(command arguments)`,
  `validate_target_paths()`, `verify_eve_access()`,
  `print_eve_remediation()`.
- Production paths проходят через `target_path()` только для test-root подстановки.

- [ ] **Step 1: Add failing filesystem tests**

Добавить тесты временного root:

```python
def test_template_layout_has_secure_modes(self):
    with tempfile.TemporaryDirectory() as root:
        result = run_bash(
            'init_paths; install_layout; write_template_config',
            env={
                "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
            },
        )
        env_file = Path(root) / "etc/mikroclear/mikroclear.env"
        state_dir = Path(root) / "var/lib/mikroclear"

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(env_file.stat().st_mode & 0o777, 0o640)
        self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
        self.assertIn("MIKROCLEAR_ROUTER_PASSWORD=", env_file.read_text())

def test_existing_template_is_not_overwritten(self):
    with tempfile.TemporaryDirectory() as root:
        env_file = Path(root) / "etc/mikroclear/mikroclear.env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("KEEP=1\n", encoding="utf-8")
        result = run_bash(
            'init_paths; write_template_config',
            env={
                "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(env_file.read_text(), "KEEP=1\n")

def test_eve_failure_does_not_change_selks_permissions(self):
    text = SCRIPT.read_text(encoding="utf-8")
    self.assertNotRegex(text, r"(chmod|chown|setfacl).*\$\{?EVE")
    result = run_bash(
        'run_as_service_user(){ return 1; }; '
        'namei(){ :; }; stat(){ :; }; verify_eve_access'
    )
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("eve.json is not readable by mikroclear", result.stderr)

def test_unexpected_symlink_target_is_rejected_before_layout_changes(self):
    with tempfile.TemporaryDirectory() as root:
        etc = Path(root) / "etc"
        etc.mkdir()
        (etc / "mikroclear").symlink_to("/tmp")
        result = run_bash(
            "init_paths; validate_target_paths",
            env={
                "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected symlink", result.stderr)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: FAIL because layout/template/EVE functions are undefined.

- [ ] **Step 3: Implement identity and secure layout**

Production:

```bash
ensure_service_identity() {
    getent group mikroclear >/dev/null ||
        groupadd --system mikroclear
    id -u mikroclear >/dev/null 2>&1 ||
        useradd --system --gid mikroclear --no-create-home \
            --home-dir /nonexistent --shell /usr/sbin/nologin mikroclear
}
```

`install_layout()` создаёт exact modes из спецификации. В test mode владельцы
не меняются, но режимы и пути совпадают. `write_template_config()` копирует
`config/mikroclear.env.example` во временный файл того же каталога, применяет
`0640` и выполняет `mv` только если target отсутствует.
`validate_target_paths()` до первой mutation проверяет каждый целевой
`/opt`, `/etc`, `/var` path и отвергает symlink или обычный файл там, где
ожидается каталог.

Production runtime check:

```bash
run_as_service_user() {
    runuser -u mikroclear -- "$@"
}

verify_eve_access() {
    if run_as_service_user test -r "${EVE_PATH}"; then
        return 0
    fi
    namei -l "${EVE_PATH}" >&2 || true
    stat -c '%U:%G %a %n' "${EVE_PATH}" >&2 || true
    print_eve_remediation >&2
    die "eve.json is not readable by mikroclear"
}
```

`print_eve_remediation()` только печатает найденный group-membership или ACL
вариант и команду повторной проверки; команда не выполняется.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
bash -n scripts/install-selks.sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-selks.sh tests/test_selks_standalone_installer.py
git diff --cached --name-only
git commit -m "Prepare secure standalone runtime layout"
```

---

### Task 6: Реализовать интерактивную конфигурацию и безопасную работу с CA

**Files:**
- Modify: `scripts/install-selks.sh`
- Modify: `tests/test_selks_standalone_installer.py`

**Interfaces:**
- Produces: `collect_interactive_config()`, `render_config()`,
  `print_masked_summary()`, `validate_ca_source(path)`,
  `install_ca(source)`, `write_config_atomic(content)`,
  `validate_existing_config()`.
- Secrets хранятся только в shell variables и stdin, не в argv.

- [ ] **Step 1: Add failing config/security tests**

Добавить:

```python
def test_rendered_config_uses_safe_defaults(self):
    result = run_bash(
        'ROUTER_USERNAME=api; ROUTER_PASSWORD=secret; ROUTER_IP=192.0.2.1; '
        'USE_SSL=true; ROUTER_PORT=8729; TLS_SERVER_NAME=router.example; '
        'ALLOW_SELF_SIGNED=false; TELEGRAM_ENABLE=false; TELEGRAM_TOKEN=; '
        'TELEGRAM_CHATID=; render_config'
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("MIKROCLEAR_CA_FILE=/etc/mikroclear/certs/mikrotik-ca.crt", result.stdout)
    self.assertIn("MIKROCLEAR_MANGLE_CONTROL_ENABLE=false", result.stdout)
    self.assertIn("MIKROCLEAR_BOT_DRY_RUN=true", result.stdout)

def test_env_renderer_quotes_special_characters_and_rejects_newlines(self):
    quoted = run_bash("env_line SECRET 'space # quote\" backslash\\\\'")
    rejected = run_bash("env_line SECRET $'first\\nsecond'")

    self.assertEqual(quoted.returncode, 0, quoted.stderr)
    self.assertEqual(
        quoted.stdout,
        r'SECRET="space # quote\" backslash\\"' + "\n",
    )
    self.assertNotEqual(rejected.returncode, 0)
    self.assertIn("newline is not allowed in environment value", rejected.stderr)

def test_summary_masks_all_secrets(self):
    result = run_bash(
        'ROUTER_USERNAME=api; ROUTER_PASSWORD=router-secret; '
        'ROUTER_IP=192.0.2.1; ROUTER_PORT=8729; USE_SSL=true; '
        'TELEGRAM_ENABLE=true; TELEGRAM_TOKEN=telegram-secret; '
        'TELEGRAM_CHATID=42; print_masked_summary'
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertNotIn("router-secret", result.stdout)
    self.assertNotIn("telegram-secret", result.stdout)
    self.assertGreaterEqual(result.stdout.count("***"), 2)

def test_atomic_writer_preserves_existing_file_on_failure(self):
    with tempfile.TemporaryDirectory() as root:
        env_file = Path(root) / "etc/mikroclear/mikroclear.env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("OLD=1\n", encoding="utf-8")
        result = run_bash(
            'init_paths; validate_config_text(){ return 1; }; '
            'write_config_atomic "NEW=1"',
            env={
                "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(env_file.read_text(), "OLD=1\n")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: FAIL because config functions are undefined.

- [ ] **Step 3: Implement interactive collection and atomic write**

`collect_interactive_config()` использует `read -r` и `read -r -s` для пароля
и Telegram token. Он проверяет непустые RouterOS username/password/host,
числовой порт 1..65535, TLS choice и CA source. `env_line(key,value)` отвергает
CR/LF, экранирует обратную косую черту и двойную кавычку и записывает
`KEY="escaped value"`, поэтому пробелы, `#` и кавычки в паролях не меняют
структуру systemd EnvironmentFile.

`render_config()` печатает полный env с canonical paths:

```bash
printf '%s\n' \
  "MIKROCLEAR_ROUTER_USERNAME=${ROUTER_USERNAME}" \
  "MIKROCLEAR_ROUTER_PASSWORD=${ROUTER_PASSWORD}" \
  "MIKROCLEAR_ROUTER_IP=${ROUTER_IP}" \
  "MIKROCLEAR_USE_SSL=${USE_SSL}" \
  "MIKROCLEAR_ROUTER_PORT=${ROUTER_PORT}" \
  "MIKROCLEAR_ALLOW_SELF_SIGNED_CERTS=${ALLOW_SELF_SIGNED}" \
  "MIKROCLEAR_CA_FILE=/etc/mikroclear/certs/mikrotik-ca.crt" \
  "MIKROCLEAR_ROUTER_TLS_SERVER_NAME=${TLS_SERVER_NAME}" \
  "MIKROCLEAR_MANGLE_CONTROL_ENABLE=false" \
  "MIKROCLEAR_TELEGRAM_ENABLE=${TELEGRAM_ENABLE}" \
  "MIKROCLEAR_TELEGRAM_TOKEN=${TELEGRAM_TOKEN}" \
  "MIKROCLEAR_TELEGRAM_CHATID=${TELEGRAM_CHATID}" \
  "MIKROCLEAR_BOT_ENABLE=${TELEGRAM_ENABLE}" \
  "MIKROCLEAR_BOT_DRY_RUN=true" \
  "MIKROCLEAR_BOT_MODULES=status,asset_resolver,mangle_control,parental_control" \
  "MIKROCLEAR_EVE_JSON=/opt/SELKS/docker/containers-data/suricata/logs/eve.json" \
  "MIKROCLEAR_STATE_DIR=/var/lib/mikroclear"
```

Перед записью `print_masked_summary()` выводит только mask для двух секретов.
`write_config_atomic()` использует `umask 077`, `mktemp` внутри
`/etc/mikroclear`, validation, `chown root:mikroclear`, `chmod 0640`, `mv`.

`validate_ca_source()` выполняет:

```bash
openssl x509 -in "${source}" -noout
```

`install_ca()` копирует только в canonical CA path через временный файл,
`root:mikroclear`, `0640`. Self-signed bypass записывается только после явного
ответа с предупреждением.

- [ ] **Step 4: Verify config tests**

Run:

```bash
bash -n scripts/install-selks.sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: `OK`; captured stdout does not contain fixture secrets.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-selks.sh tests/test_selks_standalone_installer.py
git diff --cached --name-only
git commit -m "Add secure interactive installer configuration"
```

---

### Task 7: Реализовать candidate venv, backup и обратимое переключение

**Files:**
- Modify: `scripts/install-selks.sh`
- Modify: `tests/test_selks_standalone_installer.py`

**Interfaces:**
- Produces: `acquire_install_lock()`, `prepare_candidate_venv(wheel)`,
  `create_backup()`, `switch_candidate_venv()`, `restore_previous_venv()`,
  `finalize_successful_update()`, `install_unit_candidate()`,
  `write_manifest(status)`.
- Globals: `BACKUP_DIR`, `CANDIDATE_VENV`, `ROLLBACK_VENV`,
  `HAD_PREVIOUS_INSTALL`.

- [ ] **Step 1: Add failing switch/restore tests**

Добавить:

```python
def test_candidate_switch_and_restore_are_exact(self):
    with tempfile.TemporaryDirectory() as root:
        opt = Path(root) / "opt"
        current = opt / "mikroclear-venv"
        candidate = opt / ".mikroclear-venv.candidate"
        current.mkdir(parents=True)
        candidate.mkdir()
        (current / "version").write_text("old\n", encoding="utf-8")
        (candidate / "version").write_text("new\n", encoding="utf-8")
        result = run_bash(
            'init_paths; CANDIDATE_VENV="$(target_path /opt/.mikroclear-venv.candidate)"; '
            'ROLLBACK_VENV="$(target_path /opt/.mikroclear-venv.rollback)"; '
            'switch_candidate_venv; restore_previous_venv',
            env={
                "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((current / "version").read_text(), "old\n")

def test_backup_preserves_unit_env_ca_and_manifest(self):
    with tempfile.TemporaryDirectory() as root:
        fixtures = {
            "etc/systemd/system/mikroclear.service": b"unit\n",
            "etc/mikroclear/mikroclear.env": b"SECRET=value\n",
            "etc/mikroclear/certs/mikrotik-ca.crt": b"certificate\n",
            "var/lib/mikroclear/install-manifest": b"commit=old\n",
        }
        for relative, content in fixtures.items():
            source = Path(root) / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)

        result = run_bash(
            'init_paths; '
            'BACKUP_DIR="$(target_path /var/backups/mikroclear/test-backup)"; '
            'create_backup',
            env={
                "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        backup = Path(root) / "var/backups/mikroclear/test-backup"
        expected = {
            "mikroclear.service": b"unit\n",
            "mikroclear.env": b"SECRET=value\n",
            "mikrotik-ca.crt": b"certificate\n",
            "install-manifest": b"commit=old\n",
        }
        for name, content in expected.items():
            with self.subTest(name=name):
                self.assertEqual((backup / name).read_bytes(), content)

def test_second_installer_cannot_take_held_lock(self):
    with tempfile.TemporaryDirectory() as root:
        result = run_bash(
            'init_paths; '
            'LOCK_FILE="$(target_path /run/lock/mikroclear-install.lock)"; '
            'mkdir -p "$(dirname "$LOCK_FILE")"; '
            'exec 8>"$LOCK_FILE"; flock -n 8; acquire_install_lock',
            env={
                "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another installer is running", result.stderr)
```

`create_backup()` уважает заранее установленный `BACKUP_DIR` в test mode; в
production он всегда создаёт timestamp-каталог сам.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: FAIL because candidate/backup functions are undefined.

- [ ] **Step 3: Implement staged venv and backup**

`prepare_candidate_venv()`:

```bash
python3 -m venv "${CANDIDATE_VENV}"
"${CANDIDATE_VENV}/bin/python" -m pip install --upgrade pip
"${CANDIDATE_VENV}/bin/python" -m pip install "${wheel}"
(
    cd /
    "${CANDIDATE_VENV}/bin/python" -c \
        'import mikroclear, pathlib; print(pathlib.Path(mikroclear.__file__).resolve())'
)
```

Путь импорта обязан находиться внутри candidate `site-packages`. Проверить:

```bash
if "${CANDIDATE_VENV}/bin/python" -m pip show mcp >/dev/null 2>&1; then
    die "candidate runtime unexpectedly contains mcp"
fi
```

`create_backup()` создаёт
`/var/backups/mikroclear/<UTC timestamp>/`, копирует unit/env/CA/manifest с
сохранением mode/owner и записывает pre-update `pip freeze`.

`switch_candidate_venv()` останавливает сервис только на update, перемещает
старый venv в `/opt/.mikroclear-venv.rollback.<timestamp>`, затем candidate в
`/opt/mikroclear-venv`. Все перемещения выполняются на `/opt`, чтобы возврат
был rename на том же filesystem.

`restore_previous_venv()` удаляет failed venv из active path только через
перемещение в `${BACKUP_DIR}/failed-venv`, затем возвращает rollback path.
`finalize_successful_update()` после успешного acceptance перемещает
`ROLLBACK_VENV` в `${BACKUP_DIR}/venv`, чтобы backup содержал точный старый
runtime вместе со всеми зависимостями.

- [ ] **Step 4: Verify switch/restore tests**

Run:

```bash
bash -n scripts/install-selks.sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: `OK`, old fixture восстановлен byte-for-byte.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-selks.sh tests/test_selks_standalone_installer.py
git diff --cached --name-only
git commit -m "Stage reversible Mikro-Clear updates"
```

---

### Task 8: Добавить orchestration, acceptance и автоматический rollback

**Files:**
- Modify: `scripts/install-selks.sh`
- Modify: `tests/test_selks_standalone_installer.py`

**Interfaces:**
- Produces: `install_or_update()`, `start_existing_install()`,
  `install_template_mode()`, `install_interactive_mode()`,
  `accept_install(timeout=90)`, `rollback_update()`, `show_diagnostics()`.
- Acceptance markers: `Connected to MikroTik`, `Telegram polling worker started`.
- Result codes: clean install failure nonzero/stopped; update failure nonzero after verified rollback.

- [ ] **Step 1: Add failing orchestration tests**

Добавить:

```python
def test_failed_update_runs_rollback_and_returns_nonzero(self):
    result = run_bash(
        'events=""; '
        'create_backup(){ events+=" backup"; }; '
        'prepare_candidate_venv(){ events+=" prepare"; }; '
        'switch_candidate_venv(){ events+=" switch"; }; '
        'install_unit_candidate(){ events+=" unit"; }; '
        'accept_install(){ events+=" accept"; return 1; }; '
        'rollback_update(){ events+=" rollback"; return 0; }; '
        'HAD_PREVIOUS_INSTALL=true; '
        'install_or_update || rc=$?; printf "%s|%s\\n" "${rc:-0}" "$events"'
    )
    self.assertEqual(result.stdout, "1| backup prepare switch unit accept rollback\n")

def test_clean_failure_stops_without_rollback(self):
    result = run_bash(
        'events=""; '
        'prepare_candidate_venv(){ events+=" prepare"; }; '
        'switch_candidate_venv(){ events+=" switch"; }; '
        'install_unit_candidate(){ events+=" unit"; }; '
        'accept_install(){ events+=" accept"; return 1; }; '
        'stop_service(){ events+=" stop"; }; '
        'HAD_PREVIOUS_INSTALL=false; '
        'install_or_update || rc=$?; printf "%s|%s\\n" "${rc:-0}" "$events"'
    )
    self.assertEqual(result.stdout, "1| prepare switch unit accept stop\n")

def test_acceptance_checks_required_markers_conditionally(self):
    text = SCRIPT.read_text(encoding="utf-8")
    self.assertIn("Connected to MikroTik", text)
    self.assertIn("Telegram polling worker started", text)
    self.assertIn("NRestarts", text)
    self.assertIn("User", text)
    self.assertIn("Group", text)
    self.assertIn("WorkingDirectory", text)

def test_template_mode_preserves_existing_running_install(self):
    result = run_bash(
        'events=""; existing_install(){ return 0; }; '
        'stop_service(){ events+=" stop"; }; '
        'write_template_config(){ events+=" write"; }; '
        'install_template_mode || rc=$?; '
        'printf "%s|%s\\n" "${rc:-0}" "$events"'
    )
    self.assertEqual(result.stdout, "1|\n")
    self.assertIn("existing installation", result.stderr)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: FAIL because orchestration and acceptance are undefined.

- [ ] **Step 3: Implement acceptance and rollback**

`accept_install()` records activation timestamp, starts/enables the service, and
polls until timeout:

```bash
systemctl show mikroclear.service \
  --property=ActiveState,SubState,NRestarts,User,Group,WorkingDirectory,MainPID \
  --no-pager
journalctl -u mikroclear.service --since "@${ACTIVATION_EPOCH}" --no-pager
```

Success requires:

```text
ActiveState=active
SubState=running
NRestarts=0
User=mikroclear
Group=mikroclear
WorkingDirectory=/
```

Также проверить `ps -o user= -p MainPID`, чтение EVE, запись временного файла
от `mikroclear`, marker `Connected to MikroTik` и отсутствие
`Traceback|Fatal Telegram polling worker error`.

`validate_existing_config()` безопасно читает только нужные keys без `source`.
Если `MIKROCLEAR_TELEGRAM_ENABLE=true`, acceptance дополнительно требует
`Telegram polling worker started` и `TasksCurrent>=2`.

`rollback_update()` восстанавливает rollback venv, unit/env/CA/manifest,
выполняет `systemctl daemon-reload`, restart и минимально проверяет
`active/running`, `NRestarts=0`. При ошибке rollback печатает отдельный
`ROLLBACK FAILED` и возвращает отдельный ненулевой код.

`main()` связывает режимы:

```bash
if [[ -z "${INSTALL_MODE}" ]]; then
    INSTALL_MODE="$(choose_install_mode)"
fi
case "${INSTALL_MODE}" in
    template) install_template_mode ;;
    interactive) install_interactive_mode ;;
    existing) start_existing_install ;;
    *) die "unsupported install mode: ${INSTALL_MODE}" ;;
esac
```

- [ ] **Step 4: Run focused installer tests**

Run:

```bash
bash -n scripts/install-selks.sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_standalone_installer
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-selks.sh tests/test_selks_standalone_installer.py
git diff --cached --name-only
git commit -m "Add installer acceptance and rollback"
```

---

### Task 9: Переписать русскую установочную документацию

**Files:**
- Rewrite: `docs/ru/install-from-github.md`
- Modify: `docs/ru/env-reference.md`
- Create: `docs/ru/install-test-reproduction.md`
- Modify: `README.md:Russian deployment and operator documentation`
- Create: `tests/test_install_documentation.py`

**Interfaces:**
- Consumes: exact CLI and paths из Tasks 1–8.
- Produces: canonical automated/manual Russian guide и reproducible Debian test matrix.

- [ ] **Step 1: Write failing documentation contract tests**

Создать:

```python
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/ru/install-from-github.md"
REPRO = ROOT / "docs/ru/install-test-reproduction.md"


class InstallDocumentationTests(TestCase):
    def test_guide_covers_both_modes_and_manual_install(self):
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "./scripts/install-selks.sh",
            "--interactive",
            "--config-template",
            "--start",
            "Ручная установка",
            "Обновление",
            "Rollback",
            "/status",
            "Debian 12",
            "Debian 13",
        ):
            self.assertIn(required, text)

    def test_new_install_docs_have_no_external_or_legacy_install_dependency(self):
        for path in (GUIDE, REPRO):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("/etc/mikrocata/certs", text)
            self.assertNotIn("/home/mgm/.ssh", text)
            self.assertNotIn("mcp-selks", text.lower())
            self.assertNotIn("MCP", text)

    def test_reproduction_matrix_is_executable(self):
        text = REPRO.read_text(encoding="utf-8")
        for required in (
            "Debian 12",
            "Debian 13",
            "Чистая установка",
            "Повторный запуск",
            "Успешное обновление",
            "Неуспешное обновление",
            "rollback",
            "eve.json",
            "Telegram выключен",
            "Telegram включён",
        ):
            self.assertIn(required, text)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_install_documentation
```

Expected: FAIL because the current guide assumes SSH/existing venv and reproduction document is absent.

- [ ] **Step 3: Write complete Russian operator guide**

`docs/ru/install-from-github.md` must contain exact commands for:

```bash
git clone https://github.com/paveltarasov50-coder/Mikro-Clear.git
cd Mikro-Clear
git switch --detach <tag-or-commit>
sudo ./scripts/install-selks.sh
sudo ./scripts/install-selks.sh --interactive
sudo ./scripts/install-selks.sh --config-template
sudoedit /etc/mikroclear/mikroclear.env
sudo ./scripts/install-selks.sh --start
systemctl show mikroclear.service \
  --property=ActiveState,SubState,NRestarts,User,Group,WorkingDirectory,MainPID \
  --no-pager
journalctl -u mikroclear.service -n 100 --no-pager
```

Добавить полный ручной эквивалент: prerequisites, user/group, modes, clean
archive, wheel build/validation, venv, env, CA, unit, EVE check, start,
acceptance, backup и rollback. Секреты показывать только как пустые значения.

- [ ] **Step 4: Write reproduction matrix and update references**

`docs/ru/install-test-reproduction.md` должен дать:

- создание snapshot чистой VM;
- команды для Debian 12 и 13;
- template/interactive сценарии;
- fake/local boundary для автоматических RouterOS/Telegram проверок;
- operator-only test RouterOS/test bot сценарии;
- EVE permission failure;
- idempotent rerun;
- successful update;
- acceptance failure injection только через sourceable test functions;
- rollback verification;
- команды очистки и возврата VM snapshot;
- таблицу evidence: OS, Python, commit, wheel SHA, paths/modes, systemd,
  acceptance/rollback, secret scan.

В `docs/ru/env-reference.md` заменить CA path и добавить владельца/mode env/CA.
В `README.md` добавить ссылку на reproduction document.

- [ ] **Step 5: Verify docs and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_install_documentation
if rg -n '/etc/mikrocata/certs|/home/mgm/.ssh|mcp-selks|MCP' \
  docs/ru/install-from-github.md docs/ru/install-test-reproduction.md; then
  exit 1
fi
```

Expected: unittest `OK`; scan produces no matches.

Commit:

```bash
git add README.md docs/ru/install-from-github.md docs/ru/env-reference.md \
  docs/ru/install-test-reproduction.md tests/test_install_documentation.py
git diff --cached --name-only
git commit -m "Document standalone SELKS installation"
```

---

### Task 10: Выполнить полный regression и зафиксировать verification report

**Files:**
- Create: `docs/superpowers/reports/2026-07-24-selks-standalone-installation-verification.md`
- Modify if failures demand it: only files already named in Tasks 1–9, using a new RED/GREEN cycle.

**Interfaces:**
- Consumes: completed implementation and docs.
- Produces: evidence-backed local verification report; production deploy remains out of scope.

- [ ] **Step 1: Run static and focused checks**

Run:

```bash
bash -n scripts/install-selks.sh
shellcheck scripts/install-selks.sh
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_settings \
  tests.test_standalone_install_contract \
  tests.test_wheel_artifact_validation \
  tests.test_systemd_unit \
  tests.test_systemd_candidate_unit \
  tests.test_selks_standalone_installer \
  tests.test_install_documentation
```

Expected: all commands exit `0`, unittest reports `OK`.

- [ ] **Step 2: Run the complete Python regression suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/mikroclear-pycache \
  git ls-files '*.py' | xargs .venv/bin/python -m py_compile
```

Expected: all tests pass; compilation exits `0`.

- [ ] **Step 3: Build and inspect the exact committed artifact**

После коммита Tasks 1–9:

```bash
build_dir="$(mktemp -d /tmp/mikroclear-install-verify.XXXXXX)"
git archive HEAD | tar -x -C "${build_dir}"
.venv/bin/python -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir "${build_dir}/dist" "${build_dir}"
.venv/bin/python scripts/validate_wheel_artifact.py \
  "${build_dir}"/dist/mikro_clear-*.whl
unzip -p "${build_dir}"/dist/mikro_clear-*.whl \
  '*/METADATA' | rg '^Requires-Dist:'
sha256sum "${build_dir}"/dist/mikro_clear-*.whl
```

Expected: validator prints `wheel ok`; metadata has no `Requires-Dist: mcp`;
SHA-256 is recorded in the report.

- [ ] **Step 4: Run unit/document/secret checks**

Run:

```bash
systemd-analyze verify systemd/mikroclear.service
systemd-analyze verify deploy/systemd/mikroclear.service.candidate
if rg -n '/etc/mikrocata/certs|/home/mgm/.ssh|mcp-selks|MCP' \
  scripts/install-selks.sh docs/ru/install-from-github.md \
  docs/ru/install-test-reproduction.md; then
  exit 1
fi
git diff --check
git status --short
```

Expected: unit verification and diff check exit `0`; forbidden scan is empty;
status contains only intentionally preserved user-owned files plus this task's
uncommitted report.

- [ ] **Step 5: Write the verification report with actual evidence**

Сначала получить фактические значения:

```bash
git rev-parse HEAD
sha256sum /tmp/mikroclear-install-verify.*/dist/mikro_clear-*.whl
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
```

Затем через `apply_patch` создать отчёт с заголовком
`# SELKS Standalone Installation Verification`, датой `2026-07-24` и
фактическими строками commit SHA, wheel SHA-256 и количеством тестов из этих
команд. Раздел `Local automated verification` содержит результаты каждого
шага 1–4. Раздел `VM matrix` перечисляет каждый реально выполненный Debian
12/13 сценарий; невыполненный live RouterOS/Telegram или production SELKS
сценарий записывается как `NOT RUN — requires operator test environment`, а не
как PASS. Раздел `Remaining operator acceptance` содержит точные команды из
`docs/ru/install-test-reproduction.md` для тестового SELKS.

- [ ] **Step 6: Commit verification evidence**

```bash
git add docs/superpowers/reports/2026-07-24-selks-standalone-installation-verification.md
git diff --cached --name-only
git commit -m "Record standalone installer verification"
```

- [ ] **Step 7: Final clean-scope review**

Run:

```bash
git log --oneline --decorate -12
git status --short
git diff -- requirements.txt
```

Expected: feature commits are present; user-owned `requirements.txt` and swap
file remain uncommitted and unchanged by this plan. Do not deploy or restart
production SELKS in this task.
