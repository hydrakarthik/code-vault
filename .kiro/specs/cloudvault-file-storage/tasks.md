# Implementation Plan: CloudVault File Storage (Supabase + GitHub + Vercel)

## Overview

Rewrite the existing admin/local/S3 Flask app into a multi-user app backed by Supabase Auth and private Supabase Storage, with direct browser uploads via signed URLs, GitHub CI, and Vercel deployment files. Language: Python 3. No task creates Supabase resources, pushes to GitHub, or deploys to Vercel.

## Tasks

- [x] 1. Config, dependencies, and removal of old storage package
  - [x] 1.1 Rewrite `app/config.py` and `requirements.txt`, delete `app/storage/`
    - Replace any partially edited `app/config.py` with the `Config` dataclass and `ConfigError` from the design (required: SECRET_KEY, SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_BUCKET; defaults for ALLOWED_EXTENSIONS and MAX_UPLOAD_SIZE; `production` from VERCEL or SESSION_COOKIE_SECURE; no service role key, no admin/local/S3 settings)
    - Rewrite `requirements.txt` with exact `==` pins for Flask, python-dotenv, requests, pytest, hypothesis; remove boto3 and moto and any other leftovers from a partial edit
    - Delete `app/storage/` (`local.py`, `s3.py` if present, `base.py`, `__init__.py`) and `app/storage/__pycache__`
    - _Requirements: 6.1, 6.3, 6.4, 14.1, 19.2_

- [x] 2. Supabase client modules
  - [x] 2.1 Create `app/supabase_client.py`, `app/supabase_auth.py`, `app/supabase_storage.py`
    - `SupabaseClient` (requests wrapper, timeouts, `SupabaseError`), `SupabaseAuth` (register, login, refresh, logout, `AuthResult`, auth exceptions), `SupabaseStorage` (`UserContext`, `FileRecord`, list, exists, delete, create_upload_url with `x-upsert`, download_url, view_url, key and name checks, status mapping)
    - Use the anon key and the user access token only; log only exception class and HTTP status; verify the signed upload response shape against current Supabase docs
    - _Requirements: 1.2, 2.1, 3.1, 3.2, 7.1, 7.2, 7.3, 8.2, 8.8, 10.5, 11.1, 12.2, 13.2, 14.1, 14.2, 19.1_

- [x] 3. Validation updates
  - [x] 3.1 Update `app/validation.py`
    - Remove `validate_upload`; keep `sanitize_filename`, `extension_allowed`, `format_size`, `UploadRejected`
    - Add `validate_credentials`, `validate_declared_upload`, `PREVIEW_MIME`, `preview_mimetype`
    - _Requirements: 1.4, 8.9, 9.1, 9.2, 9.3, 9.4, 12.4_

- [x] 4. Auth, routes, and app wiring
  - [x] 4.1 Rewrite `app/auth.py`, `app/routes.py`, `app/__init__.py`, and `run.py`
    - `auth.py`: login, register, logout routes; `login_required` with token refresh and 401/redirect handling; CSRF helpers (constant-time compare, header support); redirect signed-in users away from login/register
    - `routes.py`: `/`, `GET /api/files`, `POST /api/files/upload-url` (4 KB cap, CSRF), view, download, `DELETE /api/files/<name>`; user identity from session only
    - `app/__init__.py`: `create_app(config=None, supabase_client=None)`, extensions, cookie flags, context processor (`authenticated`, `user_email`), error handlers (generic 500, 502 for storage failures)
    - `run.py`: `load_dotenv()` then `create_app()`; startup fails with a clear message on `ConfigError`
    - _Requirements: 1.2, 1.3, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 4.1, 4.2, 5.2, 5.3, 6.2, 7.1, 7.2, 7.4, 8.2, 8.4, 8.5, 10.6, 11.1, 11.2, 12.2, 12.4, 12.5, 13.2, 13.3, 13.4, 14.3, 14.4, 15.2, 15.4, 19.1_

- [x] 5. Frontend
  - [x] 5.1 Update templates, `app.js`, and `styles.css`
    - Add `register.html` and a Register link on `login.html`; show `user_email` in the `base.html` navbar; pass allowed extensions, max size, and previewable types to `files.html` config; CSRF meta tag only (no refresh token)
    - `app.js`: client-side validation before any request, upload-URL fetch, XHR PUT with FormData and progress bar, error/success handling, remove multipart upload; View link or disabled "Preview unavailable" button; names inserted with `textContent`
    - `styles.css`: register page, navbar email, View/disabled states, layout fits at 600 px or less
    - _Requirements: 1.1, 2.6, 5.1, 8.1, 8.3, 8.6, 8.7, 9.5, 10.1, 10.2, 10.3, 10.4, 10.7, 12.1, 12.3, 13.1, 16.1, 16.2, 16.3, 16.4_

- [x] 6. Deployment, CI, and documentation files
  - [x] 6.1 Add `api/index.py`, `vercel.json`, `.github/workflows/ci.yml`; update `.gitignore`, `.env.example`; rewrite `README.md`
    - `api/index.py` exposes `app = create_app()`; `vercel.json` rewrites all paths to `/api/index`
    - `ci.yml`: checkout, setup-python 3.12, `pip install -r requirements.txt`, `pytest`; no secrets
    - `.gitignore` excludes `.env`, `.venv/`, caches, `.vercel/`; `.env.example` has placeholders for the four required variables only
    - README per design outline: Supabase setup, private bucket with size limit equal to MAX_UPLOAD_SIZE, RLS SQL, env vars, local run, tests, GitHub push, Vercel Git import, service role warning, statement that the project creates no Supabase resources and runs no deployment commands
    - _Requirements: 9.6, 14.5, 14.6, 15.1, 15.2, 15.3, 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7_

- [x] 7. Tests
  - [x] 7.1 Create `tests/fakes.py` (Fake_Supabase) and `tests/conftest.py`
    - Requests-session-compatible fake for `/auth/v1` and `/storage/v1` with in-memory objects, RLS prefix check, call recording, and failure injection (timeouts, 5xx, malformed bodies)
    - `conftest.py` sets dummy env values, and provides app, client, and signed-in-user fixtures plus CSRF helper
    - _Requirements: 19.3, 19.4_

  - [x] 7.2 Write `tests/test_auth.py`
    - Registration success/validation/duplicate/failure, login success, invalid credentials, unconfirmed user, cookie flags, logout, token refresh and failed refresh, access control, CSRF, redirect of signed-in users
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 4.1, 4.2, 5.2, 19.3_

  - [x] 7.3 Write `tests/test_files.py`
    - List order and empty state, upload-URL validation (400/413, 4 KB cap, empty name, upsert header), per-user isolation and 404, view and download (60 s, disposition, non-previewable 400), delete and 404, 502 on storage failures, no secret leakage, file name escaping
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.2, 8.4, 8.5, 8.8, 8.9, 9.1, 9.2, 9.3, 9.4, 10.5, 10.6, 10.7, 11.1, 11.2, 12.2, 12.3, 12.4, 12.5, 13.2, 13.3, 13.4, 14.2, 14.4, 19.3_

  - [x] 7.4 Write `tests/test_config_validation.py`
    - Config missing variable names, defaults, `validate_credentials`, `validate_declared_upload`, `format_size`, `preview_mimetype`
    - _Requirements: 1.4, 6.3, 6.4, 9.1, 9.2, 9.3, 9.4, 10.2, 12.4_

  - [x] 7.5 Write `tests/test_project_files.py` (smoke tests)
    - `.gitignore`, `.env.example`, `vercel.json`, `api/index.py`, exact pins with no boto3/moto, `ci.yml` (no `secrets.`), README sections, absence of `app/storage/` and service role key references
    - _Requirements: 14.1, 14.5, 14.6, 15.1, 15.2, 17.4, 17.5, 18.1, 18.2, 18.3, 18.6, 18.7, 19.2_

  - [ ]* 7.6 Write property tests for pure logic in `tests/test_properties_logic.py`
    - **Property 1: Credential validation** (Validates: Requirements 1.4)
    - **Property 6: Configuration loading** (Validates: Requirements 6.3, 6.4)
    - **Property 8: Declared upload validation** (Validates: Requirements 8.9, 9.1, 9.2, 9.3, 9.4)
    - **Property 12: Listing order and size formatting** (Validates: Requirements 10.2, 10.5)

  - [ ]* 7.7 Write property tests with Fake_Supabase in `tests/test_properties_app.py`
    - **Property 2: Generic authentication errors** (Validates: Requirements 1.5, 2.2)
    - **Property 3: Access control on protected routes** (Validates: Requirements 4.1, 11.3, 12.6)
    - **Property 4: CSRF enforcement** (Validates: Requirements 5.2)
    - **Property 5: Token refresh on expiry** (Validates: Requirements 3.2, 3.3)
    - **Property 7: Per-user isolation** (Validates: Requirements 7.1, 7.2, 7.3, 7.4)
    - **Property 9: Upload-URL request carries no content** (Validates: Requirements 8.2, 8.4, 8.8)
    - **Property 10: Signed URL disposition and expiry** (Validates: Requirements 11.1, 12.2, 12.4)
    - **Property 11: Delete and not-found** (Validates: Requirements 11.2, 12.5, 13.2, 13.3)
    - **Property 13: File name escaping** (Validates: Requirements 10.7)
    - **Property 14: No secret leakage** (Validates: Requirements 14.1, 14.2, 14.4)

- [x] 8. Final checkpoint - Ensure all tests pass
  - Run `pytest` and fix failures.
  - Ask the user to put their own Supabase credentials (SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_BUCKET, SECRET_KEY) in `.env` before starting a local preview with `python run.py`. Do not start the preview without credentials.
  - Do not create Supabase resources, push to GitHub, or deploy to Vercel.

## Notes

- Sub-tasks marked with `*` are optional and can be skipped for a faster MVP
- Required tasks never depend on optional tasks; optional tasks run in the last wave
- Each task references specific requirements for traceability

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["4.1", "5.1", "6.1"] },
    { "id": 3, "tasks": ["7.1"] },
    { "id": 4, "tasks": ["7.2", "7.3", "7.4", "7.5"] },
    { "id": 5, "tasks": ["7.6", "7.7"] }
  ]
}
```
