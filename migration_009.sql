-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 009 — location + trade matching for RFPs
--  Run ONCE in Supabase SQL Editor (after 008).
-- ═══════════════════════════════════════════════════════════════════

-- Subs declare what they do and where they work
alter table profiles
  add column if not exists trades       text[],   -- CSLB classes, e.g. {C-10 Electrical}
  add column if not exists work_states  text[],   -- e.g. {CA, NV}
  add column if not exists work_cities  text;     -- comma-separated, free text

-- RFPs declare where the work is and which trades are needed
alter table itbs
  add column if not exists state   text,
  add column if not exists city    text,
  add column if not exists trades  text[];
