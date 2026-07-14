-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 010 — activity tracking + bid Q&A threads
--  Run ONCE in Supabase SQL Editor.
-- ═══════════════════════════════════════════════════════════════════

-- ── last seen (updated by the app as users are active) ─────────────
alter table profiles
  add column if not exists last_seen timestamptz;

-- ── bid Q&A: one thread per (RFP, sub) — questions, clarifications,
--    revision requests. Spans bid revisions. ─────────────────────────
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
