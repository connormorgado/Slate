-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 012 — email preferences
--  Run ONCE in Supabase SQL Editor.
--
--  Transactional emails (bids, awards, verification, Q&A) always send.
--  Announcements/product updates respect this opt-out, toggled by the
--  user on My Profile.
-- ═══════════════════════════════════════════════════════════════════

alter table profiles
  add column if not exists email_opt_out boolean not null default false;
