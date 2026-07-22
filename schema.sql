-- ═══════════════════════════════════════════════════════════════════
--  SLATE — Supabase schema (pilot)
--  Run this ONCE in your Supabase project: SQL Editor -> New query ->
--  paste everything -> Run.
-- ═══════════════════════════════════════════════════════════════════

-- ── PROFILES ─────────────────────────────────────────────────────────
-- One row per user (GC or Sub). Created by the app on first login.
create table if not exists profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  contact_name text,
  last_seen   timestamptz,
  email_opt_out boolean not null default false,
  role        text not null check (role in ('gc', 'sub', 'admin')),
  company     text not null,
  trade       text,
  trades      text[],          -- CSLB classes
  work_states text[],
  work_cities text,
  region      text,
  license_no  text,            -- CSLB license number
  verification_status text not null default 'unverified'
      check (verification_status in ('unverified','pending','verified','rejected')),
  verified_at   timestamptz,
  cslb_status   text,           -- raw status line from CSLB lookup
  cslb_expires  text,           -- license expiration
  cslb_business text,
  cslb_classes  text,   -- e.g. 'B, C-10'           -- business name on the license
  created_at  timestamptz default now()
);

-- ── ITBS (bid requests) ──────────────────────────────────────────────
create table if not exists itbs (
  id          bigint generated always as identity primary key,
  gc_id       uuid not null references profiles(id),
  project     text not null,
  trade       text not null,
  scope       text,
  due_date    date,
  visibility  text not null default 'invite'
      check (visibility in ('invite','public','both')),
  location    text,
  start_date  date,
  end_date    date,
  budget_note text,
  state       text,
  city        text,
  trades      text[],
  created_at  timestamptz default now()
);

-- ── ITB FILES (drawings / scope docs, stored in the bucket) ─────────
create table if not exists itb_files (
  id          bigint generated always as identity primary key,
  itb_id      bigint not null references itbs(id) on delete cascade,
  path        text not null,   -- storage path inside the 'drawings' bucket
  filename    text not null
);

-- ── INVITES (which subs an ITB was sent to) ─────────────────────────
create table if not exists itb_invites (
  id          bigint generated always as identity primary key,
  itb_id      bigint not null references itbs(id) on delete cascade,
  sub_id      uuid not null references profiles(id),
  status      text not null default 'sent' check (status in ('sent','responded','declined','awarded','not_selected')),
  created_at  timestamptz default now(),
  unique (itb_id, sub_id)
);

-- ── BIDS (sub responses) ─────────────────────────────────────────────
create table if not exists bids (
  id          bigint generated always as identity primary key,
  itb_id      bigint not null references itbs(id) on delete cascade,
  sub_id      uuid not null references profiles(id),
  amount      numeric not null,
  note        text,
  revision    int not null default 1,   -- bid revisions: highest = current
  created_at  timestamptz default now()
);

-- ── BID FILES (sub's proposal docs, COI, inclusions — GC can view) ──
create table if not exists bid_files (
  id          bigint generated always as identity primary key,
  bid_id      bigint not null references bids(id) on delete cascade,
  path        text not null,
  filename    text not null
);

-- ═══ ROW LEVEL SECURITY ══════════════════════════════════════════════
-- Pilot-level policies: users only see what belongs to them or was
-- sent to them. Tighten further before scaling.

alter table profiles    enable row level security;
alter table itbs        enable row level security;
alter table itb_files   enable row level security;
alter table itb_invites enable row level security;
alter table bids        enable row level security;
alter table bid_files   enable row level security;

-- Profiles: any signed-in user can read (GCs browse subs); you can
-- only create/update your own row.
create policy "profiles readable by signed-in users"
  on profiles for select to authenticated using (true);
create policy "insert own profile"
  on profiles for insert to authenticated with check (id = auth.uid());
create policy "update own profile"
  on profiles for update to authenticated using (id = auth.uid());

-- Helper: checks invite membership WITHOUT triggering itb_invites' own
-- RLS policy (security definer). Required because the itbs and
-- itb_invites policies would otherwise reference each other and
-- Postgres aborts with "infinite recursion detected in policy".
create or replace function public.is_invited_to_itb(_itb_id bigint)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (
    select 1 from itb_invites
    where itb_id = _itb_id and sub_id = auth.uid()
  );
$$;

-- ITBs: GC sees their own; a sub sees ITBs they were invited to.
create policy "gc reads own itbs"
  on itbs for select to authenticated
  using (gc_id = auth.uid() or public.is_invited_to_itb(id));
create policy "gc creates itbs"
  on itbs for insert to authenticated with check (gc_id = auth.uid());
create policy "public rfps readable by signed-in users"
  on itbs for select to authenticated
  using (visibility in ('public','both'));

-- Files: visible to whoever can see the ITB; only the owning GC adds.
create policy "read files on visible itbs"
  on itb_files for select to authenticated
  using (exists (select 1 from itbs i where i.id = itb_files.itb_id
                 and (i.gc_id = auth.uid()
                      or exists (select 1 from itb_invites v
                                 where v.itb_id = i.id and v.sub_id = auth.uid()))));
create policy "gc adds files to own itbs"
  on itb_files for insert to authenticated
  with check (exists (select 1 from itbs i
                      where i.id = itb_files.itb_id and i.gc_id = auth.uid()));

-- Invites: the sub sees theirs; the GC sees invites on their ITBs.
create policy "read own or owned invites"
  on itb_invites for select to authenticated
  using (sub_id = auth.uid()
         or exists (select 1 from itbs i
                    where i.id = itb_invites.itb_id and i.gc_id = auth.uid()));
create policy "gc invites subs to own itbs"
  on itb_invites for insert to authenticated
  with check (exists (select 1 from itbs i
                      where i.id = itb_invites.itb_id and i.gc_id = auth.uid()));
create policy "sub updates own invite status"
  on itb_invites for update to authenticated using (sub_id = auth.uid());
create policy "gc updates invites on own itbs"
  on itb_invites for update to authenticated
  using (exists (select 1 from itbs i
                 where i.id = itb_invites.itb_id and i.gc_id = auth.uid()));

-- Bids: an invited sub submits one; sub sees their own, GC sees all
-- bids on their ITBs.
create policy "read own bids or bids on own itbs"
  on bids for select to authenticated
  using (sub_id = auth.uid()
         or exists (select 1 from itbs i
                    where i.id = bids.itb_id and i.gc_id = auth.uid()));
create policy "invited sub submits bid"
  on bids for insert to authenticated
  with check (sub_id = auth.uid()
              and exists (select 1 from itb_invites v
                          where v.itb_id = bids.itb_id and v.sub_id = auth.uid()));

-- Bid files: readable by the bidding sub and the ITB's GC; only the
-- bidding sub attaches.
create policy "read bid files if you can read the bid"
  on bid_files for select to authenticated
  using (exists (select 1 from bids b
                 where b.id = bid_files.bid_id
                 and (b.sub_id = auth.uid()
                      or exists (select 1 from itbs i
                                 where i.id = b.itb_id and i.gc_id = auth.uid()))));
create policy "sub attaches files to own bids"
  on bid_files for insert to authenticated
  with check (exists (select 1 from bids b
                      where b.id = bid_files.bid_id
                      and b.sub_id = auth.uid()));

-- ═══ STORAGE ═════════════════════════════════════════════════════════
-- Private bucket for drawings/scope docs. The app generates short-lived
-- signed URLs so only invited subs get working download links.
insert into storage.buckets (id, name, public)
values ('drawings', 'drawings', false)
on conflict (id) do nothing;

create policy "signed-in users upload drawings"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'drawings');
create policy "signed-in users read drawings"
  on storage.objects for select to authenticated
  using (bucket_id = 'drawings');


-- ═══ RFP BOARD: request-to-bid queue ═══
 create table if not exists bid_requests (
  id          bigint generated always as identity primary key,
  itb_id      bigint not null references itbs(id) on delete cascade,
  sub_id      uuid not null references profiles(id),
  message     text,
  status      text not null default 'requested'
      check (status in ('requested','approved','rejected')),
  created_at  timestamptz default now(),
  unique (itb_id, sub_id)
);

alter table bid_requests enable row level security;

-- The sub sees their own requests; the GC sees requests on their RFPs.
create policy "read own or owned bid requests"
  on bid_requests for select to authenticated
  using (sub_id = auth.uid()
         or exists (select 1 from itbs i
                    where i.id = bid_requests.itb_id
                    and i.gc_id = auth.uid()));

-- Only VERIFIED subs can request, and only on public/both RFPs.
create policy "verified sub requests to bid"
  on bid_requests for insert to authenticated
  with check (sub_id = auth.uid()
              and exists (select 1 from profiles p
                          where p.id = auth.uid()
                          and p.verification_status = 'verified')
              and exists (select 1 from itbs i
                          where i.id = bid_requests.itb_id
                          and i.visibility in ('public','both')));

-- The GC accepts/rejects requests on their own RFPs.
create policy "gc updates requests on own rfps"
  on bid_requests for update to authenticated
  using (exists (select 1 from itbs i
                 where i.id = bid_requests.itb_id
                 and i.gc_id = auth.uid()));


-- ═══ PROFILES: project portfolios ═══
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


-- ═══ from migration_007.sql ═══
-- ═══════════════════════════════════════════════════════════════════

-- ── allow the admin role ────────────────────────────────────────────
alter table profiles drop constraint if exists profiles_role_check;
alter table profiles add constraint profiles_role_check
  check (role in ('gc', 'sub', 'admin'));

-- ── is_admin(): security definer so policies can check the caller's
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


-- ═══ from migration_008.sql ═══
--
-- ═══════════════════════════════════════════════════════════════════

create table if not exists verification_docs (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references profiles(id) on delete cascade,
  doc_type    text not null,
  path        text not null,     -- storage path inside the 'docs' bucket
  filename    text not null,
  status      text not null default 'pending'
      check (status in ('pending', 'approved', 'rejected')),
  note        text,              -- admin note on rejection
  created_at  timestamptz default now(),
  reviewed_at timestamptz
);

alter table verification_docs enable row level security;

-- owner + admin always; GC only via an awarded invite linking them
create policy "docs readable by owner, admin, or awarding gc"
  on verification_docs for select to authenticated
  using (user_id = auth.uid()
         or public.is_admin()
         or exists (select 1 from itb_invites v
                    join itbs i on i.id = v.itb_id
                    where v.status = 'awarded'
                    and v.sub_id = verification_docs.user_id
                    and i.gc_id = auth.uid()));

create policy "owner submits own docs"
  on verification_docs for insert to authenticated
  with check (user_id = auth.uid());

create policy "admin reviews docs"
  on verification_docs for update to authenticated using (public.is_admin());

-- ── private storage bucket, path convention: {user_id}/{filename} ──
insert into storage.buckets (id, name, public)
values ('docs', 'docs', false)
on conflict (id) do nothing;

create policy "owner uploads own docs"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'docs'
              and (storage.foldername(name))[1] = auth.uid()::text);

create policy "docs readable by owner, admin, or awarding gc (storage)"
  on storage.objects for select to authenticated
  using (bucket_id = 'docs'
         and ((storage.foldername(name))[1] = auth.uid()::text
              or public.is_admin()
              or exists (select 1 from itb_invites v
                         join itbs i on i.id = v.itb_id
                         where v.status = 'awarded'
                         and i.gc_id = auth.uid()
                         and v.sub_id::text = (storage.foldername(name))[1])));


-- ═══ BID Q&A THREADS (from migration_010) ═══
create table if not exists bid_messages (
  id          bigint generated always as identity primary key,
  itb_id      bigint not null references itbs(id) on delete cascade,
  sub_id      uuid not null references profiles(id),   -- whose bid thread
  sender_id   uuid not null references profiles(id),
  message     text not null,
  created_at  timestamptz default now()
);

alter table bid_messages enable row level security;

-- Only the two parties (and admin) can read a thread
create policy "participants read bid messages"
  on bid_messages for select to authenticated
  using (sub_id = auth.uid()
         or exists (select 1 from itbs i
                    where i.id = bid_messages.itb_id
                    and i.gc_id = auth.uid())
         or public.is_admin());

-- Only the two parties can post, and only as themselves
create policy "participants send bid messages"
  on bid_messages for insert to authenticated
  with check (sender_id = auth.uid()
              and (sub_id = auth.uid()
                   or exists (select 1 from itbs i
                              where i.id = bid_messages.itb_id
                              and i.gc_id = auth.uid())));
