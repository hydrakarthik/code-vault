"""File listing, upload-URL issuance, view/download, delete, isolation, errors."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .conftest import TEST_EMAIL, csrf, register_and_confirm

OTHER_EMAIL = "other@example.com"
ROOT = Path(__file__).resolve().parent.parent


def _hdr(client):
    return {"X-CSRF-Token": csrf(client, "/")}


def _post_upload(client, payload, raw=None):
    body = raw if raw is not None else json.dumps(payload)
    return client.post(
        "/api/files/upload-url", data=body, content_type="application/json", headers=_hdr(client)
    )


def _uid(fake):
    return fake.user_id(TEST_EMAIL)


# -- list ---------------------------------------------------------------
def test_list_empty(signed_in):
    resp = signed_in.get("/api/files")
    assert resp.status_code == 200
    assert resp.get_json() == {"files": []}


def test_list_newest_first_with_metadata(signed_in, fake):
    uid = _uid(fake)
    now = datetime.now(timezone.utc)
    fake.put_object(uid, "old.txt", b"a", created_at=now - timedelta(days=2))
    fake.put_object(uid, "new.txt", b"abc", created_at=now)
    fake.put_object(uid, "mid.txt", b"", created_at=now - timedelta(days=1))
    files = signed_in.get("/api/files").get_json()["files"]
    assert [f["name"] for f in files] == ["new.txt", "mid.txt", "old.txt"]
    assert files[0]["size"] == 3
    assert datetime.fromisoformat(files[0]["uploaded_at"]).tzinfo is not None


def test_list_only_own_files(signed_in, fake):
    other = register_and_confirm(fake, OTHER_EMAIL, "another-password")
    fake.put_object(other, "secret.txt", b"x")
    fake.put_object(_uid(fake), "mine.txt", b"x")
    names = [f["name"] for f in signed_in.get("/api/files").get_json()["files"]]
    assert names == ["mine.txt"]


def test_list_storage_failure_502(signed_in, fake):
    fake.fail("/rest/v1/files", "5xx")
    resp = signed_in.get("/api/files")
    assert resp.status_code == 502
    assert "error" in resp.get_json()


def test_list_timeout_502(signed_in, fake):
    fake.fail("/rest/v1/files", "timeout", times=5)
    assert signed_in.get("/api/files").status_code == 502


def test_list_malformed_502(signed_in, fake):
    fake.fail("/rest/v1/files", "malformed")
    assert signed_in.get("/api/files").status_code == 502


# -- upload-url ---------------------------------------------------------
def test_upload_url_success_and_upsert_header(signed_in, fake):
    resp = _post_upload(signed_in, {"name": "report.pdf", "size": 1234})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "report.pdf"
    assert data["path"] == f"{_uid(fake)}/report.pdf"
    assert data["token"] and data["url"].startswith("https://fake.supabase.test/storage/v1/")
    calls = fake.calls_to("/object/upload/sign/", "POST")
    assert len(calls) == 1
    assert calls[0].headers.get("x-upsert") == "true"
    # browser PUT completes the upload and the file is then listed
    assert fake.simulate_browser_put(data["url"], b"hello") == 200
    done = signed_in.post(
        "/api/files/complete",
        data=json.dumps({"name": "report.pdf"}),
        content_type="application/json",
        headers=_hdr(signed_in),
    )
    assert done.status_code == 200
    names = [f["name"] for f in signed_in.get("/api/files").get_json()["files"]]
    assert names == ["report.pdf"]


def test_upload_url_sanitizes_name(signed_in, fake):
    resp = _post_upload(signed_in, {"name": "../../etc/my file.txt", "size": 5})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "etc_my_file.txt"
    assert resp.get_json()["path"] == f"{_uid(fake)}/etc_my_file.txt"


def test_upload_url_empty_or_bad_name_400(signed_in, fake):
    for name in ("", "///", None, 123, "..", "   "):
        resp = _post_upload(signed_in, {"name": name, "size": 5})
        assert resp.status_code == 400, name
    assert not fake.calls_to("/object/upload/sign/")


def test_upload_url_disallowed_extension_400(signed_in, fake):
    resp = _post_upload(signed_in, {"name": "evil.exe", "size": 5})
    assert resp.status_code == 400
    assert "not allowed" in resp.get_json()["error"]
    assert _post_upload(signed_in, {"name": "noext", "size": 5}).status_code == 400
    assert not fake.calls_to("/object/upload/sign/")


def test_upload_url_bad_size_400(signed_in):
    for size in (0, -1, "10", None, 1.5, True):
        assert _post_upload(signed_in, {"name": "a.txt", "size": size}).status_code == 400, size


def test_upload_url_too_large_413(signed_in, fake):
    resp = _post_upload(signed_in, {"name": "a.pdf", "size": 10_485_760 + 1})
    assert resp.status_code == 413
    assert "too large" in resp.get_json()["error"].lower()
    assert _post_upload(signed_in, {"name": "a.pdf", "size": 10_485_760}).status_code == 200


def test_upload_url_body_cap_4kb_413(signed_in, fake):
    big = json.dumps({"name": "a.txt", "size": 5, "pad": "x" * 5000})
    resp = _post_upload(signed_in, None, raw=big)
    assert resp.status_code == 413
    assert not fake.calls_to("/object/upload/sign/")


def test_upload_url_non_json_body_400(signed_in):
    assert _post_upload(signed_in, None, raw="not json").status_code == 400
    assert _post_upload(signed_in, None, raw="[1,2]").status_code == 400


def test_upload_url_requires_csrf(signed_in, fake):
    resp = signed_in.post("/api/files/upload-url", json={"name": "a.txt", "size": 5})
    assert resp.status_code == 400
    assert not fake.calls_to("/object/upload/sign/")


def test_upload_url_storage_failure_502(signed_in, fake):
    fake.fail("/object/upload/sign/", "5xx")
    assert _post_upload(signed_in, {"name": "a.txt", "size": 5}).status_code == 502


def test_upload_url_user_cannot_pick_other_prefix(signed_in, fake):
    other = register_and_confirm(fake, OTHER_EMAIL, "another-password")
    resp = _post_upload(signed_in, {"name": "a.txt", "size": 5, "user_id": other, "path": f"{other}/a.txt"})
    assert resp.status_code == 200
    assert resp.get_json()["path"] == f"{_uid(fake)}/a.txt"


# -- view / download ----------------------------------------------------
def test_download_redirects_with_60s_ttl_and_disposition(signed_in, fake):
    fake.put_object(_uid(fake), "my doc.pdf", b"x")
    resp = signed_in.get("/api/files/my%20doc.pdf/download")
    assert resp.status_code == 302
    loc = resp.headers["Location"]
    assert loc.startswith("https://fake.supabase.test/storage/v1/object/sign/")
    assert parse_qs(urlparse(loc).query)["download"] == ["my doc.pdf"]
    sign = fake.calls_to("/object/sign/", "POST")
    assert sign[-1].json == {"expiresIn": 60}


def test_view_redirects_without_download_param(signed_in, fake):
    fake.put_object(_uid(fake), "pic.png", b"x")
    resp = signed_in.get("/api/files/pic.png/view")
    assert resp.status_code == 302
    q = parse_qs(urlparse(resp.headers["Location"]).query)
    assert "download" not in q
    assert fake.calls_to("/object/sign/", "POST")[-1].json == {"expiresIn": 60}


def test_view_non_previewable_400(signed_in, fake):
    fake.put_object(_uid(fake), "doc.docx", b"x")
    resp = signed_in.get("/api/files/doc.docx/view")
    assert resp.status_code == 400
    assert not fake.calls_to("/object/sign/")


def test_view_and_download_missing_404(signed_in):
    assert signed_in.get("/api/files/nope.png/view").status_code == 404
    assert signed_in.get("/api/files/nope.png/download").status_code == 404


def test_view_and_download_other_users_file_404(signed_in, fake):
    other = register_and_confirm(fake, OTHER_EMAIL, "another-password")
    fake.put_object(other, "secret.png", b"x")
    assert signed_in.get("/api/files/secret.png/view").status_code == 404
    assert signed_in.get("/api/files/secret.png/download").status_code == 404
    assert not fake.calls_to("/object/sign/")


def test_download_storage_failure_502(signed_in, fake):
    fake.put_object(_uid(fake), "a.txt", b"x")
    fake.fail("/object/sign/", "5xx")
    assert signed_in.get("/api/files/a.txt/download").status_code == 502


def test_download_malformed_sign_response_502(signed_in, fake):
    fake.put_object(_uid(fake), "a.txt", b"x")
    fake.fail("/object/sign/", "malformed")
    assert signed_in.get("/api/files/a.txt/download").status_code == 502


def test_file_endpoints_require_login(client):
    assert client.get("/api/files").status_code == 401
    assert client.get("/api/files/a.txt/download").status_code in (302, 401)
    assert client.get("/api/files/a.png/view").status_code in (302, 401)


# -- delete -------------------------------------------------------------
def test_delete_success(signed_in, fake):
    uid = _uid(fake)
    fake.put_object(uid, "a.txt", b"x")
    resp = signed_in.delete("/api/files/a.txt", headers=_hdr(signed_in))
    assert resp.status_code == 200
    assert resp.get_json() == {"deleted": "a.txt"}
    assert not fake.has_object(uid, "a.txt")
    assert signed_in.get("/api/files").get_json() == {"files": []}


def test_delete_missing_404(signed_in):
    resp = signed_in.delete("/api/files/missing.txt", headers=_hdr(signed_in))
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "File not found."


def test_delete_other_users_file_404_and_untouched(signed_in, fake):
    other = register_and_confirm(fake, OTHER_EMAIL, "another-password")
    fake.put_object(other, "secret.txt", b"x")
    resp = signed_in.delete("/api/files/secret.txt", headers=_hdr(signed_in))
    assert resp.status_code == 404
    assert fake.has_object(other, "secret.txt")


def test_delete_requires_csrf(signed_in, fake):
    fake.put_object(_uid(fake), "a.txt", b"x")
    resp = signed_in.delete("/api/files/a.txt")
    assert resp.status_code == 400
    assert fake.has_object(_uid(fake), "a.txt")


def test_delete_storage_failure_502(signed_in, fake):
    fake.put_object(_uid(fake), "a.txt", b"x")
    fake.fail("/object/", "timeout", times=5, method="DELETE")
    resp = signed_in.delete("/api/files/a.txt", headers=_hdr(signed_in))
    assert resp.status_code == 502
    assert fake.has_object(_uid(fake), "a.txt")


# -- no secret leakage --------------------------------------------------
def test_error_responses_do_not_leak_secrets(signed_in, fake):
    fake.put_object(_uid(fake), "a.txt", b"x")
    fake.fail("/rest/v1/files", "5xx")
    fake.fail("/object/sign/", "5xx")
    with signed_in.session_transaction() as s:
        secrets_ = [s["access_token"], s["refresh_token"], "test-anon-key", "test-secret-key"]
    bodies = [
        signed_in.get("/api/files").get_data(as_text=True),
        signed_in.get("/api/files/a.txt/download").get_data(as_text=True),
        signed_in.get("/api/files/missing.txt/download").get_data(as_text=True),
    ]
    for body in bodies:
        for secret in secrets_:
            assert secret not in body
        assert "fake.supabase.test" not in body
        assert "Traceback" not in body


def test_dashboard_does_not_leak_tokens(signed_in):
    with signed_in.session_transaction() as s:
        tokens = [s["access_token"], s["refresh_token"]]
    html = signed_in.get("/").get_data(as_text=True)
    for t in tokens:
        assert t not in html
    assert "test-anon-key" not in html


# -- file name escaping -------------------------------------------------
def test_dashboard_does_not_render_file_names_server_side(signed_in, fake):
    evil = "<script>alert(1)</script>.txt"
    fake.put_object(_uid(fake), evil, b"x")
    html = signed_in.get("/").get_data(as_text=True)
    assert evil not in html
    assert "<script>alert(1)" not in html


def test_api_returns_names_as_json_data(signed_in, fake):
    evil = "<img src=x onerror=alert(1)>.txt"
    fake.put_object(_uid(fake), evil, b"x")
    resp = signed_in.get("/api/files")
    assert resp.mimetype == "application/json"
    assert resp.get_json()["files"][0]["name"] == evil
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_app_js_uses_text_content_not_inner_html():
    js = (ROOT / "public" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js
    assert "outerHTML" not in js
    assert "insertAdjacentHTML" not in js
    assert "document.write" not in js
    assert "textContent" in js
    assert "encodeURIComponent(f.name)" in js
