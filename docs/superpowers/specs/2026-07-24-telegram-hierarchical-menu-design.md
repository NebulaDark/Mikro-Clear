# Mikro-Clear Telegram Hierarchical Menu Design

## Goal

Add a button-first Telegram interface to Mikro-Clear without replacing the
existing command interface or creating another polling worker.

An authorized user initializes the interface with `/start`. Telegram then shows
one persistent reply-keyboard button:

```text
🛡 Mikro-Clear
```

Pressing it opens an inline hierarchy for status, Mangle and managed whitelist
functions. Existing `/status` and `/mangle` commands remain supported as
fallback entry points.

## Scope

The first version includes:

- `/start` and `/menu` entry points for installing or restoring the launcher;
- one persistent reply-keyboard button named `🛡 Mikro-Clear`;
- a dynamic inline main menu;
- `📊 Статус → 🛡 Общий статус`;
- `📊 Статус → 🔀 Mangle` with detailed rule information;
- `🔀 Mangle` with compact enabled/disabled control buttons;
- `🛡 Исключения` with read-only system entries and removable entries added
  through Telegram;
- an alert action that permanently excludes an RFC1918 IPv4 address and removes
  its current RouterOS block;
- editing the current menu message after navigation or a successful change;
- an extensible module registry for future bot functions;
- compatibility with `/status`, `/mangle`, alert Unblock, authorization,
  confirmation, dry-run, audit, retry and polling behavior.

The first version does not implement device or parental-control behavior. Those
modules can register menu entries later when their handlers are production
ready.

## Telegram UI Model

The design uses two Telegram keyboard types:

- `ReplyKeyboardMarkup` supplies the persistent launcher below the input field;
- `InlineKeyboardMarkup` supplies navigation and actions inside bot messages.

The Bot API supports `is_persistent` and `resize_keyboard` for reply keyboards,
inline callback buttons, callback answers and editing messages with inline
keyboards:

- <https://core.telegram.org/bots/api>
- <https://core.telegram.org/api/bots/buttons>

The launcher markup is equivalent to:

```json
{
  "keyboard": [[{"text": "🛡 Mikro-Clear"}]],
  "is_persistent": true,
  "resize_keyboard": true
}
```

The bot sends this markup only after an authorized `/start` or `/menu`. Telegram
may not allow a bot to initiate a conversation with a user, so service startup
does not send unsolicited menu messages. `/start` and `/menu` can restore the
launcher if a Telegram client hides or loses it.

## Navigation

### Main Menu

```text
Mikro-Clear

[ 📊 Статус ]  [ 🔀 Mangle ]
[ 🛡 Исключения ]
```

Only enabled modules that the current user may access are shown. Disabled or
unauthorized modules do not appear as locked placeholders.

### Status Menu

```text
Статус

[ 🛡 Общий статус ]
[ 🔀 Mangle ]
[ ⬅️ Назад ]
```

`🛡 Общий статус` reuses the existing status snapshot and formatter.

`Статус → Mangle` is read-only and shows:

```text
✅ Site
Chain: prerouting
Action: mark-routing
Packets: 0
Bytes: 0

[ 🔄 Обновить ]  [ ⬅️ Назад ]
```

Detailed Chain, Action, Packets and Bytes fields are not repeated in the Mangle
control screen.

### Mangle Control Menu

```text
Управление Mangle

✅ — правило включено
❌ — правило выключено

[ ✅ Site ]
[ ❌ Backup route ]
[ 🔄 Обновить ]
[ ⬅️ Назад ]
```

The icon describes the current RouterOS state:

- `✅ Name` means the rule is enabled; pressing it requests disable;
- `❌ Name` means the rule is disabled; pressing it requests enable.

Only rules whose comment starts with the configured `MC:` prefix are managed.
Rule shape, chain and action are display data, not additional ownership gates.

### Managed Exceptions Menu

The exceptions entry is visible only to an administrator when
`MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE=true`.

```text
Исключения

Системные — только просмотр:
🔒 192.168.10.1
🔒 10.20.0.0/16

Добавлены через Telegram:
🛡 192.168.98.200
🛡 192.168.10.10

[ 🗑 192.168.98.200 ]
[ 🗑 192.168.10.10 ]
[ 🔄 Обновить ] [ ⬅️ Назад ]
```

System entries come from `MIKROCLEAR_WHITELIST_IPS`. They are displayed but
cannot be changed from Telegram. Managed entries are exact RFC1918 IPv4
addresses stored by Mikro-Clear. The list is paginated and sorted
deterministically.

Removing a managed entry requires confirmation. A successful removal does not
block the address immediately. The next matching Suricata alert may block it
again through the normal alert-processing path. The first version does not
accept free-form addresses; managed entries can be added only from a security
alert.

## Menu Architecture

### Menu Registry

A menu registry provides the extension boundary. Each registered item has:

- a stable identifier;
- a user-facing label;
- display order;
- required permission: read or admin;
- an enabled predicate based on bot settings;
- a renderer or action adapter.

The registry filters entries for the current chat and settings before building
the keyboard. A future module adds one registry entry and its own adapter
without adding conditions to a central command chain.

The first registry contains:

- `status`, requiring read access;
- `mangle_control`, requiring admin access and an enabled Mangle module;
- `whitelist_control`, requiring admin access and enabled Telegram whitelist
  control.

### Menu Controller

One menu controller:

- recognizes `/start`, `/menu` and the exact launcher label;
- builds the persistent launcher;
- dispatches `menu:v1:*` callbacks;
- authenticates every message and callback;
- renders the current view;
- asks the Telegram transport to send or edit the view.

Navigation is stateless. The callback encodes the destination, so there is no
per-user server-side menu session to expire or migrate.

Example callbacks:

```text
menu:v1:root
menu:v1:status
menu:v1:status:general
menu:v1:status:mangle
menu:v1:mangle
```

Callback data contains only routes or short-lived action tokens and stays under
Telegram's callback-data limit. It never contains passwords, Telegram tokens,
complete RouterOS rules or other secrets.

### Existing Runtime Integration

The existing `TelegramUpdatePoller` remains the only consumer of Telegram
updates. Menu message handling is inserted before the legacy slash-command
fallback. Menu callbacks are handled before existing Mangle and Unblock action
callbacks, with each handler returning whether it consumed the update.

Existing module behavior remains behind explicit adapters:

- the status adapter calls the existing status snapshot and formatter;
- the Mangle adapter calls the existing managed-rule reader and mutation flow;
- the whitelist adapter calls the system policy, managed store and
  add/remove workflows.

The controller does not synthesize slash-command strings internally. This avoids
special cases around Mangle callbacks and keeps buttons and commands as two
entry points to the same module behavior.

## Telegram Transport Changes

The existing send-message boundary already accepts reply markup. The menu needs
an additional narrow edit boundary supporting the fields required to update a
bot message:

- chat ID;
- message ID;
- text;
- inline reply markup;
- parse mode;
- timeout.

Every inline callback is answered promptly to stop the Telegram client spinner.
Rendering and editing occur after that acknowledgement unless a retryable
delivery path requires the current polling lifecycle to retry.

If an edit fails because the source message can no longer be edited, the bot
sends a new current view. The failed edit does not authorize an action twice.

## Mangle Mutation Flow

Mangle keeps its current callback namespace and short-lived tokens:

```text
mangle:request:<token>
mangle:confirm:<token>
mangle:cancel:<token>
mangle:refresh
```

When `MIKROCLEAR_MANGLE_REQUIRE_CONFIRMATION=true`:

1. pressing a compact rule button creates or resolves an action token;
2. the message asks whether to enable or disable the named rule;
3. confirm performs the existing authorized mutation;
4. cancel performs no RouterOS write;
5. after success, the bot reads managed rules again and renders the control
   screen with the actual state.

When confirmation is disabled, the request proceeds directly to the same
authorized mutation and refresh path.

The icon is never changed optimistically. RouterOS is the source of truth after
every mutation. If the write fails or the token is stale, the bot reports the
failure and refreshes from the current RouterOS state.

Dry-run performs no RouterOS mutation, records the request in the audit log,
explicitly reports that the rule was not changed and keeps the previous icon.

## Dynamic Whitelist Architecture

### Persistent Store

`DynamicWhitelistStore` owns only Telegram-managed entries. Its default path is:

```text
<state-dir>/dynamic-whitelist.json
```

The versioned document contains sorted, unique exact IPv4 addresses:

```json
{
  "version": 1,
  "addresses": [
    "192.168.98.200"
  ]
}
```

Only addresses in `10.0.0.0/8`, `172.16.0.0/12` or `192.168.0.0/16` are
accepted. Public, loopback, link-local, multicast, unspecified, IPv6 and CIDR
input is rejected. These restrictions apply only to entries created from
Telegram; the existing system whitelist retains its current exact-IP and CIDR
support.

Store updates use an in-process lock and an atomic same-directory temporary
file, flush, `fsync` and replace sequence. File permissions remain restricted to
the service account. A missing file means an empty managed list. Invalid JSON,
an unsupported version or an invalid stored address prevents service startup
with a clear error rather than silently dropping exclusions.

### Effective Whitelist

`WhitelistPolicy` evaluates the union of:

- the immutable system entries loaded from `MIKROCLEAR_WHITELIST_IPS`;
- the current snapshot from `DynamicWhitelistStore`.

Alert processing obtains the current effective snapshot for every event, so a
Telegram change applies without a service restart. Matching remains exact IP or
CIDR matching; prefix-string matching is forbidden.

The policy is checked before a RouterOS add and before a Telegram `BLOCKED`
notification. A subsequent matching event for a managed address is therefore
skipped by the same path as an existing system-whitelist match: it is not
blocked again and does not emit another blocked alert.

### Add-And-Unblock Operation

The confirmed alert action executes in this order:

1. repeat authorization and feature checks;
2. validate the exact RFC1918 IPv4 address;
3. persist it through `DynamicWhitelistStore`;
4. remove it from the configured RouterOS address-list;
5. read RouterOS again and report the factual result.

Persistence happens before RouterOS removal so another event cannot re-add the
address between the two operations. If persistence fails, RouterOS is not
changed. If persistence succeeds but RouterOS removal fails, the managed
exception remains active and the result is reported as partial success. The
result view offers `🔄 Повторить разблокировку`, which retries only the factual
RouterOS removal for that already-managed address.

The operation uses a common low-level RouterOS removal adapter. It does not call
the upper-level ordinary Unblock policy after persisting the address, because
that policy correctly rejects a target that is already whitelisted.

## Authorization And Safety

- `/start`, `/menu` and the launcher require an allowed or admin chat.
- General and Mangle status require read access.
- Mangle control requires the admin allowlist.
- Managed-whitelist viewing and mutation require the admin allowlist.
- Every callback repeats authorization and module-enabled checks.
- A callback from an old message cannot bypass current settings.
- Every Mangle write attempt and result is audited.
- Every whitelist add, remove, dry-run, failure and partial result is audited.
- Dry-run remains enabled by default.
- No free-form Telegram text becomes a generic RouterOS command.
- Logs and callback data contain no credentials or Telegram Bot API URLs with
  unmasked tokens.
- No second update poller, service or RouterOS client lifecycle is introduced.

## Alert And Unblock Integration

Security alert messages remain outside the hierarchical menu. Their existing
text and buttons do not change. An additional managed-exception action is added
only for an administrator, an RFC1918 IPv4 target, and enabled Unblock and
whitelist-control features.

The alert keyboard keeps:

- the exact label `🔓 Unblock <IP>`;
- `AbuseIPDB` and `VirusTotal` links;
- the existing confirm and cancel step;
- existing callback names;
- existing token lifetime and single-use behavior;
- the existing managed address-list and authorization checks.

The additional row is:

```text
[ 🛡 Добавить в исключения <IP> ]
```

It opens:

```text
Добавить <IP> в постоянные исключения
и удалить из RouterOS Suricata?

[ ✅ Добавить и разблокировать ]
[ ❌ Отмена ]
```

After confirmed success, the alert text remains unchanged and only the new
button changes to `✅ В исключениях <IP>`. The status button is safe to press
again and reports that the address is already excluded.

After partial success, the alert text still remains unchanged. The keyboard
shows both `✅ В исключениях <IP>` and `🔄 Повторить разблокировку`. The retry
uses a new single-use token and never rewrites or removes the managed exception.

Whitelist callbacks use the `whitelist:v1:*` namespace and short-lived,
single-use tokens bound to the action, address, address-list and chat. Confirm
repeats authorization, feature, dry-run and address-scope checks. Stale or
replayed tokens cannot mutate the store or RouterOS.

The existing ordinary Unblock flow remains intact except for correcting its
RouterOS argument order. The common helper contract is:

```text
remove_from_address_list(resource, list_name, address)
```

Regression coverage must prove that `list_name` and `address` cannot be reversed
again.

## Whitelist Configuration And Dry-Run

The new control is explicitly gated:

```text
MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE=false
```

It is disabled by default. The alert add action is shown only when both this
setting and `MIKROCLEAR_TELEGRAM_UNBLOCK_ENABLE` are enabled. The exceptions
menu is shown when whitelist control is enabled and the current chat is an
administrator.

The general status snapshot reports whitelist-control on/off state, the managed
store path and the number of managed entries. It does not print the full address
list; that remains available only in the administrator menu.

`MIKROCLEAR_BOT_DRY_RUN=true` applies to managed add and remove operations. In
dry-run, neither the JSON store nor RouterOS changes. The bot explicitly reports
that the exception was not added or removed and that the address was not
unblocked, while the attempt is still audited.

## Error Handling

- Unauthorized messages and callbacks disclose no status or rule data.
- Disabled modules return a concise unavailable response when an old callback is
  pressed, even though they are absent from new menus.
- Expired Mangle tokens do not mutate RouterOS and trigger a fresh control view.
- A RouterOS read failure preserves the last visible state and reports that the
  refresh failed.
- A RouterOS write failure preserves actual state and is audited.
- A managed-whitelist persistence failure performs no RouterOS mutation.
- A RouterOS failure after whitelist persistence is reported as partial success;
  the persisted protection is not rolled back.
- Repeated add and removal of a missing managed address are idempotent.
- A corrupt dynamic-whitelist file fails startup before events are consumed.
- Retryable Telegram send, edit and callback-answer failures use the existing
  polling backoff and worker-health semantics.
- Non-retryable edit failure falls back to a new message without replaying a
  successful RouterOS mutation.

## Automated Test Contract

All automatic tests use fake Telegram and RouterOS boundaries. They must not
call the real Telegram API, a live RouterOS device or production SELKS.

Coverage includes:

- authorized `/start` and `/menu` launcher markup;
- rejection of unauthorized launcher requests;
- main-menu registry filtering by permission and enabled modules;
- stable `menu:v1:*` callback parsing;
- status submenu navigation;
- general status reuse;
- detailed read-only Mangle status without write buttons;
- compact `✅` and `❌` labels in Mangle control;
- enabled-to-disable and disabled-to-enable action selection;
- confirmation enabled and disabled paths;
- actual-state refresh after successful mutation;
- no icon change after failure or dry-run;
- stale-token and unauthorized-callback rejection;
- edit-message success and safe send-message fallback;
- prompt callback acknowledgement;
- compatibility of `/status` and `/mangle`;
- unchanged alert text, `🔓 Unblock <IP>`, external links, confirm and cancel
  callbacks;
- correct `list_name, address` ordering in ordinary Unblock and the common
  RouterOS removal adapter;
- exact IP and CIDR whitelist matching without string-prefix matching;
- acceptance of only RFC1918 exact IPv4 entries from Telegram;
- dynamic-store load, atomic write, idempotent add and remove, locking and
  corrupt-file startup failure;
- live union of system and managed whitelist entries without restart;
- suppression of repeated RouterOS blocking and `BLOCKED` notification for a
  managed address;
- managed-exception button visibility by address scope, feature flags and admin
  authorization;
- add confirmation, cancel, stale token, replayed token and success paths;
- persistence failure, RouterOS partial failure, removal-only retry and dry-run
  paths;
- read-only system entries, removable managed entries and pagination;
- confirmed removal without immediate RouterOS blocking;
- proof that one polling worker handles messages and callbacks.

Focused tests are followed by the complete `unittest` suite, Python compilation,
secret/forbidden-string scans and relevant project verification commands.

## Operator Acceptance

Live verification is a separate, approval-gated stage using a test RouterOS rule
with an `MC:` comment and a test Telegram bot/chat.

The operator verifies:

1. `/start` installs the single persistent launcher.
2. The launcher opens the dynamic main menu.
3. general status and detailed Mangle status render correctly.
4. an enabled test rule appears as `✅`.
5. confirmation changes it to disabled and the refreshed button appears as `❌`.
6. a second action restores `✅`.
7. dry-run leaves RouterOS and the icon unchanged.
8. audit output records attempted and completed actions without secrets.
9. a private alert target can be added to managed exceptions and is immediately
   absent from RouterOS `Suricata`.
10. the dynamic JSON contains the exact address and the exceptions menu shows it
    separately from system entries.
11. replaying the controlled EVE fixture does not block the managed address or
    send another `BLOCKED` alert.
12. removing it through the menu does not immediately block it.
13. replaying the controlled fixture after removal restores normal blocking.
14. `/status`, `/mangle` and ordinary alert Unblock still work.

Production deploy, restart and mutation are not part of implementation or
automatic tests and require a separate explicit approval. Installation and
reproduction use Git and repository scripts only; MCP is not part of the
installation path.

## Acceptance Criteria

The design is complete when:

- normal interaction requires buttons after one authorized `/start`;
- commands remain functional fallbacks;
- only available and authorized modules appear;
- status details and Mangle controls are separated;
- compact Mangle icons reflect actual RouterOS state;
- confirmation, dry-run, audit and managed ownership are preserved;
- ordinary alert Unblock works with the `🔓` icon and correct RouterOS argument
  ordering;
- administrators can permanently exclude only exact RFC1918 IPv4 alert targets;
- effective whitelist changes apply without a service restart;
- add-and-unblock prevents repeat blocking and reports partial failure safely;
- system whitelist entries remain configuration-owned and read-only;
- managed entries can be listed, paginated and removed with confirmation;
- future modules can register without adding another poller or central
  conditional chain;
- local tests prove the safety and compatibility boundaries.
