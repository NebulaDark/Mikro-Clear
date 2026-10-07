"""FastAPI application for the Mikro-Clear Web control plane."""

from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
from pathlib import Path
import secrets
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from mikroclear.bot.audit import BotAuditLog
from mikroclear.bot.settings import BotSettings
from mikroclear.security import mask_known_secret
from mikroclear.settings import Settings
from mikroclear.web.actions import ConfirmationError, ConfirmationStore
from mikroclear.web.config import WebSettings
from mikroclear.web.readers import read_jsonl, recent_alerts, text_log
from mikroclear.web.router_gateway import RouterWebGateway


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=4096)


class MangleRequest(BaseModel):
    disabled: bool


class ConfirmRequest(BaseModel):
    token: str = Field(min_length=10, max_length=4096)


class UnblockRequest(BaseModel):
    address: str = Field(min_length=2, max_length=128)


def _safe_settings(settings: Settings) -> dict[str, Any]:
    return {
        "router": {
            "host": settings.router_ip,
            "port": settings.port,
            "use_ssl": settings.use_ssl,
            "tls_server_name": settings.router_tls_server_name,
            "ca_file": settings.ca_file,
            "credentials_configured": bool(settings.username and settings.password),
        },
        "suricata": {
            "eve_json": settings.filepath,
            "severities": list(settings.severity),
            "interfaces": list(settings.listen_interfaces),
            "monitor_only": settings.monitor_only,
        },
        "blocking": {
            "list_name": settings.block_list_name,
            "timeout": settings.timeout,
            "ipv6": settings.enable_ipv6,
        },
        "telegram": {
            "enabled": settings.enable_telegram,
            "token_configured": bool(settings.telegram_token),
            "unblock_enabled": settings.telegram_unblock_enable,
            "whitelist_control_enabled": settings.telegram_whitelist_control_enable,
        },
        "mangle": {
            "enabled": settings.mangle_control_enable,
            "comment_prefix": settings.mangle_comment_prefix,
            "allowed_chains": list(settings.mangle_allowed_chains),
            "allowed_actions": list(settings.mangle_allowed_actions),
            "confirmation_required": settings.mangle_require_confirmation,
        },
        "parental": {
            "enabled": settings.parental_control_enable,
            "router_list": settings.parental_device_list_name,
            "pihole_enabled": settings.pihole_enable,
            "pihole_base_url": settings.pihole_base_url,
            "pihole_password_configured": bool(settings.pihole_app_password),
            "youtube_group": settings.parental_youtube_group_name,
        },
        "state_dir": settings.state_dir,
        "debug": settings.debug_mode,
    }


def _mask_public_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = mask_known_secret(value, secret)
        return value
    if isinstance(value, list):
        return [_mask_public_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _mask_public_value(item, secrets) for key, item in value.items()}
    return value


def create_app(*, core_settings: Settings | None = None, web_settings: WebSettings | None = None) -> FastAPI:
    core = core_settings or Settings.from_env()
    web = web_settings or WebSettings.from_env()
    web.validate()
    bot = BotSettings.from_env()
    audit = BotAuditLog(Path(bot.audit_log))
    gateway = RouterWebGateway(core)
    confirmations = ConfirmationStore(web.session_secret, ttl_seconds=web.confirm_ttl_seconds)
    known_secrets = tuple(
        secret for secret in (
            core.password,
            core.telegram_token,
            core.pihole_app_password,
            web.admin_password,
            web.session_secret,
        ) if secret
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        gateway.close()

    app = FastAPI(title="Mikro-Clear Web", version="0.1.0", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=web.session_secret,
        session_cookie="mikroclear_session",
        same_site="strict",
        https_only=web.secure_cookie,
        max_age=8 * 3600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def current_user(request: Request) -> str:
        username = str(request.session.get("user", ""))
        if not username or not request.session.get("session_id"):
            raise HTTPException(status_code=401, detail="Authentication required")
        return username

    def require_csrf(request: Request) -> str:
        username = current_user(request)
        expected = str(request.session.get("csrf", ""))
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        return username

    def audit_record(action: str, outcome: str, username: str, target: str, detail: str = "") -> None:
        audit.record(
            *(
                _mask_public_value(value, known_secrets)
                for value in (action, outcome, "web", username, target, detail)
            )
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
        valid_user = hmac.compare_digest(payload.username, web.admin_username)
        valid_password = hmac.compare_digest(payload.password, web.admin_password)
        if not (valid_user and valid_password):
            audit_record("web.login", "denied", payload.username, "session")
            raise HTTPException(status_code=401, detail="Invalid credentials")
        csrf = secrets.token_urlsafe(24)
        request.session.clear()
        request.session.update({"user": web.admin_username, "role": "admin", "csrf": csrf, "session_id": secrets.token_urlsafe(24)})
        audit_record("web.login", "success", web.admin_username, "session")
        return {"user": web.admin_username, "role": "admin", "csrf": csrf}

    @app.post("/api/auth/logout")
    def logout(request: Request, username: str = Depends(require_csrf)) -> dict[str, bool]:
        audit_record("web.logout", "success", username, "session")
        request.session.clear()
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(request: Request, username: str = Depends(current_user)) -> dict[str, str]:
        return {"user": username, "role": str(request.session.get("role", "viewer")), "csrf": str(request.session.get("csrf", ""))}

    @app.get("/api/overview")
    def overview(_username: str = Depends(current_user)) -> dict[str, Any]:
        try:
            router: dict[str, Any] = gateway.status()
        except Exception as exc:
            router = {"connected": False, "error": type(exc).__name__}
        try:
            blocked_count = len(gateway.block_entries(limit=2000))
        except Exception:
            blocked_count = None
        return {
            "router": router,
            "blocked_count": blocked_count,
            "monitor_only": core.monitor_only,
            "telegram_enabled": core.enable_telegram,
            "mangle_control_enabled": core.mangle_control_enable,
            "parental_control_enabled": core.parental_control_enable,
            "pihole_enabled": core.pihole_enable,
        }

    @app.get("/api/settings")
    def settings_view(_username: str = Depends(current_user)) -> dict[str, Any]:
        return _safe_settings(core)

    @app.get("/api/alerts")
    def alerts(limit: int = 100, q: str = "", _username: str = Depends(current_user)) -> dict[str, Any]:
        rows = recent_alerts(web.eve_json, limit=limit, query=q, max_bytes=web.max_tail_bytes)
        return {"items": rows, "count": len(rows)}

    @app.get("/api/logs")
    def logs(limit: int = 200, q: str = "", _username: str = Depends(current_user)) -> dict[str, Any]:
        if not web.service_log_file:
            return {"items": [], "count": 0, "available": False, "message": "MIKROCLEAR_WEB_LOG_FILE is not configured"}
        rows = _mask_public_value(text_log(web.service_log_file, limit=limit, query=q, max_bytes=web.max_tail_bytes), known_secrets)
        return {"items": rows, "count": len(rows), "available": True}

    @app.get("/api/audit")
    def audit_view(limit: int = 200, _username: str = Depends(current_user)) -> dict[str, Any]:
        rows = _mask_public_value(read_jsonl(bot.audit_log, limit=max(1, min(limit, 1000)), max_bytes=web.max_tail_bytes), known_secrets)
        rows.reverse()
        return {"items": rows, "count": len(rows)}

    @app.get("/api/router/blocks")
    def blocks(limit: int = 500, _username: str = Depends(current_user)) -> dict[str, Any]:
        rows = gateway.block_entries(limit=limit)
        return {"items": rows, "count": len(rows), "list": core.block_list_name}

    @app.get("/api/router/mangle")
    def mangle(_username: str = Depends(current_user)) -> dict[str, Any]:
        rows = gateway.managed_mangle()
        return {"items": rows, "count": len(rows), "enabled": core.mangle_control_enable}

    @app.post("/api/router/mangle/{rule_id}/request")
    def request_mangle(rule_id: str, payload: MangleRequest, request: Request, username: str = Depends(require_csrf)) -> dict[str, Any]:
        if core.monitor_only:
            raise HTTPException(status_code=409, detail="Monitor-only mode is enabled")
        if not core.mangle_control_enable:
            raise HTTPException(status_code=403, detail="Mangle control is disabled")
        current = next((row for row in gateway.managed_mangle() if row["id"] == rule_id), None)
        if current is None:
            raise HTTPException(status_code=404, detail="Managed mangle rule not found")
        token = confirmations.create("mangle", {"rule_id": rule_id, "disabled": payload.disabled, "name": current["name"]}, owner=str(request.session["session_id"]))
        audit_record("web.mangle.request", "pending", username, current["name"], f"disabled={payload.disabled}")
        return {"token": token, "expires_in": web.confirm_ttl_seconds, "target": current["name"], "disabled": payload.disabled}

    @app.post("/api/router/mangle/confirm")
    def confirm_mangle(payload: ConfirmRequest, request: Request, username: str = Depends(require_csrf)) -> dict[str, Any]:
        try:
            action = confirmations.consume(payload.token, kind="mangle", owner=str(request.session["session_id"]))
            gateway.set_mangle_disabled(str(action["rule_id"]), bool(action["disabled"]))
        except ConfirmationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            audit_record("web.mangle.confirm", "denied", username, "mangle", type(exc).__name__)
            raise HTTPException(status_code=403, detail="RouterOS operation denied") from exc
        except Exception as exc:
            audit_record("web.mangle.confirm", "error", username, "mangle", type(exc).__name__)
            raise HTTPException(status_code=503, detail="RouterOS action could not be confirmed") from exc
        target = str(action.get("name", action.get("rule_id", "")))
        audit_record("web.mangle.confirm", "success", username, target, f"disabled={bool(action['disabled'])}")
        return {"ok": True}

    @app.post("/api/router/unblock/request")
    def request_unblock(payload: UnblockRequest, request: Request, username: str = Depends(require_csrf)) -> dict[str, Any]:
        if core.monitor_only:
            raise HTTPException(status_code=409, detail="Monitor-only mode is enabled")
        existing = next((row for row in gateway.block_entries(limit=2000) if row["address"] == payload.address), None)
        if existing is None:
            raise HTTPException(status_code=404, detail="Address is not currently blocked")
        token = confirmations.create("unblock", {"address": existing["address"], "list": core.block_list_name}, owner=str(request.session["session_id"]))
        audit_record("web.unblock.request", "pending", username, existing["address"])
        return {"token": token, "expires_in": web.confirm_ttl_seconds, "target": existing["address"]}

    @app.post("/api/router/unblock/confirm")
    def confirm_unblock(payload: ConfirmRequest, request: Request, username: str = Depends(require_csrf)) -> dict[str, Any]:
        try:
            action = confirmations.consume(payload.token, kind="unblock", owner=str(request.session["session_id"]))
            removed = gateway.unblock(str(action["address"]))
        except ConfirmationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            audit_record("web.unblock.confirm", "denied", username, "address-list", type(exc).__name__)
            raise HTTPException(status_code=403, detail="RouterOS operation denied") from exc
        except Exception as exc:
            audit_record("web.unblock.confirm", "error", username, "address-list", type(exc).__name__)
            raise HTTPException(status_code=503, detail="RouterOS action could not be confirmed") from exc
        address = str(action["address"])
        audit_record("web.unblock.confirm", "success" if removed else "stale", username, address, f"removed={removed}")
        return {"ok": True, "removed": removed}

    static_dir = Path(web.static_dir)
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        index = static_dir / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=503, detail="Web UI assets are not installed")
        return FileResponse(index)

    return app


__all__ = ["create_app"]
