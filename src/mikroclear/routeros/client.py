from dataclasses import dataclass
import socket
import ssl
from typing import Any, Callable

try:
    import librouteros  # type: ignore
    from librouteros.query import Key  # type: ignore
except Exception:  # pragma: no cover
    librouteros = None  # type: ignore

    class Key:  # type: ignore
        def __init__(self, name: str) -> None:
            self.name = name

        def __eq__(self, other: Any) -> tuple[str, Any]:
            return (self.name, other)


@dataclass(frozen=True)
class RouterOsClientConfig:
    reconnect_sleep_seconds: int = 2


class RouterOsConnectionManager:
    def __init__(
        self,
        config: RouterOsClientConfig,
        *,
        heartbeat: Callable[[bool], bool],
        reconnect: Callable[[str], None],
        log: Callable[[str], None],
        sleep: Callable[[float], None],
        transient_errors: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        self.config = config
        self._heartbeat = heartbeat
        self._reconnect = reconnect
        self._log = log
        self._sleep = sleep
        if transient_errors is None:
            errors: tuple[type[BaseException], ...] = (ssl.SSLError, socket.timeout, TimeoutError)
            if librouteros is not None:
                errors = errors + (librouteros.exceptions.ConnectionClosed,)
            transient_errors = errors
        self._transient_errors = transient_errors

    def run_with_reconnect(self, operation_name: str, func: Callable[[], Any]) -> Any:
        try:
            self._heartbeat(False)
            return func()
        except self._transient_errors as exc:
            self._log(f"RouterOS API error during {operation_name}: {type(exc).__name__}: {exc}")
            self._reconnect(f"{operation_name} failed")
            return func()


def remove_from_address_list(address_list: Any, list_name: str, address: str) -> int:
    _address = Key("address")
    _id = Key(".id")
    _list = Key("list")
    rows = list(address_list.select(_id, _list, _address).where(_address == address, _list == list_name))
    removed = 0
    for row in rows:
        address_list.remove(row[".id"])
        removed += 1
    return removed


def add_to_address_list(address_list: Any, list_name: str, address: str, comment: str, timeout: str) -> None:
    address_list.add(list=list_name, address=address, comment=comment, timeout=timeout)
