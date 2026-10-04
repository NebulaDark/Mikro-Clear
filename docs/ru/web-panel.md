# Mikro-Clear Web Panel MVP

Ветка разработки: `feature/web-control-panel-mvp`.

## Назначение

Web Panel — отдельный control-plane для Mikro-Clear. Он не заменяет основной Suricata processing loop и не запускается внутри `mikroclear.service`.

MVP предоставляет: обзор RouterOS, Suricata alerts из `eve.json`, block address-list, подтверждаемый Unblock, managed Mangle control, чтение явно смонтированного log-файла, audit и безопасный просмотр настроек без секретов.

## Архитектура

Browser → HTTPS/reverse proxy → Vue 3 SPA → FastAPI → existing Mikro-Clear adapters → librouteros API-SSL.

Контейнер не получает Docker socket, root, произвольный shell или SSH/Telnet к RouterOS.

## Безопасность

- отдельный Web login;
- пароль и session secret только через environment;
- SameSite=Strict session cookie; Secure cookie включается для HTTPS;
- CSRF для write actions;
- short-lived one-time confirmation token;
- повторная проверка managed Mangle rule перед update;
- `MONITOR_ONLY` блокирует RouterOS writes;
- mangle ограничен существующими rules, прошедшими comment-prefix/chain/action allowlist;
- unblock работает только с `MIKROCLEAR_BLOCK_LIST_NAME`;
- audit write-actions;
- UID 10001, read-only root filesystem, drop ALL capabilities, no-new-privileges.

## Первый запуск

1. Скопировать `docker/web/mikroclear-web.env.example` в `docker/web/mikroclear-web.env` и сделать `chmod 600`.
2. Сгенерировать `MIKROCLEAR_WEB_SESSION_SECRET` командой `openssl rand -hex 32`.
3. Задать отдельный `MIKROCLEAR_WEB_ADMIN_PASSWORD`.
4. Первый запуск делать с `MIKROCLEAR_MONITOR_ONLY=true` и `MIKROCLEAR_MANGLE_CONTROL_ENABLE=false`.
5. CA RouterOS положить в `docker-data/certs/mikrotik-ca.crt` либо переопределить `MIKROCLEAR_CERTS_HOST_DIR`.
6. Сборка: `docker compose -f docker-compose.web.yml build`.
7. Запуск: `docker compose -f docker-compose.web.yml up -d`.
8. Healthcheck: `curl http://127.0.0.1:8080/healthz`.

Compose публикует сервис только на `127.0.0.1` по умолчанию. Для production использовать reverse proxy с HTTPS.

При прямом локальном HTTP-тесте временно установить `MIKROCLEAR_WEB_SECURE_COOKIE=false`. Для HTTPS вернуть `true`.

## Логи

`eve.json` монтируется read-only. Web panel намеренно не вызывает `journalctl` и не получает `/var/run/docker.sock`. Дополнительный лог читается только из файла, явно указанного через `MIKROCLEAR_WEB_LOG_FILE` и смонтированного read-only.

## Проверки перед merge

- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`
- `git ls-files '*.py' | xargs .venv/bin/python -m py_compile`
- установить extra: `pip install '.[web]'` и проверить импорт `mikroclear.web.app`;
- `docker compose -f docker-compose.web.yml config`;
- `docker compose -f docker-compose.web.yml build`.

До этих проверок ветку не считать готовой к deploy.