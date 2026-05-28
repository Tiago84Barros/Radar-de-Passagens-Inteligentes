from __future__ import annotations

import streamlit as st


CSS = """
<style>
:root {
    --radar-bg: #F6F8FB;
    --radar-panel: #FFFFFF;
    --radar-panel-soft: #F8FAFC;
    --radar-ink: #0F172A;
    --radar-muted: #64748B;
    --radar-line: #E2E8F0;
    --radar-teal: #0F766E;
    --radar-teal-soft: #CCFBF1;
    --radar-blue: #2563EB;
    --radar-amber: #B45309;
    --radar-green: #15803D;
}

.stApp { background: var(--radar-bg); color: var(--radar-ink); }
.main .block-container {
    padding-top: 1.25rem;
    padding-bottom: 2.5rem;
    max-width: 1420px;
}

[data-testid="stSidebar"] {
    background: #0F172A;
    border-right: 1px solid rgba(148,163,184,.20);
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] p {
    color: #E5EDF8;
}
[data-testid="stSidebar"] h1 {
    font-size: 1.35rem;
    font-weight: 900;
    letter-spacing: 0;
    margin-bottom: .25rem;
}
[data-testid="stSidebar"] h3 {
    color: #F8FAFC;
    font-size: .96rem;
    font-weight: 850;
    margin-top: .85rem;
}
[data-testid="stSidebar"] [data-testid="stForm"] {
    border: 1px solid rgba(148,163,184,.18);
    background: rgba(15,23,42,.48);
    border-radius: 10px;
    padding: 12px;
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #111C2F;
    border-color: rgba(148,163,184,.22);
    color: #F8FAFC;
}

.top-shell {
    display: flex;
    align-items: stretch;
    justify-content: space-between;
    gap: 18px;
    border: 1px solid var(--radar-line);
    background: linear-gradient(135deg, #FFFFFF 0%, #F8FAFC 62%, #EEF6FF 100%);
    border-radius: 12px;
    padding: 22px 24px;
    margin-bottom: 16px;
    box-shadow: 0 12px 34px rgba(15,23,42,.06);
}
.top-kicker {
    color: var(--radar-teal);
    font-size: .74rem;
    text-transform: uppercase;
    font-weight: 900;
    letter-spacing: .08em;
    margin-bottom: 6px;
}
.radar-title {
    color: var(--radar-ink);
    font-size: 1.92rem;
    font-weight: 950;
    margin: 0;
    letter-spacing: 0;
}
.radar-subtitle {
    color: var(--radar-muted);
    margin-top: 7px;
    line-height: 1.48;
    max-width: 720px;
}
.hero-status {
    min-width: 240px;
    border: 1px solid var(--radar-line);
    background: rgba(255,255,255,.80);
    border-radius: 10px;
    padding: 13px 14px;
}
.hero-status-title {
    color: var(--radar-muted);
    font-size: .74rem;
    font-weight: 850;
    text-transform: uppercase;
    letter-spacing: .08em;
    margin-bottom: 8px;
}

.demo-banner {
    border: 1px solid rgba(180,83,9,.22);
    background: #FFFBEB;
    color: #92400E;
    border-radius: 10px;
    padding: 11px 13px;
    font-weight: 750;
    margin-bottom: 14px;
}

.metric-card {
    border: 1px solid var(--radar-line);
    background: var(--radar-panel);
    border-radius: 12px;
    padding: 16px 17px;
    min-height: 118px;
    box-shadow: 0 10px 28px rgba(15,23,42,.055);
}
.metric-label {
    color: var(--radar-muted);
    font-size: .72rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    font-weight: 850;
}
.metric-value {
    color: var(--radar-ink);
    font-size: 1.65rem;
    font-weight: 950;
    margin-top: 8px;
}
.metric-help {
    color: var(--radar-muted);
    font-size: .82rem;
    margin-top: 5px;
}
.metric-indicator {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-top: 9px;
    color: var(--radar-teal);
    background: var(--radar-teal-soft);
    border-radius: 999px;
    padding: 3px 8px;
    font-size: .72rem;
    font-weight: 850;
}

.soft-card {
    border: 1px solid var(--radar-line);
    background: var(--radar-panel);
    border-radius: 12px;
    padding: 16px;
    box-shadow: 0 10px 28px rgba(15,23,42,.045);
}
.section-note {
    color: var(--radar-muted);
    font-size: .92rem;
    margin-bottom: 10px;
}

.opportunity-card {
    border: 1px solid var(--radar-line);
    background: var(--radar-panel);
    border-radius: 12px;
    padding: 16px;
    min-height: 308px;
    box-shadow: 0 10px 28px rgba(15,23,42,.055);
}
.opportunity-card.excellent {
    border-color: rgba(15,118,110,.36);
    background: linear-gradient(180deg, #FFFFFF 0%, #F0FDFA 100%);
}
.opportunity-route {
    color: var(--radar-ink);
    font-weight: 900;
    font-size: 1.1rem;
    margin-top: 10px;
}
.opportunity-price {
    color: var(--radar-teal);
    font-weight: 950;
    font-size: 1.46rem;
    margin-top: 8px;
}
.opportunity-detail {
    color: var(--radar-muted);
    font-size: .85rem;
    margin-top: 6px;
    line-height: 1.38;
}

.tag {
    display:inline-flex;
    align-items:center;
    padding: 4px 8px;
    border-radius: 999px;
    background: #E0F2FE;
    color: #075985;
    font-size: .72rem;
    font-weight: 850;
}
.tag-muted { background: #F1F5F9; color: #475569; }
.tag-alert { background: #DCFCE7; color: #166534; }
.tag-demo { background: #FEF3C7; color: #92400E; }
.tag-good { background: #E0F2FE; color: #075985; }
.tag-great { background: #CCFBF1; color: #115E59; }
.tag-excellent { background: #DBEAFE; color: #1D4ED8; }
.tag-danger { background: #FEE2E2; color: #991B1B; }

.status-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    border-bottom: 1px solid rgba(148,163,184,.18);
    padding: 7px 0;
    font-size: .84rem;
}
.status-label { color: #94A3B8; }
.status-value { color: #F8FAFC; font-weight: 850; text-align: right; }
.status-pill {
    display: inline-flex;
    align-items: center;
    border-radius: 999px;
    padding: 4px 9px;
    font-size: .74rem;
    font-weight: 850;
}
.status-ok { background: #DCFCE7; color: #166534; }
.status-warn { background: #FEF3C7; color: #92400E; }
.status-info { background: #DBEAFE; color: #1D4ED8; }
.status-neutral { background: #F1F5F9; color: #475569; }

a.buy-link {
    color: var(--radar-blue) !important;
    font-weight: 850;
    text-decoration: none;
}

[data-testid="stTabs"] button {
    font-weight: 750;
}
[data-testid="stDataFrame"] {
    border: 1px solid var(--radar-line);
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 10px 26px rgba(15,23,42,.04);
}

@media (max-width: 900px) {
    .top-shell { display: block; }
    .hero-status { margin-top: 14px; min-width: auto; }
}
</style>
"""


def load_custom_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
