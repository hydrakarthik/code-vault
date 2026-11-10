-- CloudVault private Storage bucket and per-user RLS policies.
-- Idempotent: safe to run more than once.
-- The bucket id 'cloudvault' must match SUPABASE_BUCKET. If you use another
-- name, replace every 'cloudvault' below before running.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('cloudvault', 'cloudvault', false, 10485760, null)
on conflict (id) do update
  set public = false,
      file_size_limit = excluded.file_size_limit;

drop policy if exists "users select own files" on storage.objects;
create policy "users select own files" on storage.objects
  for select to authenticated
  using (bucket_id = 'cloudvault' and (storage.foldername(name))[1] = (select auth.uid())::text);

drop policy if exists "users insert own files" on storage.objects;
create policy "users insert own files" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'cloudvault' and (storage.foldername(name))[1] = (select auth.uid())::text);

drop policy if exists "users update own files" on storage.objects;
create policy "users update own files" on storage.objects
  for update to authenticated
  using (bucket_id = 'cloudvault' and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'cloudvault' and (storage.foldername(name))[1] = (select auth.uid())::text);

drop policy if exists "users delete own files" on storage.objects;
create policy "users delete own files" on storage.objects
  for delete to authenticated
  using (bucket_id = 'cloudvault' and (storage.foldername(name))[1] = (select auth.uid())::text);
