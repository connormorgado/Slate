"""
SLATE — a subcontractor bid & endorsement platform (prototype)
==============================================================
Built by contractors, for contractors.

This is a clickable PROTOTYPE built in Streamlit (pure Python).
Nothing here talks to a real database yet — all data is mock data
defined in the DATA section below so you can demo the experience
and get reactions from GCs and subs before building a real backend.

HOW TO EDIT (the parts you'll actually touch):
  - Change companies/metrics ......... edit the SUBS list
  - Change open bid requests ......... edit the ITBS list
  - Change tier rules/labels ......... edit TIER_META
  - Change colors .................... edit the C dict
  - Change wording ................... it's all inline, search the text

HOW TO RUN LOCALLY:
  pip install -r requirements.txt
  streamlit run app.py

HOW TO PUBLISH (free):
  1. Push this repo to GitHub
  2. Go to share.streamlit.io -> "New app" -> pick your repo
  3. Set the main file to app.py -> Deploy. You get a public URL.
"""

import streamlit as st

# ─────────────────────────────────────────────────────────────────────────
#  PALETTE  — construction / drafting theme. Change these hex values to
#  rebrand the whole app.
# ─────────────────────────────────────────────────────────────────────────
C = {
    "paper":   "#EDEFEA",   # drafting-paper background
    "ink":     "#16263C",   # navy — primary text / sidebar
    "inkSoft": "#3D4E63",   # muted labels
    "line":    "#C6CCC4",   # borders
    "orange":  "#E8621A",   # safety orange — accents / primary buttons
    "blue":    "#2E5E8C",   # tier 2
    "green":   "#3E7A4E",   # tier 3 / good metrics
    "white":   "#FAFBF8",
    "accent":  "#1D7A44",   # slate-green brand accent (buttons, brand)
    "neon":    "#6EE86E",   # logo green for dark surfaces   # card background
}

# ─────────────────────────────────────────────────────────────────────────
#  DATA  — mock data. This is the part you'll edit most.
# ─────────────────────────────────────────────────────────────────────────
SUBS = [
    {"id": 1, "name": "Morgado Building & Renovation", "trade": "General / Framing", "tier": 3,
     "endorsements": 14, "onTime": 96, "responseRate": 92, "bidVariance": "+2.1%", "capacity": "Open",
     "crews": 3, "maxScope": "$1.5M", "region": "South Bay", "years": 18,
     "note": "Consistently closes punch lists inside 5 days. Zero disputed change orders in 24 mo."},
    {"id": 2, "name": "Reyes Electric Co.", "trade": "Electrical (C-10)", "tier": 3,
     "endorsements": 11, "onTime": 94, "responseRate": 88, "bidVariance": "-1.4%", "capacity": "Open",
     "crews": 4, "maxScope": "$900K", "region": "San Jose / Peninsula", "years": 12,
     "note": "Strong on service upgrades + ADU subpanels. Fast RFI turnaround."},
    {"id": 3, "name": "Bayline Plumbing & Rough-In", "trade": "Plumbing (C-36)", "tier": 2,
     "endorsements": 6, "onTime": 89, "responseRate": 95, "bidVariance": "+4.8%", "capacity": "Tight",
     "crews": 2, "maxScope": "$400K", "region": "South Bay", "years": 9,
     "note": "High response rate. Bids trend above budget on hillside work."},
    {"id": 4, "name": "Sierra Concrete & Grading", "trade": "Concrete / Grading (C-8)", "tier": 2,
     "endorsements": 7, "onTime": 91, "responseRate": 81, "bidVariance": "+0.9%", "capacity": "Open",
     "crews": 5, "maxScope": "$1.2M", "region": "Santa Clara County", "years": 21,
     "note": "Handles engineered pads + retaining. Slower to respond, reliable once mobilized."},
    {"id": 5, "name": "Vu Mechanical (HVAC)", "trade": "HVAC (C-20)", "tier": 1,
     "endorsements": 2, "onTime": 84, "responseRate": 90, "bidVariance": "-3.2%", "capacity": "Open",
     "crews": 1, "maxScope": "$150K", "region": "San Jose", "years": 4,
     "note": "Newer shop, competitive pricing. Needs 1 more endorsement for Tier 2."},
    {"id": 6, "name": "Golden State Drywall", "trade": "Drywall (C-9)", "tier": 1,
     "endorsements": 1, "onTime": 78, "responseRate": 72, "bidVariance": "+6.5%", "capacity": "Booked",
     "crews": 2, "maxScope": "$200K", "region": "East Bay / South Bay", "years": 6,
     "note": "Two late finishes flagged in last 12 mo. Currently booked through Sept."},
]

ITBS = [
    {"id": "ITB-0142", "project": "Lariat Ln Residence — 3,750 SF New Build", "trade": "Concrete / Grading",
     "due": "Jul 18", "sent": 6, "responded": 4, "status": "Open", "coverage": 67},
    {"id": "ITB-0141", "project": "Lariat Ln Residence — 3,750 SF New Build", "trade": "Framing Package",
     "due": "Jul 21", "sent": 4, "responded": 1, "status": "Open", "coverage": 25},
    {"id": "ITB-0139", "project": "Westview Dr Spec — Site Prep", "trade": "Electrical",
     "due": "Jul 10", "sent": 5, "responded": 5, "status": "Leveling", "coverage": 100},
]

TIER_META = {
    1: {"label": "TIER 1", "sub": "Verified license + insurance",          "color": C["inkSoft"], "max": "Scopes to $250K"},
    2: {"label": "TIER 2", "sub": "3+ GC endorsements",                    "color": C["blue"],    "max": "Scopes to $750K"},
    3: {"label": "TIER 3", "sub": "8+ endorsements · audited history",     "color": C["green"],   "max": "Unlimited scope access"},
}

# ─────────────────────────────────────────────────────────────────────────
#  PAGE CONFIG + CSS  — the injected CSS gets us close to the SLATE look.
#  You rarely need to touch this block.
# ─────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="SLATE", page_icon="🪧", layout="wide")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

/* App background = drafting paper */
.stApp { background: #EDEFEA; }

/* Typography helpers */
.f-disp { font-family: 'Barlow Condensed', sans-serif; }
.f-mono { font-family: 'IBM Plex Mono', monospace; }
html, body, [class*="css"] { font-family: 'Barlow', sans-serif; }

/* Sidebar = navy ink */
section[data-testid="stSidebar"] { background: #0D0F0E; }
section[data-testid="stSidebar"] * { color: #C6D0DC; }

/* Card primitive */
.card {
  background: #FAFBF8; border: 1px solid #C6CCC4; border-radius: 3px;
  padding: 16px; margin-bottom: 12px;
}
.wordmark { font-family:'Barlow Condensed',sans-serif; font-weight:700;
  font-size: 30px; color:#FFFFFF; letter-spacing:0.5px; line-height:1; }
.eyebrow { font-family:'IBM Plex Mono',monospace; font-size:10px;
  text-transform:uppercase; letter-spacing:1px; color:#3D4E63; }
.metric-val { font-family:'Barlow Condensed',sans-serif; font-weight:600; font-size:26px; }
.stamp { display:inline-block; border:2px solid; border-radius:4px;
  padding:2px 10px; transform:rotate(-4deg); font-family:'Barlow Condensed',sans-serif;
  font-weight:700; letter-spacing:2px; font-size:13px; }

/* Primary buttons -> safety orange */
.stButton > button {
  background:#1D7A44; color:#FFFFFF; border:none; border-radius:3px;
  font-family:'Barlow Condensed',sans-serif; font-weight:600; letter-spacing:1px;
}
.stButton > button:hover { background:#14572F; color:#FFFFFF; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
#  SMALL HTML HELPERS  — return strings we drop in with st.markdown.
# ─────────────────────────────────────────────────────────────────────────
def tier_stamp(tier: int) -> str:
    m = TIER_META[tier]
    return f'<span class="stamp" style="border-color:{m["color"]};color:{m["color"]}">{m["label"]}</span>'


def metric_block(label: str, value: str, warn: bool = False) -> str:
    color = C["orange"] if warn else C["ink"]
    return (f'<div class="eyebrow">{label}</div>'
            f'<div class="metric-val" style="color:{color}">{value}</div>')


def coverage_bar(pct: int) -> str:
    color = C["orange"] if pct < 40 else C["green"]
    return (f'<div style="background:{C["paper"]};height:6px;border-radius:3px;margin-top:4px">'
            f'<div style="width:{pct}%;height:6px;border-radius:3px;background:{color}"></div></div>')


# ─────────────────────────────────────────────────────────────────────────
#  SIDEBAR / NAVIGATION
# ─────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="wordmark">SLATE<span style="color:#6EE86E">.</span></div>',
                unsafe_allow_html=True)
    st.markdown('<div class="f-mono" style="font-size:9px;color:#8FA0B5;margin-top:4px">'
                'BY CONTRACTORS, FOR CONTRACTORS</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    page = st.radio(
        "Navigate",
        ["Dashboard", "Sub Network", "New Bid Request", "Tier System"],
        label_visibility="collapsed",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="f-mono" style="font-size:11px;color:#8FA0B5">'
                'ALUM ROCK DEVELOPMENT GROUP</div>', unsafe_allow_html=True)
    st.markdown('<div class="f-mono" style="font-size:11px;color:#6EE86E">'
                'GC PREMIUM · $500/mo</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
#  PAGE: DASHBOARD
# ─────────────────────────────────────────────────────────────────────────
def page_dashboard():
    st.markdown('<div class="f-disp" style="font-size:30px;font-weight:700;color:#16263C">'
                'DASHBOARD</div>', unsafe_allow_html=True)

    # Top metrics row
    cols = st.columns(4)
    stats = [("Open bid requests", "3"), ("Avg. bid coverage", "64%"),
             ("Subs in network", "38"), ("Endorsements given", "14")]
    for col, (label, val) in zip(cols, stats):
        with col:
            st.markdown(f'<div class="card">{metric_block(label, val)}</div>',
                        unsafe_allow_html=True)

    st.markdown('<div class="f-disp" style="font-size:22px;font-weight:700;color:#16263C;'
                'margin-top:8px">ACTIVE BID REQUESTS</div>', unsafe_allow_html=True)

    for b in ITBS:
        status_color = C["blue"] if b["status"] == "Leveling" else C["green"]
        html = f"""
        <div class="card">
          <div style="display:flex;flex-wrap:wrap;gap:16px;align-items:center">
            <span class="f-mono" style="font-size:11px;background:{C['paper']};
                  padding:3px 8px;border-radius:3px;color:{C['inkSoft']}">{b['id']}</span>
            <div style="flex:1;min-width:180px">
              <div style="font-weight:600;color:{C['ink']}">{b['project']}</div>
              <div class="f-mono" style="font-size:11px;color:{C['inkSoft']}">
                   {b['trade']} · due {b['due']}</div>
            </div>
            <div style="width:150px">
              <div class="f-mono" style="font-size:11px;color:{C['inkSoft']}">
                   {b['responded']}/{b['sent']} responded</div>
              {coverage_bar(b['coverage'])}
            </div>
            <span class="f-disp" style="font-weight:600;color:{status_color};
                  border:1px solid {C['line']};padding:1px 8px;border-radius:3px">
                  {b['status'].upper()}</span>
          </div>
        </div>"""
        st.markdown(html, unsafe_allow_html=True)

    # Coverage-risk alert — the "we know your real pain" feature
    st.markdown(f"""
    <div class="card" style="border-color:{C['orange']}">
      <span style="color:{C['ink']}"><b>⚠ Coverage risk:</b> Framing package (ITB-0141)
      has 25% response with 14 days to due date. 2 Tier-3 framing subs with open capacity
      match this scope — open <b>Sub Network</b> to view matches.</span>
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
#  PAGE: SUB NETWORK
# ─────────────────────────────────────────────────────────────────────────
def page_subs():
    st.markdown('<div class="f-disp" style="font-size:30px;font-weight:700;color:#16263C">'
                'SUB NETWORK</div>', unsafe_allow_html=True)

    query = st.text_input("Search", placeholder="Search trade or company…",
                          label_visibility="collapsed")
    results = [s for s in SUBS
               if query.lower() in (s["name"] + s["trade"]).lower()]

    left, right = st.columns([3, 2])

    # Left: the list. Streamlit reruns on click, so we track selection in session_state.
    if "selected_sub" not in st.session_state:
        st.session_state.selected_sub = SUBS[0]["id"]

    with left:
        for s in results:
            cap_color = {"Open": C["green"], "Tight": C["orange"]}.get(s["capacity"], C["inkSoft"])
            ot_color = C["green"] if s["onTime"] >= 90 else C["orange"]
            st.markdown(f"""
            <div class="card">
              <div style="display:flex;align-items:center;gap:12px">
                <div style="flex:1">
                  <div style="font-weight:600;color:{C['ink']}">{s['name']}</div>
                  <div class="f-mono" style="font-size:11px;color:{C['inkSoft']}">
                       {s['trade']} · {s['region']}</div>
                  <div class="f-mono" style="font-size:11px;color:{C['inkSoft']};margin-top:6px">
                    ON-TIME <b style="color:{ot_color}">{s['onTime']}%</b> &nbsp;
                    RESPONSE <b style="color:{C['ink']}">{s['responseRate']}%</b> &nbsp;
                    CAPACITY <b style="color:{cap_color}">{s['capacity'].upper()}</b>
                  </div>
                </div>
                {tier_stamp(s['tier'])}
              </div>
            </div>""", unsafe_allow_html=True)
            # A button under each card sets the selected sub for the detail pane.
            if st.button(f"View {s['name']}", key=f"view_{s['id']}"):
                st.session_state.selected_sub = s["id"]

    # Right: detail pane for the currently selected sub.
    with right:
        sel = next(s for s in SUBS if s["id"] == st.session_state.selected_sub)
        m = TIER_META[sel["tier"]]
        var_warn = sel["bidVariance"].startswith("+") and float(sel["bidVariance"].strip("+%")) > 4
        st.markdown(f"""
        <div class="card" style="border-color:{C['ink']}">
          <div class="f-disp" style="font-size:22px;font-weight:700;color:{C['ink']}">{sel['name']}</div>
          <div class="f-mono" style="font-size:11px;color:{C['inkSoft']}">
               {sel['trade']} · {sel['years']} yrs · {sel['crews']} crews</div>
          <hr style="border-color:{C['line']}">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
            <div>{metric_block("On-time finish", str(sel['onTime'])+'%', sel['onTime']<85)}</div>
            <div>{metric_block("Bid response", str(sel['responseRate'])+'%')}</div>
            <div>{metric_block("Bid vs. budget", sel['bidVariance'], var_warn)}</div>
            <div>{metric_block("Largest verified scope", sel['maxScope'])}</div>
          </div>
          <hr style="border-color:{C['line']}">
          <div>{tier_stamp(sel['tier'])}
            <div class="f-mono" style="font-size:11px;color:{C['inkSoft']};margin-top:8px">
                 {sel['endorsements']} GC endorsements · {m['max']}</div></div>
          <hr style="border-color:{C['line']}">
          <div class="eyebrow">Network notes</div>
          <div style="color:{C['ink']}">{sel['note']}</div>
        </div>""", unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        b1.button("Invite to Bid", key="invite_sel")
        b2.button("Endorse", key="endorse_sel")


# ─────────────────────────────────────────────────────────────────────────
#  PAGE: NEW BID REQUEST  (3-step wizard using session_state)
# ─────────────────────────────────────────────────────────────────────────
def page_new_itb():
    st.markdown('<div class="f-disp" style="font-size:30px;font-weight:700;color:#16263C">'
                'NEW BID REQUEST</div>', unsafe_allow_html=True)

    if "itb_step" not in st.session_state:
        st.session_state.itb_step = 1
    if "itb_picked" not in st.session_state:
        st.session_state.itb_picked = {1}  # start with Morgado selected

    step = st.session_state.itb_step
    if step <= 3:
        st.markdown(f'<div class="eyebrow">STEP {step} OF 3</div>', unsafe_allow_html=True)
        st.progress(step / 3)

    # STEP 1 — scope & drawings
    if step == 1:
        st.text_input("Project", "Lariat Ln Residence — 3,750 SF New Build")
        st.selectbox("Trade package",
                     ["Framing Package", "Concrete / Grading", "Electrical",
                      "Plumbing Rough-In", "HVAC"])
        st.text_area("Scope of work",
                     "Complete structural framing per S-series drawings. 2-story, 3,750 SF. "
                     "Includes shear walls, engineered hardware, roof trusses set. GC provides crane day.")
        st.markdown('<div class="f-mono" style="font-size:11px;color:#3D4E63">'
                    '📎 A2.1–A4.3 Plans.pdf · S1.0–S3.2 Structural.pdf · Scope_Framing_R2.docx</div>',
                    unsafe_allow_html=True)
        if st.button("Select Subs →"):
            st.session_state.itb_step = 2
            st.rerun()

    # STEP 2 — select subs (tier gating enforced here)
    elif step == 2:
        st.markdown('<div class="f-mono" style="font-size:11px;color:#3D4E63">'
                    'SCOPE VALUE EST. $410K — TIER 2+ REQUIRED. '
                    'Sorted by fit: capacity, on-time record, verified scope size.</div>',
                    unsafe_allow_html=True)

        eligible = [s for s in SUBS if s["tier"] >= 2]
        locked = [s for s in SUBS if s["tier"] < 2]

        for s in eligible:
            checked = s["id"] in st.session_state.itb_picked
            new_val = st.checkbox(
                f"{s['name']}  —  {s['onTime']}% on-time · {s['capacity'].lower()} capacity · max {s['maxScope']}",
                value=checked, key=f"pick_{s['id']}")
            if new_val:
                st.session_state.itb_picked.add(s["id"])
            else:
                st.session_state.itb_picked.discard(s["id"])

        # Locked tier-1 subs — shows exactly what they need to unlock
        locked_html = ('<div class="card" style="background:#EDEFEA">'
                       '<div class="f-mono" style="font-size:11px;color:#3D4E63">'
                       '🔒 TIER 1 SUBS — LOCKED FOR SCOPES OVER $250K</div>')
        for s in locked:
            need = 3 - s["endorsements"]
            note = (f"{need} endorsement{'s' if need > 1 else ''} from Tier 2"
                    if need > 0 else "Pending review")
            locked_html += (f'<div style="color:#3D4E63;font-size:14px;margin-top:4px">'
                            f'{s["name"]} — {s["trade"]} '
                            f'<span class="f-mono" style="font-size:11px">· {note}</span></div>')
        locked_html += '</div>'
        st.markdown(locked_html, unsafe_allow_html=True)

        c1, c2 = st.columns([1, 1])
        if c1.button("← Back"):
            st.session_state.itb_step = 1
            st.rerun()
        if c2.button("Review →"):
            st.session_state.itb_step = 3
            st.rerun()

    # STEP 3 — review & send
    elif step == 3:
        picked = [s for s in SUBS if s["id"] in st.session_state.itb_picked]
        st.markdown(f"""
        <div class="card" style="border-color:{C['ink']}">
          <div class="f-disp" style="font-size:22px;font-weight:700;color:{C['ink']}">
               REVIEW BID REQUEST</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:8px">
            <div>{metric_block("Trade package", "Framing Package")}</div>
            <div>{metric_block("Response due", "Jul 21, 2026")}</div>
            <div>{metric_block("Recipients", str(len(picked))+" subs")}</div>
            <div>{metric_block("Attachments", "3 files")}</div>
          </div>
          <div class="f-mono" style="font-size:11px;color:{C['inkSoft']};margin-top:10px">
               {' · '.join(s['name'] for s in picked) if picked else 'No subs selected'}</div>
        </div>""", unsafe_allow_html=True)

        c1, c2 = st.columns([1, 1])
        if c1.button("← Back", key="rev_back"):
            st.session_state.itb_step = 2
            st.rerun()
        if c2.button("Send Bid Request", key="send"):
            st.session_state.itb_step = 99
            st.rerun()

    # SENT confirmation
    elif step == 99:
        n = len(st.session_state.itb_picked)
        st.markdown(f"""
        <div style="text-align:center;padding:30px">
          <span class="stamp" style="border-color:{C['green']};color:{C['green']};
                font-size:26px;padding:6px 20px">SENT</span>
          <div style="color:{C['ink']};margin-top:20px;max-width:460px;margin-left:auto;margin-right:auto">
            Bid request ITB-0143 issued to {n} subcontractor{'s' if n != 1 else ''}.
            Drawings and scope attached. You'll be notified as responses come in,
            and coverage-risk alerts fire at 50% of the response window.
          </div>
        </div>""", unsafe_allow_html=True)
        if st.button("Start Another"):
            st.session_state.itb_step = 1
            st.session_state.itb_picked = {1}
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────
#  PAGE: TIER SYSTEM
# ─────────────────────────────────────────────────────────────────────────
def page_tiers():
    st.markdown('<div class="f-disp" style="font-size:30px;font-weight:700;color:#16263C">'
                'ENDORSEMENT TIERS</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="color:{C["inkSoft"]};margin-bottom:12px">'
                'Subs climb tiers through endorsements from GCs they\'ve completed work for — '
                'reputation earned on real jobs, not bought. Higher tiers unlock larger, '
                'more complex scopes.</div>', unsafe_allow_html=True)

    for t in [3, 2, 1]:
        m = TIER_META[t]
        st.markdown(f"""
        <div class="card">
          <div style="display:flex;align-items:center;gap:20px">
            {tier_stamp(t)}
            <div>
              <div style="font-weight:600;color:{C['ink']}">{m['sub']}</div>
              <div class="f-mono" style="font-size:11px;color:{C['inkSoft']}">{m['max']}</div>
            </div>
          </div>
        </div>""", unsafe_allow_html=True)

    st.markdown(f"""
    <div class="card" style="background:{C['paper']};color:{C['inkSoft']}">
      Endorsements are weighted by the endorsing GC's own track record and project size,
      and decay if inactive for 24 months — keeping tiers a live signal, not a trophy case.
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────
#  ROUTER
# ─────────────────────────────────────────────────────────────────────────
if page == "Dashboard":
    page_dashboard()
elif page == "Sub Network":
    page_subs()
elif page == "New Bid Request":
    page_new_itb()
elif page == "Tier System":
    page_tiers()
