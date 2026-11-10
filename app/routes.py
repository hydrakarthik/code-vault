"""Dashboard page and /api/files endpoints."""
from datetime import timezone

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session

from .auth import csrf_protect, get_csrf_token, login_required
from .supabase_storage import FileNotFound, UserContext
from .validation import (
    PREVIEW_MIME,
    UploadRejected,
    extension_allowed,
    preview_mimetype,
    sanitize_filename,
    validate_declared_upload,
)

bp = Blueprint("main", __name__)

MAX_BODY = 4096


def _config():
    return current_app.extensions["cloudvault_config"]


def _storage():
    return current_app.extensions["cloudvault_storage"]


def _db():
    return current_app.extensions["cloudvault_db"]


def _ctx() -> UserContext:
    """Identity comes from the session only, never from request input."""
    return UserContext(user_id=session["user_id"], access_token=session["access_token"])


def _iso_utc(dt) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


@bp.route("/")
def index():
    if not session.get("user_id"):
        return render_template("landing.html")
    return _dashboard()


@login_required
def _dashboard():
    config = _config()
    return render_template(
        "files.html",
        allowed_extensions=sorted(config.allowed_extensions),
        max_upload_size=config.max_upload_size,
        previewable=sorted(PREVIEW_MIME),
    )


@bp.route("/api/files", methods=["GET"])
@login_required
def list_files():
    rows = sorted(_db().list(_ctx()), key=lambda r: r["uploaded_at"], reverse=True)
    return jsonify(
        files=[
            {"name": r["name"], "size": r["size"], "uploaded_at": _iso_utc(r["uploaded_at"])}
            for r in rows
        ]
    )


@bp.route("/api/files/upload-url", methods=["POST"])
@login_required
@csrf_protect
def upload_url():
    if request.content_length is None or request.content_length > MAX_BODY:
        raise UploadRejected("Request too large.", 413)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    name = validate_declared_upload(data.get("name"), data.get("size"), _config())
    info = _storage().create_upload_url(_ctx(), name)
    return jsonify(**info, name=name)


@bp.route("/api/files/complete", methods=["POST"])
@login_required
@csrf_protect
def complete_upload():
    if request.content_length is None or request.content_length > MAX_BODY:
        raise UploadRejected("Request too large.", 413)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    raw = data.get("name")
    secure = sanitize_filename(raw if isinstance(raw, str) else "")
    if not secure or secure != raw:
        raise UploadRejected("Invalid file name.", 400)
    allowed = _config().allowed_extensions
    if not extension_allowed(secure, allowed):
        raise UploadRejected("Allowed types: " + ", ".join(sorted(allowed)), 400)
    ctx = _ctx()
    info = _storage().stat(ctx, secure)  # FileNotFound -> 404, nothing written
    rec = _db().upsert(ctx, secure, info["size"], info["content_type"])
    return jsonify(name=secure, size=info["size"], uploaded_at=_iso_utc(rec["uploaded_at"])), 200


@bp.route("/api/files/<name>/view", methods=["GET"])
@login_required
def view_file(name):
    if preview_mimetype(name) is None:
        return jsonify(error="Preview is not available for this file type."), 400
    return redirect(_storage().view_url(_ctx(), name, _config().signed_url_ttl), 302)


@bp.route("/api/files/<name>/download", methods=["GET"])
@login_required
def download_file(name):
    return redirect(_storage().download_url(_ctx(), name, _config().signed_url_ttl), 302)


@bp.route("/api/files/<name>", methods=["DELETE"])
@login_required
@csrf_protect
def delete_file(name):
    ctx = _ctx()
    had_object = _storage().exists(ctx, name)
    if had_object:
        _storage().delete(ctx, name)
    had_row = _db().delete(ctx, name)
    if not had_object and not had_row:
        raise FileNotFound("File not found.")
    return jsonify(deleted=name), 200
