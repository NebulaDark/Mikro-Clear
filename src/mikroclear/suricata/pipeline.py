"""Suricata alert processing pipeline."""

from typing import Any, Callable

from mikroclear.alert_processor import (
    AlertProcessorConfig,
    format_event_timestamp,
    process_alert_batch,
    process_single_alert,
    update_existing_address,
)


class AlertPipeline:
    def __init__(
        self,
        *,
        client_factory: Callable[[], Any],
        config: AlertProcessorConfig,
        validate_event: Callable[[Any], dict[str, Any] | None],
        ignore_predicate: Callable[[dict[str, Any]], bool],
        send_telegram: Callable[..., Any],
        save_restore: Callable[[Any], None],
        save_interval: int,
        now: Callable[[], float],
        log: Callable[[str], None],
        debug_log: Callable[[str], None],
    ) -> None:
        self.client_factory = client_factory
        self.config = config
        self.validate_event = validate_event
        self.ignore_predicate = ignore_predicate
        self.send_telegram = send_telegram
        self.save_restore = save_restore
        self.save_interval = save_interval
        self.now = now
        self.log = log
        self.debug_log = debug_log
        self.last_save_time = 0

    def process_alerts(self, alerts: list[dict[str, Any]] | None) -> None:
        self.last_save_time = process_alert_batch(
            alerts,
            client=self.client_factory(),
            config=self.config,
            validate_event=self.validate_event,
            process_single=self.process_single_alert,
            save_restore=self.save_restore,
            last_save_time=self.last_save_time,
            save_interval=self.save_interval,
            now=self.now,
            log=self.log,
            debug_log=self.debug_log,
        )

    def process_single_alert(self, event: dict[str, Any], address_list: Any, address_list_v6: Any) -> None:
        process_single_alert(
            event,
            address_list,
            address_list_v6,
            config=self.config,
            ignore_predicate=self.ignore_predicate,
            send_telegram=self.send_telegram,
            log=self.log,
            debug_log=self.debug_log,
        )


__all__ = [
    "AlertPipeline",
    "AlertProcessorConfig",
    "format_event_timestamp",
    "process_alert_batch",
    "process_single_alert",
    "update_existing_address",
]
