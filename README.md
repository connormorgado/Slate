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
