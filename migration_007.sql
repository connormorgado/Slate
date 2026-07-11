-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 007 — admin role + feedback system
--  Run ONCE in Supabase SQL Editor.
--  AFTER running: Table Editor -> profiles -> YOUR row -> role = 'admin'
-- ═══════════════════════════════════════════════════════════════════

-- ── allow the admin role ────────────────────────────────────────────
alter table profiles drop constraint if exists profiles_role_check;
alter table profiles add constraint profiles_role_check
  check (role in ('gc', 'sub', 'admin'));

-- ── is_admin(): security definer so policies can check the caller's
--    role WITHOUT the profiles policy referencing itself (recursion). ─
create or replace function public.is_admin()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (select 1 from profiles
                 where id = auth.uid() and role = 'admin');
$$;

-- ── admin reads everything ──────────────────────────────────────────
create policy "admin reads itbs"        on itbs        for select to authenticated using (public.is_admin());
create policy "admin reads itb_files"   on itb_files   for select to authenticated using (public.is_admin());
create policy "admin reads invites"     on itb_invites for select to authenticated using (public.is_admin());
create policy "admin reads bids"        on bids        for select to authenticated using (public.is_admin());
create policy "admin reads bid_files"   on bid_files   for select to authenticated using (public.is_admin());
create policy "admin reads requests"    on bid_requests for select to authenticated using (public.is_admin());
-- (profiles, projects, project_photos are already readable by all
--  signed-in users)

-- admin can update verification status on any profile (approve/reject)
create policy "admin updates profiles"
  on profiles for update to authenticated using (public.is_admin());

-- ── feedback ────────────────────────────────────────────────────────
create table if not exists feedback (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references profiles(id) on delete cascade,
  message     text not null,
  status      text not null default 'open'
      check (status in ('open', 'resolved')),
  created_at  timestamptz default now()
);

alter table feedback enable row level security;

create policy "users submit own feedback"
  on feedback for insert to authenticated with check (user_id = auth.uid());
create policy "read own feedback or admin reads all"
  on feedback for select to authenticated
  using (user_id = auth.uid() or public.is_admin());
create policy "admin resolves feedback"
  on feedback for update to authenticated using (public.is_admin());
