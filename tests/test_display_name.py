"""Display name tests: registration, session, dashboard rendering, validation."""
import re

import pytest

from app.validation import UploadRejected, validate_display_name

from .conftest import TEST_EMAIL, TEST_PASSWORD, csrf, login

PREFIX = TEST_EMAIL.split("@")[0]


def post_register(client, name, email="new@example.com"):
    data = {"email": email, "password": "longenough1", "csrf_token": csrf(client, "/register")}
    if name is not None:
        data["name"] = name
    return client.post("/register", data=data)


def session_of(client):
    with client.session_transaction() as s:
        return dict(s)


def chip(html):
    m = re.search(r'<span class="user-chip" title="([^"]*)">(.*?)(?:<span|</span>)', html, re.S)
    assert m, "user chip not found"
    return m.group(1), m.group(2)


def test_register_sends_cleaned_name(client, fake):
    assert post_register(client, "  Ada   Lovelace ").status_code == 200
    assert fake.calls_to("/auth/v1/signup")[0].json["data"] == {"display_name": "Ada Lovelace"}


def test_register_blank_name_sends_no_data(client, fake):
    assert post_register(client, "   ").status_code == 200
    assert "data" not in fake.calls_to("/auth/v1/signup")[0].json


def test_register_name_too_long_rejected(client, fake):
    resp = post_register(client, "x" * 51)
    body = resp.get_data(as_text=True)
    assert resp.status_code == 400
    assert "Name must be at most 50 characters." in body
    assert not fake.calls_to("/auth/v1/signup")
    assert "new@example.com" in body


def test_login_uses_metadata_name(client, fake):
    fake.add_user(TEST_EMAIL, TEST_PASSWORD, display_name="Ada")
    assert login(client).status_code == 302
    assert session_of(client)["name"] == "Ada"
    body = client.get("/").get_data(as_text=True)
    assert "Hi, Ada" in body
    title, text = chip(body)
    assert title == TEST_EMAIL
    assert text.strip() == "Ada"


def test_no_metadata_falls_back_to_email_prefix(client, fake):
    fake.add_user(TEST_EMAIL, TEST_PASSWORD)
    login(client)
    assert session_of(client)["name"] == PREFIX
    assert f"Hi, {PREFIX}" in client.get("/").get_data(as_text=True)


def test_name_is_html_escaped(client, fake):
    fake.add_user(TEST_EMAIL, TEST_PASSWORD, display_name="<b>x</b>")
    login(client)
    body = client.get("/").get_data(as_text=True)
    assert "&lt;b&gt;x&lt;/b&gt;" in body
    assert "<b>x</b>" not in body


@pytest.mark.parametrize("bad", [123, ["Ada"], "y" * 200])
def test_invalid_metadata_falls_back(client, fake, bad):
    fake.add_user(TEST_EMAIL, TEST_PASSWORD, display_name=bad)
    login(client)
    assert session_of(client)["name"] == PREFIX
    assert f"Hi, {PREFIX}" in client.get("/").get_data(as_text=True)


def test_refresh_keeps_display_name(client, fake):
    fake.add_user(TEST_EMAIL, TEST_PASSWORD, display_name="Ada")
    login(client)
    with client.session_transaction() as s:
        s["expires_at"] = 0
    fake.clear_calls()
    body = client.get("/").get_data(as_text=True)
    assert fake.calls_to("/auth/v1/token")
    assert session_of(client)["name"] == "Ada"
    assert "Hi, Ada" in body


# -- validate_display_name ---------------------------------------------------
def test_validate_removes_control_chars():
    assert validate_display_name("A\x00d\x07a\u200b") == "Ada"


def test_validate_collapses_whitespace():
    assert validate_display_name("  Ada \t\n  Lovelace  ") == "Ada Lovelace"


@pytest.mark.parametrize("raw", [None, 5, b"x", ["a"]])
def test_validate_non_str_is_empty(raw):
    assert validate_display_name(raw) == ""


def test_validate_length_boundary():
    assert validate_display_name("x" * 50) == "x" * 50
    with pytest.raises(UploadRejected) as exc:
        validate_display_name("x" * 51)
    assert exc.value.status == 400
