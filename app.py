"""
SLATE — subcontractor bid & endorsement platform (PILOT)
========================================================
Built by contractors, for contractors.

This version is wired to real services:
  - Supabase ......... login/accounts, database, file storage
  - Resend ........... email notifications to subs when an ITB goes out

SETUP (one time) — see README.md for the click-by-click version:
  1. Create a free project at supabase.com
  2. Run schema.sql in the Supabase SQL Editor
  3. Supabase -> Authentication -> Sign In / Up: turn OFF "Confirm email"
     (pilot convenience; turn back on later)
  4. Create a free account at resend.com, get an API key
  5. Put your keys in .streamlit/secrets.toml (locally) or in the
     Streamlit Cloud "Secrets" box (deployed). See secrets.toml.example.

HOW IT WORKS:
  - New users sign up with email + password, then complete a profile
    as either a GC or a Sub.
  - GCs create bid requests (ITBs): scope + due date + PDF drawings,
    pick subs from the network, hit send. Each sub gets an email and
    an in-app invite.
  - Subs see their invite inbox, download drawings via expiring signed
    links, and respond with a bid amount + note.
  - GCs see responses side by side per ITB.

The demo with mock data still lives in demo_app.py.
"""

import mimetypes
import time

import requests
import streamlit as st
from supabase import create_client

# ─────────────────────────────────────────────────────────────────────
#  CONFIG + THEME
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="SLATE", page_icon="🪧", layout="wide")

C = {
    "paper": "#EDEFEA", "ink": "#16263C", "inkSoft": "#3D4E63",
    "line": "#C6CCC4", "orange": "#E8621A", "blue": "#2E5E8C",
    "green": "#3E7A4E", "white": "#FAFBF8",
}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
.stApp { background: #EDEFEA; }
.f-disp { font-family: 'Barlow Condensed', sans-serif; }
.f-mono { font-family: 'IBM Plex Mono', monospace; }
html, body, [class*="css"] { font-family: 'Barlow', sans-serif; }
section[data-testid="stSidebar"] { background: #16263C; }
section[data-testid="stSidebar"] * { color: #C6D0DC; }
.card { background:#FAFBF8; border:1px solid #C6CCC4; border-radius:3px;
        padding:16px; margin-bottom:12px; }
.wordmark { font-family:'Barlow Condensed',sans-serif; font-weight:700;
            font-size:30px; color:#FFF; letter-spacing:0.5px; line-height:1; }
.eyebrow { font-family:'IBM Plex Mono',monospace; font-size:10px;
           text-transform:uppercase; letter-spacing:1px; color:#3D4E63; }
.stButton > button { background:#E8621A; color:#FFF; border:none; border-radius:3px;
  font-family:'Barlow Condensed',sans-serif; font-weight:600; letter-spacing:1px; }
.stButton > button:hover { background:#cf560f; color:#FFF; }
</style>
""", unsafe_allow_html=True)


def heading(text):
    st.markdown(f'<div class="f-disp" style="font-size:30px;font-weight:700;'
                f'color:{C["ink"]}">{text}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
#  SUPABASE CLIENT + AUTH HELPERS
# ─────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


def sb():
    """Client authorized as the logged-in user (so RLS policies apply)."""
    client = get_client()
    tok = st.session_state.get("access_token")
    if tok:
        client.postgrest.auth(tok)
    return client


def require_secrets():
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY") if k not in st.secrets]
    if missing:
        st.error(f"Missing secrets: {', '.join(missing)}. "
                 "Add them to .streamlit/secrets.toml (local) or the Secrets box "
                 "on Streamlit Cloud. See README.md.")
        st.stop()


def sign_in(email, password):
    res = get_client().auth.sign_in_with_password({"email": email, "password": password})
    st.session_state.access_token = res.session.access_token
    st.session_state.user_id = res.user.id
    st.session_state.user_email = res.user.email


def sign_up(email, password):
    res = get_client().auth.sign_up({"email": email, "password": password})
    if res.session is None:
        # Email confirmation is still ON in Supabase settings.
        st.info("Account created. Confirm the email Supabase sent you, then log in. "
                "(To skip this step for the pilot, turn off 'Confirm email' in "
                "Supabase -> Authentication settings.)")
        st.stop()
    st.session_state.access_token = res.session.access_token
    st.session_state.user_id = res.user.id
    st.session_state.user_email = res.user.email


def sign_out():
    for k in ("access_token", "user_id", "user_email", "profile"):
        st.session_state.pop(k, None)


def load_profile():
    rows = (sb().table("profiles").select("*")
            .eq("id", st.session_state.user_id).execute().data)
    st.session_state.profile = rows[0] if rows else None
    return st.session_state.profile


# ─────────────────────────────────────────────────────────────────────
#  EMAIL (Resend) — degrades gracefully if no key is configured
# ─────────────────────────────────────────────────────────────────────
def send_itb_email(to_email, gc_company, project, trade, due, app_url):
    api_key = st.secrets.get("RESEND_API_KEY")
    if not api_key:
        return False, "no RESEND_API_KEY configured"
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": st.secrets.get("EMAIL_FROM", "SLATE <onboarding@resend.dev>"),
                "to": [to_email],
                "subject": f"Bid request: {trade} — {project}",
                "html": (
                    f"<p><b>{gc_company}</b> invited you to bid on:</p>"
                    f"<p><b>{project}</b><br>Trade: {trade}<br>Bids due: {due}</p>"
                    f"<p>Drawings and scope are attached in SLATE. "
                    f"<a href='{app_url}'>Log in to review and respond</a>.</p>"
                    f"<p style='color:#888;font-size:12px'>SLATE — by contractors, "
                    f"for contractors.</p>"
                ),
            },
            timeout=15,
        )
        return (r.status_code in (200, 201)), r.text
    except requests.RequestException as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────
#  SCREEN: LOGIN / SIGN UP
# ─────────────────────────────────────────────────────────────────────
def screen_auth():
    st.markdown('<div class="wordmark" style="color:#16263C">SLATE'
                '<span style="color:#E8621A">.</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">BY CONTRACTORS, FOR CONTRACTORS</div>',
                unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    tab_in, tab_up = st.tabs(["Log in", "Create account"])
    with tab_in:
        email = st.text_input("Email", key="li_email")
        pw = st.text_input("Password", type="password", key="li_pw")
        if st.button("Log in"):
            try:
                sign_in(email.strip(), pw)
                st.rerun()
            except Exception:
                st.error("Login failed — check your email and password.")
    with tab_up:
        email = st.text_input("Email", key="su_email")
        pw = st.text_input("Password (8+ characters)", type="password", key="su_pw")
        if st.button("Create account"):
            if len(pw) < 8:
                st.error("Password needs at least 8 characters.")
            else:
                try:
                    sign_up(email.strip(), pw)
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not create the account: {e}")


# ─────────────────────────────────────────────────────────────────────
#  SCREEN: COMPLETE PROFILE (first login)
# ─────────────────────────────────────────────────────────────────────
def screen_onboarding():
    heading("SET UP YOUR PROFILE")
    role = st.radio("I am a…", ["General Contractor", "Subcontractor"], horizontal=True)
    company = st.text_input("Company name")
    trade, license_no = None, None
    if role == "Subcontractor":
        trade = st.text_input("Trade + license class (e.g. Electrical C-10)")
        license_no = st.text_input("CSLB license #")
    region = st.text_input("Region (e.g. South Bay)")
    if st.button("Save profile"):
        if not company.strip():
            st.error("Company name is required.")
            return
        sb().table("profiles").insert({
            "id": st.session_state.user_id,
            "email": st.session_state.user_email,
            "role": "gc" if role == "General Contractor" else "sub",
            "company": company.strip(),
            "trade": (trade or "").strip() or None,
            "license_no": (license_no or "").strip() or None,
            "region": region.strip() or None,
        }).execute()
        st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  GC SCREEN: NEW BID REQUEST  (create ITB -> upload files -> invite -> email)
# ─────────────────────────────────────────────────────────────────────
def screen_new_itb(profile):
    heading("NEW BID REQUEST")

    subs = (sb().table("profiles").select("id, company, trade, region, email")
            .eq("role", "sub").execute().data)
    if not subs:
        st.info("No subcontractors have joined yet. Invite your subs to create "
                "accounts — this screen goes live the moment the first one signs up.")
        return

    project = st.text_input("Project", placeholder="Lariat Ln Residence — 3,750 SF New Build")
    trade = st.text_input("Trade package", placeholder="Framing Package")
    scope = st.text_area("Scope of work")
    due = st.date_input("Bids due")
    files = st.file_uploader("Drawings / scope docs (PDF, DOCX)",
                             accept_multiple_files=True)

    st.markdown('<div class="eyebrow" style="margin-top:8px">SELECT SUBS</div>',
                unsafe_allow_html=True)
    picked = []
    for s in subs:
        label = f"{s['company']} — {s.get('trade') or 'trade not set'} · {s.get('region') or ''}"
        if st.checkbox(label, key=f"sub_{s['id']}"):
            picked.append(s)

    if st.button("Send Bid Request"):
        if not (project.strip() and trade.strip() and picked):
            st.error("Project, trade package, and at least one sub are required.")
            return

        with st.spinner("Creating bid request…"):
            # 1. the ITB row
            itb = (sb().table("itbs").insert({
                "gc_id": st.session_state.user_id,
                "project": project.strip(),
                "trade": trade.strip(),
                "scope": scope.strip() or None,
                "due_date": due.isoformat(),
            }).execute().data)[0]

            # 2. upload files to the private bucket, record paths
            for f in files or []:
                path = f"{itb['id']}/{int(time.time())}_{f.name}"
                mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                sb().storage.from_("drawings").upload(
                    path, f.getvalue(), {"content-type": mime})
                sb().table("itb_files").insert({
                    "itb_id": itb["id"], "path": path, "filename": f.name,
                }).execute()

            # 3. invites + emails
            app_url = st.secrets.get("APP_URL", "https://share.streamlit.io")
            emailed, failed = 0, 0
            for s in picked:
                sb().table("itb_invites").insert({
                    "itb_id": itb["id"], "sub_id": s["id"],
                }).execute()
                ok, _ = send_itb_email(s["email"], profile["company"],
                                       project, trade, due.isoformat(), app_url)
                emailed += ok
                failed += (not ok)

        st.success(f"Bid request sent to {len(picked)} sub(s). "
                   f"Emails delivered: {emailed}."
                   + (f" Email failures: {failed} — invites still show in their "
                      f"SLATE inbox." if failed else ""))


# ─────────────────────────────────────────────────────────────────────
#  GC SCREEN: DASHBOARD  (my ITBs + responses side by side)
# ─────────────────────────────────────────────────────────────────────
def screen_gc_dashboard(profile):
    heading("DASHBOARD")
    itbs = (sb().table("itbs").select("*")
            .eq("gc_id", st.session_state.user_id)
            .order("created_at", desc=True).execute().data)
    if not itbs:
        st.info("No bid requests yet — create your first one from **New Bid Request**.")
        return

    for itb in itbs:
        invites = (sb().table("itb_invites").select("sub_id, status")
                   .eq("itb_id", itb["id"]).execute().data)
        bids = (sb().table("bids").select("sub_id, amount, note, created_at")
                .eq("itb_id", itb["id"]).order("amount").execute().data)
        responded = sum(1 for v in invites if v["status"] == "responded")
        with st.expander(f"ITB-{itb['id']:04d} · {itb['project']} — {itb['trade']} "
                         f"({responded}/{len(invites)} responded, due {itb['due_date']})"):
            if itb.get("scope"):
                st.markdown(f'<div class="eyebrow">SCOPE</div>'
                            f'<div style="color:{C["ink"]}">{itb["scope"]}</div>',
                            unsafe_allow_html=True)
            if not bids:
                st.markdown(f'<div style="color:{C["inkSoft"]}">No bids yet.</div>',
                            unsafe_allow_html=True)
                continue
            # look up company names for the bids
            ids = [b["sub_id"] for b in bids]
            names = {p["id"]: p["company"] for p in
                     sb().table("profiles").select("id, company")
                     .in_("id", ids).execute().data}
            low = min(b["amount"] for b in bids)
            for b in bids:
                tag = (' <span class="f-mono" style="color:#3E7A4E;font-size:11px">'
                       'LOW BID</span>' if b["amount"] == low and len(bids) > 1 else "")
                st.markdown(
                    f'<div class="card"><b>{names.get(b["sub_id"], "Sub")}</b> — '
                    f'<span class="f-disp" style="font-size:20px;font-weight:600">'
                    f'${b["amount"]:,.0f}</span>{tag}'
                    f'<div style="color:{C["inkSoft"]};font-size:14px">'
                    f'{b.get("note") or ""}</div></div>',
                    unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
#  SUB SCREEN: INBOX  (my invites -> download drawings -> respond)
# ─────────────────────────────────────────────────────────────────────
def screen_sub_inbox(profile):
    heading("BID INVITES")
    invites = (sb().table("itb_invites").select("*")
               .eq("sub_id", st.session_state.user_id)
               .order("created_at", desc=True).execute().data)
    if not invites:
        st.info("No bid invites yet. When a GC sends you one, it lands here "
                "and in your email.")
        return

    for v in invites:
        itb = (sb().table("itbs").select("*").eq("id", v["itb_id"]).execute().data)
        if not itb:
            continue
        itb = itb[0]
        gc = (sb().table("profiles").select("company")
              .eq("id", itb["gc_id"]).execute().data)
        gc_name = gc[0]["company"] if gc else "GC"
        badge = "✅ RESPONDED" if v["status"] == "responded" else "🟠 AWAITING YOUR BID"

        with st.expander(f"{badge} · {itb['project']} — {itb['trade']} "
                         f"(from {gc_name}, due {itb['due_date']})"):
            if itb.get("scope"):
                st.markdown(f'<div class="eyebrow">SCOPE</div>'
                            f'<div style="color:{C["ink"]}">{itb["scope"]}</div>',
                            unsafe_allow_html=True)

            # drawings via short-lived signed URLs (private bucket)
            fs = (sb().table("itb_files").select("path, filename")
                  .eq("itb_id", itb["id"]).execute().data)
            if fs:
                st.markdown('<div class="eyebrow" style="margin-top:8px">DRAWINGS'
                            '</div>', unsafe_allow_html=True)
                for f in fs:
                    try:
                        signed = sb().storage.from_("drawings").create_signed_url(
                            f["path"], 3600)
                        url = signed.get("signedURL") or signed.get("signed_url")
                        st.markdown(f"- [{f['filename']}]({url})")
                    except Exception:
                        st.markdown(f"- {f['filename']} (link unavailable)")

            if v["status"] != "responded":
                amount = st.number_input("Your bid ($)", min_value=0.0, step=1000.0,
                                         key=f"amt_{v['id']}")
                note = st.text_area("Notes (inclusions, exclusions, lead time)",
                                    key=f"note_{v['id']}")
                if st.button("Submit bid", key=f"send_{v['id']}"):
                    if amount <= 0:
                        st.error("Enter a bid amount.")
                    else:
                        sb().table("bids").insert({
                            "itb_id": itb["id"],
                            "sub_id": st.session_state.user_id,
                            "amount": amount,
                            "note": note.strip() or None,
                        }).execute()
                        sb().table("itb_invites").update(
                            {"status": "responded"}).eq("id", v["id"]).execute()
                        st.success("Bid submitted.")
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  SHARED SCREEN: SUB NETWORK (GC view of registered subs)
# ─────────────────────────────────────────────────────────────────────
def screen_network():
    heading("SUB NETWORK")
    subs = (sb().table("profiles").select("company, trade, region, license_no")
            .eq("role", "sub").order("company").execute().data)
    if not subs:
        st.info("No subs registered yet.")
        return
    for s in subs:
        st.markdown(
            f'<div class="card"><b>{s["company"]}</b>'
            f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
            f'{s.get("trade") or "trade not set"} · {s.get("region") or ""} · '
            f'CSLB {s.get("license_no") or "—"}</div></div>',
            unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
#  MAIN ROUTER
# ─────────────────────────────────────────────────────────────────────
require_secrets()

if "user_id" not in st.session_state:
    screen_auth()
    st.stop()

profile = st.session_state.get("profile") or load_profile()
if profile is None:
    screen_onboarding()
    st.stop()

with st.sidebar:
    st.markdown('<div class="wordmark">SLATE<span style="color:#E8621A">.</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="f-mono" style="font-size:10px;color:#8FA0B5;'
                f'margin-top:4px">{profile["company"].upper()} · '
                f'{"GC" if profile["role"] == "gc" else "SUB"}</div>',
                unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    if profile["role"] == "gc":
        page = st.radio("Navigate", ["Dashboard", "New Bid Request", "Sub Network"],
                        label_visibility="collapsed")
    else:
        page = st.radio("Navigate", ["Bid Invites"], label_visibility="collapsed")
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Log out"):
        sign_out()
        st.rerun()

if profile["role"] == "gc":
    if page == "Dashboard":
        screen_gc_dashboard(profile)
    elif page == "New Bid Request":
        screen_new_itb(profile)
    else:
        screen_network()
else:
    screen_sub_inbox(profile)
