from __future__ import annotations

import streamlit as st


CSS = """
<style>
/* ── "Horizonte" — paleta e tipografia da marca ──────────────────
   Identidade nova (jun/2026): indigo-noturno + acento ambar de
   "horizonte ao amanhecer", contraponto frio em periwinkle. Display
   serifado com personalidade (Fraunces) + corpo refinado (IBM Plex
   Sans) — evitando Inter/Roboto/Arial e o vermelho padrao do
   Streamlit. As variaveis --radar-* mantem os nomes legados para nao
   quebrar os ~40 componentes que ja consomem este sistema; so os
   valores (a paleta) mudam. */
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700;9..144,900&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');

:root {
    --radar-bg: #11142A;
    --radar-panel: #1B1F3B;
    --radar-panel-soft: #242A4D;
    --radar-ink: #F5F1E8;
    --radar-muted: #A6ABCB;
    --radar-line: rgba(166,171,203,.20);
    --radar-teal: #F2A154;
    --radar-teal-soft: rgba(242,161,84,.14);
    --radar-blue: #7C9CF5;
    --radar-amber: #F2755A;
    --radar-green: #7BC9A0;
    --radar-card-radius: 16px;
    --radar-font-display: 'Fraunces', Georgia, serif;
    --radar-font-body: 'IBM Plex Sans', -apple-system, sans-serif;
}

/* ── Base ─────────────────────────────────────────────────────── */
.stApp { background: var(--radar-bg); color: var(--radar-ink); font-family: var(--radar-font-body); }
.stApp, .stApp p, .stApp span, .stApp label, .stApp div { font-family: var(--radar-font-body); }
[data-testid="stIconMaterial"], .material-symbols-rounded, .material-symbols-outlined, .material-icons {
    font-family: 'Material Symbols Rounded', 'Material Icons' !important;
}
.stApp h1, .stApp h2, .stApp h3,
.radar-title, .origin-card-code, .deal-card-destination, .opp-card-code,
.route-postcard-title, .decision-hero-verdict, .login-brand .login-title,
.deals-section-header, .search-summary-title {
    font-family: var(--radar-font-display) !important;
    letter-spacing: -.01em;
}

/* ── Origin postcard card (Home tab) ──────────────────────────── */
.origin-card {
    position: relative;
    border-radius: 20px;
    overflow: hidden;
    min-height: 200px;
    background-size: cover;
    background-position: center;
    background-color: #0d1e30;
    border: 1px solid rgba(45,212,191,.25);
    box-shadow: 0 18px 44px rgba(0,0,0,.4);
    margin: 4px 0 18px;
    display: flex;
    align-items: center;
}
.origin-card-inner {
    padding: 26px 30px;
    width: 100%;
}
.origin-card-kicker {
    color: var(--radar-teal);
    font-size: .8rem;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
    margin-bottom: 6px;
}
.origin-card-code {
    color: #ffffff;
    font-size: 3rem;
    font-weight: 950;
    line-height: 1;
    letter-spacing: .02em;
    text-shadow: 0 2px 18px rgba(0,0,0,.55);
}
.origin-card-city {
    color: var(--radar-ink);
    font-size: 1.5rem;
    font-weight: 800;
    margin-top: 4px;
    text-shadow: 0 1px 10px rgba(0,0,0,.5);
}
.origin-card-country {
    color: var(--radar-blue);
    font-size: .95rem;
    font-weight: 600;
    margin-top: 2px;
}
.origin-card-postcard {
    color: #d7e3f4;
    font-size: .85rem;
    margin-top: 12px;
    opacity: .9;
}

/* ── Login screen ─────────────────────────────────────────────── */
.login-page {
    position: fixed;
    inset: 0;
    background:
        radial-gradient(1100px 620px at 50% -8%, rgba(45,212,191,.14), transparent 58%),
        radial-gradient(900px 520px at 92% 108%, rgba(147,197,253,.10), transparent 60%),
        var(--radar-bg);
    z-index: -1;
}
/* Push the login card toward the vertical middle and hide chrome */
.main .block-container:has(.login-brand) { padding-top: 8vh; max-width: 1440px; }
.main .block-container:has(.login-brand) [data-testid="stHeader"],
header:has(~ .stApp .login-brand) { display: none; }

/* The login card = the form that contains .login-brand (scoped, won't touch other forms) */
[data-testid="stForm"]:has(.login-brand) {
    background: linear-gradient(180deg, rgba(20,37,61,.96) 0%, rgba(13,24,42,.96) 100%) !important;
    border: 1px solid rgba(45,212,191,.28) !important;
    border-radius: 22px !important;
    padding: 38px 36px 30px !important;
    box-shadow: 0 30px 70px rgba(0,0,0,.5), 0 0 0 1px rgba(255,255,255,.03) inset !important;
}
.login-brand { text-align: center; margin-bottom: 22px; }
.login-logo {
    width: 70px;
    height: 70px;
    margin: 0 auto 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 2.1rem;
    border-radius: 20px;
    background: linear-gradient(135deg, rgba(45,212,191,.26), rgba(45,212,191,.04));
    border: 1px solid rgba(45,212,191,.4);
    box-shadow: 0 10px 28px rgba(45,212,191,.22);
}
.login-brand .login-title {
    color: var(--radar-ink) !important;
    font-size: 1.7rem !important;
    font-weight: 900 !important;
    letter-spacing: -.02em !important;
    line-height: 1.12 !important;
    margin: 0 !important;
    padding: 0 !important;
    text-align: center !important;
}
.login-brand .login-subtitle {
    color: var(--radar-muted) !important;
    font-size: .95rem !important;
    margin: 10px 0 0 !important;
    line-height: 1.4;
}
.login-brand .login-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(148,163,184,.35), transparent);
    margin: 22px 0 16px;
}
.login-brand .login-prompt {
    color: var(--radar-blue) !important;
    font-size: .9rem !important;
    font-weight: 650 !important;
    margin: 0 !important;
}
/* Inputs / button inside the login card */
[data-testid="stForm"]:has(.login-brand) [data-testid="stTextInput"] label {
    font-weight: 700;
    color: var(--radar-ink);
}
[data-testid="stForm"]:has(.login-brand) [data-baseweb="input"] {
    border-radius: 10px;
}
[data-testid="stForm"]:has(.login-brand) .stButton > button,
[data-testid="stForm"]:has(.login-brand) [data-testid="stFormSubmitButton"] > button {
    border-radius: 11px;
    font-weight: 800;
    font-size: .98rem;
    padding: 11px 0;
    margin-top: 6px;
    background: linear-gradient(135deg, #2DD4BF, #14b8a6);
    border: none;
    box-shadow: 0 8px 22px rgba(45,212,191,.28);
}
[data-testid="stForm"]:has(.login-brand) [data-testid="stFormSubmitButton"] > button:hover {
    filter: brightness(1.06);
}
.login-footer {
    text-align: center;
    color: var(--radar-muted);
    font-size: .78rem;
    margin-top: 16px;
    opacity: .75;
}
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

/* Hint that these labels carry an explanatory tooltip (title attr) */
.deal-card-meta[title], .deal-card-miles[title], .deal-card-price[title],
.deal-badge[title], .airline-cmp-miles[title], .airline-cmp-price[title],
.airline-best-badge[title], .airline-demo-tag[title] { cursor: help; }
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
.airline-cmp-route {
    font-size: .82rem;
    color: var(--radar-muted);
    margin-top: 4px;
    cursor: help;
}
.airline-cmp-duration {
    font-size: .82rem;
    color: var(--radar-ink);
    margin-top: 2px;
    cursor: help;
}
.airline-cmp-duration-missing { color: var(--radar-muted); font-style: italic; }
.route-type {
    display: inline-block;
    font-size: .68rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: .03em;
    padding: 1px 7px;
    border-radius: 999px;
    margin-right: 5px;
    vertical-align: middle;
}
.route-type-direct {
    background: rgba(45,212,191,.18);
    color: var(--radar-teal);
    border: 1px solid rgba(45,212,191,.4);
}
.route-type-combined {
    background: rgba(168,131,255,.16);
    color: #c4b0ff;
    border: 1px solid rgba(168,131,255,.4);
}
.route-type-stops {
    background: rgba(251,191,36,.14);
    color: var(--radar-amber);
    border: 1px solid rgba(251,191,36,.36);
}
/* Direct-vs-best summary banner */
.cmp-summary {
    background: rgba(13,30,48,.55);
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 12px;
    padding: 12px 16px;
    margin: 4px 0 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.cmp-summary-row {
    font-size: .9rem;
    color: var(--radar-ink);
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
}
.cmp-summary-tag {
    font-size: .68rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: .03em;
    padding: 2px 8px;
    border-radius: 999px;
}
.cmp-summary-tag.tag-best {
    background: rgba(45,212,191,.18);
    color: var(--radar-teal);
    border: 1px solid rgba(45,212,191,.4);
}
.cmp-summary-tag.tag-direct {
    background: rgba(168,131,255,.16);
    color: #c4b0ff;
    border: 1px solid rgba(168,131,255,.4);
}
.cmp-summary-tag.tag-none {
    background: rgba(148,163,184,.14);
    color: var(--radar-muted);
    border: 1px solid rgba(148,163,184,.3);
}
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
.deal-card-duration {
    color: var(--radar-muted);
    font-size: .82rem;
    margin-top: 3px;
    cursor: help;
}
.deal-card-duration[title] {
    cursor: help;
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

/* ── Home empty states ───────────────────────────────────────── */
.home-empty {
    margin: 26px 0;
    padding: 30px 26px;
    border: 1px dashed rgba(148,163,184,.32);
    border-radius: var(--radar-card-radius);
    background: rgba(148,163,184,.05);
    color: var(--radar-muted);
    font-size: 1.04rem;
    line-height: 1.5;
    text-align: center;
}
.home-empty strong { color: var(--radar-ink); }

/* ── Airport postcards (origin / destination) ────────────────── */
.airport-card {
    position: relative;
    min-height: 220px;
    border-radius: var(--radar-card-radius);
    background-size: cover;
    background-position: center;
    overflow: hidden;
    border: 1px solid rgba(148,163,184,.16);
    box-shadow: 0 10px 28px rgba(3,8,18,.45);
    margin-bottom: 8px;
}
.airport-card-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    gap: 2px;
    padding: 18px 20px;
}
.airport-card-badge {
    align-self: flex-start;
    font-size: .74rem;
    font-weight: 800;
    letter-spacing: .02em;
    padding: 4px 11px;
    border-radius: 999px;
    margin-bottom: auto;
    backdrop-filter: blur(3px);
}
.airport-card-fallback {
    position: absolute; top: 14px; right: 14px;
    font-size: .66rem; font-weight: 700; color: #e5edf8;
    background: rgba(15,23,42,.6); padding: 2px 8px; border-radius: 999px;
    backdrop-filter: blur(3px);
}
.badge-origin { background: rgba(45,212,191,.85); color: #06241f; }
.badge-dest   { background: rgba(251,191,36,.88); color: #2a1c00; }
.airport-card-code {
    font-size: 2rem;
    font-weight: 900;
    color: #fff;
    letter-spacing: .04em;
    line-height: 1.05;
}
.airport-card-city {
    font-size: 1.18rem;
    font-weight: 800;
    color: #fff;
}
.airport-card-country {
    font-size: .9rem;
    color: rgba(248,250,252,.82);
}
.airport-card-name {
    font-size: .84rem;
    color: rgba(248,250,252,.72);
    margin-top: 2px;
}

/* ── Fare cards (best price per airline) ─────────────────────── */
.fare-cards-grid {
    display: grid;
    gap: 14px;
    align-items: stretch;
    margin: 4px 0 6px 0;
}
.fare-card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 18px;
    border-radius: 14px;
    background: rgba(20,32,50,.72);
    border: 1px solid rgba(148,163,184,.16);
    box-shadow: 0 6px 18px rgba(3,8,18,.34);
}
.fare-card-cheapest {
    border: 1.5px solid var(--radar-teal);
    box-shadow: 0 0 0 1px var(--radar-teal-soft), 0 10px 26px rgba(45,212,191,.16);
    background: linear-gradient(180deg, rgba(45,212,191,.08), rgba(20,32,50,.72));
}
.fare-card-best {
    align-self: flex-start;
    font-size: .74rem;
    font-weight: 800;
    color: #06241f;
    background: var(--radar-teal);
    padding: 3px 10px;
    border-radius: 999px;
    margin-bottom: 2px;
}
.fare-card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.fare-card-airline { font-weight: 800; color: var(--radar-ink); font-size: 1.02rem; }
.fare-badge {
    margin-left: auto;
    font-size: .72rem;
    font-weight: 800;
    padding: 3px 9px;
    border-radius: 999px;
}
.fare-card-route { font-weight: 700; color: var(--radar-ink); font-size: .98rem; }
.fare-card-route-iata { font-size: .8rem; color: var(--radar-muted); letter-spacing: .03em; }
.fare-card-dates { font-size: .86rem; color: var(--radar-muted); }
.fare-card-price { font-size: 1.7rem; font-weight: 900; color: var(--radar-teal); letter-spacing: -.01em; }
.fare-card-miles { font-size: .9rem; color: #E5EDF8; }
.fare-card-meta { font-size: .85rem; color: var(--radar-muted); }
.fare-card-foot { font-size: .78rem; color: var(--radar-muted); }
.fare-card-age {
    align-self: flex-start;
    font-size: .74rem;
    font-weight: 700;
    color: #99F6E4;
    background: rgba(45,212,191,.12);
    padding: 3px 9px;
    border-radius: 999px;
}
.fare-card-age-stale {
    color: #FBBF24;
    background: rgba(251,191,36,.12);
}
.fare-card-note {
    font-size: .8rem;
    color: #FBBF24;
    background: rgba(251,191,36,.1);
    border-radius: 8px;
    padding: 6px 9px;
}
.fare-card-btn {
    margin-top: auto;
    display: inline-block;
    text-align: center;
    text-decoration: none;
    font-weight: 800;
    font-size: .9rem;
    padding: 9px 12px;
    border-radius: 10px;
    background: var(--radar-teal);
    color: #06241f !important;
    transition: filter .15s ease;
}
.fare-card-btn:hover { filter: brightness(1.08); }

/* ── Monitor conflict prompt ─────────────────────────────────── */
.monitor-conflict {
    margin: 8px 0 12px 0;
    padding: 16px 18px;
    border-radius: 12px;
    border: 1px solid rgba(251,191,36,.34);
    background: rgba(251,191,36,.08);
    color: var(--radar-ink);
    font-size: .96rem;
    line-height: 1.5;
}

/* ── Decision radar: recommendation hero ─────────────────────── */
.decision-hero {
    margin: 18px 0 14px 0;
    padding: 22px 24px;
    border-radius: var(--radar-card-radius);
    background: rgba(20,32,50,.72);
    border: 1px solid rgba(148,163,184,.16);
    border-left: 6px solid var(--radar-teal);
    box-shadow: 0 10px 28px rgba(3,8,18,.4);
}
.decision-buy     { border-left-color: #34D399; }
.decision-miles   { border-left-color: #FBBF24; }
.decision-monitor { border-left-color: #60A5FA; }
.decision-cash    { border-left-color: #34D399; }
.decision-wait    { border-left-color: #94A3B8; }
.decision-hero-top { display: flex; justify-content: space-between; align-items: center; }
.decision-hero-kicker {
    text-transform: uppercase; letter-spacing: .08em; font-size: .76rem;
    font-weight: 800; color: var(--radar-muted);
}
.decision-hero-confidence {
    font-size: .78rem; font-weight: 800; color: var(--radar-teal);
    background: var(--radar-teal-soft); padding: 3px 10px; border-radius: 999px;
}
.decision-hero-verdict { font-size: 2rem; font-weight: 900; color: var(--radar-ink); margin: 6px 0 2px; }
.decision-hero-reason { font-size: 1.02rem; color: var(--radar-ink); margin-bottom: 6px; }
.decision-hero-reasons { margin: 0; padding-left: 18px; color: var(--radar-muted); font-size: .9rem; }
.decision-hero-reasons li { margin: 2px 0; }

/* ── Resumo da busca ─────────────────────────────────────────── */
.search-summary {
    margin: 14px 0; padding: 18px 20px; border-radius: var(--radar-card-radius);
    background: rgba(20,32,50,.72); border: 1px solid rgba(148,163,184,.16);
    border-left: 6px solid var(--radar-teal);
}
.search-summary-buy { border-left-color: #34D399; }
.search-summary-miles { border-left-color: #FBBF24; }
.search-summary-monitor { border-left-color: #60A5FA; }
.search-summary-wait { border-left-color: #94A3B8; }
.search-summary-title { font-size: 1.1rem; font-weight: 900; color: var(--radar-ink); margin-bottom: 8px; }
.summary-row { display: flex; justify-content: space-between; gap: 12px; padding: 3px 0;
    border-bottom: 1px dashed rgba(148,163,184,.12); font-size: .94rem; }
.summary-row span { color: var(--radar-muted); }
.summary-row b { color: var(--radar-ink); font-weight: 800; }
.summary-logo { height: 18px; vertical-align: middle; margin-right: 6px; border-radius: 3px; background:#fff; padding:1px 3px; }
.summary-airlines { margin-top: 10px; font-size: .9rem; color: var(--radar-ink); }
.summary-airlines span { color: var(--radar-muted); }

/* ── Best-option cards (cash / miles) ────────────────────────── */
.option-card {
    padding: 16px 18px; border-radius: 14px; height: 100%;
    background: rgba(20,32,50,.66); border: 1px solid rgba(148,163,184,.16);
}
.option-miles { border-color: rgba(251,191,36,.34); }
.option-cash  { border-color: rgba(52,211,153,.30); }
.option-card-title { font-size: .88rem; font-weight: 800; color: var(--radar-muted); }
.option-card-value { font-size: 1.8rem; font-weight: 900; color: var(--radar-ink); margin: 4px 0; }
.option-card-sub { font-size: .9rem; color: var(--radar-teal); }
.option-card-meta { font-size: .82rem; color: var(--radar-muted); margin-top: 4px; }
.option-empty { opacity: .7; }
.option-card-empty { color: var(--radar-muted); font-size: .95rem; margin-top: 6px; }

/* ── Radar overview KPI strip ────────────────────────────────── */
.radar-overview-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 6px 0 4px;
}
.radar-card {
    padding: 16px 18px; border-radius: 14px;
    background: rgba(20,32,50,.66); border: 1px solid rgba(148,163,184,.16);
}
.radar-rec  { border-left: 4px solid var(--radar-teal); }
.radar-mon  { border-left: 4px solid #60A5FA; }
.radar-miles { border-left: 4px solid #FBBF24; }
.radar-card-label { font-size: .82rem; font-weight: 800; color: var(--radar-muted); }
.radar-card-value { font-size: 1.5rem; font-weight: 900; color: var(--radar-ink); margin: 4px 0 2px; }
.radar-card-sub { font-size: .8rem; color: var(--radar-muted); }

/* ── Opportunity (destination) cards ─────────────────────────── */
.opp-group-title { font-size: 1.1rem; font-weight: 800; color: var(--radar-ink); margin: 14px 0 8px; }
.opp-card {
    position: relative; min-height: 260px; border-radius: var(--radar-card-radius);
    background-size: cover; background-position: center; overflow: hidden;
    border: 1px solid rgba(148,163,184,.16); box-shadow: 0 8px 22px rgba(3,8,18,.42);
    margin-bottom: 8px;
}
.opp-card-overlay { position: absolute; inset: 0; display: flex; flex-direction: column;
    justify-content: flex-end; gap: 2px; padding: 16px 18px; }
.opp-badge { align-self: flex-start; font-size: .72rem; font-weight: 800; padding: 3px 10px;
    border-radius: 999px; margin-bottom: auto; backdrop-filter: blur(3px); }
.opp-badge-buy    { background: rgba(52,211,153,.9); color: #06241f; }
.opp-badge-miles  { background: rgba(251,191,36,.92); color: #2a1c00; }
.opp-badge-monitor{ background: rgba(96,165,250,.9); color: #06203f; }
.opp-badge-cash   { background: rgba(52,211,153,.9); color: #06241f; }
.opp-badge-wait   { background: rgba(148,163,184,.85); color: #0b1422; }
.opp-card-code { font-size: 1.5rem; font-weight: 900; color: #fff; letter-spacing: .03em; }
.opp-demo { font-size: .6rem; font-weight: 800; background: rgba(148,163,184,.5); color: #0b1422;
    padding: 1px 6px; border-radius: 999px; vertical-align: middle; }
.opp-card-city { font-size: 1.05rem; font-weight: 800; color: #fff; }
.opp-card-country { font-size: .82rem; color: rgba(248,250,252,.8); }
.opp-card-price { font-size: 1.5rem; font-weight: 900; color: #5EEAD4; margin-top: 4px; }
.opp-card-miles { font-size: .84rem; color: rgba(248,250,252,.85); }
.opp-card-meta { font-size: .76rem; color: rgba(248,250,252,.7); margin-top: 2px; }
.opp-geo-badges { display: flex; flex-wrap: wrap; gap: 5px; margin: 5px 0 2px; }
.geo-badge { font-size: .68rem; font-weight: 800; padding: 2px 8px; border-radius: 999px;
    backdrop-filter: blur(3px); }
.geo-nat   { background: rgba(52,211,153,.85); color: #06241f; }
.geo-intl  { background: rgba(96,165,250,.85); color: #06203f; }
.geo-region{ background: rgba(248,250,252,.18); color: #fff; }
.geo-iata  { background: rgba(15,23,42,.55); color: #cbd5e1; letter-spacing: .04em; }

/* ── Applied geographic filter summary ───────────────────────── */
.filter-summary {
    margin: 4px 0 12px; padding: 10px 14px; border-radius: 10px;
    background: var(--radar-teal-soft); border: 1px solid rgba(45,212,191,.22);
    color: var(--radar-ink); font-size: .92rem;
}
.filter-count { color: var(--radar-teal); font-weight: 800; margin-left: 8px; }

/* ── Result cards (search results, comparator layout) ───────── */
.result-card {
    display: flex;
    align-items: center;
    gap: 18px;
    border: 1px solid var(--radar-line);
    background: var(--radar-panel);
    border-radius: var(--radar-card-radius);
    padding: 16px 20px;
    margin-bottom: 12px;
    box-shadow: 0 14px 34px rgba(0,0,0,.22);
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
.result-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 24px 50px rgba(0,0,0,.34);
    border-color: rgba(242,161,84,.35);
}
.result-card-col { display: flex; flex-direction: column; gap: 4px; }
.result-card-airline { flex: 1.4; min-width: 0; }
.result-card-route { flex: 2; min-width: 0; }
.result-card-price { flex: 1.3; min-width: 0; }
.result-card-action { flex: 1.1; align-items: flex-end; text-align: right; gap: 8px; }
.airline-logos { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 5px; }
.airline-logo { border-radius: 4px; background: #fff; padding: 2px 6px; object-fit: contain; display: block; }
.airline-logo-normal { height: 34px; max-width: 100px; }
.airline-logo-small  { height: 22px; max-width: 72px; }
.result-card-airline-name { font-weight: 800; font-size: 1rem; color: var(--radar-ink); }
.result-card-dates { font-weight: 650; font-size: .98rem; color: var(--radar-ink); }
.result-card-price-value { font-weight: 900; font-size: 1.18rem; color: var(--radar-ink); letter-spacing: -.01em; }
.result-card-muted { color: var(--radar-muted); font-size: .82rem; line-height: 1.4; }
.result-card-source { color: var(--radar-muted); font-size: .74rem; }
.result-card-price-note { color: var(--radar-amber); font-size: .74rem; margin-top: 4px; }
.result-card-cta {
    display: inline-block;
    padding: 8px 18px;
    border-radius: 999px;
    background: var(--radar-teal);
    color: #06241f !important;
    font-weight: 800;
    font-size: .88rem;
    text-decoration: none !important;
    transition: filter .15s ease, transform .15s ease;
}
.result-card-cta:hover { filter: brightness(1.08); transform: translateY(-1px); }
.result-card-cta-disabled {
    background: rgba(255,255,255,.06);
    color: var(--radar-muted) !important;
    cursor: default;
}
@media (max-width: 720px) {
    .result-card { flex-direction: column; align-items: stretch; gap: 10px; }
    .result-card-action { align-items: flex-start; text-align: left; }
}

/* ── Highlight cards (Recomendado / Mais barato / Mais rapido) ─ */
.highlight-cards-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    margin: 6px 0 18px;
}
.highlight-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 100%;
    padding: 18px 20px;
    border-radius: var(--radar-card-radius);
    background: var(--radar-panel);
    border: 1px solid var(--radar-line);
    border-top: 4px solid var(--radar-muted);
    box-shadow: 0 14px 34px rgba(0,0,0,.22);
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
.highlight-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 24px 50px rgba(0,0,0,.34);
}
.highlight-card-recommended { border-top-color: #FBBF24; }
.highlight-card-cheapest    { border-top-color: var(--radar-teal); }
.highlight-card-fastest     { border-top-color: #60A5FA; }
.highlight-card-badge {
    align-self: flex-start;
    font-size: .76rem;
    font-weight: 800;
    letter-spacing: .04em;
    text-transform: uppercase;
    color: var(--radar-muted);
}
.highlight-card-price {
    font-size: 1.55rem;
    font-weight: 900;
    color: var(--radar-ink);
    letter-spacing: -.01em;
}
.highlight-card-meta { color: var(--radar-muted); font-size: .85rem; line-height: 1.4; }
.highlight-card-miles { color: #99F6E4; font-size: .82rem; }
.highlight-card-empty { color: var(--radar-muted); font-size: .88rem; padding: 4px 0; }
@media (max-width: 900px) {
    .highlight-cards-grid { grid-template-columns: 1fr; }
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
    .fare-cards-grid { grid-template-columns: 1fr !important; }
    .radar-overview-grid { grid-template-columns: 1fr 1fr !important; }
}
</style>
"""


def load_custom_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
