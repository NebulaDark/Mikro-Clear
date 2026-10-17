# Parental Telegram Device Flow Design

## Goal

Сделать Telegram-интерфейс Parental Control последовательным: раздел, выбор устройства, затем действия YouTube для выбранного устройства.

## User flow

1. В корневом меню отображается `📺 Родительский контроль`.
2. Экран Parental Control показывает список управляемых устройств с иконкой `📺`.
3. Нажатие на устройство открывает экран устройства с именем, IP, текущим состоянием YouTube и кнопками действия.
4. Действия `🔒 Заблокировать YouTube` и `🔓 Разрешить YouTube` запускают существующий confirmation flow с TTL, one-shot token и проверкой chat/user ownership.
5. На экране устройства доступны `🔄 Обновить` и `⬅️ Назад`.

## Architecture

Изменения ограничиваются Telegram presentation и server-side selection state. RouterOS inventory остаётся источником списка устройств, Pi-hole policy остаётся источником состояния YouTube, а callback token продолжает хранить authoritative IP/action на сервере.

Выбор устройства передаётся callback-индексом только для чтения inventory в текущем списке. Mutation по-прежнему выполняется только после token confirmation и повторной проверки устройства policy layer.

## Scope

- Изменить presentation helpers в `src/mikroclear/bot/modules/parental.py`.
- Расширить `TelegramParentalHandler` маршрутом выбора устройства.
- Сохранить существующие confirmation/cancel/error paths.
- Добавить focused tests для списка, выбора устройства и action buttons.
- Не менять Pi-hole, RouterOS, runtime wiring, callback protocol version и feature flags.

## Acceptance criteria

- В корневом меню родительский раздел имеет иконку телевизора.
- В списке устройств используется иконка телевизора.
- В списке устройств нет непосредственных BLOCK/ALLOW кнопок.
- После выбора устройства отображаются только действия выбранного устройства.
- Existing token safety and mutation counts remain unchanged.
