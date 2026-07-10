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

import base64
import mimetypes
import os
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests
import streamlit as st
from supabase import create_client

from cslb import check_license

# ─────────────────────────────────────────────────────────────────────
#  CONFIG + THEME
# ─────────────────────────────────────────────────────────────────────
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(_APP_DIR, "assets", "slate_logo.png")
ICON_PATH = os.path.join(_APP_DIR, "assets", "slate_icon.png")

st.set_page_config(
    page_title="SLATE",
    page_icon=ICON_PATH if os.path.exists(ICON_PATH) else "🪧",
    layout="wide",
)


def _logo_b64():
    if not os.path.exists(LOGO_PATH):
        return None
    return base64.b64encode(open(LOGO_PATH, "rb").read()).decode()


def logo_html(width=170, boxed=False):
    """The SLATE logo as inline HTML. Falls back to a text wordmark if
    the image isn't found — white for the dark sidebar, dark ink when
    boxed (light backgrounds). boxed=True wraps the image in a dark card
    so the green glow reads on light pages (e.g. login)."""
    b64 = _logo_b64()
    if b64 is None:
        color = "#141B17" if boxed else "#FFFFFF"
        return (f'<div class="wordmark" style="color:{color}">SLATE'
                f'<span style="color:#6EE86E">.</span></div>')
    img = f'<img src="data:image/png;base64,{b64}" width="{width}" alt="SLATE">'
    if boxed:
        return (f'<div style="background:#101613;display:inline-block;'
                f'padding:22px 30px;border-radius:8px">{img}</div>')
    return img

C = {
    "paper": "#EDEFEA", "ink": "#141B17", "inkSoft": "#44544A",
    "line": "#C6CCC4", "accent": "#1D7A44", "neon": "#6EE86E",
    "blue": "#2E5E8C", "green": "#3E7A4E", "white": "#FAFBF8",
}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
.stApp { background: #EDEFEA; }
.f-disp { font-family: 'Barlow Condensed', sans-serif; }
.f-mono { font-family: 'IBM Plex Mono', monospace; }
html, body, [class*="css"] { font-family: 'Barlow', sans-serif; }
section[data-testid="stSidebar"] { background: #0D0F0E; }
section[data-testid="stSidebar"] * { color: #BFCCC2; }
.card { background:#FAFBF8; border:1px solid #C6CCC4; border-radius:3px;
        padding:16px; margin-bottom:12px; }
.wordmark { font-family:'Barlow Condensed',sans-serif; font-weight:700;
            font-size:30px; color:#FFF; letter-spacing:0.5px; line-height:1; }
.eyebrow { font-family:'IBM Plex Mono',monospace; font-size:10px;
           text-transform:uppercase; letter-spacing:1px; color:#3D4E63; }
.stButton > button { background:#1D7A44; color:#FFF; border:none; border-radius:3px;
  font-family:'Barlow Condensed',sans-serif; font-weight:600; letter-spacing:1px; }
.stButton > button:hover { background:#14572F; color:#FFF; }

/* ── Sidebar nav: real buttons, no radio circles ─────────────────── */
section[data-testid="stSidebar"] .stButton > button {
  width: 100%; justify-content: flex-start; text-align: left;
  background: transparent; color: #BFCCC2;
  border: 1px solid rgba(110,232,110,0.10); border-radius: 6px;
  padding: 10px 14px;
  font-family: 'Barlow Condensed', sans-serif; font-weight: 600;
  letter-spacing: 1.5px; text-transform: uppercase; font-size: 15px;
  transition: border-color .15s ease, background .15s ease,
              box-shadow .15s ease, color .15s ease;
}
section[data-testid="stSidebar"] .stButton > button:hover {
  border-color: #6EE86E; background: rgba(110,232,110,0.06);
  color: #FFFFFF;
}
/* active page (rendered as a primary button) — filled tint + glow */
section[data-testid="stSidebar"] .stButton > button[kind="primary"],
section[data-testid="stSidebar"] .stButton > button[data-testid="baseButton-primary"] {
  background: rgba(110,232,110,0.14); color: #FFFFFF;
  border: 1px solid #6EE86E;
  box-shadow: 0 0 12px rgba(110,232,110,0.22);
}
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


def send_simple_email(to_email, subject, html):
    """Generic notification email — degrades gracefully with no key."""
    api_key = st.secrets.get("RESEND_API_KEY")
    if not api_key:
        return False
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": st.secrets.get("EMAIL_FROM", "SLATE <onboarding@resend.dev>"),
                  "to": [to_email], "subject": subject, "html": html},
            timeout=15)
        return r.status_code in (200, 201)
    except requests.RequestException:
        return False


# ─────────────────────────────────────────────────────────────────────
#  SCREEN: LOGIN / SIGN UP
# ─────────────────────────────────────────────────────────────────────
def screen_auth():
    st.markdown(logo_html(width=190, boxed=True), unsafe_allow_html=True)
    st.markdown('<div class="eyebrow" style="margin-top:8px">BY CONTRACTORS, '
                'FOR CONTRACTORS</div>', unsafe_allow_html=True)
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
    contact = st.text_input("Your name", placeholder="First and last")
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
            "contact_name": contact.strip() or None,
            "trade": (trade or "").strip() or None,
            "license_no": (license_no or "").strip() or None,
            "region": region.strip() or None,
        }).execute()
        st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────
def latest_bids_by_sub(bids):
    """From all bid rows on an ITB, keep only each sub's latest revision."""
    latest = {}
    for b in bids:
        cur = latest.get(b["sub_id"])
        if cur is None or b["revision"] > cur["revision"]:
            latest[b["sub_id"]] = b
    return latest


def signed_link(path):
    """Short-lived download URL for a file in the private bucket."""
    try:
        signed = sb().storage.from_("drawings").create_signed_url(path, 3600)
        return signed.get("signedURL") or signed.get("signed_url")
    except Exception:
        return None


def upload_bid_files(itb_id, bid_id, files):
    """Store a sub's bid documents and record them against the bid."""
    for f in files or []:
        path = f"bids/{itb_id}/{bid_id}/{int(time.time())}_{f.name}"
        mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        sb().storage.from_("drawings").upload(path, f.getvalue(),
                                              {"content-type": mime})
        sb().table("bid_files").insert({
            "bid_id": bid_id, "path": path, "filename": f.name,
        }).execute()


# ─────────────────────────────────────────────────────────────────────
#  VERIFICATION HELPERS
# ─────────────────────────────────────────────────────────────────────
_NAME_NOISE = {"inc", "incorporated", "llc", "corp", "corporation", "co",
               "company", "ltd", "the", "and", "&", "of", "a", "dba",
               "general", "contractor", "contractors", "contracting"}


def _name_tokens(name):
    name = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return {t for t in name.split() if t and t not in _NAME_NOISE}


def name_match(profile_company, cslb_business):
    """True when the profile company plausibly matches the CSLB record.
    Deliberately conservative — anything fuzzy goes to manual review."""
    a, b = _name_tokens(profile_company), _name_tokens(cslb_business)
    if not a or not b:
        return False
    overlap = a & b
    return len(overlap) / min(len(a), len(b)) >= 0.6


def is_verified(profile):
    return profile.get("verification_status") == "verified"


def verified_badge(profile_or_status):
    status = (profile_or_status.get("verification_status")
              if isinstance(profile_or_status, dict) else profile_or_status)
    if status == "verified":
        return (' <span class="f-mono" style="color:#3E7A4E;font-size:11px">'
                '✓ VERIFIED</span>')
    return ""


def verification_banner(profile):
    """Nudge shown on home screens until the account is verified."""
    vs = profile.get("verification_status", "unverified")
    if vs == "verified":
        return
    if vs == "pending":
        st.info("⏳ **Verification pending review.** You'll be unlocked once "
                "your license check is approved — usually same day.")
    else:
        action = ("appear on bid lists" if profile["role"] == "sub"
                  else "send bid requests")
        st.warning(f"⚠️ **Get verified to {action}.** Open **Get Verified** in "
                   f"the sidebar — takes about a minute with your CSLB license "
                   f"number.")


def apply_verification(result, license_no, profile):
    """Hybrid decision: clean active-license + name match -> verified;
    anything else that looked like a real license -> pending review."""
    update = {
        "license_no": license_no,
        "cslb_status": result.get("status"),
        "cslb_expires": result.get("expires"),
        "cslb_business": result.get("business"),
    }
    if (result.get("active") and result.get("business")
            and name_match(profile["company"], result["business"])):
        update["verification_status"] = "verified"
        update["verified_at"] = datetime.now(timezone.utc).isoformat()
    else:
        update["verification_status"] = "pending"
    sb().table("profiles").update(update).eq(
        "id", st.session_state.user_id).execute()
    st.session_state.profile = {**profile, **update}
    return update["verification_status"]


# ─────────────────────────────────────────────────────────────────────
#  SCREEN: GET VERIFIED
# ─────────────────────────────────────────────────────────────────────
def screen_verify(profile):
    heading("GET VERIFIED")
    vs = profile.get("verification_status", "unverified")

    if vs == "verified":
        st.success(f"✓ Verified"
                   + (f" — license {profile.get('license_no')}" if profile.get("license_no") else ""))
        st.markdown(
            f'<div class="card">'
            f'<div class="eyebrow">CSLB RECORD</div>'
            f'<div style="color:{C["ink"]}">'
            f'{profile.get("cslb_business") or profile.get("company")}<br>'
            f'Status: {profile.get("cslb_status") or "—"}<br>'
            f'Expires: {profile.get("cslb_expires") or "—"}</div></div>',
            unsafe_allow_html=True)
        return

    if vs == "pending":
        st.info("⏳ Your verification is pending manual review. You'll be "
                "unlocked once it's approved. If your license or company "
                "details were wrong, you can rerun the check below.")

    st.markdown(
        f'<div style="color:{C["inkSoft"]};margin-bottom:8px">'
        f'SLATE verifies every contractor against the California CSLB before '
        f'they can {"appear on bid lists" if profile["role"] == "sub" else "send bid requests"}. '
        f'Enter your license number — we check that it\'s current and active '
        f'and that it matches your company name '
        f'(<b>{profile["company"]}</b>).</div>', unsafe_allow_html=True)

    lic = st.text_input("CSLB license #", value=profile.get("license_no") or "")
    if st.button("Run verification"):
        if not lic.strip():
            st.error("Enter your CSLB license number.")
            return
        with st.spinner("Checking CSLB…"):
            result = check_license(lic.strip())
        if not result.get("ok"):
            st.warning(f"The automated lookup didn't go through "
                       f"({result.get('error', 'lookup failed')}). "
                       f"You can [check your license manually]({result['url']}) "
                       f"and submit for review below.")
            if st.button("Submit for manual review"):
                sb().table("profiles").update({
                    "license_no": lic.strip(),
                    "verification_status": "pending",
                }).eq("id", st.session_state.user_id).execute()
                st.session_state.profile = {**profile, "license_no": lic.strip(),
                                            "verification_status": "pending"}
                st.rerun()
            return
        outcome = apply_verification(result, lic.strip(), profile)
        if outcome == "verified":
            st.success("✓ Verified! Your license is current and active and "
                       "matches your company. You're unlocked.")
            time.sleep(1.5)
            st.rerun()
        else:
            st.info(f"License found — status: **{result.get('status')}**"
                    + (f", business name on record: **{result.get('business')}**"
                       if result.get("business") else "")
                    + ". It didn't auto-match cleanly, so it's been queued for "
                    "manual review. You'll be unlocked once approved.")


# ─────────────────────────────────────────────────────────────────────
#  GC SCREEN: NEW BID REQUEST  (create ITB -> upload files -> invite -> email)
# ─────────────────────────────────────────────────────────────────────
def screen_new_itb(profile):
    heading("NEW BID REQUEST")

    if not is_verified(profile):
        verification_banner(profile)
        return

    subs = (sb().table("profiles")
            .select("id, company, trade, region, email")
            .eq("role", "sub")
            .eq("verification_status", "verified").execute().data)

    vis_label = st.radio(
        "Who can see this?",
        ["Invite specific subs only", "Post publicly on the RFP board",
         "Both — post publicly AND invite specific subs"],
        help="Public RFPs are browsable by all subs. Subs you don't invite "
             "directly must request permission to bid; you approve or reject "
             "them from Bid Requests. Attachments unlock only for approved/"
             "invited subs.")
    visibility = {"Invite specific subs only": "invite",
                  "Post publicly on the RFP board": "public",
                  "Both — post publicly AND invite specific subs": "both"}[vis_label]

    project = st.text_input("Project", placeholder="Lariat Ln Residence — 3,750 SF New Build")
    trade = st.text_input("Trade package", placeholder="Framing Package")
    scope = st.text_area("Scope of work")
    location = st.text_input("Location", placeholder="San Jose, CA (East Foothills)")
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("Expected start")
    end = c2.date_input("Expected end")
    due = c3.date_input("Bids due")
    budget_note = st.text_input("Budget note (optional, shown publicly)",
                                placeholder="e.g. Budget range available on request")
    files = st.file_uploader("Drawings / specs / schedule (PDF, DOCX)",
                             accept_multiple_files=True)

    picked = []
    if visibility in ("invite", "both"):
        st.markdown('<div class="eyebrow" style="margin-top:8px">SELECT SUBS '
                    'TO INVITE DIRECTLY</div>', unsafe_allow_html=True)
        if not subs:
            st.info("No verified subs to invite yet — they appear here once "
                    "they complete CSLB verification.")
        for s in subs:
            label = f"{s['company']} — {s.get('trade') or 'trade not set'} · {s.get('region') or ''}"
            if st.checkbox(label, key=f"sub_{s['id']}"):
                picked.append(s)

    if st.button("Post Bid Request"):
        if not (project.strip() and trade.strip()):
            st.error("Project and trade package are required.")
            return
        if visibility == "invite" and not picked:
            st.error("Invite-only bid requests need at least one sub selected "
                     "— or switch to a public posting.")
            return

        with st.spinner("Creating bid request…"):
            # 1. the ITB/RFP row
            itb = (sb().table("itbs").insert({
                "gc_id": st.session_state.user_id,
                "project": project.strip(),
                "trade": trade.strip(),
                "scope": scope.strip() or None,
                "due_date": due.isoformat(),
                "visibility": visibility,
                "location": location.strip() or None,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "budget_note": budget_note.strip() or None,
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

            # 3. direct invites + emails
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

        bits = []
        if visibility in ("public", "both"):
            bits.append("posted to the public RFP board")
        if picked:
            bits.append(f"sent to {len(picked)} invited sub(s), "
                        f"{emailed} email(s) delivered")
        st.success("Bid request " + " and ".join(bits) + "."
                   + (f" Email failures: {failed} — invites still show in "
                      f"their SLATE inbox." if failed else ""))


# ─────────────────────────────────────────────────────────────────────
#  GC SCREEN: DASHBOARD  (my ITBs + responses side by side)
# ─────────────────────────────────────────────────────────────────────
def screen_gc_dashboard(profile):
    heading("DASHBOARD")
    verification_banner(profile)
    itbs = (sb().table("itbs").select("*")
            .eq("gc_id", st.session_state.user_id)
            .order("created_at", desc=True).execute().data)
    if not itbs:
        st.info("No bid requests yet — create your first one from **New Bid Request**.")
        return

    for itb in itbs:
        invites = (sb().table("itb_invites").select("id, sub_id, status")
                   .eq("itb_id", itb["id"]).execute().data)
        bids = (sb().table("bids").select("*")
                .eq("itb_id", itb["id"]).execute().data)
        pending_reqs = (sb().table("bid_requests").select("id")
                        .eq("itb_id", itb["id"])
                        .eq("status", "requested").execute().data)
        latest = latest_bids_by_sub(bids)
        responded = sum(1 for v in invites if v["status"] in ("responded", "awarded"))
        awarded = next((v for v in invites if v["status"] == "awarded"), None)
        title_flag = " · 🏆 AWARDED" if awarded else ""
        if pending_reqs:
            title_flag += f" · 🔔 {len(pending_reqs)} bid request(s) pending"

        with st.expander(f"ITB-{itb['id']:04d} · {itb['project']} — {itb['trade']} "
                         f"({responded}/{len(invites)} responded, "
                         f"due {itb['due_date']}){title_flag}"):
            if itb.get("scope"):
                st.markdown(f'<div class="eyebrow">SCOPE</div>'
                            f'<div style="color:{C["ink"]}">{itb["scope"]}</div>',
                            unsafe_allow_html=True)
            if not latest:
                st.markdown(f'<div style="color:{C["inkSoft"]}">No bids yet.</div>',
                            unsafe_allow_html=True)
                continue

            # names + any bid documents, fetched once per ITB
            names = {p["id"]: p["company"] for p in
                     sb().table("profiles").select("id, company")
                     .in_("id", list(latest.keys())).execute().data}
            bid_ids = [b["id"] for b in latest.values()]
            files_by_bid = {}
            for f in (sb().table("bid_files").select("bid_id, path, filename")
                      .in_("bid_id", bid_ids).execute().data):
                files_by_bid.setdefault(f["bid_id"], []).append(f)

            ranked = sorted(latest.values(), key=lambda b: b["amount"])
            low = ranked[0]["amount"]
            for b in ranked:
                sub_name = names.get(b["sub_id"], "Sub")
                invite = next((v for v in invites if v["sub_id"] == b["sub_id"]), None)
                tags = ""
                if b["amount"] == low and len(ranked) > 1:
                    tags += (' <span class="f-mono" style="color:#3E7A4E;'
                             'font-size:11px">LOW BID</span>')
                if b["revision"] > 1:
                    tags += (f' <span class="f-mono" style="color:#2E5E8C;'
                             f'font-size:11px">REV {b["revision"]}</span>')
                if invite and invite["status"] == "awarded":
                    tags += (' <span class="f-mono" style="color:#1D7A44;'
                             'font-size:11px">🏆 AWARDED</span>')
                elif invite and invite["status"] == "not_selected":
                    tags += (' <span class="f-mono" style="color:#3D4E63;'
                             'font-size:11px">NOT SELECTED</span>')

                st.markdown(
                    f'<div class="card"><b>{sub_name}</b> — '
                    f'<span class="f-disp" style="font-size:20px;font-weight:600">'
                    f'${b["amount"]:,.0f}</span>{tags}'
                    f'<div style="color:{C["inkSoft"]};font-size:14px">'
                    f'{b.get("note") or ""}</div></div>',
                    unsafe_allow_html=True)

                for f in files_by_bid.get(b["id"], []):
                    url = signed_link(f["path"])
                    st.markdown(f"- 📎 [{f['filename']}]({url})" if url
                                else f"- 📎 {f['filename']} (link unavailable)")

                if not awarded and invite:
                    if st.button(f"Award to {sub_name}",
                                 key=f"award_{itb['id']}_{b['sub_id']}"):
                        for v in invites:
                            if v["sub_id"] == b["sub_id"]:
                                new_status = "awarded"
                            elif v["status"] in ("sent", "responded"):
                                new_status = "not_selected"
                            else:
                                new_status = v["status"]
                            sb().table("itb_invites").update(
                                {"status": new_status}).eq("id", v["id"]).execute()
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  SUB SCREEN: INBOX  (my invites -> download drawings -> respond)
# ─────────────────────────────────────────────────────────────────────
def screen_sub_inbox(profile):
    heading("BID INVITES")
    verification_banner(profile)
    invites = (sb().table("itb_invites").select("*")
               .eq("sub_id", st.session_state.user_id)
               .order("created_at", desc=True).execute().data)
    if not invites:
        st.info("No bid invites yet. When a GC sends you one, it lands here "
                "and in your email.")
        return

    BADGES = {"sent": "🟠 AWAITING YOUR BID", "responded": "✅ RESPONDED",
              "awarded": "🏆 AWARDED TO YOU", "not_selected": "◻️ NOT SELECTED",
              "declined": "❌ DECLINED"}

    for v in invites:
        itb = (sb().table("itbs").select("*").eq("id", v["itb_id"]).execute().data)
        if not itb:
            continue
        itb = itb[0]
        gc = (sb().table("profiles").select("company")
              .eq("id", itb["gc_id"]).execute().data)
        gc_name = gc[0]["company"] if gc else "GC"
        badge = BADGES.get(v["status"], v["status"])

        with st.expander(f"{badge} · {itb['project']} — {itb['trade']} "
                         f"(from {gc_name}, due {itb['due_date']})"):
            if v["status"] == "awarded":
                st.success("You were awarded this scope. The GC will follow up "
                           "on contract next steps.")
            elif v["status"] == "not_selected":
                st.markdown(f'<div style="color:{C["inkSoft"]}">This scope went '
                            f'to another sub. Thanks for bidding — your response '
                            f'record still counts.</div>', unsafe_allow_html=True)

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
                    url = signed_link(f["path"])
                    st.markdown(f"- [{f['filename']}]({url})" if url
                                else f"- {f['filename']} (link unavailable)")

            # my current bid (latest revision), if any
            mine = (sb().table("bids").select("*")
                    .eq("itb_id", itb["id"])
                    .eq("sub_id", st.session_state.user_id).execute().data)
            current = max(mine, key=lambda b: b["revision"]) if mine else None
            if current:
                rev_tag = (f' <span class="f-mono" style="color:#2E5E8C;'
                           f'font-size:11px">REV {current["revision"]}</span>'
                           if current["revision"] > 1 else "")
                st.markdown(
                    f'<div class="card"><div class="eyebrow">YOUR CURRENT BID</div>'
                    f'<span class="f-disp" style="font-size:20px;font-weight:600">'
                    f'${current["amount"]:,.0f}</span>{rev_tag}'
                    f'<div style="color:{C["inkSoft"]};font-size:14px">'
                    f'{current.get("note") or ""}</div></div>',
                    unsafe_allow_html=True)
                cur_files = (sb().table("bid_files").select("path, filename")
                             .eq("bid_id", current["id"]).execute().data)
                for f in cur_files:
                    url = signed_link(f["path"])
                    st.markdown(f"- 📎 [{f['filename']}]({url})" if url
                                else f"- 📎 {f['filename']} (link unavailable)")

            # bid / revise — open until the GC makes an award decision
            if v["status"] in ("sent", "responded"):
                st.markdown(f'<div class="eyebrow" style="margin-top:8px">'
                            f'{"REVISE YOUR BID" if current else "SUBMIT YOUR BID"}'
                            f'</div>', unsafe_allow_html=True)
                amount = st.number_input("Bid amount ($)", min_value=0.0,
                                         step=1000.0, key=f"amt_{v['id']}")
                note = st.text_area("Notes (inclusions, exclusions, lead time)",
                                    key=f"note_{v['id']}")
                docs = st.file_uploader(
                    "Attach bid documents (proposal PDF, inclusions list, COI)",
                    accept_multiple_files=True, key=f"docs_{v['id']}")
                label = "Submit revised bid" if current else "Submit bid"
                if st.button(label, key=f"send_{v['id']}"):
                    if amount <= 0:
                        st.error("Enter a bid amount.")
                    else:
                        new_rev = (current["revision"] + 1) if current else 1
                        bid = (sb().table("bids").insert({
                            "itb_id": itb["id"],
                            "sub_id": st.session_state.user_id,
                            "amount": amount,
                            "note": note.strip() or None,
                            "revision": new_rev,
                        }).execute().data)[0]
                        upload_bid_files(itb["id"], bid["id"], docs)
                        sb().table("itb_invites").update(
                            {"status": "responded"}).eq("id", v["id"]).execute()
                        st.success(f"Bid submitted (revision {new_rev}).")
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  SHARED SCREEN: SUB NETWORK (GC view of registered subs)
# ─────────────────────────────────────────────────────────────────────
def screen_network():
    heading("SUB NETWORK")
    subs = (sb().table("profiles")
            .select("id, company, trade, region, license_no, verification_status")
            .eq("role", "sub").order("company").execute().data)
    if not subs:
        st.info("No subs registered yet.")
        return
    for s in subs:
        badge = verified_badge(s)
        extra = ("" if s.get("verification_status") == "verified" else
                 f' <span class="f-mono" style="color:{C["inkSoft"]};'
                 f'font-size:11px">NOT YET VERIFIED — can\'t be invited</span>')
        st.markdown(
            f'<div class="card"><b>{s["company"]}</b>{badge}{extra}'
            f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
            f'{s.get("trade") or "trade not set"} · {s.get("region") or ""} · '
            f'CSLB {s.get("license_no") or "—"}</div></div>',
            unsafe_allow_html=True)
        if st.button("View profile", key=f"netprof_{s['id']}"):
            st.session_state.view_profile = s["id"]
            st.rerun()
        if s.get("license_no"):
            if st.button(f"Verify CSLB #{s['license_no']}", key=f"cslb_{s['id']}"):
                with st.spinner("Checking CSLB…"):
                    res = check_license(s["license_no"])
                if res.get("ok") and res.get("active"):
                    exp = f" · expires {res['expires']}" if res.get("expires") else ""
                    st.success(f"License is {res['status']}{exp}. "
                               f"[View on CSLB]({res['url']})")
                elif res.get("ok"):
                    st.warning(f"License status: {res['status']}. "
                               f"[View on CSLB]({res['url']})")
                else:
                    st.warning(f"Couldn't verify automatically "
                               f"({res.get('error', 'lookup failed')}). "
                               f"[Check manually on CSLB]({res['url']})")


# ─────────────────────────────────────────────────────────────────────
#  SUB SCREEN: RFP BOARD  (browse public postings -> request to bid)
# ─────────────────────────────────────────────────────────────────────
def screen_rfp_board(profile):
    heading("RFP BOARD")
    st.markdown(f'<div style="color:{C["inkSoft"]};margin-bottom:8px">Open '
                f'bid requests posted publicly by verified GCs. Request '
                f'permission to bid — once the GC approves, the RFP lands in '
                f'your Bid Invites with drawings unlocked.</div>',
                unsafe_allow_html=True)

    rfps = (sb().table("itbs").select("*")
            .in_("visibility", ["public", "both"])
            .order("created_at", desc=True).execute().data)
    if not rfps:
        st.info("No public RFPs posted yet — check back soon.")
        return

    # my existing invites + requests, to label each card correctly
    my_invites = {v["itb_id"] for v in
                  sb().table("itb_invites").select("itb_id")
                  .eq("sub_id", st.session_state.user_id).execute().data}
    my_requests = {r["itb_id"]: r for r in
                   sb().table("bid_requests").select("itb_id, status")
                   .eq("sub_id", st.session_state.user_id).execute().data}
    gc_names = {p["id"]: p["company"] for p in
                sb().table("profiles").select("id, company")
                .in_("id", list({r["gc_id"] for r in rfps})).execute().data}

    for r in rfps:
        gc_name = gc_names.get(r["gc_id"], "GC")
        with st.expander(f"{r['project']} — {r['trade']} · {gc_name} "
                         f"(bids due {r['due_date']})"):
            meta = (f'📍 {r.get("location") or "location TBD"} · '
                    f'🗓 {r.get("start_date") or "TBD"} → {r.get("end_date") or "TBD"}')
            if r.get("budget_note"):
                meta += f' · 💲 {r["budget_note"]}'
            st.markdown(
                f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
                f'{meta}</div>', unsafe_allow_html=True)
            if r.get("scope"):
                st.markdown(f'<div class="eyebrow" style="margin-top:6px">SCOPE'
                            f'</div><div style="color:{C["ink"]}">{r["scope"]}'
                            f'</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="f-mono" style="font-size:11px;'
                        f'color:{C["inkSoft"]};margin-top:6px">Drawings & specs '
                        f'unlock once you\'re approved to bid.</div>',
                        unsafe_allow_html=True)
            if st.button(f"View {gc_name}'s profile", key=f"gcprof_{r['id']}"):
                st.session_state.view_profile = r["gc_id"]
                st.rerun()

            # this sub's standing on this RFP
            if r["id"] in my_invites:
                st.success("You're on this bid list — see **Bid Invites** to respond.")
            elif r["id"] in my_requests:
                rq = my_requests[r["id"]]
                if rq["status"] == "requested":
                    st.info("⏳ Bid request sent — waiting on the GC.")
                elif rq["status"] == "approved":
                    st.success("Approved — see **Bid Invites** to respond.")
                else:
                    st.markdown(f'<div style="color:{C["inkSoft"]}">The GC '
                                f'didn\'t approve your request on this one. '
                                f'Your record isn\'t affected.</div>',
                                unsafe_allow_html=True)
            elif not is_verified(profile):
                st.warning("Get verified to request permission to bid — open "
                           "**Get Verified** in the sidebar.")
            else:
                msg = st.text_input("Message to the GC (optional — e.g. crew "
                                    "availability, relevant experience)",
                                    key=f"reqmsg_{r['id']}")
                if st.button("Request to Bid", key=f"req_{r['id']}"):
                    sb().table("bid_requests").insert({
                        "itb_id": r["id"],
                        "sub_id": st.session_state.user_id,
                        "message": msg.strip() or None,
                    }).execute()
                    st.success("Request sent — the GC will approve or decline.")
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  GC SCREEN: BID REQUESTS  (approve/reject subs asking to bid)
# ─────────────────────────────────────────────────────────────────────
def screen_gc_requests(profile):
    heading("BID REQUESTS")
    my_itbs = {i["id"]: i for i in
               sb().table("itbs").select("id, project, trade, due_date")
               .eq("gc_id", st.session_state.user_id).execute().data}
    if not my_itbs:
        st.info("No bid requests yet — they arrive when subs ask to bid on "
                "your public RFPs.")
        return
    reqs = (sb().table("bid_requests").select("*")
            .in_("itb_id", list(my_itbs.keys()))
            .order("created_at", desc=True).execute().data)
    if not reqs:
        st.info("No sub requests yet on your public RFPs.")
        return

    sub_profiles = {p["id"]: p for p in
                    sb().table("profiles")
                    .select("id, company, trade, region, verification_status")
                    .in_("id", list({r["sub_id"] for r in reqs})).execute().data}

    pending = [r for r in reqs if r["status"] == "requested"]
    decided = [r for r in reqs if r["status"] != "requested"]

    for group, title in ((pending, "AWAITING YOUR DECISION"),
                         (decided, "DECIDED")):
        if not group:
            continue
        st.markdown(f'<div class="eyebrow" style="margin-top:8px">{title}</div>',
                    unsafe_allow_html=True)
        for rq in group:
            itb = my_itbs[rq["itb_id"]]
            s = sub_profiles.get(rq["sub_id"], {})
            st.markdown(
                f'<div class="card"><b>{s.get("company","Sub")}</b>'
                f'{verified_badge(s)}'
                f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
                f'{s.get("trade") or ""} · {s.get("region") or ""} — wants to bid '
                f'on <b>{itb["project"]} / {itb["trade"]}</b></div>'
                + (f'<div style="color:{C["ink"]};font-size:14px;margin-top:4px">'
                   f'"{rq["message"]}"</div>' if rq.get("message") else "")
                + (f'<div class="f-mono" style="font-size:11px;'
                   f'color:{C["inkSoft"]};margin-top:4px">STATUS: '
                   f'{rq["status"].upper()}</div>' if rq["status"] != "requested" else "")
                + '</div>', unsafe_allow_html=True)
            b1, b2, b3 = st.columns([1, 1, 2])
            if b1.button("View profile", key=f"vp_{rq['id']}"):
                st.session_state.view_profile = rq["sub_id"]
                st.rerun()
            if rq["status"] == "requested":
                if b2.button("Approve", key=f"ok_{rq['id']}"):
                    existing = (sb().table("itb_invites").select("id")
                                .eq("itb_id", rq["itb_id"])
                                .eq("sub_id", rq["sub_id"]).execute().data)
                    if not existing:
                        sb().table("itb_invites").insert({
                            "itb_id": rq["itb_id"], "sub_id": rq["sub_id"],
                        }).execute()
                    sb().table("bid_requests").update(
                        {"status": "approved"}).eq("id", rq["id"]).execute()
                    sub_email = (sb().table("profiles").select("email")
                                 .eq("id", rq["sub_id"]).execute().data)
                    if sub_email:
                        app_url = st.secrets.get("APP_URL",
                                                 "https://share.streamlit.io")
                        send_simple_email(
                            sub_email[0]["email"],
                            f"Approved to bid: {itb['project']}",
                            f"<p><b>{profile['company']}</b> approved your "
                            f"request to bid on <b>{itb['project']} — "
                            f"{itb['trade']}</b> (due {itb['due_date']}).</p>"
                            f"<p><a href='{app_url}'>Log in to SLATE</a> — "
                            f"it's in your Bid Invites with drawings unlocked.</p>")
                    st.rerun()
                if b3.button("Reject", key=f"no_{rq['id']}"):
                    sb().table("bid_requests").update(
                        {"status": "rejected"}).eq("id", rq["id"]).execute()
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  SCREEN: MY PROFILE  (portfolio editor — GCs and subs)
# ─────────────────────────────────────────────────────────────────────
def _stat_cards(stats):
    """Row of metric cards: list of (label, value) tuples."""
    cols = st.columns(len(stats))
    for col, (label, val) in zip(cols, stats):
        with col:
            col.markdown(
                f'<div class="card"><div class="eyebrow">{label}</div>'
                f'<div class="metric-val" style="color:{C["ink"]}">{val}</div>'
                f'</div>', unsafe_allow_html=True)


def _week_window():
    today = date.today()
    return today, today + timedelta(days=7)


def screen_my_profile(profile):
    # Personal greeting — first name if we have it, company otherwise
    who = ((profile.get("contact_name") or "").strip().split()[0]
           if (profile.get("contact_name") or "").strip()
           else profile["company"])
    st.markdown(f'<div class="eyebrow">WELCOME BACK</div>'
                f'<div class="f-disp" style="font-size:30px;font-weight:700;'
                f'color:{C["ink"]};margin-bottom:6px">{who}, let\'s jump '
                f'back in.</div>', unsafe_allow_html=True)
    verification_banner(profile)

    # one-time nudge for accounts created before names were collected
    if not (profile.get("contact_name") or "").strip():
        with st.expander("Add your name for a personal touch"):
            nm = st.text_input("Your name", key="add_contact_name")
            if st.button("Save name"):
                if nm.strip():
                    sb().table("profiles").update(
                        {"contact_name": nm.strip()}).eq(
                        "id", st.session_state.user_id).execute()
                    st.session_state.profile = {**profile,
                                                "contact_name": nm.strip()}
                    st.rerun()

    # ── Owner-only activity dashboard (never shown on the public view) ─
    uid = st.session_state.user_id
    today, week_out = _week_window()

    if profile["role"] == "gc":
        itbs = (sb().table("itbs").select("id, due_date")
                .eq("gc_id", uid).execute().data)
        itb_ids = [i["id"] for i in itbs]
        invites, requests = [], []
        if itb_ids:
            invites = (sb().table("itb_invites").select("itb_id, status")
                       .in_("itb_id", itb_ids).execute().data)
            requests = (sb().table("bid_requests").select("id, status")
                        .in_("itb_id", itb_ids).execute().data)
        awarded_itbs = {v["itb_id"] for v in invites if v["status"] == "awarded"}
        open_rfps = len([i for i in itbs if i["id"] not in awarded_itbs])
        due_week = len([i for i in itbs
                        if i["id"] not in awarded_itbs and i.get("due_date")
                        and today <= date.fromisoformat(i["due_date"]) <= week_out])
        responses = len([v for v in invites
                         if v["status"] in ("responded", "awarded")])
        pending_reqs = len([r for r in requests if r["status"] == "requested"])
        _stat_cards([("Open RFPs", open_rfps),
                     ("Bids due this week", due_week),
                     ("Responses received", responses),
                     ("Sub requests pending", pending_reqs)])
    else:
        invites = (sb().table("itb_invites").select("itb_id, status")
                   .eq("sub_id", uid).execute().data)
        my_reqs = (sb().table("bid_requests").select("id, status")
                   .eq("sub_id", uid).execute().data)
        active_ids = [v["itb_id"] for v in invites
                      if v["status"] in ("sent", "responded")]
        due_week = 0
        if active_ids:
            active_itbs = (sb().table("itbs").select("id, due_date")
                           .in_("id", active_ids).execute().data)
            due_week = len([i for i in active_itbs if i.get("due_date")
                            and today <= date.fromisoformat(i["due_date"]) <= week_out])
        accepted = len([r for r in my_reqs if r["status"] == "approved"])
        awarded = len([v for v in invites if v["status"] == "awarded"])
        pending = len([v for v in invites if v["status"] == "responded"])
        not_sel = len([v for v in invites if v["status"] == "not_selected"])
        _stat_cards([("Bids due this week", due_week),
                     ("Requests accepted", accepted),
                     ("Awarded", awarded),
                     ("Pending decision", pending),
                     ("Not selected", not_sel)])

    st.markdown(f'<div class="f-mono" style="font-size:10px;'
                f'color:{C["inkSoft"]};margin-bottom:10px">Activity summary is '
                f'private to you — other contractors only see your portfolio '
                f'below.</div>', unsafe_allow_html=True)

    st.markdown(
        f'<div class="card"><b>{profile["company"]}</b>{verified_badge(profile)}'
        f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
        f'{"GC" if profile["role"] == "gc" else profile.get("trade") or "Sub"} · '
        f'{profile.get("region") or ""} · CSLB {profile.get("license_no") or "—"}'
        f'</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div style="color:{C["inkSoft"]};margin-bottom:6px">Your '
                f'portfolio is your evidence of excellence — every GC and sub '
                f'on SLATE can see it. Add current and completed projects with '
                f'photos.</div>', unsafe_allow_html=True)

    with st.expander("➕ Add a project"):
        title = st.text_input("Project title", key="np_title")
        pstatus = st.radio("Status", ["Current", "Completed"], horizontal=True,
                           key="np_status")
        c1, c2 = st.columns(2)
        ploc = c1.text_input("Location", key="np_loc")
        pyear = c2.text_input("Year", key="np_year",
                              placeholder="2026 or 2024–2025")
        pdesc = st.text_area("Description (scope, size, role)", key="np_desc")
        pphotos = st.file_uploader("Upload photos (JPG/PNG — select several "
                                   "at once)", accept_multiple_files=True,
                                   key="np_photos")
        if st.button("Add project"):
            if not title.strip():
                st.error("Project title is required.")
            else:
                proj = (sb().table("projects").insert({
                    "owner_id": st.session_state.user_id,
                    "title": title.strip(),
                    "status": pstatus.lower(),
                    "location": ploc.strip() or None,
                    "year": pyear.strip() or None,
                    "description": pdesc.strip() or None,
                }).execute().data)[0]
                for ph in pphotos or []:
                    path = (f"portfolio/{st.session_state.user_id}/"
                            f"{proj['id']}/{int(time.time())}_{ph.name}")
                    mime = mimetypes.guess_type(ph.name)[0] or "image/jpeg"
                    sb().storage.from_("drawings").upload(
                        path, ph.getvalue(), {"content-type": mime})
                    sb().table("project_photos").insert({
                        "project_id": proj["id"], "path": path,
                        "caption": None,
                    }).execute()
                st.success(f"Project added"
                           + (f" with {len(pphotos)} photo(s)." if pphotos
                              else "."))
                st.rerun()

    projects = (sb().table("projects").select("*")
                .eq("owner_id", st.session_state.user_id)
                .order("created_at", desc=True).execute().data)
    if not projects:
        st.info("No projects yet — add your first one above.")
        return

    for p in projects:
        with st.expander(f"{'🔨' if p['status'] == 'current' else '✅'} "
                         f"{p['title']} ({p['status']}"
                         f"{', ' + p['year'] if p.get('year') else ''})",
                         expanded=True):
            if p.get("description"):
                st.markdown(f'<div style="color:{C["ink"]}">{p["description"]}'
                            f'</div>', unsafe_allow_html=True)
            photos = (sb().table("project_photos").select("*")
                      .eq("project_id", p["id"]).execute().data)
            if photos:
                cols = st.columns(3)
                for i, ph in enumerate(photos):
                    url = signed_link(ph["path"])
                    if url:
                        cols[i % 3].image(url, caption=ph.get("caption") or "")
                    if cols[i % 3].button("Remove", key=f"delph_{ph['id']}"):
                        sb().table("project_photos").delete().eq(
                            "id", ph["id"]).execute()
                        st.rerun()

            up = st.file_uploader("Add a photo (JPG/PNG)", key=f"up_{p['id']}")
            cap = st.text_input("Photo caption", key=f"cap_{p['id']}",
                                placeholder="e.g. Finished kitchen — custom cabinetry")
            if st.button("Upload photo", key=f"addph_{p['id']}"):
                if up is None:
                    st.error("Choose a photo first.")
                else:
                    path = (f"portfolio/{st.session_state.user_id}/{p['id']}/"
                            f"{int(time.time())}_{up.name}")
                    mime = mimetypes.guess_type(up.name)[0] or "image/jpeg"
                    sb().storage.from_("drawings").upload(
                        path, up.getvalue(), {"content-type": mime})
                    sb().table("project_photos").insert({
                        "project_id": p["id"], "path": path,
                        "caption": cap.strip() or None,
                    }).execute()
                    st.rerun()

            if st.button("Delete this project", key=f"delp_{p['id']}"):
                sb().table("projects").delete().eq("id", p["id"]).execute()
                st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  SCREEN: PUBLIC PROFILE VIEW  (anyone signed-in, via View Profile)
# ─────────────────────────────────────────────────────────────────────
def screen_public_profile(uid):
    rows = (sb().table("profiles")
            .select("id, company, role, trade, region, license_no, "
                    "verification_status, cslb_expires")
            .eq("id", uid).execute().data)
    if not rows:
        st.error("Profile not found.")
        return
    p = rows[0]
    if st.button("← Back"):
        st.session_state.pop("view_profile", None)
        st.rerun()
    heading(p["company"].upper())
    st.markdown(
        f'<div class="card">{verified_badge(p) or "Not yet verified"}'
        f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
        f'{"General Contractor" if p["role"] == "gc" else p.get("trade") or "Subcontractor"} · '
        f'{p.get("region") or ""} · CSLB {p.get("license_no") or "—"}'
        + (f' · expires {p["cslb_expires"]}' if p.get("cslb_expires") else "")
        + '</div></div>', unsafe_allow_html=True)

    projects = (sb().table("projects").select("*").eq("owner_id", uid)
                .order("created_at", desc=True).execute().data)
    if not projects:
        st.info("No portfolio projects posted yet.")
        return
    for status, label in (("current", "CURRENT WORK"),
                          ("completed", "COMPLETED WORK")):
        group = [p2 for p2 in projects if p2["status"] == status]
        if not group:
            continue
        st.markdown(f'<div class="eyebrow" style="margin-top:10px">{label}</div>',
                    unsafe_allow_html=True)
        for pr in group:
            with st.expander(f"{pr['title']}"
                             f"{' · ' + pr['year'] if pr.get('year') else ''}"
                             f"{' · ' + pr['location'] if pr.get('location') else ''}",
                             expanded=True):
                if pr.get("description"):
                    st.markdown(f'<div style="color:{C["ink"]}">'
                                f'{pr["description"]}</div>',
                                unsafe_allow_html=True)
                photos = (sb().table("project_photos").select("path, caption")
                          .eq("project_id", pr["id"]).execute().data)
                cols = st.columns(3)
                for i, ph in enumerate(photos):
                    url = signed_link(ph["path"])
                    if url:
                        cols[i % 3].image(url, caption=ph.get("caption") or "")


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
    st.markdown(logo_html(width=150), unsafe_allow_html=True)
    check = " ✓" if is_verified(profile) else ""
    st.markdown(f'<div class="f-mono" style="font-size:10px;color:#7FA98C;'
                f'margin-top:4px">{profile["company"].upper()} · '
                f'{"GC" if profile["role"] == "gc" else "SUB"}{check}</div>',
                unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    nav_items = (["My Profile", "Dashboard", "New Bid Request",
                  "Bid Requests", "Sub Network", "Get Verified"]
                 if profile["role"] == "gc" else
                 ["My Profile", "Bid Invites", "RFP Board", "Get Verified"])
    if st.session_state.get("page") not in nav_items:
        st.session_state.page = nav_items[0]
    for item in nav_items:
        active = st.session_state.page == item
        if st.button(item, key=f"nav_{item}",
                     type="primary" if active else "secondary"):
            st.session_state.page = item
            st.session_state.pop("view_profile", None)
            st.rerun()
    page = st.session_state.page
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Log out"):
        sign_out()
        st.rerun()

# Viewing someone's profile takes over the page until Back is clicked
if st.session_state.get("view_profile"):
    screen_public_profile(st.session_state.view_profile)
elif page == "Get Verified":
    screen_verify(profile)
elif page == "My Profile":
    screen_my_profile(profile)
elif profile["role"] == "gc":
    if page == "Dashboard":
        screen_gc_dashboard(profile)
    elif page == "New Bid Request":
        screen_new_itb(profile)
    elif page == "Bid Requests":
        screen_gc_requests(profile)
    else:
        screen_network()
else:
    if page == "RFP Board":
        screen_rfp_board(profile)
    else:
        screen_sub_inbox(profile)
