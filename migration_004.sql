-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 004 — public RFP board + request-to-bid queue
--  Run ONCE in Supabase SQL Editor on your EXISTING project.
-- ═══════════════════════════════════════════════════════════════════

-- ── RFP fields on bid requests ──────────────────────────────────────
alter table itbs
  add column if not exists visibility text not null default 'invite'
      check (visibility in ('invite','public','both')),
  add column if not exists location    text,
  add column if not exists start_date  date,
  add column if not exists end_date    date,
  add column if not exists budget_note text;

-- Public/both RFPs are browsable by any signed-in user. (Attachments
-- stay gated by the existing itb_files policy — invited subs only.)
create policy "public rfps readable by signed-in users"
  on itbs for select to authenticated
  using (visibility in ('public','both'));

-- ── Request-to-bid queue ────────────────────────────────────────────
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
