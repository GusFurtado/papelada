"""Optional single-user login.

Enabled by USERNAME and PASSWORD (PASSWORD_FILE for a Docker secret); with both
empty there is no login at all. A session is a signed cookie: an expiry time and
an HMAC of it under a random key made at startup. Nothing about the login is ever
written to the volume, the password isn't kept (only a digest, to compare), and
the key is unrelated to ENCRYPTION_KEY. Restarting the app, which is also how the
credentials are changed, ends every session."""

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, Optional, Tuple

COOKIE_NAME = "papelada_session"
SESSION_SECONDS = 14 * 24 * 3600

# Failed logins are counted per client address, and across all clients (a proxy
# hides the real address, and many addresses can try at once). Past a limit,
# logins are refused until the oldest failure leaves the window.
THROTTLE_WINDOW = 15 * 60
MAX_FAILURES_PER_CLIENT = 5
MAX_FAILURES_TOTAL = 50


class AuthConfigError(RuntimeError):
    """The login is configured wrongly (fatal at startup)."""


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def load_credentials_from_env() -> Optional[Tuple[str, str]]:
    """(username, password) when the login is enabled, None when both are empty.
    Setting only one of them is an error: it would be a login nobody can pass,
    or worse, no login where one was meant."""
    username = os.environ.get("USERNAME", "").strip()
    password = os.environ.get("PASSWORD", "")
    password_file = os.environ.get("PASSWORD_FILE", "").strip()
    if not password and password_file:
        password = Path(password_file).read_text().rstrip("\r\n")
    if not username and not password:
        return None
    if not username or not password:
        raise AuthConfigError(
            "USERNAME and PASSWORD (or PASSWORD_FILE) must be set together: set both to enable the login, "
            "or leave both empty to disable it."
        )
    return username, password


class Throttle:
    """Sliding window of failed attempts."""

    def __init__(self, window: int = THROTTLE_WINDOW):
        self.window = window
        self.failures: Dict[str, Deque[float]] = {}
        self.lock = threading.Lock()

    def _prune(self, now: float) -> None:
        for key in list(self.failures):
            times = self.failures[key]
            while times and times[0] <= now - self.window:
                times.popleft()
            if not times:
                del self.failures[key]

    def retry_after(self, client: str, now: Optional[float] = None) -> int:
        """Seconds until `client` may try again; 0 if it may try now."""
        now = time.monotonic() if now is None else now
        with self.lock:
            self._prune(now)
            wait = 0.0
            for key, limit in ((client, MAX_FAILURES_PER_CLIENT), ("*", MAX_FAILURES_TOTAL)):
                times = self.failures.get(key)
                if times and len(times) >= limit:
                    wait = max(wait, times[len(times) - limit] + self.window - now)
            return int(wait) + 1 if wait > 0 else 0

    def fail(self, client: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        with self.lock:
            for key in (client, "*"):
                self.failures.setdefault(key, deque()).append(now)

    def succeed(self, client: str) -> None:
        with self.lock:
            self.failures.pop(client, None)


class Auth:
    def __init__(self, username: str, password: str):
        self._username = _digest(username)
        self._password = _digest(password)
        self._key = secrets.token_bytes(32)
        self.throttle = Throttle()

    def check(self, username: str, password: str) -> bool:
        """Always compares both, in constant time, so a wrong username isn't
        distinguishable from a wrong password."""
        user_ok = hmac.compare_digest(_digest(username), self._username)
        password_ok = hmac.compare_digest(_digest(password), self._password)
        return user_ok and password_ok

    def _sign(self, payload: bytes) -> bytes:
        return hmac.new(self._key, payload, hashlib.sha256).digest()

    def new_session(self, now: Optional[float] = None) -> str:
        expires = str(int((time.time() if now is None else now) + SESSION_SECONDS))
        return f"{expires}.{self._sign(expires.encode()).hex()}"

    def valid_session(self, token: Optional[str], now: Optional[float] = None) -> bool:
        try:
            expires, signature = (token or "").split(".")
            expires_at = int(expires)
            signature_bytes = bytes.fromhex(signature)
        except ValueError:
            return False
        if not hmac.compare_digest(signature_bytes, self._sign(expires.encode())):
            return False
        return expires_at > (time.time() if now is None else now)
