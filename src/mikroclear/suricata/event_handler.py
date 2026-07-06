"""pyinotify event handler factory for Suricata eve.json."""

from typing import Any, Callable


def make_event_handler(
    pyinotify_module: Any,
    *,
    filepath: str,
    tailer: Any,
    process_alerts: Callable[[list[dict[str, Any]]], None],
    log: Callable[[str], None],
    debug_traceback: Callable[[], str],
    debug_enabled: Callable[[], bool],
) -> type:
    class EventHandler(pyinotify_module.ProcessEvent):  # type: ignore[misc]
        def process_IN_MODIFY(self, event: Any) -> None:
            if event.pathname == filepath:
                try:
                    process_alerts(tailer.read_json(filepath))
                except Exception as exc:
                    log(f"Error processing eve.json modification: {type(exc).__name__}: {exc}")
                    if debug_enabled():
                        print(debug_traceback(), flush=True)

        def process_IN_CREATE(self, event: Any) -> None:
            if event.pathname == filepath:
                log("New eve.json detected. Resetting file position.")
                tailer.reset()
                self.process_IN_MODIFY(event)

        def process_IN_DELETE(self, event: Any) -> None:
            if event.pathname == filepath:
                log("eve.json deleted. Waiting for new file.")

        def process_IN_MOVED_TO(self, event: Any) -> None:
            if event.pathname == filepath:
                self.process_IN_CREATE(event)

    return EventHandler


__all__ = ["make_event_handler"]
