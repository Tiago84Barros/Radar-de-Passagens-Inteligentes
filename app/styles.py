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
    --radar-card-radius: 16px;
}

/* ── Base ─────────────────────────────────────────────────────── */
.stApp { background: var(--radar-bg); color: var(--radar-ink); }
.main .block-container {
    padding-top: 1.25rem;
    padding-bottom: 2.5rem;
    max-width: 1440px;
}

/* ── Sidebar ─────────────────────────────────────────────────── */
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

/* ── Header / Hero ───────────────────────────────────────────── */
.top-shell {
    display: flex;
    align-items: stretch;
    justify-content: space-between;
    gap: 18px;
    border: 1px solid var(--radar-line);
    background: linear-gradient(135deg, #0F1B2D 0%, #10243A 58%, #0A1D2F 100%);
    border-radius: 14px;
    padding: 24px 28px;
    margin-bottom: 20px;
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
    font-size: 2.1rem;
    font-weight: 950;
    margin: 0;
    letter-spacing: -.01em;
}
.radar-subtitle {
    color: var(--radar-muted);
    margin-top: 8px;
    line-height: 1.5;
    max-width: 720px;
    font-size: 1.02rem;
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

/* ── Demo / Warning banner ───────────────────────────────────── */
.demo-banner {
    border: 1px solid rgba(251,191,36,.32);
    background: rgba(251,191,36,.11);
    color: #FDE68A;
    border-radius: 10px;
    padding: 11px 13px;
    font-weight: 750;
    margin-bottom: 14px;
}

/* ── Metric cards ─────────────────────────────────────────────── */
.metric-card {
    border: 1px solid var(--radar-line);
    background: var(--radar-panel);
    border-radius: 13px;
    padding: 17px 18px;
    min-height: 120px;
    box-shadow: 0 16px 34px rgba(0,0,0,.22);
    transition: border-color .2s;
}
.metric-card:hover { border-color: rgba(45,212,191,.35); }
.metric-label {
    color: var(--radar-muted);
    font-size: .72rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    font-weight: 850;
}
.metric-info {
    display: inline-block;
    margin-left: 5px;
    color: var(--radar-teal);
    cursor: help;
    font-weight: 700;
    opacity: .75;
    text-transform: none;
}
.metric-info:hover { opacity: 1; }
.metric-card { cursor: default; }
.metric-value {
    color: var(--radar-ink);
    font-size: 1.65rem;
    font-weight: 950;
    margin-top: 8px;
    line-height: 1.1;
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

/* ── Section headers ──────────────────────────────────────────── */
.deals-section-header {
    font-size: 1.42rem;
    font-weight: 900;
    color: var(--radar-ink);
    margin: 28px 0 4px 0;
    letter-spacing: -.01em;
    display: flex;
    align-items: center;
    gap: 10px;
}
.deals-section-subtitle {
    color: var(--radar-muted);
    font-size: .93rem;
    margin-bottom: 14px;
    line-height: 1.45;
}

/* ── Airline comparison cards ────────────────────────────────── */
.airline-cmp-grid {
    display: grid;
    gap: .85rem;
    align-items: stretch;
    margin-bottom: .5rem;
}
.airline-cmp-card {
    border: 1px solid var(--radar-line);
    background: var(--radar-panel);
    border-radius: 14px;
    padding: 14px 16px 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    transition: transform .16s ease, border-color .16s ease;
}
.airline-cmp-card:hover {
    transform: translateY(-2px);
    border-color: rgba(45,212,191,.38);
}
.airline-cmp-card-best {
    border-color: var(--radar-teal);
    background: linear-gradient(180deg, rgba(45,212,191,.10), var(--radar-panel) 60%);
    box-shadow: 0 14px 34px rgba(45,212,191,.14);
}
.airline-cmp-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 40px;
}
.airline-logo { height: 34px; width: auto; object-fit: contain; }
.airline-logo-fallback { font-size: 1.6rem; }
.airline-best-badge {
    background: var(--radar-teal);
    color: #06231d;
    font-size: .66rem;
    font-weight: 800;
    padding: 2px 8px;
    border-radius: 999px;
    letter-spacing: .02em;
    white-space: nowrap;
}
.airline-cmp-name {
    color: var(--radar-ink);
    font-size: .98rem;
    font-weight: 750;
}
.airline-demo-tag {
    color: var(--radar-amber);
    font-size: .64rem;
    border: 1px solid rgba(251,191,36,.4);
    border-radius: 6px;
    padding: 1px 5px;
    margin-left: 6px;
    vertical-align: middle;
}
.airline-cmp-price {
    color: var(--radar-teal);
    font-size: 1.5rem;
    font-weight: 850;
    line-height: 1.15;
}
.airline-cmp-miles { color: var(--radar-amber); font-size: .86rem; }
.airline-cmp-btn {
    display: block;
    text-align: center;
    margin-top: 8px;
    padding: 7px 0;
    border-radius: 9px;
    background: rgba(45,212,191,.16);
    color: var(--radar-teal) !important;
    border: 1px solid rgba(45,212,191,.34);
    font-weight: 750;
    font-size: .84rem;
    text-decoration: none;
}
.airline-cmp-btn:hover { background: rgba(45,212,191,.28); }

/* ── Deal cards grid ─────────────────────────────────────────── */
.deal-cards-grid {
    display: grid;
    gap: 1rem;
    align-items: start;
    margin-bottom: .5rem;
}

/* ── "Dados Ausentes" placeholder (no real data collected yet) ── */
.dados-ausentes {
    border: 1px dashed var(--radar-line);
    background: rgba(255,255,255,0.02);
    border-radius: var(--radar-card-radius);
    padding: 1.25rem 1rem;
    text-align: center;
    color: var(--radar-muted, #94a3b8);
    margin: .25rem 0 1rem;
}
.dados-ausentes strong {
    color: #e2e8f0;
    font-size: 1.05rem;
}
.dados-ausentes span {
    display: block;
    margin-top: .35rem;
    font-size: .85rem;
    line-height: 1.4;
}

/* ── Deal cards (home screen opportunities) ───────────────────── */
.deal-card {
    border: 1px solid var(--radar-line);
    background: var(--radar-panel);
    border-radius: var(--radar-card-radius);
    overflow: hidden;
    box-shadow: 0 18px 42px rgba(0,0,0,.26);
    transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    margin-bottom: 6px;
    display: flex;
    flex-direction: column;
    height: 100%;
}
.deal-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 28px 60px rgba(0,0,0,.40);
    border-color: rgba(45,212,191,.38);
}

.deal-card-header {
    position: relative;
    height: 178px;
    background-size: cover !important;
    background-position: center !important;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 12px 14px 14px;
}
.deal-card-header-top {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    align-items: flex-start;
}
.deal-card-destination {
    color: #FFFFFF;
    font-size: 1.35rem;
    font-weight: 950;
    text-shadow: 0 3px 12px rgba(0,0,0,.55);
    line-height: 1.15;
    letter-spacing: -.01em;
    margin-top: auto;
}
.deal-card-country {
    color: rgba(255,255,255,.80);
    font-size: .82rem;
    font-weight: 750;
    text-shadow: 0 2px 8px rgba(0,0,0,.55);
    margin-top: 2px;
}

.deal-card-body {
    padding: 14px 16px 16px;
    display: flex;
    flex-direction: column;
    gap: 5px;
    flex: 1;
}
.deal-card-route {
    color: var(--radar-ink);
    font-size: .98rem;
    font-weight: 900;
    letter-spacing: -.01em;
}
.deal-card-iata {
    color: var(--radar-muted);
    font-size: .74rem;
    font-weight: 850;
    letter-spacing: .05em;
    text-transform: uppercase;
    margin-top: -3px;
}
.deal-card-dates {
    color: var(--radar-muted);
    font-size: .84rem;
    margin-top: 2px;
}
.deal-card-price {
    color: var(--radar-teal);
    font-size: 1.65rem;
    font-weight: 950;
    margin-top: 4px;
    letter-spacing: -.02em;
    line-height: 1.1;
}
.deal-card-miles {
    color: var(--radar-amber);
    font-size: .92rem;
    font-weight: 850;
    display: flex;
    align-items: center;
    gap: 5px;
}
.miles-est-tag {
    color: var(--radar-muted);
    font-size: .72rem;
    font-weight: 700;
    background: rgba(148,163,184,.12);
    border-radius: 999px;
    padding: 1px 6px;
}
.deal-card-meta {
    color: var(--radar-muted);
    font-size: .82rem;
    margin-top: 2px;
}
.deal-card-meta strong { color: var(--radar-ink); }

.deal-card-btn {
    display: block;
    text-align: center;
    background: var(--radar-teal);
    color: #08111F !important;
    font-weight: 900;
    font-size: .86rem;
    border-radius: 8px;
    padding: 9px 14px;
    text-decoration: none !important;
    margin-top: 10px;
    transition: background .15s, opacity .15s;
    letter-spacing: .01em;
}
.deal-card-btn:hover { background: #5EEAD4; }
.deal-card-btn-demo {
    background: rgba(45,212,191,.18);
    color: var(--radar-teal) !important;
    border: 1px solid rgba(45,212,191,.38);
}
.deal-card-btn-demo:hover { background: rgba(45,212,191,.28); }

/* ── Deal badges ──────────────────────────────────────────────── */
.deal-badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: .70rem;
    font-weight: 850;
    letter-spacing: .02em;
    text-transform: uppercase;
    white-space: nowrap;
}
.badge-national  { background: rgba(16,185,129,.20); color: #6EE7B7; }
.badge-intl      { background: rgba(129,140,248,.20); color: #C7D2FE; }
.badge-excellent { background: rgba(251,191,36,.22); color: #FDE68A; }
.badge-great     { background: rgba(45,212,191,.20); color: #99F6E4; }
.badge-good      { background: rgba(147,197,253,.18); color: #BFDBFE; }
.badge-muted       { background: rgba(148,163,184,.14); color: #CBD5E1; }
.badge-demo        { background: rgba(251,191,36,.16); color: #FDE68A; }
.badge-connection  { background: rgba(45,212,191,.22); color: #99F6E4; }

.deal-card-combined-note {
    color: #FDE68A;
    font-size: .72rem;
    line-height: 1.4;
    margin-top: 4px;
    padding: 4px 8px;
    background: rgba(251,191,36,.10);
    border-radius: 6px;
    border-left: 2px solid rgba(251,191,36,.45);
}

/* ── Legacy opportunity cards (Oportunidades tab) ─────────────── */
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
    border-radius: 14px;
    padding: 18px;
    min-height: 300px;
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
.opportunity-miles {
    color: var(--radar-amber);
    font-weight: 850;
    font-size: .96rem;
    margin-top: 3px;
}
.opportunity-detail {
    color: var(--radar-muted);
    font-size: .85rem;
    margin-top: 6px;
    line-height: 1.38;
}

/* ── Generic tags ────────────────────────────────────────────── */
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
.tag-muted     { background: rgba(148,163,184,.14); color: #CBD5E1; }
.tag-alert     { background: rgba(134,239,172,.15); color: #BBF7D0; }
.tag-demo      { background: rgba(251,191,36,.16); color: #FDE68A; }
.tag-good      { background: rgba(147,197,253,.16); color: #BFDBFE; }
.tag-great     { background: rgba(45,212,191,.16); color: #99F6E4; }
.tag-excellent { background: rgba(96,165,250,.18); color: #BFDBFE; }
.tag-danger    { background: rgba(248,113,113,.16); color: #FECACA; }

/* ── Status rows (sidebar) ───────────────────────────────────── */
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
.status-ok      { background: rgba(134,239,172,.15); color: #BBF7D0; }
.status-warn    { background: rgba(251,191,36,.16); color: #FDE68A; }
.status-info    { background: rgba(147,197,253,.16); color: #BFDBFE; }
.status-neutral { background: rgba(148,163,184,.14); color: #CBD5E1; }

/* ── Route postcard (year calendar) ─────────────────────────── */
.route-postcard {
    position: relative;
    min-height: 285px;
    border: 1px solid var(--radar-line);
    border-radius: 18px;
    background-size: cover;
    background-position: center;
    overflow: hidden;
    margin: 14px 0 20px;
    box-shadow: 0 22px 52px rgba(0,0,0,.34);
}
.route-postcard::after {
    content: "";
    position: absolute;
    inset: 16px;
    border: 1px solid rgba(255,255,255,.20);
    border-radius: 13px;
    pointer-events: none;
}
.route-postcard-content {
    position: relative;
    z-index: 1;
    display: flex;
    min-height: 285px;
    flex-direction: column;
    justify-content: flex-end;
    max-width: 760px;
    padding: 28px 32px;
}
.route-postcard-title {
    display: flex;
    align-items: center;
    gap: 14px;
    color: #FFFFFF;
    font-size: clamp(2.1rem, 4vw, 4.4rem);
    font-weight: 950;
    line-height: .95;
    text-shadow: 0 7px 28px rgba(0,0,0,.52);
}
.route-arrow {
    color: var(--radar-teal);
    font-size: clamp(.95rem, 1.4vw, 1.25rem);
    font-weight: 950;
    letter-spacing: .12em;
    text-transform: uppercase;
    padding: 8px 12px;
    border: 1px solid rgba(45,212,191,.38);
    border-radius: 999px;
    background: rgba(8,17,31,.52);
}
.route-postcard-subtitle {
    color: #E5EDF8;
    font-size: 1.08rem;
    font-weight: 820;
    margin-top: 12px;
    text-shadow: 0 5px 18px rgba(0,0,0,.45);
}
.route-postcard-meta {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 16px;
}
.route-postcard-meta span {
    display: inline-flex;
    align-items: center;
    border-radius: 999px;
    padding: 7px 11px;
    color: #DBEAFE;
    background: rgba(15,27,45,.72);
    border: 1px solid rgba(147,197,253,.22);
    font-size: .82rem;
    font-weight: 850;
}

/* ── Links ───────────────────────────────────────────────────── */
a.buy-link {
    color: var(--radar-blue) !important;
    font-weight: 850;
    text-decoration: none;
}

/* ── Malha aérea expandida ───────────────────────────────────── */
.malha-banner {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    border: 1px solid rgba(45,212,191,.28);
    background: linear-gradient(135deg, rgba(45,212,191,.08) 0%, rgba(15,27,45,.70) 100%);
    border-radius: 12px;
    padding: 13px 16px;
    color: #E5EDF8;
    font-size: .90rem;
    line-height: 1.5;
    margin-bottom: 4px;
}
.malha-banner-icon { font-size: 1.3rem; flex-shrink: 0; margin-top: 1px; }
.malha-banner strong { color: var(--radar-teal); }

.malha-info {
    border: 1px solid rgba(45,212,191,.22);
    background: rgba(45,212,191,.06);
    border-radius: 10px;
    padding: 10px 12px;
    margin: 8px 0;
}
.malha-title {
    color: var(--radar-teal);
    font-size: .78rem;
    font-weight: 850;
    text-transform: uppercase;
    letter-spacing: .06em;
    margin-bottom: 5px;
}
.malha-desc { color: var(--radar-muted); font-size: .78rem; margin-bottom: 4px; }
.malha-hubs { color: var(--radar-ink); font-size: .84rem; font-weight: 850; letter-spacing: .05em; }
.malha-route { color: var(--radar-teal); font-size: .78rem; margin-top: 4px; opacity: .85; }

.tag-connection { background: rgba(45,212,191,.18); color: #99F6E4; }
.via-hub-tag { color: #99F6E4 !important; font-weight: 750; }

/* ── Milhas tab ──────────────────────────────────────────────── */
.miles-card {
    border: 1px solid rgba(251,191,36,.25);
    background: linear-gradient(135deg, #1a1a0a 0%, #0f1b2d 100%);
    border-radius: 13px;
    padding: 18px;
    min-height: 120px;
    box-shadow: 0 16px 34px rgba(0,0,0,.22);
}
.miles-card-label {
    color: rgba(251,191,36,.8);
    font-size: .72rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    font-weight: 850;
}
.miles-card-value {
    color: var(--radar-amber);
    font-size: 1.55rem;
    font-weight: 950;
    margin-top: 8px;
}
.miles-disclaimer {
    border: 1px solid rgba(251,191,36,.22);
    background: rgba(251,191,36,.08);
    border-radius: 10px;
    padding: 12px 16px;
    color: #FDE68A;
    font-size: .88rem;
    line-height: 1.5;
    margin: 14px 0;
}

/* ── Tabs ────────────────────────────────────────────────────── */
[data-testid="stTabs"] button {
    font-weight: 750;
}
[data-testid="stDataFrame"] {
    border: 1px solid var(--radar-line);
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 16px 32px rgba(0,0,0,.18);
}

/* ── Responsive ──────────────────────────────────────────────── */
@media (max-width: 900px) {
    .top-shell { display: block; }
    .hero-status { margin-top: 14px; min-width: auto; }
    .route-postcard { min-height: 240px; }
    .route-postcard-content { min-height: 240px; padding: 22px; }
    .route-postcard-title { display: grid; gap: 8px; }
    .route-arrow { width: fit-content; }
    .deal-card-header { height: 150px; }
    .deal-cards-grid { grid-template-columns: 1fr !important; }
    .airline-cmp-grid { grid-template-columns: 1fr 1fr !important; }
}
</style>
"""


def load_custom_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
