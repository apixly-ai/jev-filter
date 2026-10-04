"""Pooled fixed-origin Jev transport. No result cache, body logging or redirects."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .validation import validate_request, validate_response

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class ProviderError(RuntimeError):
    """A sanitized provider failure; response bodies and keys are never attached."""

    def __init__(self, code: str, *, unknown_usage_attempts: int | None = None):
        super().__init__(code)
        self.unknown_usage_attempts = unknown_usage_attempts

    @property
    def code(self) -> str:
        return str(self)


def credential() -> str:
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        path = Path(
            os.environ.get(
                "TYPESAFE_API_KEY_FILE",
                str(
                    Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
                    / "jev-context/api-key"
                ),
            )
        )
        try:
            key = _read_private_file(path)
        except OSError:
            raise ProviderError("credentials_missing") from None
    if not key or len(key) > 8192 or any(c.isspace() for c in key):
        raise ProviderError("credentials_invalid")
    return key


def _read_private_file(path: Path) -> str:
    """Read a key file that must be a regular, non-symlinked file private to the user.

    POSIX opens with O_NOFOLLOW and checks owner/mode atomically on the open descriptor.
    Windows has neither O_NOFOLLOW nor Unix modes: symlinks are rejected via lstat before
    opening, and privacy relies on the profile directory ACL rather than a mode check.
    """
    if not hasattr(os, "O_NOFOLLOW") and os.path.islink(path):
        raise ProviderError("credential_file_permissions")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags)) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ProviderError("credential_file_permissions")
        if hasattr(os, "getuid") and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ProviderError("credential_file_permissions")
        return stream.read(8193).strip()


class Client:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        pooled: bool = True,
        timeout: float = 25,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._key = api_key
        self.pooled = pooled
        self.timeout = timeout
        self.transport = transport
        self.sleep = sleep
        self.closed = False
        self.local = threading.local()
        self.clients: list[httpx.Client] = []
        self.lock = threading.Lock()
        self.stats = {"clients_created": 0, "client_reuses": 0, "requests": 0}

    def _client(self) -> httpx.Client:
        if self.closed:
            raise ProviderError("client_closed")
        client = getattr(self.local, "client", None)
        if client is not None:
            with self.lock:
                self.stats["client_reuses"] += 1
            return client
        client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=False,
            transport=self.transport,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
        with self.lock:
            self.clients.append(client)
            self.stats["clients_created"] += 1
        self.local.client = client
        return client

    def _discard(self, client: httpx.Client) -> None:
        client.close()
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)
        self.local.client = None

    def call(self, body: dict[str, Any], key: str | None = None) -> dict[str, Any]:
        validate_request(body)
        key = key or self._key or credential()
        if not key or any(c.isspace() for c in key):
            raise ProviderError("credentials_invalid")
        started = time.perf_counter()
        for attempt in range(3):
            client = self._client()
            with self.lock:
                self.stats["requests"] += 1
            try:
                with client.stream(
                    "POST", ENDPOINT, json=body, headers={"Authorization": "Bearer " + key}
                ) as response:
                    status = response.status_code
                    retry = response.headers.get("retry-after", "")
                    chunks = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 4 * 1024 * 1024:
                            raise ProviderError(
                                "response_too_large", unknown_usage_attempts=attempt + 1
                            )
                        chunks.append(chunk)
                    raw = b"".join(chunks)
            except httpx.HTTPError:
                self._discard(client)
                raise ProviderError(
                    "transport_failed_usage_unknown", unknown_usage_attempts=attempt + 1
                ) from None
            if not self.pooled:
                self._discard(client)
            if status != 200:
                if status in (429, 503, 529) and attempt < 2:
                    try:
                        delay = min(5, max(0, float(retry)))
                    except ValueError:
                        delay = 0.5 * 2**attempt
                    self.sleep(delay)
                    continue
                raise ProviderError(
                    f"http_{status}_body_suppressed", unknown_usage_attempts=attempt + 1
                )
            try:
                result = json.loads(raw)
                validate_response(body, result)
            except (ValueError, TypeError, KeyError):
                raise ProviderError(
                    "response_invalid_usage_unknown", unknown_usage_attempts=attempt + 1
                ) from None
            return {
                "ok": True,
                "model": result["model"],
                "answers": result["answers"],
                "usage": result["usage"],
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "attempts": attempt + 1,
                "usage_complete": attempt == 0,
                "unknown_usage_attempts": attempt,
            }
        raise ProviderError("retry_exhausted")

    def close(self) -> None:
        with self.lock:
            self.closed = True
            clients, self.clients = self.clients, []
        for client in clients:
            client.close()
        self.local.client = None

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def evaluate(body: dict[str, Any], client: Client, cache: Any = None) -> dict[str, Any]:
    if cache is not None:
        raise ValueError("result caching is not supported")
    result = client.call(body)
    return {
        **result,
        "cache_hit_questions": 0,
        "network_questions": len(body["questions"]),
        "usage_basis": "new network requests only; retries without usage remain unknown",
    }
