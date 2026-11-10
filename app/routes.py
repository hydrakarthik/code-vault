"""Dashboard page and /api/files endpoints."""
from datetime import timezone

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session

from .auth import csrf_protect, get_csrf_token, login_required
from .supabase_storage import UserContext
from .validation import PREVIEW_MIME, UploadRejected, preview_mimetype, validate_declared_upload

bp = Blueprint("main", __name__)

MAX_BODY = 4096


def _config():
    return current_app.extensions["cloudvault_config"]


def _storage():
    return current_app.extensions["cloudvault_storage"]


def _ctx() -> UserContext:
    """Identity comes from the session only, never from request input."""
    return UserContext(user_id=session["user_id"], access_token=session["access_token"])


def _iso_utc(dt) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


@bp.route("/")
@login_required
def index():
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
    records = sorted(_storage().list(_ctx()), key=lambda r: r.uploaded_at, reverse=True)
    return jsonify(
        files=[
            {"name": r.name, "size": r.size, "uploaded_at": _iso_utc(r.uploaded_at)}
            for r in records
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
    _storage().delete(_ctx(), name)
    return jsonify(deleted=name), 200
