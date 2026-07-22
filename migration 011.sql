-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 011 — CSLB classification storage (role cross-check)
--  Run ONCE in Supabase SQL Editor.
--
--  Stores the license classifications parsed from CSLB (e.g. "B",
--  "C-10") so SLATE can flag likely role mistakes: a "GC" holding only
--  C-class specialty licenses is probably a subcontractor.
-- ═══════════════════════════════════════════════════════════════════

alter table profiles
  add column if not exists cslb_classes text;   -- e.g. "B, C-10"
