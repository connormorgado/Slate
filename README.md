# SLATE

A subcontractor bid & endorsement platform — **pilot**.
Built by contractors, for contractors.

Two apps in this repo:

| File | What it is |
|---|---|
| `app.py` | The real pilot: login, database, file upload, email notifications |
| `demo_app.py` | The original mock-data demo (no setup needed, good for pitching) |

## What the pilot does

- **Accounts** — GCs and subs sign up with email + password, complete a profile
- **GC: New Bid Request** — scope + due date + drawing PDFs, pick subs, send.
  Every invited sub gets an **email** and an in-app invite
- **Sub: Bid Invites** — inbox of ITBs with drawing downloads (expiring signed
  links) and a respond form (bid amount + notes)
- **GC: Dashboard** — every ITB with responses side by side, low bid flagged
- **GC: Sub Network** — all registered subs with trade, region, CSLB #

## One-time setup (~20 minutes)

### 1. Supabase (database + login + file storage — free)
1. Create a project at **supabase.com**
2. Open **SQL Editor** → New query → paste all of `schema.sql` → **Run**
3. Go to **Authentication → Sign In / Providers** → turn **off** "Confirm email"
   (pilot convenience; turn back on later)
4. Go to **Project Settings → API** and copy the **Project URL** and the
   **anon public** key

### 2. Resend (email notifications — free)
1. Create an account at **resend.com** → **API Keys** → create one
2. For the pilot you can send from `onboarding@resend.dev`. To email anyone
   (not just yourself), verify a domain you own under **Domains** — takes
   ~10 minutes with two DNS records

### 3. Secrets
- **Local:** copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
  and fill in your keys. This file is gitignored — never commit it.
- **Streamlit Cloud:** App → **Settings → Secrets** → paste the same contents

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py        # the pilot
streamlit run demo_app.py   # the mock demo
```

## Deploy (free)

1. Push this repo to GitHub
2. **share.streamlit.io** → New app → pick the repo → main file `app.py`
3. Paste your secrets into Settings → Secrets → Deploy
4. Put the resulting URL into the `APP_URL` secret so invite emails link back
   to the app

## Pilot test checklist (do this before showing anyone)

1. Sign up as yourself → choose **General Contractor**
2. Open an incognito window → sign up with a second email → choose
   **Subcontractor**
3. As the GC: create a bid request with a PDF, select the sub, send
4. Check the sub email inbox for the notification
5. As the sub: open Bid Invites, download the PDF, submit a bid
6. As the GC: see the bid on the Dashboard

## Known pilot limits (by design — validate first, build second)

- No performance metrics or endorsement tiers yet (needs real job data)
- No payments (invoice founding members manually)
- Streamlit logs you out on page refresh (session isn't persisted) — fine for
  a pilot, solved in the post-validation rebuild
- One bid per sub per ITB, no bid revisions yet

## Migration 002 — bid revisions, awards, bid documents, CSLB

If your Supabase project was set up before these features: run
`migration_002.sql` once in the SQL Editor. Fresh installs skip this —
`schema.sql` already includes everything.

New in this version:

- **Bid revisions** — subs can resubmit; the GC sees the latest number
  with a REV badge, and history stays in the database
- **Award / not selected** — GC clicks "Award to [sub]" on the dashboard;
  the winner sees 🏆 AWARDED TO YOU, everyone else sees NOT SELECTED.
  No more ghosting — every bidder hears back
- **Bid documents** — subs attach proposal PDFs, inclusions lists, COIs;
  the GC downloads them right under each bid
- **CSLB verification** — a "Verify CSLB #" button on Sub Network checks
  the license against the state board's public lookup (best-effort HTML
  parsing since CSLB has no official API; falls back to a manual-check
  link if the site blocks or changes)

## Migration 003 — contractor verification

Run `migration_003.sql` once in the SQL Editor (existing projects only).

How verification works:

- Everyone can sign up, but **unverified GCs can't send bid requests** and
  **unverified subs don't appear on bid lists**. Both see a Get Verified
  prompt on their home screen.
- **Get Verified** (sidebar) checks their CSLB license: current-and-active
  license + company name matching the CSLB record = instant ✓ VERIFIED.
- Anything fuzzy (name mismatch, inactive license, lookup blocked) goes to
  **pending** for manual review.

**Approving pending accounts (that's you):** Supabase → Table Editor →
`profiles` → find the row → set `verification_status` to `verified`.
Your existing test accounts start as `unverified` — verify them the same
way, or run the flow with a real license number.

Pilot-level caveat: verification runs client-side with the user's own
database permissions, so a technically savvy user could theoretically
self-verify via the API. Fine for a trusted pilot; move the decision into
a Supabase Edge Function before opening signups to strangers.

## Migrations 004 + 005 — public RFP board & contractor profiles

Run `migration_004.sql` then `migration_005.sql` once each in the SQL Editor
(existing projects; fresh installs get everything from schema.sql).

**Public RFP board.** Posting a bid request now has a visibility choice:
invite-only (how it worked before), public on the RFP board, or both.
Public postings show the GC, scope, location, expected start/end, due date,
and optional budget note. Attachments stay locked until a sub is approved.

**Request to bid.** Subs browse the board (verified or not) but must be
verified to request permission. GCs approve/reject from the new
**Bid Requests** page — approval creates the invite, unlocks drawings, and
emails the sub. Pending requests show a 🔔 count on the dashboard.

**Profiles & portfolios.** Everyone gets **My Profile**: current and
completed projects with photos and captions — evidence of excellence.
View anyone's profile from the RFP board, Sub Network, or Bid Requests.

**Smoke test checklist for this release:**
1. GC: post an RFP with visibility "Both", one PDF, no invited subs
2. Sub (verified): find it on RFP Board -> Request to Bid with a message
3. GC: Dashboard shows 🔔 -> Bid Requests -> View profile -> Approve
4. Sub: invite appears in Bid Invites with the PDF downloadable -> bid
5. Sub: My Profile -> add a project + photo with caption
6. GC: Sub Network -> View profile -> see the project and photo
7. Unverified account: can browse RFP Board, gets verify prompt on request
