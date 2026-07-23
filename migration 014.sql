-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 014 — announcement images
--  Run ONCE in Supabase SQL Editor.
--
--  Public bucket so images embedded in announcement emails render in
--  Gmail/Outlook (email clients strip embedded/base64 images; they
--  need a hosted URL). Only the admin can upload here; anything in
--  this bucket is world-readable by design — announcement images only.
-- ═══════════════════════════════════════════════════════════════════

insert into storage.buckets (id, name, public)
values ('announce', 'announce', true)
on conflict (id) do nothing;

create policy "admin uploads announcement images"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'announce' and public.is_admin());

create policy "announcement images readable"
  on storage.objects for select to authenticated
  using (bucket_id = 'announce');
