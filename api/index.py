"""Vercel entrypoint. Vercel's Python runtime detects the WSGI `app` variable."""
from app import create_app

app = create_app()
