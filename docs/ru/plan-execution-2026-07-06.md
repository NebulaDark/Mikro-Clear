# Plan execution 2026-07-06

Дата: 2026-07-06.

Этот отчет фиксирует выполнение шагов 1-5 из
`docs/ru/project-status-plan-2026-07-06.md`.

## 1. State reconciliation

Статус: operator reported done, service health verified.

Что проверено:

```text
mikroclear.service: active/running
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
NRestarts=0
```

Попытка выполнить root/operator block для `/var/lib/mikroclear` уперлась в
ограничение текущего SSH/MCP пользователя:

```text
sudo: a terminal is required to read the password
sudo: a password is required
```

Также подтверждено:

```text
sudo -n ls -la /var/lib/mikroclear /var/lib/mikrocata
sudo: a password is required
```

После operator run service был проверен:

```text
ActiveState=active
SubState=running
NRestarts=0
ExecMainStartTimestamp=Mon 2026-07-06 14:33:25 MSK
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
```

Ограничение остается: текущий SSH/MCP пользователь не может напрямую
подтвердить содержимое `/var/lib/mikroclear` через `sudo -n stat`, потому что
sudo все еще требует пароль. Фактический file listing/mode check должен быть
снят sudo-capable operator output.

## 2. Observation checks

Статус: service health verified, journal visibility limited.

После operator reconciliation service был перезапущен и проверен:

```text
ActiveState=active
SubState=running
NRestarts=0
ExecMainStartTimestamp=Mon 2026-07-06 14:33:25 MSK
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
```

MCP status позднее подтвердил, что service продолжал работать:

```text
Active: active (running) since Mon 2026-07-06 12:15:12 MSK
Main PID: python -m mikroclear
```

Ограничение: текущий пользователь не видит system journal entries для
`mikroclear.service` без membership в `adm`/`systemd-journal` или sudo.

## 3. Remove legacy env fallback from tracked systemd

Статус: подготовлено в branch
`feature/remove-legacy-fallback-and-hardening-plan`.

Из tracked unit и deploy candidate удалены:

```text
EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env
/etc/mikrocata from ReadOnlyPaths
/var/lib/mikrocata from ReadWritePaths
```

Tracked unit теперь использует только:

```text
EnvironmentFile=-/etc/mikroclear/mikroclear.env
ReadWritePaths=/var/lib/mikroclear
ReadOnlyPaths=/opt/SELKS/docker/containers-data/suricata/logs /etc/mikroclear
```

Production deploy этого unit не выполнялся. Deploy остается gated до
operator state reconciliation.

## 4. Compatibility shim deprecation

Статус: выполнено без runtime behavior change.

Deprecated compatibility docstrings добавлены в top-level shim files:

```text
src/mikroclear/asset_resolver.py
src/mikroclear/state_store.py
src/mikroclear/eve_watcher.py
src/mikroclear/telegram_notify.py
src/mikroclear/telegram_polling.py
src/mikroclear/telegram_unblock.py
src/mikroclear/routeros_client.py
src/mikroclear/routeros_tls.py
src/mikroclear/alert_logic.py
src/mikroclear/events.py
```

Runtime warnings intentionally not added, so production logs stay quiet.

Detailed deprecation gates:

```text
docs/ru/compatibility-shim-deprecation.md
```

## 5. Dedicated service user

Статус: подготовлен cutover checklist, production unit не переведен.

Причина: service user cutover требует root/operator проверки ownership,
Suricata `eve.json` access, RouterOS TLS file access и state writability.

Документ:

```text
docs/ru/dedicated-service-user-cutover.md
```

Tracked unit пока остается:

```ini
User=root
Group=root
```

## Verification

Пройдено:

```text
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
Ran 196 tests - OK

git ls-files '*.py' | xargs .venv/bin/python -m py_compile
OK

PYTHONPATH=src .venv/bin/python -c "import mikroclear.app as app; svc = app.build_service(); print(type(svc).__name__)"
MikroClearService
```

Secret scan:

```text
No real secrets found.
Matches are limited to test fixture passwords and historical plan documents.
```

`systemd-analyze verify` note:

```text
Local verify is not a clean signal in this workspace:
- sandbox run failed with SO_PASSCRED;
- unrestricted run reported missing /opt/mikroclear-venv/bin/python locally;
- deploy/systemd/mikroclear.service.candidate is not accepted directly because
  it does not use a .service filename.
```

The unit behavior is covered by focused tests instead.

## Next required operator action

Run state reconciliation on SELKS as sudo-capable operator, then collect a real
journal/status observation window. Only after that should the cleaned systemd
unit be deployed.
