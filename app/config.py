"""Application configuration loaded and validated from environment variables."""
from dataclasses import dataclass
import os

DEFAULT_EXTENSIONS = ("pdf", "txt", "docx", "xlsx", "csv", "png", "jpg", "gif")
DEFAULT_MAX_BYTES = 10_485_760
REQUIRED_VARS = ("SECRET_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_BUCKET")


class ConfigError(Exception):
    """Raised when the environment configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    secret_key: str
    supabase_url: str  # trailing slash stripped
    supabase_anon_key: str
    supabase_bucket: str
    allowed_extensions: frozenset[str]
    max_upload_size: int
    production: bool
    signed_url_ttl: int = 60

    @classmethod
    def from_env(cls, env=os.environ) -> "Config":
        # Strip stray whitespace (e.g. a tab pasted into a dashboard field), which
        # would otherwise end up inside URLs such as the Storage bucket path.
        values = {name: (env.get(name) or "").strip() for name in REQUIRED_VARS}
        for name in REQUIRED_VARS:
            if not values[name]:
                raise ConfigError(f"Missing required environment variable: {name}")

        raw_ext = env.get("ALLOWED_EXTENSIONS")
        extensions = (
            {e.strip().lower().lstrip(".") for e in raw_ext.split(",") if e.strip()}
            if raw_ext
            else set()
        )
        if not extensions:
            extensions = set(DEFAULT_EXTENSIONS)

        raw_size = env.get("MAX_UPLOAD_SIZE")
        try:
            max_size = int(raw_size) if raw_size else DEFAULT_MAX_BYTES
        except ValueError:
            raise ConfigError("MAX_UPLOAD_SIZE must be an integer number of bytes")
        if max_size <= 0:
            raise ConfigError("MAX_UPLOAD_SIZE must be a positive number of bytes")

        production = bool(env.get("VERCEL")) or (
            (env.get("SESSION_COOKIE_SECURE") or "").strip().lower() in ("1", "true")
        )

        return cls(
            secret_key=values["SECRET_KEY"],
            supabase_url=values["SUPABASE_URL"].rstrip("/"),
            supabase_anon_key=values["SUPABASE_ANON_KEY"],
            supabase_bucket=values["SUPABASE_BUCKET"],
            allowed_extensions=frozenset(extensions),
            max_upload_size=max_size,
            production=production,
        )
