"""Auth tests: registration, login, logout, refresh, access control, CSRF."""
import pytest

from app import create_app
from app.auth import CSRF_EXPIRED, INVALID_CREDENTIALS, NOT_CONFIRMED, REGISTER_FAILED, REGISTER_MSG
from app.supabase_client import SupabaseClient

from .conftest import TEST_EMAIL, TEST_PASSWORD, csrf, login, make_config, register_and_confirm


def register(client, email="new@example.com", password="longenough1", token=None):
    token = token if token is not None else csrf(client, "/register")
    return client.post(
        "/register", data={"email": email, "password": password, "csrf_token": token}
    )


def session_of(client):
    with client.session_transaction() as s:
        return dict(s)


# -- registration (1.3-1.6) ------------------------------------------------
def test_register_success_shows_message_and_no_session(client, fake):
    resp = register(client)
    assert resp.status_code == 200
    assert REGISTER_MSG in resp.get_data(as_text=True)
    assert "new@example.com" in fake.users
    assert "user_id" not in session_of(client)
    assert "access_token" not in session_of(client)


@pytest.mark.parametrize(
    "email,password,fragment",
    [
        ("not-an-email", "longenough1", "valid email"),
        ("a@b.com", "short", "at least 8"),
        ("a@b.com", "x" * 129, "at most 128"),
    ],
)
def test_register_validation_rejected_with_400(client, fake, email, password, fragment):
    resp = register(client, email, password)
    assert resp.status_code == 400
    assert fragment in resp.get_data(as_text=True)
    assert not fake.calls_to("/auth/v1/signup")
    assert "user_id" not in session_of(client)


def test_register_duplicate_email_is_indistinguishable(client, fake):
    register_and_confirm(fake)
    dup = register(client, TEST_EMAIL)
    fresh = register(client, "other@example.com")
    assert dup.status_code == fresh.status_code == 200
    assert REGISTER_MSG in dup.get_data(as_text=True)
    assert REGISTER_MSG in fresh.get_data(as_text=True)
    assert "already" not in dup.get_data(as_text=True).lower()
    assert "user_id" not in session_of(client)


@pytest.mark.parametrize("kind", ["5xx", "timeout"])
def test_register_supabase_failure_generic_error(client, fake, kind):
    token = csrf(client, "/register")
    fake.fail("/auth/v1/signup", kind)
    resp = register(client, token=token)
    body = resp.get_data(as_text=True)
    assert REGISTER_FAILED in body
    assert REGISTER_MSG not in body
    assert "user_id" not in session_of(client)


def test_register_bad_csrf_rejected(client, fake):
    csrf(client, "/register")
    resp = register(client, token="wrong")
    assert resp.status_code == 400
    assert CSRF_EXPIRED in resp.get_data(as_text=True)
    assert not fake.calls_to("/auth/v1/signup")


# -- login (2.1-2.3) ---------------------------------------------------------
def test_login_success_creates_session_and_redirects(client, fake):
    uid = register_and_confirm(fake)
    resp = login(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    s = session_of(client)
    assert s["user_id"] == uid
    assert s["email"] == TEST_EMAIL
    assert s["access_token"] and s["refresh_token"] and s["expires_at"]
    page = client.get("/")
    assert page.status_code == 200
    assert TEST_EMAIL in page.get_data(as_text=True)


def test_login_normalizes_email(client, fake):
    register_and_confirm(fake)
    resp = login(client, email="  USER@Example.com ")
    assert resp.status_code == 302


@pytest.mark.parametrize(
    "email,password",
    [(TEST_EMAIL, "wrong-password"), ("nobody@example.com", TEST_PASSWORD), ("", ""), (TEST_EMAIL, "")],
)
def test_login_invalid_credentials_generic(client, fake, email, password):
    register_and_confirm(fake)
    resp = login(client, email, password)
    assert resp.status_code == 200
    assert INVALID_CREDENTIALS in resp.get_data(as_text=True)
    assert "user_id" not in session_of(client)


def test_login_unconfirmed_user_rejected(client, fake):
    fake.add_user(TEST_EMAIL, TEST_PASSWORD, confirmed=False)
    resp = login(client)
    body = resp.get_data(as_text=True)
    assert NOT_CONFIRMED in body
    assert INVALID_CREDENTIALS not in body
    assert "user_id" not in session_of(client)


def test_login_supabase_outage_gives_generic_error(client, fake):
    register_and_confirm(fake)
    token = csrf(client, "/login")
    fake.fail("/auth/v1/token", "5xx")
    resp = client.post(
        "/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD, "csrf_token": token}
    )
    assert INVALID_CREDENTIALS in resp.get_data(as_text=True)
    assert "user_id" not in session_of(client)


def test_login_rotates_csrf_token_and_clears_old_session(client, fake):
    register_and_confirm(fake)
    old = csrf(client, "/login")
    login(client)
    assert session_of(client)["csrf_token"] != old


# -- cookie flags (2.4, 2.5) ---------------------------------------------------
def test_session_cookie_httponly_samesite_not_secure_in_dev(client):
    resp = client.get("/login")
    cookie = resp.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" not in cookie


def test_session_cookie_secure_in_production(fake):
    config = make_config(production=True)
    sb = SupabaseClient(config.supabase_url, config.supabase_anon_key, session=fake)
    prod = create_app(config, supabase_client=sb)
    cookie = prod.test_client().get("/login").headers["Set-Cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


# -- logout (3.1, 5.2) ---------------------------------------------------------
def test_logout_revokes_token_clears_session_and_redirects(signed_in, fake):
    token = session_of(signed_in)["access_token"]
    resp = signed_in.post("/logout", data={"csrf_token": session_of(signed_in)["csrf_token"]})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert "user_id" not in session_of(signed_in)
    calls = fake.calls_to("/auth/v1/logout", "POST")
    assert len(calls) == 1 and calls[0].token == token
    assert token not in fake.access_tokens


def test_logout_without_csrf_rejected_and_keeps_session(signed_in, fake):
    resp = signed_in.post("/logout")
    assert resp.status_code == 400
    assert "user_id" in session_of(signed_in)
    assert not fake.calls_to("/auth/v1/logout")


def test_logout_succeeds_even_if_revocation_fails(signed_in, fake):
    fake.fail("/auth/v1/logout", "5xx")
    resp = signed_in.post("/logout", data={"csrf_token": session_of(signed_in)["csrf_token"]})
    assert resp.status_code == 302
    assert "user_id" not in session_of(signed_in)


def test_logout_requires_session(client):
    resp = client.post("/logout")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


# -- token refresh (3.2, 3.3) --------------------------------------------------
def _signed_in_with_expiring_token(fake, app):
    """Log in with tokens inside the refresh skew window, then restore normal expiry."""
    register_and_confirm(fake)
    fake.expires_in = 10
    c = app.test_client()
    assert login(c).status_code == 302
    fake.expires_in = 3600
    fake.clear_calls()
    return c


def test_expiring_token_is_refreshed_and_stored(fake, app):
    c = _signed_in_with_expiring_token(fake, app)
    old = session_of(c)
    resp = c.get("/api/files")
    assert resp.status_code == 200
    new = session_of(c)
    assert len(fake.calls_to("/auth/v1/token", "POST")) == 1
    assert fake.calls_to("/auth/v1/token")[0].params["grant_type"] == "refresh_token"
    assert new["access_token"] != old["access_token"]
    assert new["refresh_token"] != old["refresh_token"]
    assert new["expires_at"] > old["expires_at"]
    # The storage call used the refreshed token.
    assert fake.calls_to("/object/list/")[0].token == new["access_token"]
    # Valid token afterwards: no second refresh.
    c.get("/api/files")
    assert len(fake.calls_to("/auth/v1/token")) == 1


def test_expired_access_token_in_fake_is_refreshed(fake, app, signed_in):
    old = session_of(signed_in)
    fake.expire_access_token(old["access_token"])
    with signed_in.session_transaction() as s:
        s["expires_at"] = 0
    assert signed_in.get("/api/files").status_code == 200
    assert session_of(signed_in)["access_token"] != old["access_token"]


def test_failed_refresh_api_returns_401_and_clears_session(fake, app):
    c = _signed_in_with_expiring_token(fake, app)
    fake.refresh_tokens.clear()
    resp = c.get("/api/files")
    assert resp.status_code == 401
    assert "user_id" not in session_of(c)


def test_failed_refresh_page_redirects_to_login(fake, app):
    c = _signed_in_with_expiring_token(fake, app)
    fake.fail("/auth/v1/token", "5xx")
    resp = c.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert "user_id" not in session_of(c)


# -- access control (4.1, 4.2) -------------------------------------------------
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/files"),
        ("post", "/api/files/upload-url"),
        ("get", "/api/files/a.txt/view"),
        ("get", "/api/files/a.txt/download"),
        ("delete", "/api/files/a.txt"),
    ],
)
def test_api_requires_session(client, fake, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401
    assert resp.get_json()["error"]
    assert not fake.calls_to("/storage/v1")


def test_dashboard_redirects_anonymous_to_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


@pytest.mark.parametrize("path", ["/login", "/register"])
def test_signed_in_user_redirected_from_auth_pages(signed_in, path):
    resp = signed_in.get(path)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


# -- CSRF (5.2) ----------------------------------------------------------------
def test_login_without_csrf_rejected(client, fake):
    register_and_confirm(fake)
    resp = client.post("/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 400
    assert CSRF_EXPIRED in resp.get_data(as_text=True)
    assert "user_id" not in session_of(client)
    assert not fake.calls_to("/auth/v1/token")


def test_login_with_wrong_csrf_rejected(client, fake):
    register_and_confirm(fake)
    csrf(client, "/login")
    resp = login_with_token(client, "bogus")
    assert resp.status_code == 400
    assert "user_id" not in session_of(client)


def login_with_token(client, token):
    return client.post(
        "/login",
        data={"email": TEST_EMAIL, "password": TEST_PASSWORD, "csrf_token": token},
    )


def test_upload_url_and_delete_require_csrf(signed_in, fake):
    resp = signed_in.post("/api/files/upload-url", json={"name": "a.txt", "size": 5})
    assert resp.status_code == 400
    resp = signed_in.delete("/api/files/a.txt")
    assert resp.status_code == 400
    assert not fake.calls_to("/storage/v1")


def test_csrf_header_accepted_for_state_changing_api(signed_in):
    token = session_of(signed_in)["csrf_token"]
    resp = signed_in.post(
        "/api/files/upload-url", json={"name": "a.txt", "size": 5}, headers={"X-CSRF-Token": token}
    )
    assert resp.status_code == 200
