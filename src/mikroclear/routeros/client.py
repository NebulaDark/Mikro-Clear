from dataclasses import dataclass
import socket
import ssl
import traceback
from typing import Any, Callable

try:
    import librouteros  # type: ignore
    from librouteros import connect as routeros_connect  # type: ignore
except Exception:  # pragma: no cover
    librouteros = None  # type: ignore
    routeros_connect = None  # type: ignore

from mikroclear.routeros.address_list import add_to_address_list, remove_from_address_list
from mikroclear.routeros.ssl_context import build_routeros_ssl_context, make_routeros_ssl_wrapper


@dataclass(frozen=True)
class RouterOsClientConfig:
    reconnect_sleep_seconds: int = 2


@dataclass(frozen=True)
class RouterOsConnectConfig:
    username: str
    password: str
    host: str
    port: int
    use_ssl: bool
    tls_server_name: str


@dataclass(frozen=True)
class RouterOsLifecycleConfig:
    heartbeat_seconds: int = 60
    reconnect_sleep_seconds: int = 2
    enable_ipv6: bool = False


def build_routeros_connect_kwargs(
    config: RouterOsConnectConfig,
    *,
    ssl_context: Any,
    ssl_wrapper_factory: Callable[[Any, str], Any],
    login_method: Any = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "username": config.username,
        "password": config.password,
        "host": config.host,
        "port": config.port,
    }
    if login_method is not None:
        kwargs["login_method"] = login_method
    if config.use_ssl:
        kwargs["ssl_wrapper"] = ssl_wrapper_factory(ssl_context, config.tls_server_name or config.host)
    return kwargs


class RouterOsApiLifecycle:
    def __init__(
        self,
        config: RouterOsLifecycleConfig,
        *,
        connect: Callable[[], Any],
        log: Callable[[str], None],
        sleep: Callable[[float], None],
        time: Callable[[], float],
        transient_errors: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        self.config = config
        self.api: Any = None
        self.connected_at = 0.0
        self.last_heartbeat = 0.0
        self._connect = connect
        self._log = log
        self._sleep = sleep
        self._time = time
        if transient_errors is None:
            errors: tuple[type[BaseException], ...] = (ssl.SSLError, socket.timeout, TimeoutError)
            if librouteros is not None:
                errors = errors + (librouteros.exceptions.ConnectionClosed,)
            transient_errors = errors
        self._transient_errors = transient_errors

    def mark_connected(self, api: Any) -> None:
        self.api = api
        self.connected_at = self._time()
        self.last_heartbeat = 0.0

    def close(self) -> None:
        if self.api is not None:
            try:
                close_method = getattr(self.api, "close", None)
                if callable(close_method):
                    close_method()
            except Exception:
                pass
        self.api = None

    def reconnect(self, reason: str = "") -> None:
        if reason:
            self._log(f"RouterOS API reconnect requested: {reason}")
        self.close()
        self._sleep(max(0, self.config.reconnect_sleep_seconds))
        self.mark_connected(self._connect())

    def ensure_connected(self) -> Any:
        if self.api is None:
            self.mark_connected(self._connect())
        return self.api

    def heartbeat(self, force: bool = False) -> bool:
        now = self._time()
        if not force and now - self.last_heartbeat < self.config.heartbeat_seconds:
            return True

        try:
            api = self.ensure_connected()
            resources = api.path("/system/resource")
            for _ in resources:
                break
            self.last_heartbeat = now
            return True
        except self._transient_errors as exc:
            self.reconnect(f"heartbeat failed: {type(exc).__name__}: {exc}")
            return False
        except Exception as exc:
            self._log(f"RouterOS heartbeat error: {type(exc).__name__}: {exc}")
            return False

    def paths(self) -> tuple[Any, Any | None, Any]:
        api = self.ensure_connected()
        address_list = api.path("/ip/firewall/address-list")
        address_list_v6 = api.path("/ipv6/firewall/address-list") if self.config.enable_ipv6 else None
        resources = api.path("/system/resource")
        return address_list, address_list_v6, resources

    def run_with_reconnect(self, operation_name: str, func: Callable[[], Any]) -> Any:
        manager = RouterOsConnectionManager(
            RouterOsClientConfig(reconnect_sleep_seconds=self.config.reconnect_sleep_seconds),
            heartbeat=self.heartbeat,
            reconnect=self.reconnect,
            log=self._log,
            sleep=self._sleep,
            transient_errors=self._transient_errors,
        )
        return manager.run_with_reconnect(operation_name, func)


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


class RouterOSClient:
    def __init__(
        self,
        settings: Any,
        *,
        log: Callable[[str], None],
        send_system_notification: Callable[[str, str], Any],
        sleep: Callable[[float], None],
        time: Callable[[], float],
        connect_func: Callable[..., Any] | None = None,
        socket_module: Any = socket,
    ) -> None:
        self.settings = settings
        self.log = log
        self.send_system_notification = send_system_notification
        self.sleep = sleep
        self.time = time
        self.connect_func = connect_func or routeros_connect
        self.socket_module = socket_module
        self.lifecycle = RouterOsApiLifecycle(
            RouterOsLifecycleConfig(
                heartbeat_seconds=settings.router_heartbeat_seconds,
                reconnect_sleep_seconds=settings.router_reconnect_sleep_seconds,
                enable_ipv6=settings.enable_ipv6,
            ),
            connect=self.connect_once,
            log=log,
            sleep=sleep,
            time=time,
        )

    @property
    def api(self) -> Any:
        return self.lifecycle.api

    @api.setter
    def api(self, value: Any) -> None:
        self.lifecycle.api = value

    @property
    def connected_at(self) -> float:
        return self.lifecycle.connected_at

    @connected_at.setter
    def connected_at(self, value: float) -> None:
        self.lifecycle.connected_at = value

    @property
    def last_heartbeat(self) -> float:
        return self.lifecycle.last_heartbeat

    @last_heartbeat.setter
    def last_heartbeat(self, value: float) -> None:
        self.lifecycle.last_heartbeat = value

    def close(self) -> None:
        self.lifecycle.close()

    def connect_once(self) -> Any:
        if self.connect_func is None:
            raise RuntimeError("librouteros is required to connect to RouterOS")

        actual_port = self.settings.port or (8729 if self.settings.use_ssl else 8728)
        self.socket_module.setdefaulttimeout(self.settings.socket_timeout_seconds)

        login_method = None
        try:
            import librouteros.login as routeros_login  # type: ignore

            login_method = routeros_login.plain if hasattr(routeros_login, "plain") else None
        except Exception:
            login_method = None

        ssl_context = (
            build_routeros_ssl_context(
                cafile=self.settings.ca_file,
                allow_self_signed=self.settings.allow_self_signed_certs,
            )
            if self.settings.use_ssl
            else None
        )
        kwargs = build_routeros_connect_kwargs(
            RouterOsConnectConfig(
                username=self.settings.username,
                password=self.settings.password,
                host=self.settings.router_ip,
                port=actual_port,
                use_ssl=self.settings.use_ssl,
                tls_server_name=self.settings.router_tls_server_name or self.settings.router_ip,
            ),
            ssl_context=ssl_context,
            ssl_wrapper_factory=make_routeros_ssl_wrapper,
            login_method=login_method,
        )

        return self.connect_func(**kwargs)

    def connect(self, shutdown_requested: Callable[[], bool] | None = None) -> None:
        should_stop = shutdown_requested or (lambda: False)
        actual_port = self.settings.port or (8729 if self.settings.use_ssl else 8728)

        if not self.settings.username or not self.settings.password or not self.settings.router_ip:
            self.log("RouterOS credentials are incomplete. Check MIKROCLEAR_ROUTER_USERNAME/PASSWORD/IP.")
            while not should_stop():
                self.sleep(self.settings.router_connect_retry_seconds)
            return

        while not should_stop():
            try:
                self.close()
                protocol = "SSL" if self.settings.use_ssl else "plain API"
                self.log(f"Connecting to MikroTik {self.settings.router_ip}:{actual_port} via {protocol}...")
                self.lifecycle.mark_connected(self.connect_once())
                self.log("Connected to MikroTik")
                if self.settings.router_connect_notify_enable:
                    self.send_system_notification(
                        f"Connected to MikroTik {self.settings.router_ip}:{actual_port} via {protocol}",
                        "SYSTEM",
                    )
                return
            except Exception as exc:
                self._log_connect_error(exc)
                self.sleep(self.settings.router_connect_retry_seconds)

    def _log_connect_error(self, exc: BaseException) -> None:
        if librouteros is not None and isinstance(exc, librouteros.exceptions.TrapError):
            msg = str(exc).lower()
            if "invalid user name or password" in msg:
                self.log("Invalid MikroTik username or password. Retrying later.")
            else:
                self.log(f"MikroTik TrapError during login: {exc}")
            return
        if librouteros is not None and isinstance(exc, librouteros.exceptions.ConnectionClosed):
            self.log(
                f"Connection closed during RouterOS login: {exc}. "
                f"Retrying in {self.settings.router_connect_retry_seconds}s."
            )
            return
        if isinstance(exc, (ssl.SSLError, socket.timeout, TimeoutError)):
            self.log(
                f"SSL/socket error connecting to MikroTik: {type(exc).__name__}: {exc}. "
                f"Retrying in {self.settings.router_connect_retry_seconds}s."
            )
            return
        if isinstance(exc, ConnectionRefusedError):
            self.log(
                "Connection refused. Check /ip service api-ssl and firewall. "
                f"Retrying in {self.settings.router_connect_retry_seconds}s."
            )
            return
        if isinstance(exc, OSError):
            self.log(f"OS error connecting to MikroTik: {exc}. Retrying in {self.settings.router_connect_retry_seconds}s.")
            return
        self.log(f"Unexpected error connecting to MikroTik: {type(exc).__name__}: {exc}")
        if getattr(self.settings, "debug_mode", False):
            print(traceback.format_exc(), flush=True)

    def reconnect(self, reason: str = "") -> None:
        if reason:
            self.log(f"RouterOS API reconnect requested: {reason}")
        self.close()
        self.sleep(max(0, self.settings.router_reconnect_sleep_seconds))
        self.connect()

    def ensure_connected(self) -> Any:
        if self.api is None:
            self.connect()
        return self.api

    def heartbeat(self, force: bool = False) -> bool:
        return self.lifecycle.heartbeat(force=force)

    def paths(self) -> tuple[Any, Any | None, Any]:
        self.ensure_connected()
        return self.lifecycle.paths()

    def run_with_reconnect(self, operation_name: str, func: Callable[[], Any]) -> Any:
        manager = RouterOsConnectionManager(
            RouterOsClientConfig(reconnect_sleep_seconds=self.settings.router_reconnect_sleep_seconds),
            heartbeat=self.heartbeat,
            reconnect=self.reconnect,
            log=self.log,
            sleep=self.sleep,
        )
        return manager.run_with_reconnect(operation_name, func)
