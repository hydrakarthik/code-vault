"""FakeSupabase: an in-memory, requests.Session-compatible stand-in for Supabase.

Simulates /auth/v1 (signup, password/refresh grants, logout) and /storage/v1
(list, sign, upload/sign, delete) with an RLS-style prefix check, call recording,
and failure injection. No network access.
"""
import itertools
import mimetypes
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import requests


class FakeResponse:
    def __init__(self, status_code=200, body=None, raw=None):
        self.status_code = status_code
        self._body = body
        self.text = raw if raw is not None else ("" if body is None else str(body))

    def json(self):
        if self._body is None:
            raise ValueError("no json body")
        return self._body


@dataclass
class Call:
    method: str
    path: str  # path without scheme/host, no query
    token: str | None
    json: object = None
    params: dict | None = None
    headers: dict = field(default_factory=dict)


@dataclass
class _User:
    id: str
    email: str
    password: str
    confirmed: bool = False
    metadata: object = None


class FakeSupabase:
    BASE = "https://fake.supabase.test"

    def __init__(self, bucket="files", expires_in=3600):
        self.bucket = bucket
        self.expires_in = expires_in
        self.users: dict[str, _User] = {}  # by email
        self.objects: dict[str, dict] = {}  # key -> {data, created_at}
        self.access_tokens: dict[str, tuple[str, int]] = {}  # token -> (user_id, exp)
        self.refresh_tokens: dict[str, str] = {}  # token -> user_id
        self.upload_tokens: dict[str, str] = {}  # token -> key
        self.rows: dict[tuple[str, str], dict] = {}  # (user_id, name) -> public.files row
        self.calls: list[Call] = []
        self._failures: list[dict] = []
        self._counter = itertools.count(1)

    # -- test helpers ----------------------------------------------------
    def add_user(self, email, password, confirmed=True, display_name=None) -> str:
        meta = {"display_name": display_name} if display_name is not None else {}
        user = _User(str(uuid.uuid4()), email.strip().lower(), password, confirmed, meta)
        self.users[user.email] = user
        return user.id

    def confirm(self, email):
        self.users[email.strip().lower()].confirmed = True

    def user_id(self, email) -> str:
        return self.users[email.strip().lower()].id

    def put_object(self, user_id, name, data=b"", created_at=None, row=True):
        """Insert a storage object and (by default) a matching public.files row."""
        if isinstance(data, str):
            data = data.encode()
        created_at = created_at or datetime.now(timezone.utc)
        self.objects[f"{user_id}/{name}"] = {"data": data, "created_at": created_at}
        if row:
            self.put_row(user_id, name, len(data), created_at=created_at)

    def put_row(self, user_id, name, size=0, created_at=None, content_type=None):
        """Insert a public.files row only (no storage object)."""
        created_at = created_at or datetime.now(timezone.utc)
        self.rows[(user_id, name)] = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "name": name,
            "size": size,
            "content_type": content_type or mimetypes.guess_type(name)[0],
            "object_key": f"{user_id}/{name}",
            "created_at": created_at,
            "updated_at": created_at,
        }

    def has_row(self, user_id, name) -> bool:
        return (user_id, name) in self.rows

    def rows_for(self, user_id) -> list:
        return [r for (u, _), r in self.rows.items() if u == user_id]

    def has_object(self, user_id, name) -> bool:
        return f"{user_id}/{name}" in self.objects

    def simulate_browser_put(self, signed_url, data=b""):
        """Simulate the browser PUT to a signed upload URL. Returns status code."""
        q = parse_qs(urlparse(signed_url).query)
        token = (q.get("token") or [None])[0]
        key = self.upload_tokens.get(token)
        if key is None:
            return 401
        self.put_object(key.split("/", 1)[0], key.split("/", 1)[1], data)
        return 200

    def expire_access_token(self, token):
        uid, _ = self.access_tokens[token]
        self.access_tokens[token] = (uid, int(time.time()) - 10)

    def fail(self, path_contains, kind="5xx", times=1, method=None):
        """Inject a failure. kind: 'timeout' | '5xx' | 'malformed'."""
        self._failures.append(
            {"path": path_contains, "kind": kind, "times": times, "method": method}
        )

    def calls_to(self, path_contains, method=None):
        return [
            c for c in self.calls
            if path_contains in c.path and (method is None or c.method == method)
        ]

    def clear_calls(self):
        self.calls.clear()

    # -- requests.Session API --------------------------------------------
    def request(self, method, url, json=None, params=None, headers=None, timeout=None, **_):
        parsed = urlparse(url)
        path = unquote(parsed.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        params = {**query, **(params or {})}
        headers = dict(headers or {})
        auth = headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else None
        self.calls.append(Call(method, path, token, json, params, headers))

        for f in self._failures:
            if f["times"] > 0 and f["path"] in path and f["method"] in (None, method):
                f["times"] -= 1
                if f["kind"] == "timeout":
                    raise requests.Timeout("injected timeout")
                if f["kind"] == "5xx":
                    return FakeResponse(503, {"message": "unavailable"})
                if f["kind"] == "malformed":
                    return FakeResponse(200, None, raw="<<not json>>")

        if path.startswith("/auth/v1/"):
            return self._auth(method, path[len("/auth/v1"):], json, params, token)
        if path.startswith("/storage/v1/"):
            return self._storage(method, path[len("/storage/v1"):], json, token)
        if path == "/rest/v1/files":
            return self._rest_files(method, json, params, token)
        return FakeResponse(404, {"message": "not found"})

    # -- auth ------------------------------------------------------------
    def _issue(self, user: _User) -> dict:
        n = next(self._counter)
        access = f"access-{n}-{uuid.uuid4().hex}"
        refresh = f"refresh-{n}-{uuid.uuid4().hex}"
        exp = int(time.time()) + self.expires_in
        self.access_tokens[access] = (user.id, exp)
        self.refresh_tokens[refresh] = user.id
        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": self.expires_in,
            "expires_at": exp,
            "token_type": "bearer",
            "user": {"id": user.id, "email": user.email, "user_metadata": user.metadata},
        }

    def _auth(self, method, path, body, params, token):
        body = body if isinstance(body, dict) else {}
        if path == "/signup" and method == "POST":
            email = str(body.get("email", "")).strip().lower()
            if not email or len(str(body.get("password", ""))) < 6:
                return FakeResponse(422, {"error_code": "weak_password"})
            if email not in self.users:  # existing users are obfuscated: same 200
                self.add_user(email, body["password"], confirmed=False)
                data = body.get("data")
                self.users[email].metadata = data if isinstance(data, dict) else {}
            return FakeResponse(200, {"id": self.users[email].id, "email": email})
        if path == "/token" and method == "POST":
            grant = params.get("grant_type")
            if grant == "password":
                user = self.users.get(str(body.get("email", "")).strip().lower())
                if user is None or user.password != body.get("password"):
                    return FakeResponse(
                        400, {"error_code": "invalid_credentials", "msg": "Invalid login credentials"}
                    )
                if not user.confirmed:
                    return FakeResponse(
                        400, {"error_code": "email_not_confirmed", "msg": "Email not confirmed"}
                    )
                return FakeResponse(200, self._issue(user))
            if grant == "refresh_token":
                uid = self.refresh_tokens.pop(body.get("refresh_token"), None)
                if uid is None:
                    return FakeResponse(400, {"error_code": "refresh_token_not_found"})
                user = next(u for u in self.users.values() if u.id == uid)
                return FakeResponse(200, self._issue(user))
        if path == "/logout" and method == "POST":
            if token in self.access_tokens:
                uid = self.access_tokens.pop(token)[0]
                for r in [r for r, u in self.refresh_tokens.items() if u == uid]:
                    del self.refresh_tokens[r]
                return FakeResponse(204)
            return FakeResponse(401, {"message": "invalid token"})
        return FakeResponse(404, {"message": "not found"})

    # -- storage ---------------------------------------------------------
    def _uid(self, token):
        entry = self.access_tokens.get(token)
        if entry is None or entry[1] <= time.time():
            return None
        return entry[0]

    def _split_obj(self, rest):
        """rest = '<bucket>/<uid>/<name>' -> (bucket, key)."""
        bucket, _, key = rest.partition("/")
        return bucket, key

    def _rls_ok(self, uid, key):
        return uid is not None and key.split("/", 1)[0] == uid

    def _storage(self, method, path, body, token):
        uid = self._uid(token)
        body = body if isinstance(body, dict) else {}

        if method == "POST" and path.startswith("/object/list/"):
            if path[len("/object/list/"):] != self.bucket:
                return FakeResponse(404, {"message": "bucket not found"})
            if uid is None:
                return FakeResponse(401, {"message": "unauthorized"})
            prefix = str(body.get("prefix", "")).strip("/")
            search = body.get("search")
            items = []
            if prefix == uid:  # RLS: other prefixes are simply empty
                for key, obj in self.objects.items():
                    owner, _, name = key.partition("/")
                    if owner != prefix or (search and search not in name):
                        continue
                    items.append({
                        "name": name,
                        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
                        "created_at": obj["created_at"].isoformat(),
                        "updated_at": obj["created_at"].isoformat(),
                        "metadata": {
                            "size": len(obj["data"]),
                            "mimetype": mimetypes.guess_type(name)[0] or "application/octet-stream",
                        },
                    })
                items.sort(key=lambda i: i["created_at"], reverse=True)
            offset = int(body.get("offset") or 0)
            limit = int(body.get("limit") or 100)
            return FakeResponse(200, items[offset:offset + limit])

        if method == "POST" and path.startswith("/object/upload/sign/"):
            bucket, key = self._split_obj(path[len("/object/upload/sign/"):])
            if bucket != self.bucket:
                return FakeResponse(404, {"message": "bucket not found"})
            if not self._rls_ok(uid, key):
                return FakeResponse(403, {"message": "new row violates row-level security policy"})
            tok = f"upload-{uuid.uuid4().hex}"
            self.upload_tokens[tok] = key
            return FakeResponse(
                200, {"url": f"/object/upload/sign/{bucket}/{key}?token={tok}", "token": tok}
            )

        if method == "POST" and path.startswith("/object/sign/"):
            bucket, key = self._split_obj(path[len("/object/sign/"):])
            if bucket != self.bucket:
                return FakeResponse(404, {"message": "bucket not found"})
            if not self._rls_ok(uid, key) or key not in self.objects:
                return FakeResponse(404, {"statusCode": "404", "error": "not_found"})
            return FakeResponse(
                200, {"signedURL": f"/object/sign/{bucket}/{key}?token=read-{uuid.uuid4().hex}"}
            )

        if method == "DELETE" and path.startswith("/object/"):
            bucket, key = self._split_obj(path[len("/object/"):])
            if bucket != self.bucket:
                return FakeResponse(404, {"message": "bucket not found"})
            if not self._rls_ok(uid, key) or key not in self.objects:
                return FakeResponse(404, {"statusCode": "404", "error": "not_found"})
            del self.objects[key]
            return FakeResponse(200, {"message": "Successfully deleted"})

        return FakeResponse(404, {"message": "not found"})

    # -- PostgREST: public.files with RLS (user_id = auth.uid()) -----------
    @staticmethod
    def _row_json(row):
        out = dict(row)
        out["created_at"] = row["created_at"].isoformat()
        out["updated_at"] = row["updated_at"].isoformat()
        return out

    def _visible(self, uid, params):
        rows = [r for r in self.rows.values() if r["user_id"] == uid]  # RLS
        for col in ("user_id", "name"):
            val = params.get(col)
            if val is not None:
                if not val.startswith("eq."):
                    return []
                rows = [r for r in rows if r[col] == val[3:]]
        return rows

    def _rest_files(self, method, body, params, token):
        uid = self._uid(token)
        if uid is None:
            return FakeResponse(401, {"message": "JWT expired or invalid"})
        if method == "GET":
            rows = self._visible(uid, params)
            rows.sort(key=lambda r: r["updated_at"], reverse=True)
            return FakeResponse(200, [self._row_json(r) for r in rows])
        if method == "DELETE":
            rows = self._visible(uid, params)
            for r in rows:
                del self.rows[(r["user_id"], r["name"])]
            return FakeResponse(200, [self._row_json(r) for r in rows])
        if method == "POST":
            body = body if isinstance(body, dict) else {}
            name = body.get("name")
            if (
                body.get("user_id") != uid
                or not isinstance(name, str)
                or body.get("object_key") != f"{uid}/{name}"
            ):
                return FakeResponse(
                    403, {"message": "new row violates row-level security policy for table \"files\""}
                )
            now = datetime.now(timezone.utc)
            existing = self.rows.get((uid, name))
            if existing is None:
                self.rows[(uid, name)] = {
                    "id": str(uuid.uuid4()),
                    "user_id": uid,
                    "name": name,
                    "size": body.get("size"),
                    "content_type": body.get("content_type"),
                    "object_key": body["object_key"],
                    "created_at": now,
                    "updated_at": now,
                }
            else:
                existing["size"] = body.get("size")
                existing["content_type"] = body.get("content_type")
                existing["updated_at"] = max(now, existing["updated_at"] + timedelta(microseconds=1))
            return FakeResponse(201, [self._row_json(self.rows[(uid, name)])])
        return FakeResponse(405, {"message": "method not allowed"})
