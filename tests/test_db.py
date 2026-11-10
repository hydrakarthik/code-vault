"""File metadata in PostgreSQL: complete, list, delete, RLS isolation, DB failures."""
import json
from datetime import datetime, timedelta, timezone

from .conftest import TEST_EMAIL, TEST_PASSWORD, csrf, login, register_and_confirm

OTHER_EMAIL = "other@example.com"
OTHER_PASSWORD = "another-password"


def _hdr(client):
    return {"X-CSRF-Token": csrf(client, "/")}


def _uid(fake):
    return fake.user_id(TEST_EMAIL)


def _complete(client, payload, raw=None, headers=True):
    body = raw if raw is not None else json.dumps(payload)
    return client.post(
        "/api/files/complete",
        data=body,
        content_type="application/json",
        headers=_hdr(client) if headers else {},
    )


def _other_client(fake, app):
    uid = register_and_confirm(fake, OTHER_EMAIL, OTHER_PASSWORD)
    c = app.test_client()
    assert login(c, OTHER_EMAIL, OTHER_PASSWORD).status_code == 302
    return c, uid


# -- complete -----------------------------------------------------------
def test_complete_success_upserts_row_from_storage_metadata(signed_in, fake):
    uid = _uid(fake)
    fake.put_object(uid, "report.pdf", b"hello", row=False)
    resp = _complete(signed_in, {"name": "report.pdf"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "report.pdf"
    assert body["size"] == 5
    assert datetime.fromisoformat(body["uploaded_at"]).tzinfo is not None
    rows = fake.rows_for(uid)
    assert len(rows) == 1
    assert rows[0]["size"] == 5
    assert rows[0]["content_type"] == "application/pdf"
    assert rows[0]["object_key"] == f"{uid}/report.pdf"
    # client-supplied size is never trusted
    fake.put_object(uid, "a.txt", b"abc", row=False)
    assert _complete(signed_in, {"name": "a.txt", "size": 999999}).get_json()["size"] == 3


def test_complete_missing_object_404_and_no_row(signed_in, fake):
    resp = _complete(signed_in, {"name": "ghost.txt"})
    assert resp.status_code == 404
    assert fake.rows_for(_uid(fake)) == []
    assert not fake.calls_to("/rest/v1/files", "POST")


def test_complete_requires_csrf(signed_in, fake):
    fake.put_object(_uid(fake), "a.txt", b"x", row=False)
    resp = _complete(signed_in, {"name": "a.txt"}, headers=False)
    assert resp.status_code == 400
    assert fake.rows_for(_uid(fake)) == []


def test_complete_invalid_or_disallowed_name_400(signed_in, fake):
    uid = _uid(fake)
    fake.put_object(uid, "evil.exe", b"x", row=False)
    for name in ("evil.exe", "a/b.txt", "my file.txt", "", "..", None, 5):
        assert _complete(signed_in, {"name": name}).status_code == 400, name
    assert _complete(signed_in, {}).status_code == 400
    assert fake.rows_for(uid) == []
    assert not fake.calls_to("/rest/v1/files")


def test_complete_body_over_4kb_413(signed_in, fake):
    resp = _complete(signed_in, {"name": "a.txt", "pad": "x" * 5000})
    assert resp.status_code == 413
    assert not fake.calls_to("/rest/v1/files")


def test_complete_replace_bumps_uploaded_at_keeps_one_row(signed_in, fake):
    uid = _uid(fake)
    fake.put_object(uid, "a.txt", b"one", row=False)
    first = _complete(signed_in, {"name": "a.txt"}).get_json()
    fake.put_object(uid, "a.txt", b"three", row=False)  # browser upsert
    second = _complete(signed_in, {"name": "a.txt"}).get_json()
    assert datetime.fromisoformat(second["uploaded_at"]) > datetime.fromisoformat(first["uploaded_at"])
    assert second["size"] == 5
    rows = fake.rows_for(uid)
    assert len(rows) == 1
    assert rows[0]["created_at"] <= rows[0]["updated_at"]
    assert [f["name"] for f in signed_in.get("/api/files").get_json()["files"]] == ["a.txt"]


def test_complete_db_failure_502(signed_in, fake):
    fake.put_object(_uid(fake), "a.txt", b"x", row=False)
    fake.fail("/rest/v1/files", "5xx")
    assert _complete(signed_in, {"name": "a.txt"}).status_code == 502


# -- list ---------------------------------------------------------------
def test_list_reads_from_db_newest_first(signed_in, fake):
    uid = _uid(fake)
    now = datetime.now(timezone.utc)
    fake.put_object(uid, "old.txt", b"a", created_at=now - timedelta(days=2))
    fake.put_object(uid, "new.txt", b"abc", created_at=now)
    fake.put_object(uid, "mid.txt", b"", created_at=now - timedelta(days=1))
    fake.put_object(uid, "orphan.txt", b"zz", row=False)  # object without row: not listed
    fake.clear_calls()
    files = signed_in.get("/api/files").get_json()["files"]
    assert [f["name"] for f in files] == ["new.txt", "mid.txt", "old.txt"]
    assert fake.calls_to("/rest/v1/files", "GET")
    assert not fake.calls_to("/object/list/")
    call = fake.calls_to("/rest/v1/files", "GET")[0]
    assert call.params["user_id"] == f"eq.{uid}"
    assert call.params["order"] == "updated_at.desc"


def test_list_db_failure_502(signed_in, fake):
    for kind in ("5xx", "timeout", "malformed"):
        fake.fail("/rest/v1/files", kind)
        resp = signed_in.get("/api/files")
        assert resp.status_code == 502, kind
        assert "error" in resp.get_json()


# -- delete -------------------------------------------------------------
def test_delete_removes_object_and_row(signed_in, fake):
    uid = _uid(fake)
    fake.put_object(uid, "a.txt", b"x")
    resp = signed_in.delete("/api/files/a.txt", headers=_hdr(signed_in))
    assert resp.status_code == 200
    assert not fake.has_object(uid, "a.txt")
    assert not fake.has_row(uid, "a.txt")


def test_delete_row_only_cleans_up_200(signed_in, fake):
    uid = _uid(fake)
    fake.put_row(uid, "a.txt", 1)
    resp = signed_in.delete("/api/files/a.txt", headers=_hdr(signed_in))
    assert resp.status_code == 200
    assert not fake.has_row(uid, "a.txt")


def test_delete_object_only_200(signed_in, fake):
    uid = _uid(fake)
    fake.put_object(uid, "a.txt", b"x", row=False)
    resp = signed_in.delete("/api/files/a.txt", headers=_hdr(signed_in))
    assert resp.status_code == 200
    assert not fake.has_object(uid, "a.txt")


def test_delete_neither_404(signed_in, fake):
    resp = signed_in.delete("/api/files/nope.txt", headers=_hdr(signed_in))
    assert resp.status_code == 404


def test_delete_db_failure_502(signed_in, fake):
    fake.put_object(_uid(fake), "a.txt", b"x")
    fake.fail("/rest/v1/files", "5xx", method="DELETE")
    resp = signed_in.delete("/api/files/a.txt", headers=_hdr(signed_in))
    assert resp.status_code == 502


# -- Property 15: per-user row isolation --------------------------------
def test_property_15_rows_isolated_between_users(signed_in, fake, app):
    other_client, other = _other_client(fake, app)
    mine = _uid(fake)
    names = ["a.txt", "b.pdf", "c d.png", "<x>.txt"]
    for n in names:
        fake.put_object(other, n, b"secret")
    fake.put_object(mine, "mine.txt", b"m")

    # B's rows never appear in A's listing
    assert [f["name"] for f in signed_in.get("/api/files").get_json()["files"]] == ["mine.txt"]
    assert sorted(f["name"] for f in other_client.get("/api/files").get_json()["files"]) == sorted(names)

    # A cannot delete B's rows or objects
    for n in names:
        assert signed_in.delete(f"/api/files/{n}", headers=_hdr(signed_in)).status_code == 404
        assert fake.has_row(other, n) and fake.has_object(other, n)

    # A's complete for B's object name creates nothing for B and 404s for A
    assert _complete(signed_in, {"name": "a.txt"}).status_code == 404
    assert len(fake.rows_for(other)) == len(names)
    assert not fake.has_row(mine, "a.txt")


def test_property_15_rls_rejects_foreign_row_writes(fake, signed_in):
    """The DB layer (RLS) rejects rows whose user_id or object_key mismatch the token."""
    other = fake.add_user("x@example.com", "password-x")
    with signed_in.session_transaction() as s:
        token = s["access_token"]
    base = "https://fake.supabase.test/rest/v1/files"
    hdr = {"Authorization": f"Bearer {token}", "apikey": "k"}
    bad_user = {"user_id": other, "name": "a.txt", "size": 1, "object_key": f"{other}/a.txt"}
    bad_key = {"user_id": _uid(fake), "name": "a.txt", "size": 1, "object_key": f"{other}/a.txt"}
    assert fake.request("POST", base, json=bad_user, headers=hdr).status_code == 403
    assert fake.request("POST", base, json=bad_key, headers=hdr).status_code == 403
    assert fake.request("POST", base, json=bad_key, headers={"apikey": "k"}).status_code == 401
    assert fake.rows == {}


# -- Property 16: complete only for existing objects ---------------------
def test_property_16_complete_only_for_existing_objects(signed_in, fake):
    uid = _uid(fake)
    fake.put_object(uid, "present.txt", b"abc", row=False)
    for name in ("present.txt", "absent.txt", "also-absent.pdf", "x.png"):
        resp = _complete(signed_in, {"name": name})
        if fake.has_object(uid, name):
            assert resp.status_code == 200
            assert fake.has_row(uid, name)
        else:
            assert resp.status_code == 404
            assert not fake.has_row(uid, name)
    assert [r["name"] for r in fake.rows_for(uid)] == ["present.txt"]


# -- apikey / Authorization headers --------------------------------------
def test_anon_calls_send_only_apikey_and_user_calls_send_bearer(fake, app, config):
    register_and_confirm(fake)
    c = app.test_client()
    # signup (anon)
    token = csrf(c, "/register")
    c.post(
        "/register",
        data={"email": "new@example.com", "password": "some-password-1", "csrf_token": token},
    )
    assert login(c).status_code == 302
    anon = fake.calls_to("/auth/v1/signup") + fake.calls_to("/auth/v1/token")
    assert anon
    for call in anon:
        assert "Authorization" not in call.headers
        assert call.token is None
        assert call.headers["apikey"] == config.supabase_anon_key

    fake.clear_calls()
    c.get("/api/files")
    calls = fake.calls_to("/rest/v1/files")
    assert calls
    with c.session_transaction() as s:
        access = s["access_token"]
    for call in calls:
        assert call.headers["Authorization"] == f"Bearer {access}"
        assert call.headers["apikey"] == config.supabase_anon_key
