# CloudVault

A small multi-user Flask app for storing files. Users register and sign in with email and password, then upload, list, view, download, and delete their own files. Auth and private file storage run on Supabase. Source lives on GitHub and the app deploys to Vercel.

This project creates no Supabase resources and runs no deployment commands. You set up Supabase, GitHub, and Vercel yourself by following the steps below.

## Supabase setup

1. Create a Supabase project.
2. Authentication > Providers: enable Email (email and password sign-in) and require email confirmation.
3. Authentication > URL Configuration:
   - Site URL: `http://127.0.0.1:5000` for local use (switch to your Vercel URL in production).
   - Redirect URLs: add `http://127.0.0.1:5000/**` and `https://<project>.vercel.app/**`.
4. Storage: create a **private** bucket. Set its file size limit equal to `MAX_UPLOAD_SIZE` (default 10485760 bytes, 10 MiB). Files go straight from the browser to Supabase, so this limit is the independent size enforcement.
5. SQL Editor: run the policies below, replacing `<bucket>` with your bucket name. They limit each user to objects under their own `<user_id>/` folder.

```sql
create policy "users select own files" on storage.objects
  for select to authenticated
  using (bucket_id = '<bucket>' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "users insert own files" on storage.objects
  for insert to authenticated
  with check (bucket_id = '<bucket>' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "users update own files" on storage.objects
  for update to authenticated
  using (bucket_id = '<bucket>' and (storage.foldername(name))[1] = auth.uid()::text)
  with check (bucket_id = '<bucket>' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "users delete own files" on storage.objects
  for delete to authenticated
  using (bucket_id = '<bucket>' and (storage.foldername(name))[1] = auth.uid()::text);
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | yes | | Signs session cookies. Use a long random value. |
| `SUPABASE_URL` | yes | | Project URL, for example `https://xyz.supabase.co`. |
| `SUPABASE_ANON_KEY` | yes | | Project anon (public) key. |
| `SUPABASE_BUCKET` | yes | | Name of the private bucket. |
| `ALLOWED_EXTENSIONS` | no | `pdf,txt,docx,xlsx,csv,png,jpg,gif` | Comma-separated list. |
| `MAX_UPLOAD_SIZE` | no | `10485760` | Maximum upload size in bytes. |

Missing required values stop the app at startup with a message naming the variable. Generate a secret key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Never configure the Supabase service role key in CloudVault, and never expose it to the browser.** The app only uses the anon key plus each user's own access token, so Row Level Security applies to every call.

## Run locally

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Edit `.env` with your values first (never commit it), then open http://127.0.0.1:5000.

## Tests

```
pytest
```

Tests use `hypothesis` and an in-memory fake of Supabase. They need no network access or real credentials.

## Push to GitHub

```bash
git remote add origin https://github.com/hydrakarthik/code-vault.git
git push -u origin main
```

If `origin` already exists, skip the first command. GitHub Actions (`.github/workflows/ci.yml`) runs `pytest` on every push and pull request. It uses no secrets.

## Deploy to Vercel

1. In Vercel, choose Add New > Project and import the GitHub repository.
2. In Project Settings > Environment Variables, set `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_BUCKET`. Set them in the Vercel dashboard only, never in the repository.
3. Deploy. Pushes to `main` deploy to production and pull requests get preview deployments.
4. Add the resulting `https://<project>.vercel.app/**` URL to the Supabase redirect URLs.

`vercel.json` rewrites all paths to `api/index.py`, which exposes the Flask `app`. Vercel limits request bodies to about 4.5 MB, so files are uploaded directly from the browser to Supabase using a short-lived signed URL.
