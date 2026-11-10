-- CloudVault file metadata. Idempotent: safe to run more than once.
-- Run in the Supabase SQL Editor before storage.sql.

begin;

create table if not exists public.files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 255 and position('/' in name) = 0),
  size bigint not null default 0 check (size >= 0),
  content_type text,
  object_key text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, name)
);

create index if not exists files_user_id_updated_at_idx
  on public.files (user_id, updated_at desc);

-- Keep updated_at current on every update.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists files_set_updated_at on public.files;
create trigger files_set_updated_at
  before update on public.files
  for each row execute function public.set_updated_at();

-- Row Level Security: each user sees only their own rows.
alter table public.files enable row level security;

-- Supabase grants ALL (including TRUNCATE, which bypasses RLS) to anon and
-- authenticated on new public tables by default. Reset, then grant only the
-- four row-level operations to signed-in users.
revoke all on table public.files from public, anon, authenticated;
grant select, insert, update, delete on table public.files to authenticated;

-- The trigger function is only for the trigger; nobody needs to call it directly.
revoke execute on function public.set_updated_at() from public, anon, authenticated;

drop policy if exists "files select own" on public.files;
create policy "files select own" on public.files
  for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "files insert own" on public.files;
create policy "files insert own" on public.files
  for insert to authenticated
  with check (
    (select auth.uid()) = user_id
    and object_key = user_id::text || '/' || name
  );

drop policy if exists "files update own" on public.files;
create policy "files update own" on public.files
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check (
    (select auth.uid()) = user_id
    and object_key = user_id::text || '/' || name
  );

drop policy if exists "files delete own" on public.files;
create policy "files delete own" on public.files
  for delete to authenticated
  using ((select auth.uid()) = user_id);

commit;
