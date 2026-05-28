from __future__ import annotations

import streamlit as st


CSS = """
<style>
:root {
    --radar-bg: #08111F;
    --radar-panel: #0F1B2D;
    --radar-panel-soft: #13233A;
    --radar-ink: #F8FAFC;
    --radar-muted: #9AA8BC;
    --radar-line: rgba(148,163,184,.20);
    --radar-teal: #2DD4BF;
    --radar-teal-soft: rgba(45,212,191,.14);
    --radar-blue: #93C5FD;
    --radar-amber: #FBBF24;
    --radar-green: #86EFAC;
}

.stApp { background: var(--radar-bg); color: var(--radar-ink); }
.main .block-container {
    padding-top: 1.25rem;
    padding-bottom: 2.5rem;
    max-width: 1420px;
}

[data-testid="stSidebar"] {
    background: #0A1220;
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
    background: linear-gradient(135deg, #0F1B2D 0%, #10243A 58%, #0A1D2F 100%);
    border-radius: 12px;
    padding: 22px 24px;
    margin-bottom: 16px;
    box-shadow: 0 18px 42px rgba(0,0,0,.28);
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
    background: rgba(8,17,31,.62);
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
    border: 1px solid rgba(251,191,36,.32);
    background: rgba(251,191,36,.11);
    color: #FDE68A;
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
    box-shadow: 0 16px 34px rgba(0,0,0,.22);
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
    box-shadow: 0 16px 34px rgba(0,0,0,.18);
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
    box-shadow: 0 16px 34px rgba(0,0,0,.22);
}
.opportunity-card.excellent {
    border-color: rgba(45,212,191,.42);
    background: linear-gradient(180deg, #10243A 0%, #0D2A31 100%);
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
    background: rgba(147,197,253,.16);
    color: #BFDBFE;
    font-size: .72rem;
    font-weight: 850;
}
.tag-muted { background: rgba(148,163,184,.14); color: #CBD5E1; }
.tag-alert { background: rgba(134,239,172,.15); color: #BBF7D0; }
.tag-demo { background: rgba(251,191,36,.16); color: #FDE68A; }
.tag-good { background: rgba(147,197,253,.16); color: #BFDBFE; }
.tag-great { background: rgba(45,212,191,.16); color: #99F6E4; }
.tag-excellent { background: rgba(96,165,250,.18); color: #BFDBFE; }
.tag-danger { background: rgba(248,113,113,.16); color: #FECACA; }

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
.status-ok { background: rgba(134,239,172,.15); color: #BBF7D0; }
.status-warn { background: rgba(251,191,36,.16); color: #FDE68A; }
.status-info { background: rgba(147,197,253,.16); color: #BFDBFE; }
.status-neutral { background: rgba(148,163,184,.14); color: #CBD5E1; }

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
    box-shadow: 0 16px 32px rgba(0,0,0,.18);
}

@media (max-width: 900px) {
    .top-shell { display: block; }
    .hero-status { margin-top: 14px; min-width: auto; }
}
</style>
"""


def load_custom_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
