"""Pure validation helpers. No Flask request context required."""
import re

from werkzeug.utils import secure_filename

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PREVIEW_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "csv": "text/plain",
}


class UploadRejected(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


def sanitize_filename(raw: str) -> str:
    return secure_filename(raw or "")


def extension_allowed(name: str, allowed) -> bool:
    return "." in name and name.rsplit(".", 1)[1].lower() in allowed


def validate_credentials(email, password) -> str:
    """Return the normalized (stripped, lowercased) email or raise UploadRejected(msg, 400)."""
    email = email.strip().lower() if isinstance(email, str) else ""
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise UploadRejected("Enter a valid email address.", 400)
    if not isinstance(password, str) or len(password) < 8:
        raise UploadRejected("Password must be at least 8 characters.", 400)
    if len(password) > 128:
        raise UploadRejected("Password must be at most 128 characters.", 400)
    return email


def validate_declared_upload(name, size, config) -> str:
    """Validate a declared (not yet uploaded) file; return the secure filename."""
    secure = sanitize_filename(name if isinstance(name, str) else "")
    if not secure:
        raise UploadRejected("Invalid file name.", 400)
    if not extension_allowed(secure, config.allowed_extensions):
        types = ", ".join(sorted(config.allowed_extensions))
        raise UploadRejected(f"File type not allowed. Allowed types: {types}.", 400)
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise UploadRejected("File size must be a positive integer.", 400)
    if size > config.max_upload_size:
        raise UploadRejected(
            f"File too large. Maximum size is {format_size(config.max_upload_size)}.", 413)
    return secure


def preview_mimetype(name):
    """Return the preview MIME type for a file name, or None if not previewable."""
    if not isinstance(name, str) or "." not in name:
        return None
    return PREVIEW_MIME.get(name.rsplit(".", 1)[1].lower())
