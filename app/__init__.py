"""Application factory: wiring, error handlers, security headers."""
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from .config import Config
from .supabase_auth import SupabaseAuth
from .supabase_db import FilesRepo
from .supabase_client import SupabaseClient, SupabaseError
from .supabase_storage import FileNotFound, InvalidFileName, StorageError, SupabaseStorage
from .validation import UploadRejected

MAX_CONTENT_LENGTH = 16 * 1024  # no file content passes through Flask
GENERIC_500 = "Something went wrong. Please try again."
STORAGE_MSG = "Storage error. Please try again."
# public/** is served by the Vercel CDN in production and by Flask locally.
STATIC_DIR = Path(__file__).resolve().parent.parent / "public" / "static"


def _is_api() -> bool:
    return request.path.startswith("/api/")


def _error(message: str, status: int):
    """JSON for API paths, rendered error page otherwise."""
    if _is_api():
        return jsonify(error=message), status
    return render_template("error.html", message=message, status=status), status


def create_app(config=None, supabase_client=None):
    """Build the Flask app. Tests may inject config and a SupabaseClient."""
    config = config or Config.from_env()
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.config.update(
        SECRET_KEY=config.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.production,
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    )
    client = supabase_client or SupabaseClient(config.supabase_url, config.supabase_anon_key)
    app.extensions["cloudvault_config"] = config
    app.extensions["cloudvault_client"] = client
    app.extensions["cloudvault_auth"] = SupabaseAuth(client)
    app.extensions["cloudvault_db"] = FilesRepo(client)
    app.extensions["cloudvault_storage"] = SupabaseStorage(
        client, config.supabase_bucket, config.supabase_url
    )

    from .auth import bp as auth_bp, get_csrf_token
    from .routes import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    app.jinja_env.globals["get_csrf_token"] = get_csrf_token

    @app.context_processor
    def inject_auth():
        return {
            "authenticated": bool(session.get("user_id")),
            "user_email": session.get("email"),
        }

    @app.errorhandler(UploadRejected)
    def handle_upload_rejected(e):
        return _error(e.message, e.status)

    @app.errorhandler(FileNotFound)
    def handle_not_found(e):
        return _error("File not found.", 404)

    @app.errorhandler(InvalidFileName)
    def handle_invalid_name(e):
        return _error("Invalid file name.", 400)

    @app.errorhandler(StorageError)
    def handle_storage_error(e):
        app.logger.warning("Storage error: %s", type(e).__name__)
        return _error(STORAGE_MSG, 502)

    @app.errorhandler(SupabaseError)
    def handle_supabase_error(e):
        app.logger.warning("Supabase error: %s", type(e).__name__)
        return _error(STORAGE_MSG, 502)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(e):
        return _error("Request too large.", 413)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        return _error(e.description or e.name, e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Log only the class name; tracebacks could include tokens in locals/messages.
        app.logger.error("Unhandled exception: %s", type(e).__name__)
        return _error(GENERIC_500, 500)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if _is_api():
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app
