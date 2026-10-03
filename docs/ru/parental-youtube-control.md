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

## Ручные действия в production

Этот раздел фиксирует ручные действия оператора и результаты preflight. Секреты, session SID и содержимое credential files в документацию не помещаются.

### SELKS

Подтверждена текущая конфигурация production service:

```text
Service: mikroclear.service
State: active (running)
ExecStart: /opt/mikroclear-venv/bin/python -m mikroclear
EnvironmentFile: /etc/mikroclear/mikroclear.env
Service account: mikroclear:mikroclear
Writable runtime path: /var/lib/mikroclear
Environment file: root:mikroclear, mode 640
```

Доступ service account к environment file подтверждён:

```text
sudo -u mikroclear test -r /etc/mikroclear/mikroclear.env: PASS
```

До deployment новой версии production runtime остаётся на `3.1.1-TZSP0-ASSET-RESOLVER`. Это ожидаемое состояние до установки нового artifact.

### Pi-hole TLS

Production Pi-hole доступен по адресу `https://pihole.21port.ru` и IP `192.168.10.32`.

Проверенный сертификат:

```text
CN: 21port.ru
SAN: *.21port.ru, 21port.ru
Issuer: Let's Encrypt
```

Hostname validation проходит для `https://pihole.21port.ru`. Она не проходит для `https://192.168.10.32` и `https://pi.hole`, поэтому production environment должен использовать:

```text
MIKROCLEAR_PIHOLE_BASE_URL=https://pihole.21port.ru
MIKROCLEAR_PIHOLE_VERIFY_TLS=true
```

`--insecure` и `verify=False` не используются как workaround.

### Pi-hole application password и API

Отдельный Pi-hole application password создан оператором вручную и хранится только вне Git. В production environment вручную заданы:

```text
MIKROCLEAR_PIHOLE_BASE_URL=https://pihole.21port.ru
MIKROCLEAR_PIHOLE_APP_PASSWORD=<SECRET STORED OUTSIDE GIT>
MIKROCLEAR_PIHOLE_VERIFY_TLS=true
```

Пароль не хранится в Git и не выводится в документацию, логи или Telegram. Временный Pi-hole SID используется только внутри API session и не сохраняется в environment.

Проверка выполнялась от имени service account `mikroclear`:

```text
Pi-hole URL: https://pihole.21port.ru
TLS verification: True
Application password: SET
Authentication: PASS
GET /api/groups: PASS
GET /api/clients: PASS
API session logout: PASS
```

Текущее состояние Pi-hole:

```text
groups: 1
clients: 0
MikroClear-YouTube-Blocked: NOT CONFIGURED
```

Во время preflight не выполнялись `POST /api/clients`, `PUT /api/clients/*`, `DELETE`, создание YouTube group, создание domain rules или изменение group memberships. Исключения составили только `POST /api/auth` и `DELETE /api/auth` для открытия и закрытия временной session.

### RouterOS API

Подтверждён существующий production RouterOS API-SSL endpoint:

```text
Endpoint: 192.168.10.1:8729
API SSL: enabled
RouterOS credentials: SET
RouterOS authentication: PASS
```

Используется существующий API user. Новый RouterOS user для Parental Control не создаётся. Parental adapter остаётся read-only независимо от фактических прав production account и не использует SSH/Telnet parsing.

### MC-Parental

Выполнена read-only проверка:

```text
MC-Parental entries: 0
MC-Parental: NOT CONFIGURED
```

В RouterOS не требуется заранее создавать отдельный объект address-list. Список фактически появляется после добавления первой записи. Команда ниже приведена только как будущая write-stage reference и во время preflight не выполнялась:

```routeros
/ip firewall address-list add list=MC-Parental address=<IP> comment="<DEVICE>"
```

### Pilot device

Выбран первый pilot candidate:

```text
Device: Samsung TV
Hostname: Samsung
Comment: Televizor_Spalnaya
IPv4: 192.168.10.48
MAC: 64:E7:D8:10:CB:3C
DHCP: bound, static lease, dynamic=false, disabled=false
```

Устройство пока не добавлено в `MC-Parental`.

### DNS anti-bypass

MikroTik уже используется для сетевого DNS enforcement. Parental Control MVP не меняет RouterOS firewall dynamically.

RouterOS policy предусматривает:

```text
обычный DNS -> только Pi-hole
external DNS TCP/UDP 53 -> blocked
DoT/DoQ TCP/UDP 853 -> blocked
```

Потенциальные bypass paths, требующие отдельной политики: DoH TCP/443, DoH3/QUIC UDP/443, VPN, proxy, Tor, embedded resolvers и IPv6. Весь TCP/443 не блокируется.

### Что ещё не выполнено

```text
[ ] hotfix merged into main
[ ] new Mikro-Clear artifact built
[ ] new artifact deployed to SELKS
[ ] MikroClear-YouTube-Blocked created
[ ] YouTube regex rules assigned
[ ] Samsung 192.168.10.48 added to MC-Parental
[ ] parental feature enabled
[ ] Pi-hole integration enabled
[ ] Telegram pilot BLOCK tested
[ ] Telegram pilot ALLOW tested
[ ] IPv6 bypass validated
[ ] rollback tested
```

### Что намеренно не выполнялось во время preflight

- production service не перезапускался;
- wheel не устанавливался;
- RouterOS firewall, NAT, mangle и routes не изменялись;
- DHCP lease не изменялся;
- запись в `MC-Parental` не создавалась;
- Pi-hole YouTube group не создавалась;
- Pi-hole clients не создавались;
- Pi-hole memberships не изменялись;
- parental feature не включалась;
- Telegram BLOCK/ALLOW не выполнялся.
