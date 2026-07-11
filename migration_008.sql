-- ═══════════════════════════════════════════════════════════════════
--  SLATE migration 008 — document-based verification
--  Run ONCE in Supabase SQL Editor (after 007).
--
--  Access model:
--    * The uploading contractor and the admin can always see the docs
--    * Everyone else sees only completion badges (✓ COI on file)
--    * A GC gains access to a sub's documents ONLY after awarding
--      that sub a scope — enforced at the database level
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
