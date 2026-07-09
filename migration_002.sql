-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 002 — bid revisions, award status, bid documents
--  Run ONCE in Supabase SQL Editor on your EXISTING project.
--  (Fresh installs don't need this — schema.sql already includes it.)
-- ═══════════════════════════════════════════════════════════════════

-- ── 1. BID REVISIONS ────────────────────────────────────────────────
-- Drop the one-bid-per-sub rule and add a revision counter.
alter table bids drop constraint if exists bids_itb_id_sub_id_key;
alter table bids add column if not exists revision int not null default 1;

-- ── 2. AWARD STATUS ─────────────────────────────────────────────────
-- Invites can now be awarded / not selected, and the GC may update
-- invite status on their own ITBs (previously only the sub could).
alter table itb_invites drop constraint if exists itb_invites_status_check;
alter table itb_invites add constraint itb_invites_status_check
  check (status in ('sent','responded','declined','awarded','not_selected'));

create policy "gc updates invites on own itbs"
  on itb_invites for update to authenticated
  using (exists (select 1 from itbs i
                 where i.id = itb_invites.itb_id and i.gc_id = auth.uid()));

-- ── 3. BID DOCUMENTS (sub uploads for the GC to view) ──────────────
create table if not exists bid_files (
  id        bigint generated always as identity primary key,
  bid_id    bigint not null references bids(id) on delete cascade,
  path      text not null,   -- storage path inside the 'drawings' bucket
  filename  text not null
);

alter table bid_files enable row level security;

create policy "read bid files if you can read the bid"
  on bid_files for select to authenticated
  using (exists (select 1 from bids b
                 where b.id = bid_files.bid_id
                 and (b.sub_id = auth.uid()
                      or exists (select 1 from itbs i
                                 where i.id = b.itb_id
                                 and i.gc_id = auth.uid()))));

create policy "sub attaches files to own bids"
  on bid_files for insert to authenticated
  with check (exists (select 1 from bids b
                      where b.id = bid_files.bid_id
                      and b.sub_id = auth.uid()));
