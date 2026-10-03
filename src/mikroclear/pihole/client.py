"""Strict, lazy Pi-hole v6 REST client."""

from __future__ import annotations

import json
from typing import Any, Callable

import requests

from mikroclear.security import mask_known_secret


class PiholeClientError(RuntimeError):
    """Controlled error safe to expose to the Telegram boundary."""

    def __init__(self, message: str, *, ambiguous: bool = False, status_code: int | None = None) -> None:
        super().__init__(message)
        self.ambiguous = bool(ambiguous)
        self.status_code = status_code


class PiholeClient:
    def __init__(
        self,
        base_url: str,
        app_password: str,
        *,
        verify_tls: bool = True,
        ca_file: str = "",
        connect_timeout: int = 3,
        read_timeout: int = 5,
        retry_count: int = 1,
        request_get: Callable[..., Any] = requests.get,
        request_post: Callable[..., Any] = requests.post,
        request_put: Callable[..., Any] = requests.put,
        request_delete: Callable[..., Any] = requests.delete,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.app_password = str(app_password)
        self.verify = ca_file if ca_file else bool(verify_tls)
        self.timeout = (max(1, int(connect_timeout)), max(1, int(read_timeout)))
        self.retry_count = max(0, int(retry_count))
        self._sid = ""
        self._requests = {
            "GET": request_get,
            "POST": request_post,
            "PUT": request_put,
            "DELETE": request_delete,
        }

    def _auth(self) -> None:
        response = self._send("POST", "/api/auth", json={"password": self.app_password})
        try:
            payload = response.json()
            sid = payload.get("session", {}).get("sid")
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PiholeClientError("Pi-hole authentication returned invalid JSON") from exc
        if not sid:
            raise PiholeClientError("Pi-hole authentication did not return a session")
        self._sid = str(sid)

    def _send(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return self._requests[method](
                f"{self.base_url}/{path.lstrip('/')}",
                timeout=self.timeout,
                verify=self.verify,
                **kwargs,
            )
        except Exception as exc:
            message = mask_known_secret(str(exc), self.app_password)
            raise PiholeClientError(f"Pi-hole request failed: {message[:180]}") from exc

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        method = str(method).upper()
        if method not in self._requests:
            raise ValueError(f"Unsupported Pi-hole method: {method}")
        is_read = method == "GET"
        is_mutation = method in {"POST", "PUT"}
        read_retries = 0
        reauth_attempted = False
        request_kwargs = dict(kwargs)
        request_headers = dict(request_kwargs.pop("headers", {}) or {})
        while True:
            if not self._sid:
                self._auth()
            headers = dict(request_headers)
            headers["X-FTL-SID"] = self._sid
            try:
                response = self._send(method, path, headers=headers, **request_kwargs)
            except PiholeClientError as exc:
                if is_read and read_retries < self.retry_count:
                    read_retries += 1
                    continue
                if is_mutation:
                    raise PiholeClientError(
                        str(exc), ambiguous=True
                    ) from exc
                raise

            if response.status_code == 401 and not reauth_attempted:
                reauth_attempted = True
                self._sid = ""
                continue
            if response.status_code == 401:
                raise PiholeClientError(
                    "Pi-hole API authentication failed after re-authentication",
                    ambiguous=is_mutation,
                    status_code=401,
                )
            if is_read and (response.status_code == 429 or response.status_code >= 500):
                if read_retries < self.retry_count:
                    read_retries += 1
                    continue
            if response.status_code >= 400:
                detail = mask_known_secret(str(getattr(response, "text", ""))[:180], self.app_password)
                raise PiholeClientError(
                    f"Pi-hole API HTTP {response.status_code}: {detail}",
                    ambiguous=is_mutation and (response.status_code == 429 or response.status_code >= 500),
                    status_code=response.status_code,
                )
            try:
                return response.json()
            except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise PiholeClientError(
                    "Pi-hole API returned invalid JSON",
                    ambiguous=is_mutation,
                ) from exc

    def close(self) -> None:
        if not self._sid:
            return
        try:
            self.request("DELETE", "/api/auth")
        finally:
            self._sid = ""

    # Policy-facing methods keep Pi-hole endpoint details out of the domain layer.
    def list_groups(self) -> Any:
        from mikroclear.pihole.groups import list_groups
        return list_groups(self)

    def find_group(self, name: str) -> Any:
        from mikroclear.pihole.groups import find_group
        return find_group(self, name)

    def list_clients(self) -> Any:
        from mikroclear.pihole.groups import list_clients
        return list_clients(self)

    def find_client(self, ip: str) -> Any:
        from mikroclear.pihole.groups import find_client
        return find_client(self, ip)

    def add_client(self, ip: str) -> Any:
        from mikroclear.pihole.groups import add_client
        return add_client(self, ip)

    def set_group_membership(self, record: Any, group: Any, enabled: bool) -> None:
        from mikroclear.pihole.groups import set_group_membership
        set_group_membership(self, record, group, enabled)


__all__ = ["PiholeClient", "PiholeClientError"]
