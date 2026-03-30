"""
app.py — Streamlit read-only dashboard for the SLC Video Pipeline.
Reads job state from the MySQL database. No processing happens here.
"""

import streamlit as st
from database import get_queue, clear_done, retry_failed

st.set_page_config(page_title="SLC Video Pipeline", page_icon="🎬", layout="wide")

# ── CSS (dark theme matching original) ───────────────────────────────────
st.markdown("""<style>
.stApp{background:linear-gradient(135deg,#0a2a3c 0%,#0d3b54 30%,#0f4c6e 60%,#1a3a5c 100%)}
header[data-testid="stHeader"]{background:rgba(10,42,60,.85);backdrop-filter:blur(10px)}
.stButton>button[kind="primary"]{background:#60ccbe!important;color:#0a2a3c!important;border:none!important;border-radius:12px!important;font-weight:600!important;padding:.6rem 2rem!important}
.stButton>button[kind="primary"]:hover{background:#4dbcad!important;box-shadow:0 4px 20px rgba(96,204,190,.3)!important}
.q-row{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px 14px;margin-bottom:8px}
.badge-pending{background:rgba(255,200,80,.15);color:#ffc850;border:1px solid rgba(255,200,80,.3);padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}
.badge-processing{background:rgba(96,204,190,.15);color:#60ccbe;border:1px solid rgba(96,204,190,.4);padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}
.badge-done{background:rgba(80,200,120,.15);color:#50c878;border:1px solid rgba(80,200,120,.3);padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}
.badge-failed{background:rgba(255,80,80,.15);color:#ff5050;border:1px solid rgba(255,80,80,.3);padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}
</style>""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────────
st.markdown("""<div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">
  <h1 style="margin:0;font-size:28px">🎬 SLC Video Pipeline</h1>
  <span style="background:#60ccbe;color:#0a2a3c;font-size:11px;font-weight:700;
        padding:3px 12px;border-radius:20px;text-transform:uppercase">Dashboard</span>
</div>""", unsafe_allow_html=True)

st.markdown("---")

# ── Load queue from database ─────────────────────────────────────────────
queue = get_queue()

pending    = [j for j in queue if j["status"] == "pending"]
processing = [j for j in queue if j["status"] == "processing"]
done       = [j for j in queue if j["status"] == "done"]
failed     = [j for j in queue if j["status"] == "failed"]

# ── Summary metrics ──────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("🟡 Pending",    len(pending))
c2.metric("🔵 Processing", len(processing))
c3.metric("✅ Done",        len(done))
c4.metric("❌ Failed",      len(failed))

st.markdown("---")

# ── Job table ────────────────────────────────────────────────────────────
if not queue:
    st.info("No jobs in the queue. Send a batch via the Chrome extension to get started.")
else:
    for job in queue:
        badge_html = {
            "pending":    '<span class="badge-pending">🟡 Pending</span>',
            "processing": '<span class="badge-processing">🔵 Processing</span>',
            "done":       '<span class="badge-done">✅ Done</span>',
            "failed":     '<span class="badge-failed">❌ Failed</span>',
        }.get(job["status"], job["status"])

        created = job["created_at"].strftime("%Y-%m-%d %H:%M") if job["created_at"] else ""

        od_link = ""
        if job.get("onedrive_url"):
            od_link = (
                f' · <a href="{job["onedrive_url"]}" target="_blank" '
                f'style="color:#50c878;font-size:12px">OneDrive ↗</a>'
            )

        error_hint = ""
        if job["status"] == "failed" and job.get("error_message"):
            short = job["error_message"][:120]
            error_hint = (
                f'<div style="color:#ff5050;font-size:11px;margin-top:4px">'
                f'Error: {short}</div>'
            )

        st.markdown(f"""<div class="q-row">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <span style="font-weight:700;color:rgba(255,255,255,.4);font-size:12px">#{job['id']}</span>
            {badge_html}
            <span style="font-weight:600;color:#fff">{job['course_name']}</span>
            <span style="color:rgba(96,204,190,.8);font-size:13px">{job['unit_number']}</span>
            <span style="color:rgba(255,255,255,.35);font-size:12px">{created}{od_link}</span>
          </div>
          {error_hint}
        </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── Action buttons ───────────────────────────────────────────────────────
col1, col2, col3 = st.columns([1, 1, 2])

with col1:
    if st.button("🗑 Clear Done Jobs", type="primary", use_container_width=True):
        clear_done()
        st.rerun()

with col2:
    if st.button("🔄 Retry Failed Jobs", type="primary", use_container_width=True):
        retry_failed()
        st.rerun()

with col3:
    if st.button("🔃 Refresh", use_container_width=True):
        st.rerun()
