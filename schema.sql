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
  role        text not null check (role in ('gc', 'sub')),
  company     text not null,
  trade       text,            -- subs only, e.g. 'Electrical (C-10)'
  region      text,
  license_no  text,            -- CSLB license number
  verification_status text not null default 'unverified'
      check (verification_status in ('unverified','pending','verified','rejected')),
  verified_at   timestamptz,
  cslb_status   text,           -- raw status line from CSLB lookup
  cslb_expires  text,           -- license expiration
  cslb_business text,           -- business name on the license
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
