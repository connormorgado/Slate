-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 013 — granular email notification preferences
--  Run ONCE in Supabase SQL Editor.
--
--  Users control three categories from Settings:
--    email_opt_out        -> announcements / product updates
--    notify_bid_activity  -> bids, awards, requests, RFP matches, reminders
--    notify_messages      -> bid Q&A thread messages
--  Verification/document emails always send (transactional).
-- ═══════════════════════════════════════════════════════════════════

alter table profiles
  add column if not exists notify_bid_activity boolean not null default true,
  add column if not exists notify_messages     boolean not null default true;
