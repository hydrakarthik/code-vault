"""Smoke tests for deployment, CI, and documentation files."""
import importlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gitignore_excludes_secrets_and_caches():
    lines = {l.strip() for l in read(".gitignore").splitlines()}
    assert ".env" in lines
    assert ".venv/" in lines
    assert ".vercel/" in lines
    assert any("__pycache__" in l for l in lines)
    assert any("pytest_cache" in l for l in lines)


def test_env_example_has_only_required_variables():
    keys = set()
    for line in read(".env.example").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keys.add(line.split("=", 1)[0])
    assert keys == {"SECRET_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_BUCKET"}


def test_vercel_json_rewrites_all_paths_to_api_index():
    data = json.loads(read("vercel.json"))
    rewrites = data["rewrites"]
    assert {"source": "/(.*)", "destination": "/api/index"} in rewrites


def test_api_index_exposes_flask_app():
    from flask import Flask

    module = importlib.import_module("api.index")
    assert isinstance(module.app, Flask)


def test_requirements_exact_pins_without_boto3_or_moto():
    lines = [
        l.strip() for l in read("requirements.txt").splitlines()
        if l.strip() and not l.startswith("#")
    ]
    assert lines
    for line in lines:
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+==[0-9][^\s=<>~!]*", line), line
    text = read("requirements.txt").lower()
    assert "boto3" not in text
    assert "moto" not in text


def test_ci_workflow_runs_pytest_without_secrets():
    ci = read(".github/workflows/ci.yml")
    assert "secrets." not in ci
    assert "pytest" in ci
    assert "pip install -r requirements.txt" in ci


def test_readme_has_required_sections():
    readme = read("README.md")
    for heading in (
        "Supabase setup",
        "Environment variables",
        "Run locally",
        "Tests",
        "Push to GitHub",
        "Deploy to Vercel",
    ):
        assert re.search(rf"^#+\s+{re.escape(heading)}", readme, re.M), heading
    assert "service role" in readme.lower()
    assert "creates no Supabase resources" in readme


def test_old_storage_package_removed():
    assert not (ROOT / "app" / "storage").exists()


def test_no_service_role_key_references_in_code():
    files = list((ROOT / "app").rglob("*.py")) + list((ROOT / "api").rglob("*.py"))
    files += list((ROOT / "app" / "static" / "js").glob("*.js"))
    assert files
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "service_role" not in text, f
        assert "SERVICE_ROLE" not in text, f
