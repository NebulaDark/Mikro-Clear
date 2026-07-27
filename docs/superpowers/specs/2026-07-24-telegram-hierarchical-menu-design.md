# Mikro-Clear Telegram Hierarchical Menu Design

## Goal

Add a button-first Telegram interface to Mikro-Clear without replacing the
existing command interface or creating another polling worker.

An authorized user initializes the interface with `/start`. Telegram then shows
one persistent reply-keyboard button:

```text
🛡 Mikro-Clear
```

Pressing it opens an inline hierarchy for status and Mangle functions. Existing
`/status` and `/mangle` commands remain supported as fallback entry points.

## Scope

The first version includes:

- `/start` and `/menu` entry points for installing or restoring the launcher;
- one persistent reply-keyboard button named `🛡 Mikro-Clear`;
- a dynamic inline main menu;
- `📊 Статус → 🛡 Общий статус`;
- `📊 Статус → 🔀 Mangle` with detailed rule information;
- `🔀 Mangle` with compact enabled/disabled control buttons;
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
- `mangle_control`, requiring admin access and an enabled Mangle module.

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
- the Mangle adapter calls the existing managed-rule reader and mutation flow.

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

## Authorization And Safety

- `/start`, `/menu` and the launcher require an allowed or admin chat.
- General and Mangle status require read access.
- Mangle control requires the admin allowlist.
- Every callback repeats authorization and module-enabled checks.
- A callback from an old message cannot bypass current settings.
- Every Mangle write attempt and result is audited.
- Dry-run remains enabled by default.
- No free-form Telegram text becomes a generic RouterOS command.
- Logs and callback data contain no credentials or Telegram Bot API URLs with
  unmasked tokens.
- No second update poller, service or RouterOS client lifecycle is introduced.

## Alert And Unblock Non-Regression Contract

Security alert messages remain outside the hierarchical menu. Their content and
button behavior do not change.

The alert keyboard keeps:

- the exact label `🔓 Unblock <IP>`;
- `AbuseIPDB` and `VirusTotal` links;
- the existing confirm and cancel step;
- existing callback names;
- existing token lifetime and single-use behavior;
- the existing managed address-list and authorization checks.

The current repository already implements and tests the `🔓` label. This menu
work adds it to the broader regression boundary but does not rewrite the Unblock
flow.

## Error Handling

- Unauthorized messages and callbacks disclose no status or rule data.
- Disabled modules return a concise unavailable response when an old callback is
  pressed, even though they are absent from new menus.
- Expired Mangle tokens do not mutate RouterOS and trigger a fresh control view.
- A RouterOS read failure preserves the last visible state and reports that the
  refresh failed.
- A RouterOS write failure preserves actual state and is audited.
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
- unchanged `🔓 Unblock <IP>`, external links, confirm and cancel callbacks;
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
9. `/status`, `/mangle` and alert Unblock still work.

Production deploy, restart and mutation are not part of implementation or
automatic tests and require a separate explicit approval.

## Acceptance Criteria

The design is complete when:

- normal interaction requires buttons after one authorized `/start`;
- commands remain functional fallbacks;
- only available and authorized modules appear;
- status details and Mangle controls are separated;
- compact Mangle icons reflect actual RouterOS state;
- confirmation, dry-run, audit and managed ownership are preserved;
- alert Unblock remains unchanged with the `🔓` icon;
- future modules can register without adding another poller or central
  conditional chain;
- local tests prove the safety and compatibility boundaries.
