"""Supabase Auth (GoTrue) calls."""
import logging
import time
from dataclasses import dataclass

from .supabase_client import SupabaseClient, SupabaseError
from .validation import validate_display_name

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthResult:
    user_id: str
    email: str
    access_token: str
    refresh_token: str
    expires_at: int
    display_name: str = ""


def _safe_display_name(user) -> str:
    try:
        meta = user.get("user_metadata")
        raw = meta.get("display_name") if isinstance(meta, dict) else None
        return validate_display_name(raw)
    except Exception:
        return ""


class AuthError(Exception):
    """Generic authentication failure."""


class InvalidCredentials(AuthError):
    pass


class EmailNotConfirmed(AuthError):
    pass


class RegistrationFailed(AuthError):
    pass


def _json(resp):
    try:
        data = resp.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _not_confirmed(data):
    code = data.get("error_code") or data.get("code")
    msg = str(data.get("msg") or data.get("message") or data.get("error_description") or "")
    return code == "email_not_confirmed" or "email not confirmed" in msg.lower()


class SupabaseAuth:
    def __init__(self, client: SupabaseClient):
        self.client = client

    def _build(self, data) -> AuthResult:
        try:
            user = data["user"]
            expires_at = data.get("expires_at")
            if not isinstance(expires_at, int) or isinstance(expires_at, bool):
                expires_at = int(time.time()) + int(data["expires_in"])
            return AuthResult(
                user_id=str(user["id"]),
                email=str(user.get("email") or ""),
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=expires_at,
                display_name=_safe_display_name(user),
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("Malformed auth response: %s", type(exc).__name__)
            raise AuthError("Malformed auth response") from exc

    def register(self, email, password, display_name="") -> None:
        body = {"email": email, "password": password}
        if display_name:
            body["data"] = {"display_name": display_name}
        try:
            resp = self.client.request("POST", "/auth/v1/signup", json=body)
        except SupabaseError as exc:
            raise RegistrationFailed("Registration failed") from exc
        if resp.status_code != 200:
            log.warning("Signup failed: status %s", resp.status_code)
            raise RegistrationFailed("Registration failed")

    def login(self, email, password) -> AuthResult:
        try:
            resp = self.client.request(
                "POST",
                "/auth/v1/token",
                params={"grant_type": "password"},
                json={"email": email, "password": password},
            )
        except SupabaseError as exc:
            raise AuthError("Login failed") from exc
        if resp.status_code == 200:
            return self._build(_json(resp))
        log.warning("Login failed: status %s", resp.status_code)
        if resp.status_code in (400, 401, 403, 422):
            if _not_confirmed(_json(resp)):
                raise EmailNotConfirmed("Email not confirmed")
            raise InvalidCredentials("Invalid credentials")
        raise AuthError("Login failed")

    def refresh(self, refresh_token) -> AuthResult:
        try:
            resp = self.client.request(
                "POST",
                "/auth/v1/token",
                params={"grant_type": "refresh_token"},
                json={"refresh_token": refresh_token},
            )
        except SupabaseError as exc:
            raise AuthError("Refresh failed") from exc
        if resp.status_code != 200:
            log.warning("Refresh failed: status %s", resp.status_code)
            raise AuthError("Refresh failed")
        return self._build(_json(resp))

    def logout(self, access_token) -> None:
        """Best effort; failures are logged and swallowed."""
        try:
            resp = self.client.request("POST", "/auth/v1/logout", token=access_token)
            if resp.status_code >= 400:
                log.warning("Logout failed: status %s", resp.status_code)
        except Exception as exc:
            log.warning("Logout failed: %s", type(exc).__name__)
