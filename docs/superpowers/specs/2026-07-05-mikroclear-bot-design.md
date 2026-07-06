# Mikro-Clear Telegram Control Plane Design

## Goal

Design `mikroclear-bot` as an extensible Telegram control plane for Mikro-Clear.
The bot must not become a collection of separate services. It should run as one
service with modular command handlers and shared safety controls.

The first implementation slice should make `/status` the initial read-only
module in this architecture.

## Non-Goals

- Do not deploy to production SELKS as part of this design.
- Do not create or change MikroTik firewall filter rules without a separate
  explicit operator confirmation.
- Do not manage NAT, routes, system users, RouterOS services, or global firewall
  rules.
- Do not add new production credentials to the repository.

## Recommended Shape

Keep the bot inside the existing Mikro-Clear package under a dedicated namespace:

```text
src/mikroclear/
  bot/
    __init__.py
    app.py
    settings.py
    auth.py
    audit.py
    routeros_session.py
    telegram_io.py
    dispatcher.py

    modules/
      __init__.py
      status.py
      mangle_control.py
      parental_control.py
      asset_resolver.py
```

The Telegram transport layer receives updates, authenticates the chat/operator,
dispatches commands or callback actions, and sends responses. Feature logic lives
in modules. RouterOS access, audit logging, dry-run handling, and authorization
are shared infrastructure.

This keeps one service/runtime while avoiding a larger `legacy.py` control plane.

## Core Components

### Bot Settings

`mikroclear.bot.settings` loads bot-specific settings from environment variables
while reusing existing Mikro-Clear Telegram and RouterOS configuration.

Settings include enabled modules, dry-run mode, admin chat IDs, allowed chat IDs,
Mangle allowlists, parental-control list names, and audit log path.

### Auth

`mikroclear.bot.auth` owns authorization decisions:

- read actions require `MIKROCLEAR_BOT_ALLOWED_CHAT_IDS` or admin access;
- write actions require `MIKROCLEAR_BOT_ADMIN_CHAT_IDS`;
- unknown chats receive no privileged data;
- every rejected write attempt is logged.

### Audit

`mikroclear.bot.audit` records every write attempt and result. Each record should
include timestamp, Telegram chat/operator identity, module, action, target, dry-run
state, result, and error text if applicable. Audit output must not contain secrets.

### RouterOS Session

`mikroclear.bot.routeros_session` reuses existing RouterOS TLS/client behavior and
provides narrow helpers to modules. It must not expose generic write access to
Telegram handlers.

### Dispatcher

`mikroclear.bot.dispatcher` maps Telegram commands and callback tokens to module
handlers. It should support both text commands and inline keyboard callbacks.
Write actions should prefer callback tokens over free-form text.

## v1 Modules

### status

Read-only module and first implementation target.

Commands:

- `/status`

Response fields:

- service uptime;
- RouterOS connection state based on current client state;
- monitored EVE path;
- primary block address-list name;
- monitor-only mode;
- bot dry-run mode;
- enabled bot modules;
- Telegram unblock enabled state;
- state directory.

The response must not include Telegram tokens, RouterOS passwords, cookies,
authorization headers, or raw environment content.

### asset_resolver

Read-only support module for displaying devices.

Sources:

- MikroTik DHCP leases;
- fallback PTR DNS lookup;
- existing local resolver behavior where useful.

Displayed fields:

- IP address;
- MAC address when known;
- hostname when known;
- DHCP comment when known;
- source of the name.

The module should be reusable by `parental_control` so device labels are
consistent across commands.

### mangle_control

Read/write module for managed Mangle rules only.

Allowed scope:

- `/ip firewall mangle` rules where `comment` starts with `MC:`.
- only chains listed in `MIKROCLEAR_MANGLE_ALLOWED_CHAINS`;
- only actions listed in `MIKROCLEAR_MANGLE_ALLOWED_ACTIONS`.

Operations:

- list managed Mangle rules;
- enable a managed rule;
- disable a managed rule.

All writes require admin allowlist, pass through dry-run handling, and create an
audit record. The module must not accept arbitrary RouterOS paths from Telegram.

### parental_control

Read/write module for controlled internet blocking.

Allowed scope:

- only the address-list configured as `MIKROCLEAR_PARENTAL_ADDRESS_LIST`;
- default list name: `MC-Parental-Blocked`.

Operations:

- list managed devices;
- show current status for a device;
- block a selected device;
- unblock a selected device;
- temporary block for 15, 30, or 60 minutes.

The bot v1 may add or remove address-list entries only. It must not create,
modify, enable, or disable the firewall filter rule used to enforce blocking.

For DHCP-managed devices, the module should resolve the current IP from DHCP lease
data before writing. Audit records should include IP and MAC when known.

## Environment Variables

```text
MIKROCLEAR_BOT_ENABLE=false
MIKROCLEAR_BOT_DRY_RUN=true

MIKROCLEAR_BOT_ADMIN_CHAT_IDS=
MIKROCLEAR_BOT_ALLOWED_CHAT_IDS=

MIKROCLEAR_BOT_MODULES=status,asset_resolver,mangle_control,parental_control

MIKROCLEAR_MANGLE_COMMENT_PREFIX=MC:
MIKROCLEAR_MANGLE_ALLOWED_CHAINS=prerouting
MIKROCLEAR_MANGLE_ALLOWED_ACTIONS=mark-routing

MIKROCLEAR_PARENTAL_ADDRESS_LIST=MC-Parental-Blocked
MIKROCLEAR_PARENTAL_ALLOWED_TIMEOUTS=15m,30m,60m
MIKROCLEAR_PARENTAL_COMMENT_PREFIX=MC:

MIKROCLEAR_ASSET_RESOLVER_DHCP_ENABLE=true
MIKROCLEAR_ASSET_RESOLVER_PTR_ENABLE=true
MIKROCLEAR_ASSET_RESOLVER_CACHE_TTL=3600

MIKROCLEAR_BOT_AUDIT_LOG=/var/lib/mikroclear/bot-audit.log
```

Existing Telegram token/chat ID and RouterOS credential/TLS settings remain the
source of connection credentials. Example env files must keep secret values blank.

## RouterOS Prerequisites

### Parental Control Firewall Rule

An operator must create the enforcement rule manually before enabling write
actions:

```text
/ip firewall filter
add chain=forward src-address-list=MC-Parental-Blocked action=drop comment="MC:Parental-Block"
```

The bot v1 may verify that a rule with comment `MC:Parental-Block` exists and
warn if it does not. It must not create or change this rule without a separate
explicit confirmation workflow outside v1.

### Mangle Rules

Managed Mangle rules must have comments starting with `MC:` and must also match
the configured chain/action allowlists. Rules without that prefix are out of
scope even if their chain/action would otherwise be allowed.

### DHCP Leases

For device display and parental-control targeting, RouterOS read access should
allow reading DHCP leases. PTR fallback may use DNS lookups where available.

## Security Rules

- Bot write actions require admin allowlist.
- Bot read actions require allowed-chat allowlist or admin access.
- Every write action is audited.
- Dry-run mode defaults to enabled.
- Write handlers must check managed scope before checking requested action.
- `mangle_control` may modify only `MC:` Mangle rules with allowed chains/actions.
- `parental_control` may modify only `MC-Parental-Blocked` entries.
- No module may change NAT, routes, RouterOS users, RouterOS services, or global
  firewall rules.
- Responses and logs must mask secrets.
- Telegram free-form text must not become a generic RouterOS command channel.

## Risks And Mitigations

### Accidentally Touching Unmanaged RouterOS Objects

Risk: a broad query or ID reuse could affect a rule not owned by Mikro-Clear.

Mitigation: filter by comment prefix and module-specific scope before any write.
Tests should use fake RouterOS resources containing both managed and unmanaged
objects.

### Parental Control Target Drift

Risk: blocking by IP can become stale when DHCP assigns a new address.

Mitigation: resolve the current DHCP lease before writing, display MAC/IP/hostname
to the operator, and audit both MAC and IP when known.

### Dangerous Telegram UX

Risk: free-form commands can be ambiguous and may encourage unsafe parsing.

Mitigation: use lists and inline callbacks for write actions. Keep text commands
for read-only actions and entry points.

### Dry-Run Confusion

Risk: operators may think a write happened when dry-run is enabled, or vice versa.

Mitigation: `/status` and every write response must explicitly show dry-run state.
Audit records must also include dry-run state.

### Shared Runtime Coupling

Risk: combining alert processing and bot control plane can increase shared state.

Mitigation: keep bot modules behind narrow interfaces and avoid direct mutation of
alert processing state. Shared objects should be settings, RouterOS session, auth,
audit, and Telegram I/O only.

## Implementation Order

1. Add bot settings, auth, audit, dispatcher, and `status` module with tests.
2. Wire `/status` into Telegram polling as the first read-only command.
3. Add `asset_resolver` read-only module and tests.
4. Add `parental_control` in dry-run mode with fake RouterOS tests.
5. Add `mangle_control` in dry-run mode with fake RouterOS tests.
6. Only after local tests and operator review, plan SELKS deployment separately.

## Acceptance Criteria

- `/status` works for allowed chats and rejects unknown chats.
- `/status` contains no secrets and shows dry-run state.
- Write-capable modules cannot be invoked by non-admin chats.
- Dry-run mode prevents RouterOS writes while still logging intended actions.
- Parental control writes are limited to `MC-Parental-Blocked`.
- Mangle writes are limited to `MC:` rules with allowed chains/actions.
- Unit tests cover allowed and rejected operations for every module.
