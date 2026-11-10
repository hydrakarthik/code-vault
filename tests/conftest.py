"""Shared fixtures. Dummy env values mean tests need no secrets or network."""
import os
import re

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.test")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_BUCKET", "files")

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.supabase_client import SupabaseClient  # noqa: E402

from .fakes import FakeSupabase  # noqa: E402

TEST_EMAIL = "user@example.com"
TEST_PASSWORD = "correct-horse-battery"

_META_RE = re.compile(r'<meta name="csrf-token" content="([^"]+)"')
_INPUT_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def make_config(**overrides) -> Config:
    values = dict(
        secret_key="test-secret-key",
        supabase_url="https://fake.supabase.test",
        supabase_anon_key="test-anon-key",
        supabase_bucket="files",
        allowed_extensions=frozenset({"pdf", "txt", "docx", "xlsx", "csv", "png", "jpg", "gif"}),
        max_upload_size=10_485_760,
        production=False,
    )
    values.update(overrides)
    return Config(**values)


def csrf(client, path="/login") -> str:
    """GET a page and extract the CSRF token (meta tag, else hidden input)."""
    html = client.get(path).get_data(as_text=True)
    m = _META_RE.search(html) or _INPUT_RE.search(html)
    assert m, f"no CSRF token found on {path}"
    return m.group(1)


def register_and_confirm(fake, email=TEST_EMAIL, password=TEST_PASSWORD) -> str:
    """Create a confirmed user directly in the fake; returns the user id."""
    return fake.add_user(email, password, confirmed=True)


def login(client, email=TEST_EMAIL, password=TEST_PASSWORD):
    token = csrf(client, "/login")
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token}
    )


@pytest.fixture
def fake():
    return FakeSupabase(bucket="files")


@pytest.fixture
def config():
    return make_config()


@pytest.fixture
def app(fake, config):
    client = SupabaseClient(config.supabase_url, config.supabase_anon_key, session=fake)
    app = create_app(config, supabase_client=client)
    app.config["TESTING"] = False  # keep production error handlers active
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def signed_in(fake, app):
    """A test client logged in as a confirmed user (fake.user_id(TEST_EMAIL))."""
    register_and_confirm(fake)
    c = app.test_client()
    resp = login(c)
    assert resp.status_code == 302, "fixture login failed"
    fake.clear_calls()
    return c
