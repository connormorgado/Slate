-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 005 — contractor profiles: project portfolios
--  Run ONCE in Supabase SQL Editor on your EXISTING project
--  (run 004 first).
-- ═══════════════════════════════════════════════════════════════════

-- ── Portfolio projects (GCs and subs both) ──────────────────────────
create table if not exists projects (
  id          bigint generated always as identity primary key,
  owner_id    uuid not null references profiles(id) on delete cascade,
  title       text not null,
  status      text not null default 'completed'
      check (status in ('current','completed')),
  description text,
  location    text,
  year        text,
  created_at  timestamptz default now()
);

create table if not exists project_photos (
  id          bigint generated always as identity primary key,
  project_id  bigint not null references projects(id) on delete cascade,
  path        text not null,   -- storage path inside the 'drawings' bucket
  caption     text
);

alter table projects       enable row level security;
alter table project_photos enable row level security;

-- Portfolios are social: any signed-in user can view.
create policy "projects readable by signed-in users"
  on projects for select to authenticated using (true);
create policy "photos readable by signed-in users"
  on project_photos for select to authenticated using (true);

-- You manage only your own portfolio.
create policy "insert own projects"
  on projects for insert to authenticated with check (owner_id = auth.uid());
create policy "update own projects"
  on projects for update to authenticated using (owner_id = auth.uid());
create policy "delete own projects"
  on projects for delete to authenticated using (owner_id = auth.uid());

create policy "add photos to own projects"
  on project_photos for insert to authenticated
  with check (exists (select 1 from projects p
                      where p.id = project_photos.project_id
                      and p.owner_id = auth.uid()));
create policy "delete photos on own projects"
  on project_photos for delete to authenticated
  using (exists (select 1 from projects p
                 where p.id = project_photos.project_id
                 and p.owner_id = auth.uid()));
