"""Tests for Config.from_env and pure validation helpers."""
import pytest

from app.config import Config, ConfigError, DEFAULT_EXTENSIONS, DEFAULT_MAX_BYTES, REQUIRED_VARS
from app.validation import (
    UploadRejected,
    format_size,
    preview_mimetype,
    validate_credentials,
    validate_declared_upload,
)


def base_env(**extra):
    env = {
        "SECRET_KEY": "s",
        "SUPABASE_URL": "https://x.supabase.co/",
        "SUPABASE_ANON_KEY": "anon",
        "SUPABASE_BUCKET": "bucket",
    }
    env.update(extra)
    return env


@pytest.mark.parametrize("name", REQUIRED_VARS)
def test_missing_required_var_named_in_error(name):
    env = base_env()
    del env[name]
    with pytest.raises(ConfigError, match=name):
        Config.from_env(env)


def test_empty_required_var_rejected():
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        Config.from_env(base_env(SECRET_KEY=""))


def test_defaults():
    c = Config.from_env(base_env())
    assert c.allowed_extensions == frozenset(DEFAULT_EXTENSIONS)
    assert c.max_upload_size == DEFAULT_MAX_BYTES == 10_485_760
    assert c.supabase_url == "https://x.supabase.co"
    assert c.production is False
    assert c.signed_url_ttl == 60


def test_custom_extensions_and_size():
    c = Config.from_env(base_env(ALLOWED_EXTENSIONS=" .PDF, txt ,,", MAX_UPLOAD_SIZE="500"))
    assert c.allowed_extensions == frozenset({"pdf", "txt"})
    assert c.max_upload_size == 500


def test_blank_extensions_fall_back_to_default():
    c = Config.from_env(base_env(ALLOWED_EXTENSIONS=" , "))
    assert c.allowed_extensions == frozenset(DEFAULT_EXTENSIONS)


@pytest.mark.parametrize("val", ["abc", "0", "-5"])
def test_invalid_max_size(val):
    with pytest.raises(ConfigError, match="MAX_UPLOAD_SIZE"):
        Config.from_env(base_env(MAX_UPLOAD_SIZE=val))


def test_production_flags():
    assert Config.from_env(base_env(VERCEL="1")).production is True
    assert Config.from_env(base_env(SESSION_COOKIE_SECURE="TRUE")).production is True
    assert Config.from_env(base_env(SESSION_COOKIE_SECURE="0")).production is False


def test_validate_credentials_normalizes():
    assert validate_credentials("  Bob@Example.COM ", "12345678") == "bob@example.com"


@pytest.mark.parametrize("email", ["", "nope", "a@b", "a b@c.com", None, 5, "a" * 250 + "@b.co"])
def test_validate_credentials_bad_email(email):
    with pytest.raises(UploadRejected) as e:
        validate_credentials(email, "12345678")
    assert e.value.status == 400


@pytest.mark.parametrize("pw", ["short", None, "x" * 129])
def test_validate_credentials_bad_password(pw):
    with pytest.raises(UploadRejected) as e:
        validate_credentials("a@b.co", pw)
    assert e.value.status == 400


def test_validate_credentials_password_bounds_ok():
    validate_credentials("a@b.co", "x" * 8)
    validate_credentials("a@b.co", "x" * 128)


@pytest.fixture
def cfg():
    return Config.from_env(base_env(MAX_UPLOAD_SIZE="1000"))


def test_declared_upload_ok(cfg):
    assert validate_declared_upload("my file.PDF", 1000, cfg) == "my_file.PDF"


@pytest.mark.parametrize("name", ["", None, "../..", 3])
def test_declared_upload_bad_name(cfg, name):
    with pytest.raises(UploadRejected) as e:
        validate_declared_upload(name, 10, cfg)
    assert e.value.status == 400


def test_declared_upload_bad_extension(cfg):
    with pytest.raises(UploadRejected, match="not allowed") as e:
        validate_declared_upload("a.exe", 10, cfg)
    assert e.value.status == 400
    with pytest.raises(UploadRejected):
        validate_declared_upload("noext", 10, cfg)


@pytest.mark.parametrize("size", [0, -1, True, "5", 1.5, None])
def test_declared_upload_bad_size(cfg, size):
    with pytest.raises(UploadRejected) as e:
        validate_declared_upload("a.txt", size, cfg)
    assert e.value.status == 400


def test_declared_upload_too_large(cfg):
    with pytest.raises(UploadRejected) as e:
        validate_declared_upload("a.txt", 1001, cfg)
    assert e.value.status == 413


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(1023) == "1023 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1024 ** 2) == "1.0 MB"
    assert format_size(10_485_760) == "10.0 MB"


def test_preview_mimetype():
    assert preview_mimetype("a.PNG") == "image/png"
    assert preview_mimetype("a.jpg") == "image/jpeg"
    assert preview_mimetype("a.pdf") == "application/pdf"
    assert preview_mimetype("a.csv") == "text/plain"
    assert preview_mimetype("a.docx") is None
    assert preview_mimetype("noext") is None
    assert preview_mimetype(None) is None


def test_required_values_are_whitespace_trimmed():
    # A tab pasted into the Vercel dashboard once produced bucket "%09cloudvault".
    from app.config import Config
    cfg = Config.from_env({
        "SECRET_KEY": " s3cret\n",
        "SUPABASE_URL": "\thttps://x.supabase.co/ ",
        "SUPABASE_ANON_KEY": " key ",
        "SUPABASE_BUCKET": "\tcode-vault ",
    })
    assert cfg.supabase_bucket == "code-vault"
    assert cfg.supabase_url == "https://x.supabase.co"
    assert cfg.supabase_anon_key == "key"
    assert cfg.secret_key == "s3cret"


def test_whitespace_only_required_value_is_missing():
    import pytest
    from app.config import Config, ConfigError
    with pytest.raises(ConfigError, match="SUPABASE_BUCKET"):
        Config.from_env({"SECRET_KEY": "s", "SUPABASE_URL": "u", "SUPABASE_ANON_KEY": "k", "SUPABASE_BUCKET": "\t "})
