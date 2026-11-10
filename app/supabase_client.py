"""Thin wrapper around requests for Supabase REST endpoints."""
import logging

import requests

log = logging.getLogger(__name__)


class SupabaseError(Exception):
    """Raised when a Supabase request cannot be completed (network/timeout)."""


class SupabaseClient:
    def __init__(self, url, anon_key, session=None, timeout=(3.05, 10)):
        self.base = url.rstrip("/")
        self.anon_key = anon_key
        self.http = session or requests.Session()
        self.timeout = timeout

    def request(self, method, path, *, token=None, json=None, params=None, headers=None):
        # The apikey header always carries the configured key (legacy anon JWT or
        # sb_publishable_...). Publishable keys are not JWTs, so Authorization is
        # sent only when a user access token is supplied.
        h = {"apikey": self.anon_key}
        if token:
            h["Authorization"] = f"Bearer {token}"
        h.update(headers or {})
        try:
            return self.http.request(
                method,
                self.base + path,
                json=json,
                params=params,
                headers=h,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            # Log only the exception class; never URLs, headers, or bodies.
            log.warning("Supabase request failed: %s", type(exc).__name__)
            raise SupabaseError("Supabase request failed") from exc
