"""Session authentication (Supabase Auth) and CSRF protection."""
import hmac
import logging
import secrets
import time
from functools import wraps

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .supabase_auth import (
    AuthError,
    AuthResult,
    EmailNotConfirmed,
    RegistrationFailed,
)
from .validation import UploadRejected, validate_credentials, validate_display_name

log = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)

SESSION_KEYS = ("user_id", "email", "access_token", "refresh_token", "expires_at", "csrf_token", "name")
INVALID_CREDENTIALS = "Invalid email or password."
NOT_CONFIRMED = "Please confirm your email address before logging in."
CSRF_EXPIRED = "Your session expired. Please try again."
REGISTER_MSG = "Check your inbox to confirm your account."
REGISTER_FAILED = "Registration could not be completed. Please try again."
SKEW_SECONDS = 30
MAX_SESSION_BYTES = 3800


def _auth():
    return current_app.extensions["cloudvault_auth"]


def _store(result: AuthResult) -> None:
    """Store only the whitelisted auth fields in the session."""
    session["user_id"] = result.user_id
    session["email"] = result.email
    session["access_token"] = result.access_token
    session["refresh_token"] = result.refresh_token
    session["expires_at"] = result.expires_at
    session["name"] = result.display_name or (
        result.email.split("@")[0] if result.email else "")
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    try:
        size = len(current_app.session_interface.get_signing_serializer(current_app).dumps(dict(session)))
        if size > MAX_SESSION_BYTES:
            log.warning("Session cookie is large (%s bytes)", size)
    except Exception:  # size check is advisory only
        pass


def _unauth():
    if request.path.startswith("/api/"):
        return jsonify(error="Authentication required"), 401
    return redirect(url_for("auth.login"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return _unauth()
        if session.get("expires_at", 0) <= time.time() + SKEW_SECONDS:
            try:
                _store(_auth().refresh(session.get("refresh_token", "")))
            except AuthError:
                session.clear()
                return _unauth()
        return view(*args, **kwargs)

    return wrapped


def _session_required(view):
    """Require a session but skip token refresh (used by logout)."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return _unauth()
        return view(*args, **kwargs)

    return wrapped


def get_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def _csrf_valid() -> bool:
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf_token", "")
    return bool(expected) and hmac.compare_digest(sent.encode(), expected.encode())


def csrf_protect(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _csrf_valid():
            return jsonify(error="Invalid CSRF token"), 400
        return view(*args, **kwargs)

    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("main.index"))

    def render(status=200, **kw):
        ctx = dict(error=None, message=None, email="")
        ctx.update(kw)
        get_csrf_token()
        return render_template("login.html", **ctx), status

    if request.method == "GET":
        return render()

    email = (request.form.get("email") or "").strip().lower()
    if not _csrf_valid():
        return render(400, error=CSRF_EXPIRED, email=email)

    password = request.form.get("password") or ""
    if not email or not password:
        return render(error=INVALID_CREDENTIALS, email=email)
    try:
        result = _auth().login(email, password)
    except EmailNotConfirmed:
        return render(error=NOT_CONFIRMED, email=email)
    except AuthError:
        return render(error=INVALID_CREDENTIALS, email=email)

    session.clear()
    session["csrf_token"] = secrets.token_urlsafe(32)
    _store(result)
    return redirect(url_for("main.index"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("main.index"))

    def render(status=200, **kw):
        ctx = dict(error=None, message=None, email="", name="", registered=False)
        ctx.update(kw)
        get_csrf_token()
        return render_template("register.html", **ctx), status

    if request.method == "GET":
        return render()

    raw_email = (request.form.get("email") or "").strip()
    raw_name = request.form.get("name") or ""
    if not _csrf_valid():
        return render(400, error=CSRF_EXPIRED, email=raw_email, name=raw_name)

    try:
        display_name = validate_display_name(raw_name)
        email = validate_credentials(raw_email, request.form.get("password"))
    except UploadRejected as exc:
        return render(400, error=exc.message, email=raw_email, name=raw_name)

    try:
        _auth().register(email, request.form.get("password"), display_name)
    except RegistrationFailed:
        return render(error=REGISTER_FAILED, email=raw_email, name=raw_name)
    return render(message=REGISTER_MSG, registered=True)


@bp.route("/logout", methods=["POST"])
@_session_required
@csrf_protect
def logout():
    _auth().logout(session.get("access_token", ""))
    session.clear()
    return redirect(url_for("auth.login"))
