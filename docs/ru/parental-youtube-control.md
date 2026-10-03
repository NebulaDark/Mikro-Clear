# Родительский контроль YouTube

## Назначение

Mikro-Clear показывает устройства из RouterOS address-list `MC-Parental` и управляет только membership Pi-hole группы `MikroClear-YouTube-Blocked`.

- устройство находится в группе — YouTube заблокирован;
- устройство не находится в группе — YouTube разрешён;
- остальные Pi-hole groups устройства сохраняются;
- Telegram action доступен только admin chat и требует confirmation.

Все новые настройки по умолчанию выключены. Включение требует `MIKROCLEAR_PARENTAL_CONTROL_ENABLE=true`, `MIKROCLEAR_PIHOLE_ENABLE=true` и application password Pi-hole в environment file. Пароль не хранится в Git и не выводится в Telegram или логах.

`MIKROCLEAR_PIHOLE_BASE_URL` задаётся только через environment. При включённой интеграции URL должен быть непустым и использовать hostname или IP, который присутствует в SAN TLS-сертификата Pi-hole. Для текущего production Pi-hole проверен адрес `https://pihole.21port.ru`; код не подставляет endpoint автоматически.

## Подготовка

1. На RouterOS вручную создать static DHCP lease и добавить IP устройства в `MC-Parental`.
2. В Pi-hole вручную создать группу `MikroClear-YouTube-Blocked`.
3. Назначить regex из `config/parental/youtube-domains.txt` только этой группе.
4. Создать отдельный Pi-hole application password и настроить HTTPS CA.
5. Проверить anti-bypass DNS rules RouterOS и IPv6 topology до pilot.

В MVP Mikro-Clear читает RouterOS inventory и изменяет Pi-hole group membership через REST API. Он не добавляет устройства, не меняет firewall/mangle/NAT rules и не блокирует DoH, VPN или QUIC автоматически.

## Безопасность и отказоустойчивость

Pi-hole session создаётся лениво. После `401` выполняется одна re-auth попытка; timeout, `429`, `5xx`, TLS и malformed JSON превращаются в контролируемые ошибки. Callback tokens одноразовые, привязаны к chat/user и истекают через `MIKROCLEAR_PARENTAL_ACTION_TTL_SECONDS`.

Перед изменением policy IP повторно проверяется в `MC-Parental`; после изменения состояние перечитывается из Pi-hole. Локальная shadow copy blocked/allowed не используется.

## Ограничения

DNS/DoT enforcement не блокирует DoH через TCP/443, VPN, proxy или embedded resolver. IPv4-only firewall checks недостаточны при активном IPv6. Эти меры требуют отдельного read-only preflight и отдельного security review.
