"""Web-panel configuration loaded only from environment variables."""

from dataclasses import dataclass
import os


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class WebSettings:
    host: str = "0.0.0.0"
    port: int = 8080
    admin_username: str = "admin"
    admin_password: str = ""
    session_secret: str = ""
    secure_cookie: bool = True
    confirm_ttl_seconds: int = 120
    eve_json: str = "/data/eve.json"
    service_log_file: str = ""
    static_dir: str = "/app/static"
    max_tail_bytes: int = 4 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "WebSettings":
        return cls(
            host=os.getenv("MIKROCLEAR_WEB_HOST", "0.0.0.0").strip(),
            port=_env_int("MIKROCLEAR_WEB_PORT", 8080),
            admin_username=os.getenv("MIKROCLEAR_WEB_ADMIN_USERNAME", "admin").strip(),
            admin_password=os.getenv("MIKROCLEAR_WEB_ADMIN_PASSWORD", ""),
            session_secret=os.getenv("MIKROCLEAR_WEB_SESSION_SECRET", ""),
            secure_cookie=_env_bool("MIKROCLEAR_WEB_SECURE_COOKIE", True),
            confirm_ttl_seconds=max(30, _env_int("MIKROCLEAR_WEB_CONFIRM_TTL_SECONDS", 120)),
            eve_json=os.getenv("MIKROCLEAR_WEB_EVE_JSON", "/data/eve.json").strip(),
            service_log_file=os.getenv("MIKROCLEAR_WEB_LOG_FILE", "").strip(),
            static_dir=os.getenv("MIKROCLEAR_WEB_STATIC_DIR", "/app/static").strip(),
            max_tail_bytes=max(256 * 1024, _env_int("MIKROCLEAR_WEB_MAX_TAIL_BYTES", 4 * 1024 * 1024)),
        )

    def validate(self) -> None:
        if not self.admin_username:
            raise ValueError("MIKROCLEAR_WEB_ADMIN_USERNAME must not be empty")
        if not self.admin_password:
            raise ValueError("MIKROCLEAR_WEB_ADMIN_PASSWORD must be set")
        if len(self.session_secret) < 32:
            raise ValueError("MIKROCLEAR_WEB_SESSION_SECRET must contain at least 32 characters")
        if not 1 <= self.port <= 65535:
            raise ValueError("MIKROCLEAR_WEB_PORT must be a valid TCP port")


__all__ = ["WebSettings"]
