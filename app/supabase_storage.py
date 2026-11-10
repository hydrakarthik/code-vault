"""Supabase Storage calls scoped to a single user's prefix."""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlparse

from .supabase_client import SupabaseClient, SupabaseError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserContext:
    user_id: str
    access_token: str


@dataclass(frozen=True)
class FileRecord:
    name: str
    size: int
    uploaded_at: datetime  # tz-aware UTC


class StorageError(Exception):
    pass


class FileNotFound(StorageError):
    pass


class InvalidFileName(StorageError):
    pass


def _json(resp):
    try:
        return resp.json()
    except Exception:
        return None


def _is_not_found(resp) -> bool:
    if resp.status_code == 404:
        return True
    if resp.status_code == 400:
        data = _json(resp)
        if isinstance(data, dict):
            return str(data.get("statusCode")) == "404" or data.get("error") in (
                "not_found",
                "Not found",
            )
    return False


def _parse_time(value) -> datetime:
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(0, tz=timezone.utc)


class SupabaseStorage:
    def __init__(self, client: SupabaseClient, bucket: str, supabase_url: str):
        self.client = client
        self.bucket = bucket
        self.storage_base = supabase_url.rstrip("/") + "/storage/v1"

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _check_name(name):
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or "\\" in name
            or "\x00" in name
            or name in (".", "..")
        ):
            raise InvalidFileName("Invalid file name.")

    def key(self, ctx: UserContext, name: str) -> str:
        self._check_name(name)
        return f"{ctx.user_id}/{name}"

    def _obj_path(self, prefix: str, ctx, name) -> str:
        key = self.key(ctx, name)
        enc = "/".join(quote(seg, safe="") for seg in key.split("/"))
        return f"/storage/v1/object/{prefix}{quote(self.bucket, safe='')}/{enc}"

    def _send(self, method, path, ctx, **kw):
        try:
            return self.client.request(method, path, token=ctx.access_token, **kw)
        except SupabaseError as exc:
            raise StorageError("Storage request failed") from exc

    @staticmethod
    def _fail(resp):
        log.warning("Storage call failed: status %s", resp.status_code)
        raise StorageError("Storage request failed")

    def _absolute(self, rel: str) -> str:
        if rel.startswith("http://") or rel.startswith("https://"):
            return rel
        if rel.startswith("/storage/v1"):
            rel = rel[len("/storage/v1"):]
        if not rel.startswith("/"):
            rel = "/" + rel
        return self.storage_base + rel

    # -- operations ------------------------------------------------------
    def list(self, ctx: UserContext) -> list:
        resp = self._send(
            "POST",
            f"/storage/v1/object/list/{quote(self.bucket, safe='')}",
            ctx,
            json={
                "prefix": ctx.user_id,
                "limit": 1000,
                "offset": 0,
                "sortBy": {"column": "created_at", "order": "desc"},
            },
        )
        if resp.status_code != 200:
            self._fail(resp)
        data = _json(resp)
        if not isinstance(data, list):
            log.warning("Storage list returned malformed body")
            raise StorageError("Storage request failed")
        records = []
        for item in data:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            meta = item.get("metadata") or {}
            size = meta.get("size") if isinstance(meta, dict) else None
            if not isinstance(size, int) or isinstance(size, bool):
                size = 0
            records.append(
                FileRecord(
                    name=name,
                    size=size,
                    uploaded_at=_parse_time(item.get("created_at") or item.get("updated_at")),
                )
            )
        records.sort(key=lambda r: r.uploaded_at, reverse=True)
        return records

    def exists(self, ctx: UserContext, name: str) -> bool:
        self._check_name(name)
        resp = self._send(
            "POST",
            f"/storage/v1/object/list/{quote(self.bucket, safe='')}",
            ctx,
            json={"prefix": ctx.user_id, "limit": 100, "offset": 0, "search": name},
        )
        if resp.status_code != 200:
            self._fail(resp)
        data = _json(resp)
        if not isinstance(data, list):
            raise StorageError("Storage request failed")
        return any(
            isinstance(i, dict) and i.get("name") == name and i.get("id") is not None
            for i in data
        )

    def delete(self, ctx: UserContext, name: str) -> None:
        if not self.exists(ctx, name):
            raise FileNotFound("File not found.")
        resp = self._send("DELETE", self._obj_path("", ctx, name), ctx)
        if _is_not_found(resp):
            raise FileNotFound("File not found.")
        if resp.status_code not in (200, 204):
            self._fail(resp)

    def create_upload_url(self, ctx: UserContext, name: str) -> dict:
        key = self.key(ctx, name)
        resp = self._send(
            "POST",
            self._obj_path("upload/sign/", ctx, name),
            ctx,
            headers={"x-upsert": "true"},
        )
        if resp.status_code not in (200, 201):
            self._fail(resp)
        data = _json(resp)
        if not isinstance(data, dict) or not isinstance(data.get("url"), str):
            log.warning("Malformed signed upload response")
            raise StorageError("Storage request failed")
        url = self._absolute(data["url"])
        token = data.get("token")
        if not isinstance(token, str) or not token:
            token = (parse_qs(urlparse(url).query).get("token") or [None])[0]
        if not token:
            log.warning("Signed upload response missing token")
            raise StorageError("Storage request failed")
        return {"url": url, "token": token, "path": key}

    def _signed_read(self, ctx, name, ttl) -> str:
        self._check_name(name)
        if not self.exists(ctx, name):
            raise FileNotFound("File not found.")
        resp = self._send(
            "POST",
            self._obj_path("sign/", ctx, name),
            ctx,
            json={"expiresIn": ttl},
        )
        if _is_not_found(resp):
            raise FileNotFound("File not found.")
        if resp.status_code != 200:
            self._fail(resp)
        data = _json(resp)
        signed = data.get("signedURL") if isinstance(data, dict) else None
        if not isinstance(signed, str) or not signed:
            log.warning("Malformed signed URL response")
            raise StorageError("Storage request failed")
        return self._absolute(signed)

    def download_url(self, ctx: UserContext, name: str, ttl: int) -> str:
        url = self._signed_read(ctx, name, ttl)
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}download={quote(name, safe='')}"

    def view_url(self, ctx: UserContext, name: str, ttl: int) -> str:
        return self._signed_read(ctx, name, ttl)
