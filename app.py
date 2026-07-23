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
import io
import mimetypes
import os
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests
import streamlit as st
from PIL import Image
from supabase import create_client

try:
    import pillow_heif
    pillow_heif.register_heif_opener()   # lets PIL open iPhone HEIC files
except Exception:
    pass

from cslb import check_license

import streamlit.components.v1 as components

# CSLB contractor classifications (common set — extend anytime)
TRADES = [
    "A - General Engineering", "B - General Building",
    "C-2 Insulation", "C-4 Boiler", "C-5 Framing",
    "C-6 Cabinet & Millwork", "C-7 Low Voltage", "C-8 Concrete",
    "C-9 Drywall", "C-10 Electrical", "C-11 Elevator",
    "C-12 Earthwork & Paving", "C-13 Fencing", "C-15 Flooring & Floor Covering",
    "C-16 Fire Protection", "C-17 Glazing", "C-20 HVAC",
    "C-21 Building Moving & Demolition", "C-23 Ornamental Metal",
    "C-27 Landscaping", "C-28 Lock & Security", "C-29 Masonry",
    "C-33 Painting & Decorating", "C-34 Pipeline", "C-35 Plastering",
    "C-36 Plumbing", "C-38 Refrigeration", "C-39 Roofing",
    "C-42 Sanitation", "C-43 Sheet Metal", "C-45 Signs", "C-46 Solar",
    "C-50 Reinforcing Steel", "C-51 Structural Steel",
    "C-53 Swimming Pool", "C-54 Ceramic & Mosaic Tile",
    "C-57 Well Drilling", "C-60 Welding", "C-61 Limited Specialty",
]

US_STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID",
             "IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS",
             "MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK",
             "OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV",
             "WI","WY"]

DOC_TYPES = ["Certificate of Insurance (COI)",
             "Contractor License Certificate",
             "Workers' Comp Certificate",
             "Business License"]


def photo_to_jpeg(uploaded, max_px=1600):
    """Convert any uploaded photo (including iPhone HEIC) to a
    web-friendly JPEG, resized for fast profile loads.
    Returns (bytes, filename). Falls back to the raw file if
    conversion fails."""
    try:
        img = Image.open(io.BytesIO(uploaded.getvalue()))
        img = img.convert("RGB")
        img.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85, optimize=True)
        base = uploaded.name.rsplit(".", 1)[0]
        return buf.getvalue(), f"{base}.jpg"
    except Exception:
        return uploaded.getvalue(), uploaded.name

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


COOKIE_NAME = "slate_rt"


def _queue_session_cookie(session):
    """Queue the refresh token to be written to the browser on the NEXT
    stable page render. Writing immediately before st.rerun() loses the
    cookie — the rerun cancels the render before the browser gets it."""
    if session and getattr(session, "refresh_token", None):
        st.session_state._pending_rt = session.refresh_token


def flush_cookie_writes():
    """Render any queued cookie writes/deletes. Called once at the top of
    every page run, after any st.rerun() that queued them has completed."""
    rt = st.session_state.pop("_pending_rt", None)
    if rt:
        components.html(
            f"<script>document.cookie='{COOKIE_NAME}={rt}; path=/; "
            f"max-age=2592000; SameSite=Lax';</script>", height=0)
    if st.session_state.pop("_clear_rt", None):
        components.html(
            f"<script>document.cookie='{COOKIE_NAME}=; path=/; "
            f"max-age=0; SameSite=Lax';</script>", height=0)


def try_restore_session():
    """On page load, quietly log back in from the browser cookie.
    Reads via st.context.cookies (native, present on the first run)."""
    if "user_id" in st.session_state:
        return
    try:
        rt = st.context.cookies.get(COOKIE_NAME)
    except Exception:
        return
    if not rt:
        return
    try:
        res = get_client().auth.refresh_session(rt)
        if res and res.session:
            st.session_state.access_token = res.session.access_token
            st.session_state.user_id = res.user.id
            st.session_state.user_email = res.user.email
            _queue_session_cookie(res.session)   # tokens rotate: store new one
    except Exception:
        st.session_state._clear_rt = True        # stale token — clean it up


def sign_in(email, password):
    res = get_client().auth.sign_in_with_password({"email": email, "password": password})
    st.session_state.access_token = res.session.access_token
    st.session_state.user_id = res.user.id
    st.session_state.user_email = res.user.email
    _queue_session_cookie(res.session)


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
    _queue_session_cookie(res.session)


def sign_out():
    st.session_state._clear_rt = True
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    for k in ("access_token", "user_id", "user_email", "profile", "page"):
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


def email_html(title, body_html, cta_label=None, cta_url=None):
    """Consistent branded wrapper for all SLATE notification emails."""
    cta = ""
    if cta_label:
        url = cta_url or st.secrets.get("APP_URL",
                                        "https://slate-bids.streamlit.app")
        cta = (f"<p style='margin-top:18px'><a href='{url}' "
               f"style='background:#1D7A44;color:#fff;padding:12px 22px;"
               f"border-radius:4px;text-decoration:none;font-weight:600'>"
               f"{cta_label}</a></p>")
    return (f"<div style='font-family:Arial,sans-serif;max-width:560px'>"
            f"<div style='background:#0D0F0E;padding:14px 20px;"
            f"border-radius:6px 6px 0 0'><span style='color:#6EE86E;"
            f"font-weight:800;letter-spacing:3px;font-size:18px'>SLATE."
            f"</span></div>"
            f"<div style='border:1px solid #C6CCC4;border-top:none;"
            f"padding:22px 20px;border-radius:0 0 6px 6px'>"
            f"<h2 style='margin:0 0 10px 0;color:#141B17'>{title}</h2>"
            f"<div style='color:#3D4E63;font-size:15px;line-height:1.5'>"
            f"{body_html}</div>{cta}"
            f"<p style='color:#8FA394;font-size:11px;margin-top:22px'>"
            f"SLATE — by contractors, for contractors.</p></div></div>")


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


def handle_password_recovery():
    """Handles the reset link from the Supabase email. Returns True while
    the recovery flow owns the page. Requires the Reset Password email
    template in Supabase to link to:
    {{ .SiteURL }}/?token_hash={{ .TokenHash }}&type=recovery
    (see README)."""
    qp = st.query_params
    if qp.get("type") != "recovery" or not qp.get("token_hash"):
        return False

    if "recovery_verified" not in st.session_state:
        try:
            res = get_client().auth.verify_otp(
                {"token_hash": qp["token_hash"], "type": "recovery"})
            st.session_state.access_token = res.session.access_token
            st.session_state.user_id = res.user.id
            st.session_state.user_email = res.user.email
            st.session_state.recovery_verified = True
        except Exception:
            st.error("This reset link is invalid or has expired — request "
                     "a fresh one from the login page.")
            if st.button("Back to login"):
                st.query_params.clear()
                st.rerun()
            return True

    st.markdown(logo_html(width=190, boxed=True), unsafe_allow_html=True)
    heading("SET A NEW PASSWORD")
    pw1 = st.text_input("New password (8+ characters)", type="password")
    pw2 = st.text_input("Confirm new password", type="password")
    if st.button("Update password"):
        if len(pw1) < 8:
            st.error("Password needs at least 8 characters.")
        elif pw1 != pw2:
            st.error("Passwords don't match.")
        else:
            try:
                get_client().auth.update_user({"password": pw1})
                st.query_params.clear()
                st.session_state.pop("recovery_verified", None)
                st.success("Password updated — you're logged in.")
                time.sleep(1.2)
                st.rerun()
            except Exception as e:
                st.error(f"Couldn't update the password: {e}")
    return True


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
        with st.expander("Forgot your password?"):
            r_email = st.text_input("Account email", key="reset_email")
            if st.button("Send reset link"):
                if not r_email.strip():
                    st.error("Enter your account email.")
                else:
                    try:
                        get_client().auth.reset_password_for_email(
                            r_email.strip(),
                            {"redirect_to": st.secrets.get("APP_URL", "")})
                        st.success("Reset link sent — check your email. "
                                   "The link brings you back here to set a "
                                   "new password.")
                    except Exception:
                        st.success("If that email has an account, a reset "
                                   "link is on its way.")
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
    ROLE_DESC = {
        "General Contractor": ("As a **General Contractor**, you'll POST "
                               "bid requests (RFPs), invite subcontractors, "
                               "and receive & award bids."),
        "Subcontractor": ("As a **Subcontractor**, you'll BROWSE open RFPs, "
                          "request to bid, and SUBMIT bids to general "
                          "contractors."),
    }
    st.info(ROLE_DESC[role])
    role_confirm = st.checkbox(f"Yes, that's me — I'm a {role.lower()}")
    company = st.text_input("Company name")
    trade, license_no, trades_sel, states_sel, cities = None, None, [], [], ""
    if role == "Subcontractor":
        trades_sel = st.multiselect("Trades (CSLB classifications)", TRADES)
        license_no = st.text_input("CSLB license #")
        states_sel = st.multiselect("States you work in", US_STATES,
                                    default=["CA"])
        cities = st.text_input("Cities / areas you serve",
                               placeholder="e.g. San Jose, Santa Clara, Gilroy")
        trade = ", ".join(trades_sel) if trades_sel else None
    region = st.text_input("Region (e.g. South Bay)")
    if st.button("Save profile"):
        if not role_confirm:
            st.error(f"Please confirm the role description above — this "
                     f"determines which tools you get.")
            return
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
            "trades": trades_sel or None,
            "work_states": states_sel or None,
            "work_cities": cities.strip() or None,
            "license_no": (license_no or "").strip() or None,
            "region": region.strip() or None,
        }).execute()
        st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────
#  ACTIVITY TRACKING + BID Q&A HELPERS
# ─────────────────────────────────────────────────────────────────────
def touch_last_seen():
    """Record activity, at most once per 10 minutes per session, so
    Streamlit's constant reruns don't hammer the database."""
    now = time.time()
    if now - st.session_state.get("_ls_ts", 0) > 600:
        try:
            sb().table("profiles").update(
                {"last_seen": datetime.now(timezone.utc).isoformat()}
            ).eq("id", st.session_state.user_id).execute()
        except Exception:
            pass
        st.session_state._ls_ts = now


def activity_label(last_seen):
    """Human-friendly activity signal shown on profiles and cards."""
    if not last_seen:
        return "⚪ New to SLATE"
    try:
        dt = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
    except Exception:
        return ""
    delta = datetime.now(timezone.utc) - dt
    if delta.total_seconds() < 3600:
        return "🟢 Active now"
    if delta.days < 1:
        return "🟢 Active today"
    if delta.days < 7:
        return "🟢 Active this week"
    return f"⚪ Last seen {delta.days}d ago"


def activity_chip(last_seen):
    lbl = activity_label(last_seen)
    return (f' <span class="f-mono" style="font-size:10px;'
            f'color:{C["inkSoft"]}">{lbl}</span>' if lbl else "")


def bid_thread(itb_id, sub_id, msgs, other_name, other_email,
               itb_project, my_company):
    """In-bid Q&A thread between the GC and one sub. Rendered as a
    toggle (not an expander — these sit inside expanders already).
    Replaces the email back-and-forth for pricing questions and
    revision requests."""
    tkey = f"thread_open_{itb_id}_{sub_id}"
    if st.button(f"💬 Bid Q&A ({len(msgs)})", key=f"tgl_{itb_id}_{sub_id}"):
        st.session_state[tkey] = not st.session_state.get(tkey, False)
        st.rerun()
    if not st.session_state.get(tkey):
        return

    for m in msgs:
        mine = m["sender_id"] == st.session_state.user_id
        who = "You" if mine else other_name
        align = "margin-left:14%" if mine else "margin-right:14%"
        bg = "#E3EFE6" if mine else C["white"]
        st.markdown(
            f'<div class="card" style="{align};background:{bg};'
            f'padding:10px 14px;margin-bottom:6px">'
            f'<span class="f-mono" style="font-size:10px;'
            f'color:{C["inkSoft"]}">{who} · '
            f'{str(m["created_at"])[:16].replace("T", " ")}</span>'
            f'<div style="color:{C["ink"]}">{m["message"]}</div></div>',
            unsafe_allow_html=True)

    gen = st.session_state.get("msg_gen", 0)
    txt = st.text_input("Message", key=f"bm_{itb_id}_{sub_id}_{gen}",
                        label_visibility="collapsed",
                        placeholder="Ask a question, request a revision, "
                                    "clarify pricing…")
    if st.button("Send", key=f"bms_{itb_id}_{sub_id}"):
        if not txt.strip():
            st.error("Write a message first.")
        else:
            sb().table("bid_messages").insert({
                "itb_id": itb_id, "sub_id": sub_id,
                "sender_id": st.session_state.user_id,
                "message": txt.strip(),
            }).execute()
            st.session_state.msg_gen = gen + 1
            if other_email:
                app_url = st.secrets.get("APP_URL",
                                         "https://slate-bids.streamlit.app")
                send_simple_email(
                    other_email,
                    f"New bid message: {itb_project}",
                    f"<p><b>{my_company}</b> sent a message on the bid for "
                    f"<b>{itb_project}</b>:</p>"
                    f"<p style='border-left:3px solid #1D7A44;"
                    f"padding-left:10px'>{txt.strip()}</p>"
                    f"<p><a href='{app_url}'>Reply in SLATE</a> — keep the "
                    f"whole conversation with the bid.</p>")
            st.rerun()


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


def switch_role(profile, new_role):
    """Self-serve role correction. Existing data (bids, RFPs,
    portfolio) stays in the database; only the toolset changes."""
    sb().table("profiles").update({"role": new_role}).eq(
        "id", st.session_state.user_id).execute()
    st.session_state.profile = {**profile, "role": new_role}
    st.session_state.pop("page", None)
    st.rerun()


def role_mismatch_check(profile, classes):
    """CSLB cross-check: a 'GC' whose license is only C-class
    specialty work is very likely a subcontractor who mis-clicked."""
    if not classes:
        return
    has_general = any(c in ("A", "B") for c in classes)
    if profile["role"] == "gc" and not has_general:
        st.warning(f"⚠️ Your license shows specialty classification"
                   f"{'s' if len(classes) > 1 else ''} "
                   f"**{', '.join(classes)}** — general contractors "
                   f"typically hold a B (General Building). Did you mean "
                   f"to sign up as a **Subcontractor**?")
        if st.button("Yes — switch my account to Subcontractor",
                     key="fix_role_sub"):
            switch_role(profile, "sub")


def apply_verification(result, license_no, profile):
    """Hybrid decision: clean active-license + name match -> verified;
    anything else that looked like a real license -> pending review."""
    update = {
        "license_no": license_no,
        "cslb_status": result.get("status"),
        "cslb_expires": result.get("expires"),
        "cslb_business": result.get("business"),
        "cslb_classes": ", ".join(result.get("classes") or []) or None,
    }
    if (result.get("active") and result.get("business")
            and name_match(profile["company"], result["business"])):
        update["verification_status"] = "verified"
        update["verified_at"] = datetime.now(timezone.utc).isoformat()
        send_simple_email(
            st.session_state.user_email, "You're verified on SLATE ✓",
            email_html("You're verified!",
                       f"Your CSLB license checked out — "
                       f"<b>{profile['company']}</b> is now fully unlocked "
                       f"on SLATE.", "Open SLATE"))
    else:
        update["verification_status"] = "pending"
    sb().table("profiles").update(update).eq(
        "id", st.session_state.user_id).execute()
    st.session_state.profile = {**profile, **update}
    return update["verification_status"]


def doc_status_summary(uid):
    """Approved-doc badges for public display — names only, never files."""
    docs = (sb().table("verification_docs").select("doc_type, status")
            .eq("user_id", uid).execute().data)
    latest = {}
    for d in docs:
        latest[d["doc_type"]] = d["status"]   # rows come oldest-first; last wins
    approved = [t for t, s in latest.items() if s == "approved"]
    return approved, len(DOC_TYPES)


def render_docs_section(profile):
    """Document verification — shown on Get Verified for both roles."""
    st.markdown('<div class="eyebrow" style="margin-top:14px">'
                'VERIFICATION DOCUMENTS</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="color:{C["inkSoft"]};font-size:14px;'
                f'margin-bottom:6px">Upload your compliance documents. '
                f'SLATE reviews each one; other contractors see only '
                f'completion badges — never the documents themselves. A GC '
                f'gains access to a sub\'s documents only after awarding '
                f'them a scope.</div>', unsafe_allow_html=True)

    docs = (sb().table("verification_docs").select("*")
            .eq("user_id", st.session_state.user_id)
            .order("created_at").execute().data)
    latest = {}
    for d in docs:
        latest[d["doc_type"]] = d

    ICONS = {"approved": "✅", "pending": "⏳", "rejected": "❌"}
    gen = st.session_state.get("doc_gen", 0)
    for i, dt in enumerate(DOC_TYPES):
        cur = latest.get(dt)
        badge = (f'{ICONS[cur["status"]]} {cur["status"].upper()}'
                 if cur else "— not submitted")
        note = (f' · {cur["note"]}' if cur and cur.get("note")
                and cur["status"] == "rejected" else "")
        st.markdown(f'<div class="card"><b>{dt}</b> '
                    f'<span class="f-mono" style="font-size:11px;'
                    f'color:{C["inkSoft"]}">{badge}{note}</span></div>',
                    unsafe_allow_html=True)
        if not cur or cur["status"] == "rejected":
            up = st.file_uploader("Upload (PDF/JPG/PNG)",
                                  key=f"doc_{i}_{gen}",
                                  label_visibility="collapsed")
            if up is not None and st.button(f"Submit {dt.split(' (')[0]}",
                                            key=f"docbtn_{i}"):
                path = (f"{st.session_state.user_id}/"
                        f"{int(time.time())}_{up.name}")
                mime = mimetypes.guess_type(up.name)[0] or "application/pdf"
                sb().storage.from_("docs").upload(
                    path, up.getvalue(), {"content-type": mime})
                sb().table("verification_docs").insert({
                    "user_id": st.session_state.user_id,
                    "doc_type": dt, "path": path, "filename": up.name,
                }).execute()
                st.session_state.doc_gen = gen + 1
                st.rerun()


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
            f'Classifications: {profile.get("cslb_classes") or "—"}<br>'
            f'Expires: {profile.get("cslb_expires") or "—"}</div></div>',
            unsafe_allow_html=True)
        role_mismatch_check(
            profile, [c.strip() for c in
                      (profile.get("cslb_classes") or "").split(",")
                      if c.strip()])
        render_docs_section(profile)
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
            # CSLB's site sometimes blocks automated lookups — queue for
            # manual review automatically so nobody hits a dead end.
            sb().table("profiles").update({
                "license_no": lic.strip(),
                "verification_status": "pending",
            }).eq("id", st.session_state.user_id).execute()
            st.session_state.profile = {**profile,
                                        "license_no": lic.strip(),
                                        "verification_status": "pending"}
            st.info("The automated CSLB lookup couldn't complete, so your "
                    "license has been sent to SLATE for manual review — "
                    "usually same-day. You'll get an email when you're "
                    "approved.")
            time.sleep(2)
            st.rerun()
        outcome = apply_verification(result, lic.strip(), profile)
        role_mismatch_check(st.session_state.profile, result.get("classes"))
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
    render_docs_section(profile)


# ─────────────────────────────────────────────────────────────────────
#  GC SCREEN: NEW BID REQUEST  (create ITB -> upload files -> invite -> email)
# ─────────────────────────────────────────────────────────────────────
def screen_new_itb(profile):
    heading("NEW BID REQUEST")

    if not is_verified(profile):
        verification_banner(profile)
        return

    subs = (sb().table("profiles")
            .select("id, company, trade, region, email, trades, work_states, "
                    "work_cities, notify_bid_activity")
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
    trades_needed = st.multiselect("Trades needed (CSLB classifications — "
                                   "select all that apply)", TRADES)
    trade = ", ".join(trades_needed)
    scope = st.text_area("Scope of work")
    lc1, lc2 = st.columns([1, 2])
    r_state = lc1.selectbox("Work state", US_STATES,
                            index=US_STATES.index("CA"))
    r_city = lc2.text_input("Work city", placeholder="San Jose")
    location = f"{r_city.strip()}, {r_state}" if r_city.strip() else r_state
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
        matched, unspecified = [], []
        for s in subs:
            trade_ok = (not trades_needed
                        or (s.get("trades")
                            and set(trades_needed) & set(s["trades"])))
            state_ok = (not s.get("work_states")
                        or r_state in s["work_states"])
            has_info = bool(s.get("trades")) and bool(s.get("work_states"))
            if trade_ok and state_ok:
                (matched if has_info else unspecified).append(s)
        st.markdown(f'<div class="f-mono" style="font-size:11px;'
                    f'color:{C["inkSoft"]}">Filtered to subs matching the '
                    f'selected trades and working in {r_state}. '
                    f'{len(subs) - len(matched) - len(unspecified)} sub(s) '
                    f'filtered out.</div>', unsafe_allow_html=True)
        if not matched and not unspecified:
            st.info("No verified subs match this trade + location yet.")
        for s in matched:
            label = (f"{s['company']} — "
                     f"{', '.join(s.get('trades') or [])} · "
                     f"{s.get('work_cities') or s.get('region') or ''}")
            if st.checkbox(label, key=f"sub_{s['id']}"):
                picked.append(s)
        if unspecified:
            with st.expander(f"{len(unspecified)} sub(s) with trades/service "
                             f"area not yet specified"):
                for s in unspecified:
                    label = (f"{s['company']} — "
                             f"{s.get('trade') or 'trade not set'} · "
                             f"{s.get('region') or ''}")
                    if st.checkbox(label, key=f"sub_{s['id']}"):
                        picked.append(s)

    if st.button("Post Bid Request"):
        if not (project.strip() and trades_needed):
            st.error("Project and at least one trade are required.")
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
                "state": r_state,
                "city": r_city.strip() or None,
                "trades": trades_needed,
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

        notified = 0
        if visibility in ("public", "both"):
            for sm in subs:
                trade_ok = (not trades_needed
                            or (sm.get("trades")
                                and set(trades_needed) & set(sm["trades"])))
                state_ok = (sm.get("work_states")
                            and r_state in sm["work_states"])
                already = any(p2["id"] == sm["id"] for p2 in picked)
                if (trade_ok and state_ok and not already
                        and sm.get("email")
                        and sm.get("notify_bid_activity") is not False):
                    ok = send_simple_email(
                        sm["email"],
                        f"New RFP in your area: {project.strip()}",
                        email_html(
                            "New work on the board",
                            f"<b>{profile['company']}</b> posted "
                            f"<b>{project.strip()} — {trade}</b> in "
                            f"{location}. It matches your trades and "
                            f"service area — request to bid before "
                            f"{due.isoformat()}.", "View the RFP"))
                    notified += ok

        bits = []
        if visibility in ("public", "both"):
            bits.append(f"posted to the public RFP board "
                        f"({notified} matching subs notified)")
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
        st.markdown(f'<div class="f-mono" style="font-size:11px;'
                    f'color:{C["inkSoft"]}">Looking to BID ON work instead '
                    f'of posting it? You may have picked the wrong role at '
                    f'signup.</div>', unsafe_allow_html=True)
        if st.button("I'm actually a Subcontractor — switch my role",
                     key="dash_role_fix"):
            switch_role(profile, "sub")
        return

    # ── money + activity summary across all my RFPs ──
    itb_ids = [i["id"] for i in itbs]
    all_bids = (sb().table("bids").select("itb_id, sub_id, amount, revision")
                .in_("itb_id", itb_ids).execute().data)
    all_invites = (sb().table("itb_invites").select("itb_id, sub_id, status")
                   .in_("itb_id", itb_ids).execute().data)
    awarded_by_itb = {v["itb_id"]: v["sub_id"] for v in all_invites
                      if v["status"] == "awarded"}
    latest = {}
    for b in all_bids:
        k = (b["itb_id"], b["sub_id"])
        if k not in latest or b["revision"] > latest[k]["revision"]:
            latest[k] = b
    awarded_total = sum(b["amount"] for (t, s), b in latest.items()
                        if awarded_by_itb.get(t) == s)
    under_review = sum(b["amount"] for (t, s), b in latest.items()
                       if t not in awarded_by_itb)
    bids_received = len(latest)
    awaiting_subs = sum(1 for v in all_invites if v["status"] == "sent")
    _stat_cards([("Awarded", f"${awarded_total:,.0f}"),
                 ("Bids under review", f"${under_review:,.0f}"),
                 ("Bids received", bids_received),
                 ("Awaiting sub response", awaiting_subs)])

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
            subs_info = {p["id"]: p for p in
                         sb().table("profiles")
                         .select("id, company, email, last_seen, "
                                 "notify_messages, notify_bid_activity")
                         .in_("id", list(latest.keys())).execute().data}
            names = {k: v["company"] for k, v in subs_info.items()}
            all_msgs = (sb().table("bid_messages").select("*")
                        .eq("itb_id", itb["id"])
                        .order("created_at").execute().data)
            msgs_by_sub = {}
            for m in all_msgs:
                msgs_by_sub.setdefault(m["sub_id"], []).append(m)
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
                    f'<div class="card"><b>{sub_name}</b>'
                    f'{activity_chip(subs_info.get(b["sub_id"], {}).get("last_seen"))} — '
                    f'<span class="f-disp" style="font-size:20px;font-weight:600">'
                    f'${b["amount"]:,.0f}</span>{tags}'
                    f'<div style="color:{C["inkSoft"]};font-size:14px">'
                    f'{b.get("note") or ""}</div></div>',
                    unsafe_allow_html=True)

                for f in files_by_bid.get(b["id"], []):
                    url = signed_link(f["path"])
                    st.markdown(f"- 📎 [{f['filename']}]({url})" if url
                                else f"- 📎 {f['filename']} (link unavailable)")

                _si = subs_info.get(b["sub_id"], {})
                bid_thread(itb["id"], b["sub_id"],
                           msgs_by_sub.get(b["sub_id"], []),
                           sub_name,
                           (_si.get("email")
                            if _si.get("notify_messages") is not False
                            else None),
                           itb["project"], profile["company"])

                if invite and invite["status"] == "awarded":
                    vdocs = (sb().table("verification_docs")
                             .select("doc_type, path, filename")
                             .eq("user_id", b["sub_id"])
                             .eq("status", "approved").execute().data)
                    if vdocs:
                        st.markdown('<div class="eyebrow">VERIFIED DOCUMENTS '
                                    '(unlocked by award)</div>',
                                    unsafe_allow_html=True)
                        for vd in vdocs:
                            try:
                                sg = sb().storage.from_("docs").create_signed_url(
                                    vd["path"], 3600)
                                u = sg.get("signedURL") or sg.get("signed_url")
                                st.markdown(f"- 🔓 [{vd['doc_type']} — "
                                            f"{vd['filename']}]({u})")
                            except Exception:
                                st.markdown(f"- 🔓 {vd['doc_type']} — "
                                            f"{vd['filename']} (link unavailable)")
                if not awarded and invite:
                    if st.button(f"Award to {sub_name}",
                                 key=f"award_{itb['id']}_{b['sub_id']}"):
                        all_invited = {p["id"]: p for p in
                                       sb().table("profiles")
                                       .select("id, company, email, "
                                               "notify_bid_activity")
                                       .in_("id", [v["sub_id"]
                                                   for v in invites])
                                       .execute().data}
                        for v in invites:
                            if v["sub_id"] == b["sub_id"]:
                                new_status = "awarded"
                            elif v["status"] in ("sent", "responded"):
                                new_status = "not_selected"
                            else:
                                new_status = v["status"]
                            sb().table("itb_invites").update(
                                {"status": new_status}).eq("id", v["id"]).execute()
                            inv_p = all_invited.get(v["sub_id"], {})
                            if (not inv_p.get("email")
                                    or inv_p.get("notify_bid_activity")
                                    is False):
                                continue
                            if new_status == "awarded":
                                send_simple_email(
                                    inv_p["email"],
                                    f"🏆 Awarded: {itb['project']}",
                                    email_html(
                                        "You won the scope!",
                                        f"<b>{profile['company']}</b> awarded "
                                        f"you <b>{itb['project']} — "
                                        f"{itb['trade']}</b>. Your verified "
                                        f"documents are now visible to the "
                                        f"GC, who will follow up on contract "
                                        f"next steps.", "Open SLATE"))
                            elif new_status == "not_selected" and \
                                    v["status"] == "responded":
                                send_simple_email(
                                    inv_p["email"],
                                    f"Bid decision: {itb['project']}",
                                    email_html(
                                        "This one went to another sub",
                                        f"<b>{itb['project']} — "
                                        f"{itb['trade']}</b> was awarded to "
                                        f"another bidder. Thanks for the "
                                        f"number — your response record on "
                                        f"SLATE still counts, and there's "
                                        f"more work on the board.",
                                        "Browse open RFPs"))
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

    # ── money + activity summary ──
    my_bids = (sb().table("bids").select("itb_id, amount, revision")
               .eq("sub_id", st.session_state.user_id).execute().data)
    latest_by_itb = {}
    for b in my_bids:
        cur = latest_by_itb.get(b["itb_id"])
        if cur is None or b["revision"] > cur["revision"]:
            latest_by_itb[b["itb_id"]] = b
    status_by_itb = {v["itb_id"]: v["status"] for v in invites}
    outstanding = sum(b["amount"] for t, b in latest_by_itb.items()
                      if status_by_itb.get(t) == "responded")
    awarded_amt = sum(b["amount"] for t, b in latest_by_itb.items()
                      if status_by_itb.get(t) == "awarded")
    awaiting_you = sum(1 for v in invites if v["status"] == "sent")
    responded_ct = sum(1 for v in invites
                       if v["status"] in ("responded", "awarded",
                                          "not_selected"))
    _stat_cards([("Bids outstanding", f"${outstanding:,.0f}"),
                 ("Awarded to you", f"${awarded_amt:,.0f}"),
                 ("Awaiting your bid", awaiting_you),
                 ("Responded", responded_ct)])

    BADGES = {"sent": "🟠 AWAITING YOUR BID", "responded": "✅ RESPONDED",
              "awarded": "🏆 AWARDED TO YOU", "not_selected": "◻️ NOT SELECTED",
              "declined": "❌ DECLINED"}

    for v in invites:
        itb = (sb().table("itbs").select("*").eq("id", v["itb_id"]).execute().data)
        if not itb:
            continue
        itb = itb[0]
        gc = (sb().table("profiles")
              .select("company, email, last_seen, notify_messages, "
                      "notify_bid_activity")
              .eq("id", itb["gc_id"]).execute().data)
        gc_name = gc[0]["company"] if gc else "GC"
        gc_email = gc[0].get("email") if gc else None
        gc_msg_ok = bool(gc) and gc[0].get("notify_messages") is not False
        gc_bid_ok = bool(gc) and gc[0].get("notify_bid_activity") is not False
        gc_seen = gc[0].get("last_seen") if gc else None
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

            st.markdown(f'<div class="f-mono" style="font-size:10px;'
                        f'color:{C["inkSoft"]}">{gc_name}: '
                        f'{activity_label(gc_seen)}</div>',
                        unsafe_allow_html=True)
            if itb.get("scope"):
                st.markdown(f'<div class="eyebrow">SCOPE</div>'
                            f'<div style="color:{C["ink"]}">{itb["scope"]}</div>',
                            unsafe_allow_html=True)

            th_msgs = (sb().table("bid_messages").select("*")
                       .eq("itb_id", itb["id"])
                       .eq("sub_id", st.session_state.user_id)
                       .order("created_at").execute().data)
            bid_thread(itb["id"], st.session_state.user_id, th_msgs,
                       gc_name, gc_email if gc_msg_ok else None,
                       itb["project"], profile["company"])

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
                        if gc_email and gc_bid_ok:
                            what = ("revised their bid" if new_rev > 1
                                    else "submitted a bid")
                            send_simple_email(
                                gc_email,
                                f"{'Revised' if new_rev > 1 else 'New'} bid: "
                                f"{itb['project']}",
                                email_html(
                                    f"{profile['company']} {what}",
                                    f"<b>${amount:,.0f}</b> on "
                                    f"<b>{itb['project']} — {itb['trade']}"
                                    f"</b>"
                                    + (f" (revision {new_rev})"
                                       if new_rev > 1 else "")
                                    + ".", "Review bids"))
                        st.success(f"Bid submitted (revision {new_rev}).")
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  SHARED SCREEN: SUB NETWORK (GC view of registered subs)
# ─────────────────────────────────────────────────────────────────────
def screen_directory(profile):
    looking_for = "sub" if profile["role"] == "gc" else "gc"
    heading("SUB NETWORK" if looking_for == "sub" else "FIND GCS")

    q = st.text_input("Search", label_visibility="collapsed",
                      placeholder="Search by company, trade, or region…")
    rows = (sb().table("profiles")
            .select("id, company, trade, region, license_no, "
                    "verification_status, last_seen")
            .eq("role", looking_for).order("company").execute().data)
    if q.strip():
        needle = q.strip().lower()
        rows = [r for r in rows if needle in " ".join(
            filter(None, [r.get("company"), r.get("trade"),
                          r.get("region")])).lower()]

    if not rows:
        st.info("No matches — try a broader search term."
                if q.strip() else
                ("No subs registered yet." if looking_for == "sub"
                 else "No GCs registered yet."))
        return

    st.markdown(f'<div class="f-mono" style="font-size:11px;'
                f'color:{C["inkSoft"]};margin-bottom:6px">'
                f'{len(rows)} result{"s" if len(rows) != 1 else ""}</div>',
                unsafe_allow_html=True)

    for s in rows:
        badge = verified_badge(s)
        extra = ("" if s.get("verification_status") == "verified" else
                 f' <span class="f-mono" style="color:{C["inkSoft"]};'
                 f'font-size:11px">NOT YET VERIFIED'
                 + (" — can't be invited" if looking_for == "sub" else "")
                 + '</span>')
        role_line = (s.get("trade") or "trade not set"
                     if looking_for == "sub" else "General Contractor")
        st.markdown(
            f'<div class="card"><b>{s["company"]}</b>{badge}{extra}'
            f'{activity_chip(s.get("last_seen"))}'
            f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
            f'{role_line} · {s.get("region") or ""} · '
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
    gc_rows = {p["id"]: p for p in
               sb().table("profiles")
               .select("id, company, last_seen, email, notify_bid_activity")
               .in_("id", list({r["gc_id"] for r in rfps})).execute().data}
    gc_names = {k: v["company"] for k, v in gc_rows.items()}

    for r in rfps:
        gc_name = gc_names.get(r["gc_id"], "GC")
        with st.expander(f"{r['project']} — {r['trade']} · {gc_name} "
                         f"(bids due {r['due_date']})"):
            st.markdown('<div class="eyebrow">POSTED BY</div>',
                        unsafe_allow_html=True)
            if st.button(f"🏗 {gc_name}", key=f"gcprof_{r['id']}",
                         help="View this GC's profile and portfolio"):
                st.session_state.view_profile = r["gc_id"]
                st.rerun()
            st.markdown(f'<div class="f-mono" style="font-size:10px;'
                        f'color:{C["inkSoft"]}">'
                        f'{activity_label(gc_rows.get(r["gc_id"], {}).get("last_seen"))}'
                        f'</div>', unsafe_allow_html=True)
            meta = (f'📍 {r.get("location") or "location TBD"} · '
                    f'🗓 {r.get("start_date") or "TBD"} → {r.get("end_date") or "TBD"}')
            if r.get("trades"):
                meta += f' · 🛠 {", ".join(r["trades"])}'
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
                    _gcr = gc_rows.get(r["gc_id"], {})
                    gc_email = _gcr.get("email")
                    if gc_email and _gcr.get("notify_bid_activity") is not False:
                        msg_part = (f"<br><i>\"{msg.strip()}\"</i>"
                                    if msg.strip() else "")
                        send_simple_email(
                            gc_email,
                            f"Bid request: {r['project']}",
                            email_html(
                                f"{profile['company']} wants to bid",
                                f"A verified sub requested permission to bid "
                                f"on <b>{r['project']} — {r['trade']}</b>."
                                f"{msg_part}", "Review the request"))
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
                    .select("id, company, trade, region, "
                            "verification_status, last_seen")
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
                f'{verified_badge(s)}{activity_chip(s.get("last_seen"))}'
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
    st.markdown('<div class="eyebrow" style="margin-top:10px">PORTFOLIO — '
                'SHOWCASE YOUR WORK</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="color:{C["inkSoft"]};margin-bottom:6px">Photos '
                f'and descriptions of jobs you\'ve built — past and current. '
                f'This is what GCs and subs see when they vet you. '
                f'(Looking for work to bid on? That\'s the RFP Board.)</div>',
                unsafe_allow_html=True)

    if "show_add_project" not in st.session_state:
        st.session_state.show_add_project = False
    toggle_label = ("➖ Close" if st.session_state.show_add_project
                    else "➕ Add work to your portfolio")
    if st.button(toggle_label, key="toggle_add_project"):
        st.session_state.show_add_project = not st.session_state.show_add_project
        st.rerun()

    if st.session_state.show_add_project:
        fg = st.session_state.get("form_gen", 0)
        title = st.text_input("Project title", key=f"np_title_{fg}")
        pstatus = st.radio("Status", ["Current", "Completed"], horizontal=True,
                           key=f"np_status_{fg}")
        c1, c2 = st.columns(2)
        ploc = c1.text_input("Location", key=f"np_loc_{fg}")
        pyear = c2.text_input("Year", key=f"np_year_{fg}",
                              placeholder="2026 or 2024–2025")
        pdesc = st.text_area("Description (scope, size, role)",
                             key=f"np_desc_{fg}")
        pphotos = st.file_uploader("Upload photos (JPG/PNG/HEIC — select "
                                   "several at once)",
                                   accept_multiple_files=True,
                                   key=f"np_photos_{fg}")
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
                    data, fname = photo_to_jpeg(ph)
                    path = (f"portfolio/{st.session_state.user_id}/"
                            f"{proj['id']}/{int(time.time())}_{fname}")
                    mime = mimetypes.guess_type(fname)[0] or "image/jpeg"
                    sb().storage.from_("drawings").upload(
                        path, data, {"content-type": mime})
                    sb().table("project_photos").insert({
                        "project_id": proj["id"], "path": path,
                        "caption": None,
                    }).execute()
                # fresh widget identities = guaranteed-blank form next time
                st.session_state.form_gen = fg + 1
                # collapse the form; the new project appears below
                st.session_state.show_add_project = False
                st.rerun()

    projects = (sb().table("projects").select("*")
                .eq("owner_id", st.session_state.user_id)
                .order("created_at", desc=True).execute().data)
    if not projects:
        st.info("Nothing showcased yet — add photos of a job you've "
                "built using the button above.")
        return

    for p in projects:
        editing = st.session_state.get("edit_project") == p["id"]
        with st.expander(f"{'🔨' if p['status'] == 'current' else '✅'} "
                         f"{p['title']} ({p['status']}"
                         f"{', ' + p['year'] if p.get('year') else ''})",
                         expanded=True):
            if p.get("description"):
                st.markdown(f'<div style="color:{C["ink"]}">{p["description"]}'
                            f'</div>', unsafe_allow_html=True)
            photos = (sb().table("project_photos").select("*")
                      .eq("project_id", p["id"]).execute().data)

            # ── published view (what visitors see) ──
            if not editing:
                if photos:
                    cols = st.columns(3)
                    for i, ph in enumerate(photos):
                        url = signed_link(ph["path"])
                        if url:
                            cols[i % 3].image(url,
                                              caption=ph.get("caption") or "")
                if st.button("✏️ Edit project", key=f"edit_{p['id']}"):
                    st.session_state.edit_project = p["id"]
                    st.rerun()
                continue

            # ── edit mode (owner tools) ──
            st.markdown(f'<div class="f-mono" style="font-size:10px;'
                        f'color:{C["inkSoft"]}">EDITING — visitors never see '
                        f'these controls</div>', unsafe_allow_html=True)
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

            gen = st.session_state.get("photo_gen", 0)
            ups = st.file_uploader(
                "Add photos (JPG/PNG/HEIC — select several at once)",
                accept_multiple_files=True, key=f"up_{p['id']}_{gen}")
            cap = st.text_input(
                "Caption (optional — applies to this batch)",
                key=f"cap_{p['id']}_{gen}",
                placeholder="e.g. Finished kitchen — custom cabinetry")
            if st.button("Upload photos", key=f"addph_{p['id']}"):
                if not ups:
                    st.error("Choose at least one photo first.")
                else:
                    for up in ups:
                        data, fname = photo_to_jpeg(up)
                        path = (f"portfolio/{st.session_state.user_id}/"
                                f"{p['id']}/{int(time.time())}_{fname}")
                        mime = mimetypes.guess_type(fname)[0] or "image/jpeg"
                        sb().storage.from_("drawings").upload(
                            path, data, {"content-type": mime})
                        sb().table("project_photos").insert({
                            "project_id": p["id"], "path": path,
                            "caption": cap.strip() or None,
                        }).execute()
                    st.session_state.photo_gen = gen + 1  # clears the picker
                    st.rerun()

            b_done, b_del = st.columns(2)
            if b_done.button("✓ Done editing", key=f"done_{p['id']}"):
                st.session_state.pop("edit_project", None)
                st.rerun()
            if b_del.button("Delete this project", key=f"delp_{p['id']}"):
                sb().table("projects").delete().eq("id", p["id"]).execute()
                st.session_state.pop("edit_project", None)
                st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  SCREEN: PUBLIC PROFILE VIEW  (anyone signed-in, via View Profile)
# ─────────────────────────────────────────────────────────────────────
def screen_public_profile(uid):
    rows = (sb().table("profiles")
            .select("id, company, role, trade, region, license_no, "
                    "verification_status, cslb_expires, last_seen")
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
        f'{activity_chip(p.get("last_seen"))}'
        f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
        f'{"General Contractor" if p["role"] == "gc" else p.get("trade") or "Subcontractor"} · '
        f'{p.get("region") or ""} · CSLB {p.get("license_no") or "—"}'
        + (f' · expires {p["cslb_expires"]}' if p.get("cslb_expires") else "")
        + '</div></div>', unsafe_allow_html=True)

    approved_docs, total_docs = doc_status_summary(uid)
    if approved_docs:
        chips = " · ".join(f"✅ {d.split(' (')[0]}" for d in approved_docs)
        st.markdown(f'<div class="card"><div class="eyebrow">SLATE-VERIFIED '
                    f'DOCUMENTS ({len(approved_docs)}/{total_docs})</div>'
                    f'<div class="f-mono" style="font-size:12px;'
                    f'color:{C["green"]}">{chips}</div>'
                    f'<div class="f-mono" style="font-size:10px;'
                    f'color:{C["inkSoft"]}">Documents verified by SLATE — '
                    f'files release to the GC upon award.</div></div>',
                    unsafe_allow_html=True)

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
#  FEEDBACK WIDGET  (sidebar, all users) — lands in the admin inbox
# ─────────────────────────────────────────────────────────────────────
def feedback_widget():
    """Sidebar feedback — styled like a nav item, opens a clean inline
    form. Submissions land in the admin Feedback Inbox."""
    fb_open = st.session_state.get("fb_open", False)
    if st.button("Feedback", key="nav_feedback",
                 type="primary" if fb_open else "secondary"):
        st.session_state.fb_open = not fb_open
        st.rerun()
    if fb_open:
        gen = st.session_state.get("fb_gen", 0)
        msg = st.text_area("Feedback", key=f"fb_msg_{gen}",
                           label_visibility="collapsed", height=110,
                           placeholder="What's working? What's broken? "
                                       "What's missing?")
        if st.button("Send", key="fb_send"):
            if not msg.strip():
                st.error("Write something first.")
            else:
                sb().table("feedback").insert({
                    "user_id": st.session_state.user_id,
                    "message": msg.strip(),
                }).execute()
                st.session_state.fb_gen = gen + 1
                st.session_state.fb_open = False
                st.success("Sent — every message gets read.")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────
#  ADMIN SCREENS
# ─────────────────────────────────────────────────────────────────────
def screen_admin_home(profile):
    heading("SLATE ADMIN")
    profiles_all = (sb().table("profiles")
                    .select("id, role, verification_status, last_seen, "
                            "created_at").execute().data)
    itbs_all = sb().table("itbs").select("id").execute().data
    bids_all = (sb().table("bids").select("itb_id, sub_id, amount, revision")
                .execute().data)
    fb_open = (sb().table("feedback").select("id")
               .eq("status", "open").execute().data)
    docs_pending = (sb().table("verification_docs").select("id")
                    .eq("status", "pending").execute().data)
    ver_pending = [p for p in profiles_all
                   if p["verification_status"] == "pending"]
    latest = {}
    for b in bids_all:
        k = (b["itb_id"], b["sub_id"])
        if k not in latest or b["revision"] > latest[k]["revision"]:
            latest[k] = b
    bid_vol = sum(b["amount"] for b in latest.values())
    _stat_cards([("GCs", sum(1 for p in profiles_all if p["role"] == "gc")),
                 ("Subs", sum(1 for p in profiles_all if p["role"] == "sub")),
                 ("RFPs posted", len(itbs_all)),
                 ("Bid volume", f"${bid_vol:,.0f}")])
    _stat_cards([("Verified users",
                  sum(1 for p in profiles_all
                      if p["verification_status"] == "verified")),
                 ("Pending verifications", len(ver_pending)),
                 ("Docs awaiting review", len(docs_pending)),
                 ("Open feedback", len(fb_open))])

    def _days_ago(ts):
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt).days
        except Exception:
            return None

    contractors = [p for p in profiles_all if p["role"] != "admin"]
    seen_days = [(_days_ago(p.get("last_seen"))) for p in contractors]
    active7 = sum(1 for d in seen_days if d is not None and d < 7)
    active30 = sum(1 for d in seen_days if d is not None and d < 30)
    inactive30 = sum(1 for d in seen_days if d is None or d >= 30)
    new_week = sum(1 for p in contractors
                   if (_days_ago(p.get("created_at")) or 99) < 7)
    _stat_cards([("Active last 7 days", active7),
                 ("Active last 30 days", active30),
                 ("Inactive 30+ days", inactive30),
                 ("New signups this week", new_week)])
    st.markdown(f'<div class="f-mono" style="font-size:10px;'
                f'color:{C["inkSoft"]}">Activity counts from when tracking '
                f'went live — accounts never seen since then count as '
                f'inactive.</div>', unsafe_allow_html=True)

    st.markdown('<div class="eyebrow" style="margin-top:14px">NUDGES</div>',
                unsafe_allow_html=True)
    if st.button("📣 Email reminders for bids due within 3 days"):
        today, cutoff = date.today(), date.today() + timedelta(days=3)
        due_itbs = {i["id"]: i for i in
                    sb().table("itbs").select("id, project, trade, due_date")
                    .execute().data
                    if i.get("due_date")
                    and today <= date.fromisoformat(i["due_date"]) <= cutoff}
        sent = 0
        if due_itbs:
            open_inv = (sb().table("itb_invites").select("itb_id, sub_id")
                        .in_("itb_id", list(due_itbs.keys()))
                        .eq("status", "sent").execute().data)
            sub_emails = {p["id"]: p for p in
                          sb().table("profiles")
                          .select("id, email, company, notify_bid_activity")
                          .in_("id", list({v["sub_id"] for v in open_inv}))
                          .execute().data} if open_inv else {}
            for v in open_inv:
                itb = due_itbs[v["itb_id"]]
                sp = sub_emails.get(v["sub_id"], {})
                if (sp.get("email")
                        and sp.get("notify_bid_activity") is not False):
                    sent += send_simple_email(
                        sp["email"],
                        f"⏰ Bid due {itb['due_date']}: {itb['project']}",
                        email_html(
                            "The ball's in your court",
                            f"Your bid on <b>{itb['project']} — "
                            f"{itb['trade']}</b> is due "
                            f"<b>{itb['due_date']}</b> and you haven't "
                            f"responded yet.", "Submit your bid"))
        st.success(f"Reminders sent: {sent}.")
    st.markdown(f'<div class="f-mono" style="font-size:11px;'
                f'color:{C["inkSoft"]}">Pending items live in the '
                f'Verification Queue and Feedback Inbox.</div>',
                unsafe_allow_html=True)


def screen_admin_users():
    heading("ALL USERS")
    q = st.text_input("Search users", label_visibility="collapsed",
                      placeholder="Search company, trade, or region…")
    rows = (sb().table("profiles")
            .select("id, company, role, trade, region, license_no, "
                    "verification_status, email, last_seen")
            .order("company").execute().data)
    if q.strip():
        n = q.strip().lower()
        rows = [r for r in rows if n in " ".join(
            filter(None, [r.get("company"), r.get("trade"),
                          r.get("region"), r.get("email")])).lower()]
    for r in rows:
        st.markdown(
            f'<div class="card"><b>{r["company"]}</b>{verified_badge(r)}'
            f' <span class="f-mono" style="font-size:11px;'
            f'color:{C["blue"]}">{r["role"].upper()}</span>'
            f'{activity_chip(r.get("last_seen"))}'
            f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
            f'{r.get("email")} · {r.get("trade") or "—"} · '
            f'{r.get("region") or "—"} · CSLB {r.get("license_no") or "—"} · '
            f'status: {r["verification_status"]}</div></div>',
            unsafe_allow_html=True)
        ac1, ac2 = st.columns([1, 3])
        if ac1.button("View profile", key=f"adminprof_{r['id']}"):
            st.session_state.view_profile = r["id"]
            st.rerun()
        if r["role"] in ("gc", "sub"):
            other = "sub" if r["role"] == "gc" else "gc"
            if ac2.button(f"Fix role → {other.upper()}",
                          key=f"adminrole_{r['id']}"):
                sb().table("profiles").update({"role": other}).eq(
                    "id", r["id"]).execute()
                st.rerun()


def screen_admin_rfps():
    heading("ALL RFPS & BIDS")
    itbs = (sb().table("itbs").select("*")
            .order("created_at", desc=True).execute().data)
    if not itbs:
        st.info("No RFPs posted yet.")
        return
    gc_names = {p["id"]: p["company"] for p in
                sb().table("profiles").select("id, company")
                .in_("id", list({i["gc_id"] for i in itbs})).execute().data}
    for itb in itbs:
        bids = (sb().table("bids").select("sub_id, amount, revision")
                .eq("itb_id", itb["id"]).execute().data)
        latest = latest_bids_by_sub(bids)
        with st.expander(f"ITB-{itb['id']:04d} · {itb['project']} — "
                         f"{itb['trade']} · {gc_names.get(itb['gc_id'], 'GC')} "
                         f"({len(latest)} bids, {itb.get('visibility')}, "
                         f"due {itb['due_date']})"):
            if not latest:
                st.markdown(f'<div style="color:{C["inkSoft"]}">No bids.</div>',
                            unsafe_allow_html=True)
                continue
            names = {p["id"]: p["company"] for p in
                     sb().table("profiles").select("id, company")
                     .in_("id", list(latest.keys())).execute().data}
            for b in sorted(latest.values(), key=lambda x: x["amount"]):
                st.markdown(f'- **{names.get(b["sub_id"], "Sub")}** — '
                            f'${b["amount"]:,.0f}'
                            + (f' (rev {b["revision"]})'
                               if b["revision"] > 1 else ""))


def screen_admin_queue():
    heading("VERIFICATION QUEUE")

    # ── pending profile verifications ──
    pend = (sb().table("profiles").select("*")
            .eq("verification_status", "pending").execute().data)
    st.markdown('<div class="eyebrow">PENDING LICENSE VERIFICATIONS</div>',
                unsafe_allow_html=True)
    if not pend:
        st.markdown(f'<div style="color:{C["inkSoft"]}">None pending.</div>',
                    unsafe_allow_html=True)
    for p in pend:
        st.markdown(
            f'<div class="card"><b>{p["company"]}</b> ({p["role"].upper()})'
            f'<div class="f-mono" style="font-size:11px;color:{C["inkSoft"]}">'
            f'Profile company: {p["company"]} · CSLB record: '
            f'{p.get("cslb_business") or "not parsed"} · '
            f'license {p.get("license_no") or "—"} · '
            f'status: {p.get("cslb_status") or "—"}</div>'
            + (f'<a href="https://www.cslb.ca.gov/OnlineServices/'
               f'CheckLicenseII/LicenseDetail.aspx?LicNum='
               f'{"".join(ch for ch in (p.get("license_no") or "") if ch.isdigit())}" '
               f'target="_blank" class="f-mono" style="font-size:11px;'
               f'color:{C["blue"]}">Check license on CSLB ↗</a>'
               if p.get("license_no") else "")
            + '</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if c1.button("Approve", key=f"vok_{p['id']}"):
            sb().table("profiles").update({
                "verification_status": "verified",
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", p["id"]).execute()
            if p.get("email"):
                send_simple_email(
                    p["email"], "You're verified on SLATE ✓",
                    email_html("You're verified!",
                               f"Your license review is complete — "
                               f"<b>{p['company']}</b> is now fully "
                               f"unlocked on SLATE.", "Open SLATE"))
            st.rerun()
        if c2.button("Reject", key=f"vno_{p['id']}"):
            sb().table("profiles").update(
                {"verification_status": "rejected"}).eq(
                "id", p["id"]).execute()
            st.rerun()

    # ── pending documents ──
    st.markdown('<div class="eyebrow" style="margin-top:14px">'
                'DOCUMENTS AWAITING REVIEW</div>', unsafe_allow_html=True)
    docs = (sb().table("verification_docs").select("*")
            .eq("status", "pending").order("created_at").execute().data)
    if not docs:
        st.markdown(f'<div style="color:{C["inkSoft"]}">None pending.</div>',
                    unsafe_allow_html=True)
        return
    owners = {p["id"]: p["company"] for p in
              sb().table("profiles").select("id, company")
              .in_("id", list({d["user_id"] for d in docs})).execute().data}
    for d in docs:
        url = None
        try:
            signed = sb().storage.from_("docs").create_signed_url(
                d["path"], 3600)
            url = signed.get("signedURL") or signed.get("signed_url")
        except Exception:
            pass
        st.markdown(
            f'<div class="card"><b>{owners.get(d["user_id"], "User")}</b> — '
            f'{d["doc_type"]}'
            f'<div class="f-mono" style="font-size:11px;'
            f'color:{C["inkSoft"]}">{d["filename"]} · '
            f'submitted {str(d["created_at"])[:10]}</div></div>',
            unsafe_allow_html=True)
        if url:
            st.markdown(f"[📄 Open document]({url})")
        c1, c2, c3 = st.columns([1, 1, 2])
        if c1.button("Approve", key=f"dok_{d['id']}"):
            sb().table("verification_docs").update({
                "status": "approved",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", d["id"]).execute()
            owner_email = (sb().table("profiles").select("email")
                           .eq("id", d["user_id"]).execute().data)
            if owner_email:
                send_simple_email(
                    owner_email[0]["email"],
                    f"Document approved: {d['doc_type']}",
                    email_html("Document approved ✓",
                               f"Your <b>{d['doc_type']}</b> was reviewed "
                               f"and approved. The ✓ badge now shows on "
                               f"your public profile.", "View your profile"))
            st.rerun()
        rej_note = c3.text_input("Rejection note (optional)",
                                 key=f"dnote_{d['id']}",
                                 label_visibility="collapsed",
                                 placeholder="Reason if rejecting…")
        if c2.button("Reject", key=f"dno_{d['id']}"):
            sb().table("verification_docs").update({
                "status": "rejected",
                "note": rej_note.strip() or None,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", d["id"]).execute()
            owner_email = (sb().table("profiles").select("email")
                           .eq("id", d["user_id"]).execute().data)
            if owner_email:
                note_txt = (f"<br><i>Reviewer note: {rej_note.strip()}</i>"
                            if rej_note.strip() else "")
                send_simple_email(
                    owner_email[0]["email"],
                    f"Document needs attention: {d['doc_type']}",
                    email_html("Document not approved",
                               f"Your <b>{d['doc_type']}</b> couldn't be "
                               f"approved as submitted.{note_txt}<br>"
                               f"Re-upload a corrected version under "
                               f"Get Verified.", "Re-upload in SLATE"))
            st.rerun()


def screen_admin_feedback():
    heading("FEEDBACK INBOX")
    rows = (sb().table("feedback").select("*")
            .order("created_at", desc=True).execute().data)
    if not rows:
        st.info("No feedback yet.")
        return
    users = {p["id"]: p for p in
             sb().table("profiles").select("id, company, role, email")
             .in_("id", list({r["user_id"] for r in rows})).execute().data}
    open_rows = [r for r in rows if r["status"] == "open"]
    done_rows = [r for r in rows if r["status"] != "open"]
    for group, label in ((open_rows, "OPEN"), (done_rows, "RESOLVED")):
        if not group:
            continue
        st.markdown(f'<div class="eyebrow" style="margin-top:10px">{label} '
                    f'({len(group)})</div>', unsafe_allow_html=True)
        for r in group:
            u = users.get(r["user_id"], {})
            st.markdown(
                f'<div class="card"><b>{u.get("company", "User")}</b> '
                f'<span class="f-mono" style="font-size:11px;'
                f'color:{C["blue"]}">{u.get("role", "").upper()}</span>'
                f'<div style="color:{C["ink"]};margin-top:4px">'
                f'{r["message"]}</div>'
                f'<div class="f-mono" style="font-size:10px;'
                f'color:{C["inkSoft"]}">{u.get("email", "")} · '
                f'{str(r["created_at"])[:16].replace("T", " ")}</div></div>',
                unsafe_allow_html=True)
            if r["status"] == "open":
                if st.button("Mark resolved", key=f"fbres_{r['id']}"):
                    sb().table("feedback").update(
                        {"status": "resolved"}).eq("id", r["id"]).execute()
                    st.rerun()


def _announce_body_html(body, image_urls):
    """Paragraphs on blank lines, line breaks preserved, [imageN] tokens
    swapped for hosted images (leftover images append at the end)."""
    used = set()
    paras = []
    for p in body.split("\n\n"):
        if not p.strip():
            continue
        chunk = p.strip().replace("\n", "<br>")
        for i, url in enumerate(image_urls, start=1):
            token = f"[image{i}]"
            if token in chunk:
                chunk = chunk.replace(
                    token, f'<img src="{url}" width="100%" '
                           f'style="border-radius:6px;border:1px solid '
                           f'#C6CCC4;margin:8px 0">')
                used.add(i)
        paras.append(f"<p>{chunk}</p>")
    for i, url in enumerate(image_urls, start=1):
        if i not in used:
            paras.append(f'<p><img src="{url}" width="100%" '
                         f'style="border-radius:6px;border:1px solid '
                         f'#C6CCC4;margin:8px 0"></p>')
    return "".join(paras)


def screen_admin_announce(profile):
    heading("ANNOUNCEMENTS")
    st.markdown(f'<div style="color:{C["inkSoft"]};margin-bottom:8px">Send '
                f'a product update to every SLATE user (minus opt-outs). '
                f'Upload screenshots below and place them in your text with '
                f'<b>[image1]</b>, <b>[image2]</b>… — images without a token '
                f'are added at the end.</div>', unsafe_allow_html=True)

    gen = st.session_state.get("ann_gen", 0)
    subj = st.text_input("Subject", key=f"ann_s_{gen}",
                         placeholder="SLATE V2.4: Bid Q&A is live")
    body = st.text_area("Message (blank line = new paragraph, "
                        "[image1] places the first screenshot)",
                        key=f"ann_b_{gen}", height=220)
    imgs = st.file_uploader("Screenshots (PNG/JPG — order matters: first "
                            "file = [image1])", accept_multiple_files=True,
                            key=f"ann_i_{gen}")

    # host the images so email clients can render them
    if imgs and st.session_state.get("ann_img_sig") != [f.name for f in imgs]:
        urls = []
        for f in imgs:
            data, fname = photo_to_jpeg(f, max_px=1100)
            path = f"{int(time.time())}_{fname}"
            sb().storage.from_("announce").upload(
                path, data, {"content-type": "image/jpeg"})
            pub = sb().storage.from_("announce").get_public_url(path)
            urls.append(pub if isinstance(pub, str)
                        else pub.get("publicUrl") or pub.get("public_url"))
        st.session_state.ann_img_urls = urls
        st.session_state.ann_img_sig = [f.name for f in imgs]
    if not imgs:
        st.session_state.ann_img_urls = []
        st.session_state.ann_img_sig = None
    image_urls = st.session_state.get("ann_img_urls", [])
    if image_urls:
        st.markdown(f'<div class="f-mono" style="font-size:11px;'
                    f'color:{C["green"]}">✓ {len(image_urls)} image(s) '
                    f'hosted and ready — reference with '
                    f'{", ".join(f"[image{i+1}]" for i in range(len(image_urls)))}'
                    f'</div>', unsafe_allow_html=True)

    with st.expander("Preview"):
        st.markdown(email_html(subj or "Subject",
                               _announce_body_html(body, image_urls)
                               or "<p>…</p>", "Open SLATE"),
                    unsafe_allow_html=True)

    recipients = (sb().table("profiles").select("email, email_opt_out, role")
                  .neq("role", "admin").execute().data)
    to_send = [r["email"] for r in recipients
               if r.get("email") and not r.get("email_opt_out")]
    st.markdown(f'<div class="f-mono" style="font-size:11px;'
                f'color:{C["inkSoft"]}">Will send to {len(to_send)} user(s) '
                f'({len(recipients) - len(to_send)} opted out or no email). '
                f'Heads up: Resend free tier caps at 100 emails/day.</div>',
                unsafe_allow_html=True)
    confirm = st.checkbox("I've previewed this and I'm ready to send",
                          key=f"ann_c_{gen}")
    if st.button("Send announcement"):
        if not (subj.strip() and body.strip()):
            st.error("Subject and message are both required.")
        elif not confirm:
            st.error("Tick the confirmation box after previewing.")
        else:
            html_body = _announce_body_html(body, image_urls)
            ok = fail = 0
            with st.spinner(f"Sending to {len(to_send)} users…"):
                for em in to_send:
                    if send_simple_email(em, subj.strip(),
                                         email_html(subj.strip(), html_body,
                                                    "Open SLATE")):
                        ok += 1
                    else:
                        fail += 1
            st.session_state.ann_gen = gen + 1
            st.session_state.ann_img_urls = []
            st.session_state.ann_img_sig = None
            st.success(f"Announcement sent: {ok} delivered, {fail} failed.")


# ─────────────────────────────────────────────────────────────────────
#  MAIN ROUTER
# ─────────────────────────────────────────────────────────────────────
require_secrets()

try_restore_session()          # stay logged in across page refreshes
flush_cookie_writes()          # write any queued cookie from the last run

if handle_password_recovery(): # reset-link flow owns the page when active
    st.stop()

if "user_id" not in st.session_state:
    screen_auth()
    st.stop()

profile = st.session_state.get("profile") or load_profile()
if profile is None:
    screen_onboarding()
    st.stop()

touch_last_seen()

with st.sidebar:
    st.markdown(logo_html(width=150), unsafe_allow_html=True)
    check = " ✓" if is_verified(profile) else ""
    st.markdown(f'<div class="f-mono" style="font-size:10px;color:#7FA98C;'
                f'margin-top:4px">{profile["company"].upper()} · '
                f'{profile["role"].upper()}{check}</div>',
                unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    if profile["role"] == "admin":
        nav_items = ["Admin Home", "Users", "All RFPs", "Verification Queue",
                     "Feedback Inbox", "Announcements"]
    elif profile["role"] == "gc":
        nav_items = ["My Profile", "Dashboard", "New Bid Request",
                     "Bid Requests", "Sub Network", "Get Verified",
                     "Settings"]
    else:
        nav_items = ["My Profile", "Bid Invites", "RFP Board", "Find GCs",
                     "Get Verified", "Settings"]
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
    if profile["role"] != "admin":
        feedback_widget()
    if st.button("Log out"):
        sign_out()
        st.rerun()

# Viewing someone's profile takes over the page until Back is clicked
if st.session_state.get("view_profile"):
    screen_public_profile(st.session_state.view_profile)
elif profile["role"] == "admin":
    if page == "Admin Home":
        screen_admin_home(profile)
    elif page == "Users":
        screen_admin_users()
    elif page == "All RFPs":
        screen_admin_rfps()
    elif page == "Verification Queue":
        screen_admin_queue()
    elif page == "Announcements":
        screen_admin_announce(profile)
    else:
        screen_admin_feedback()
elif page == "Get Verified":
    screen_verify(profile)
elif page == "My Profile":
    screen_my_profile(profile)
elif page == "Settings":
    screen_settings(profile)
elif profile["role"] == "gc":
    if page == "Dashboard":
        screen_gc_dashboard(profile)
    elif page == "New Bid Request":
        screen_new_itb(profile)
    elif page == "Bid Requests":
        screen_gc_requests(profile)
    else:
        screen_directory(profile)
else:
    if page == "RFP Board":
        screen_rfp_board(profile)
    elif page == "Find GCs":
        screen_directory(profile)
    else:
        screen_sub_inbox(profile)
