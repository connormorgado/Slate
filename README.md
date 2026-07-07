# SLATE

A subcontractor bid & endorsement platform — **prototype**.
Built by contractors, for contractors.

This is a clickable prototype (mock data, no backend yet) for showing GCs and
subs the experience and getting reactions before building the real thing.

## What's here

- **Dashboard** — active bid requests, response coverage, and a coverage-risk alert
- **Sub Network** — searchable subs with verified performance metrics + endorsement tiers
- **New Bid Request** — 3-step flow: scope & drawings → select subs (tier-gated) → send
- **Tier System** — how subs climb tiers through GC endorsements

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL it prints (usually http://localhost:8501).

## Publish it online (free)

1. Push this folder to a **GitHub** repo.
2. Go to **share.streamlit.io** and sign in with GitHub.
3. Click **New app**, pick your repo, set the main file to `app.py`, and **Deploy**.
4. You get a public URL you can text to contractors.

## Editing later

Everything you'll want to change lives near the top of `app.py`:

- `SUBS` — the subcontractor companies and their metrics
- `ITBS` — the open bid requests shown on the dashboard
- `TIER_META` — tier labels, requirements, and scope limits
- `C` — the color palette (rebrand the whole app from here)

All the wording is inline in the page functions — just search for the text and edit it.

## Next steps (not built yet)

- Sub-side view (their incoming bid invites + their own scorecard)
- Real accounts, login, and a database
- Actual file upload for drawings/scopes
