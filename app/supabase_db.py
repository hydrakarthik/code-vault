"""PostgREST access to public.files, using the user's access token (RLS applies)."""
import logging
from datetime import datetime, timezone

from .supabase_client import SupabaseClient, SupabaseError
from .supabase_storage import StorageError, UserContext, _json, _parse_time

log = logging.getLogger(__name__)

SELECT = "name,size,content_type,created_at,updated_at"


class DatabaseError(StorageError):
    pass


def _rows(resp):
    data = _json(resp)
    if not isinstance(data, list):
        log.warning("Database returned malformed body")
        raise DatabaseError("Database request failed")
    return data


class FilesRepo:
    def __init__(self, client: SupabaseClient):
        self.client = client

    def _send(self, method, ctx: UserContext, **kw):
        try:
            resp = self.client.request(method, "/rest/v1/files", token=ctx.access_token, **kw)
        except SupabaseError as exc:
            raise DatabaseError("Database request failed") from exc
        if not 200 <= resp.status_code < 300:
            log.warning("Database call failed: status %s", resp.status_code)
            raise DatabaseError("Database request failed")
        return resp

    def list(self, ctx: UserContext) -> list:
        resp = self._send(
            "GET",
            ctx,
            params={
                "select": SELECT,
                "user_id": f"eq.{ctx.user_id}",
                "order": "updated_at.desc",
            },
        )
        out = []
        for row in _rows(resp):
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                continue
            size = row.get("size")
            if not isinstance(size, int) or isinstance(size, bool):
                size = 0
            out.append(
                {
                    "name": row["name"],
                    "size": size,
                    "uploaded_at": _parse_time(row.get("updated_at") or row.get("created_at")),
                }
            )
        out.sort(key=lambda r: r["uploaded_at"], reverse=True)
        return out

    def upsert(self, ctx: UserContext, name: str, size: int, content_type) -> dict:
        resp = self._send(
            "POST",
            ctx,
            params={"on_conflict": "user_id,name"},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            json={
                "user_id": ctx.user_id,
                "name": name,
                "size": size,
                "content_type": content_type,
                "object_key": f"{ctx.user_id}/{name}",
            },
        )
        rows = _rows(resp)
        row = rows[0] if rows and isinstance(rows[0], dict) else {}
        return {
            "name": name,
            "size": size,
            "uploaded_at": _parse_time(row.get("updated_at") or row.get("created_at"))
            if row
            else datetime.now(timezone.utc),
        }

    def delete(self, ctx: UserContext, name: str) -> bool:
        resp = self._send(
            "DELETE",
            ctx,
            params={"user_id": f"eq.{ctx.user_id}", "name": f"eq.{name}"},
            headers={"Prefer": "return=representation"},
        )
        return len(_rows(resp)) > 0
