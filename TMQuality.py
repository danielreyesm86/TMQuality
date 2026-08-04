"""
TMQuality 5.4.0 optimizada
Sistema de gestión de Control de Calidad Analítico para laboratorio.

Arquitectura
------------
- Streamlit (interfaz)
- PostgreSQL / Supabase (persistencia)
- psycopg2 (conexión)
- Plotly (visualización)
- ReportLab (informes PDF)

Seguridad
---------
- No existen credenciales administrativas predeterminadas.
- Si no hay administradores activos, el alta inicial requiere un token de
  bootstrap guardado en Streamlit Secrets:

    [database]
    url = "postgresql://..."

    [security]
    bootstrap_token = "TOKEN_LARGO_Y_ALEATORIO"

Una vez creado el primer administrador, el token deja de ser necesario para
el uso normal de la aplicación.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import psycopg2
from psycopg2 import IntegrityError
from psycopg2.extras import RealDictCursor
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, Image
)


# -----------------------------------------------------------------------------
# IDENTIDAD VISUAL TMQUALITY
# Los logos se cargan desde /assets para reducir el tamaño del script, el tiempo
# de importación y el consumo de memoria de cada proceso Streamlit.
# -----------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
ASSETS_DIR = APP_DIR / "assets" / "logos"

def _asset_b64(filename: str) -> str:
    """Carga un recurso visual desde assets/logos y lo convierte a base64."""
    asset_path = ASSETS_DIR / filename
    return base64.b64encode(asset_path.read_bytes()).decode("ascii")

LOGO_FULL_B64 = _asset_b64("tmquality_logo_full.png")
LOGO_ICON_B64 = _asset_b64("tmquality_logo_icon.png")



APP_VERSION = "5.7.0"
PBKDF2_ITERATIONS = 260_000
LEGACY_PBKDF2_ITERATIONS = 100_000
ROLES = ["Administrador", "Supervisor", "Operador"]
ESTADOS = ["Aceptado", "Advertencia", "Rechazado", "Pendiente"]
TURNOS = ["Mañana", "Tarde", "Noche", "Otro"]

# -----------------------------------------------------------------------------
# CONFIGURACIÓN Y ESTILO
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="TMQuality",
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
/* TMQuality 4.0 — interfaz clínica clara inspirada en dashboards SaaS modernos */
:root {
  --tmq-navy:#13233f; --tmq-blue:#1769d2; --tmq-blue-soft:#eaf3ff;
  --tmq-green:#0da778; --tmq-green-soft:#e9f8f3; --tmq-red:#ef334e;
  --tmq-red-soft:#fff0f2; --tmq-amber:#d99113; --tmq-amber-soft:#fff7e8;
  --tmq-bg:#f5f7fb; --tmq-card:#ffffff; --tmq-sidebar:#fbfcfe;
  --tmq-text:#14213d; --tmq-muted:#6d7890; --tmq-border:#e4e9f1;
  --tmq-shadow:0 8px 28px rgba(20,33,61,.07); --tmq-radius:20px;
}
html,body,#root,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:var(--tmq-bg)!important;color:var(--tmq-text)!important;}
[data-testid="stMainBlockContainer"]{padding-top:1.5rem!important;max-width:1500px;}
[data-testid="stSidebar"],[data-testid="stSidebarContent"]{background:var(--tmq-sidebar)!important;color:var(--tmq-text)!important;border-right:1px solid var(--tmq-border)!important;}
[data-testid="stSidebar"] *{color:var(--tmq-text);}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:var(--tmq-muted);}
#MainMenu{visibility:hidden;}
footer{visibility:hidden;}
.tmq-brand{display:flex;align-items:center;gap:.75rem;margin:.15rem 0 1.2rem 0;}
.tmq-brand img{width:52px;height:52px;object-fit:contain;}
.tmq-brand-name{font-size:1.34rem;font-weight:850;color:var(--tmq-navy);letter-spacing:-.03em;}
.tmq-brand-sub{font-size:.72rem;color:var(--tmq-muted);margin-top:.08rem;}
.tmq-topbar{background:var(--tmq-card);border:1px solid var(--tmq-border);border-radius:22px;padding:1.15rem 1.35rem;margin-bottom:1.1rem;box-shadow:var(--tmq-shadow);display:flex;justify-content:space-between;gap:1rem;align-items:center;}
.tmq-topbar h1{font-size:1.72rem;margin:0;color:var(--tmq-navy);letter-spacing:-.035em;}
.tmq-topbar p{margin:.3rem 0 0;color:var(--tmq-muted);font-size:.91rem;}
.tmq-user-pill{background:#f7f9fc;border:1px solid var(--tmq-border);border-radius:999px;padding:.5rem .78rem;font-size:.78rem;font-weight:750;color:var(--tmq-navy);white-space:nowrap;}
.tmq-section{font-size:1.08rem;font-weight:820;color:var(--tmq-navy);margin:1.2rem 0 .65rem;letter-spacing:-.02em;}
.tmq-kpi{border:1px solid var(--tmq-border);border-radius:var(--tmq-radius);padding:1.05rem 1.1rem;background:var(--tmq-card);box-shadow:var(--tmq-shadow);min-height:126px;position:relative;overflow:hidden;}
.tmq-kpi:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent,var(--tmq-blue));}
.tmq-kpi .label{color:var(--tmq-muted);font-size:.72rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;}
.tmq-kpi .value{color:var(--tmq-navy);font-size:1.82rem;font-weight:880;margin-top:.35rem;letter-spacing:-.04em;}
.tmq-kpi .hint{color:var(--tmq-muted);font-size:.76rem;margin-top:.28rem;}
.tmq-kpi.good{--accent:var(--tmq-green);background:linear-gradient(135deg,#fff 45%,var(--tmq-green-soft));}
.tmq-kpi.warn{--accent:var(--tmq-amber);background:linear-gradient(135deg,#fff 45%,var(--tmq-amber-soft));}
.tmq-kpi.bad{--accent:var(--tmq-red);background:linear-gradient(135deg,#fff 45%,var(--tmq-red-soft));}
.tmq-kpi.info{--accent:var(--tmq-blue);background:linear-gradient(135deg,#fff 45%,var(--tmq-blue-soft));}
.tmq-status{border-radius:22px;padding:1.2rem 1.25rem;color:white;min-height:145px;box-shadow:var(--tmq-shadow);background:linear-gradient(135deg,#14345f,#1769d2);}
.tmq-status.good{background:linear-gradient(135deg,#087b5b,#13b887);}
.tmq-status.bad{background:linear-gradient(135deg,#b61f38,#ef4960);}
.tmq-status .eyebrow{font-size:.72rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;opacity:.82;}
.tmq-status .big{font-size:1.55rem;font-weight:900;margin:.45rem 0 .15rem;}
.tmq-status .small{font-size:.82rem;opacity:.88;}
.tmq-card{background:var(--tmq-card);border:1px solid var(--tmq-border);border-radius:22px;padding:1rem 1.1rem;box-shadow:var(--tmq-shadow);}
[data-testid="stPlotlyChart"]{background:var(--tmq-card)!important;border:1px solid var(--tmq-border);border-radius:22px;padding:.35rem;box-shadow:var(--tmq-shadow);overflow:hidden;}
[data-baseweb="select"]>div,[data-baseweb="input"]>div,[data-baseweb="textarea"]>div,[data-testid="stTextInputRootElement"],[data-testid="stNumberInputContainer"]{background:#fff!important;color:var(--tmq-text)!important;border-color:var(--tmq-border)!important;border-radius:12px!important;}
[data-baseweb="select"] *{color:var(--tmq-text)!important;}
[data-testid="stForm"],[data-testid="stExpander"]{background:#fff!important;border:1px solid var(--tmq-border)!important;border-radius:18px!important;}
div.stButton>button,div.stDownloadButton>button{border-radius:12px!important;border:1px solid var(--tmq-border)!important;min-height:42px;font-weight:750!important;}
button[kind="primary"],div.stButton>button[kind="primary"]{background:var(--tmq-blue)!important;border-color:var(--tmq-blue)!important;color:white!important;}
[data-testid="stSidebar"] div[role="radiogroup"] label{background:transparent;border-radius:12px;padding:.42rem .55rem;margin:.08rem 0;}
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked){background:var(--tmq-blue-soft);}
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p{color:var(--tmq-blue)!important;font-weight:800;}
hr{border-color:var(--tmq-border)!important;}
[data-testid="stDataFrame"]{border:1px solid var(--tmq-border);border-radius:16px;overflow:hidden;background:#fff;}
.tmq-login-wrap{max-width:470px;margin:2.5rem auto 0;background:#fff;border:1px solid var(--tmq-border);border-radius:28px;padding:1.6rem 1.7rem .5rem;box-shadow:0 20px 55px rgba(20,33,61,.11);text-align:center;}
.tmq-login-wrap img{max-width:250px;width:70%;margin:0 auto .5rem;}
.tmq-login-title{font-size:1.35rem;font-weight:850;color:var(--tmq-navy);}
.tmq-login-sub{font-size:.82rem;color:var(--tmq-muted);margin:.25rem 0 1rem;}
/* Correcciones de accesibilidad y login — TMQuality 4.0.1 */
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
[data-testid="stTextInput"] label,
[data-testid="stTextInput"] label p,
[data-testid="stNumberInput"] label,
[data-testid="stNumberInput"] label p,
[data-testid="stSelectbox"] label,
[data-testid="stSelectbox"] label p,
[data-testid="stTextArea"] label,
[data-testid="stTextArea"] label p,
[data-testid="stDateInput"] label,
[data-testid="stDateInput"] label p,
[data-testid="stRadio"] label p,
[data-testid="stCheckbox"] label p {color:var(--tmq-text)!important;opacity:1!important;font-weight:700!important;}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea {
  color:var(--tmq-text)!important;
  -webkit-text-fill-color:var(--tmq-text)!important;
  caret-color:var(--tmq-blue)!important;
  opacity:1!important;
  background:#fff!important;
}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-baseweb="input"] input::placeholder,
[data-baseweb="textarea"] textarea::placeholder {
  color:#8a94a8!important;
  -webkit-text-fill-color:#8a94a8!important;
  opacity:1!important;
}
[data-testid="stTextInputRootElement"] svg,
[data-baseweb="input"] svg {color:#657189!important;fill:#657189!important;}

.tmq-login-shell{max-width:560px;margin:2.2rem auto 0;}
.tmq-login-head{background:#fff;border:1px solid var(--tmq-border);border-radius:26px;padding:1.35rem 1.5rem 1.1rem;box-shadow:0 18px 50px rgba(20,33,61,.10);text-align:center;margin-bottom:.85rem;}
.tmq-login-head img{max-width:225px;width:58%;margin:0 auto .4rem;display:block;}
.tmq-login-title{font-size:1.42rem;font-weight:850;color:var(--tmq-navy)!important;}
.tmq-login-sub{font-size:.84rem;color:var(--tmq-muted)!important;margin:.28rem 0 0;}
.tmq-login-help{font-size:.82rem;color:var(--tmq-muted);margin-top:.8rem;line-height:1.45;}

/* Evita que el tema del navegador/Streamlit vuelva blancos los textos del formulario */
.stApp form [data-testid="stMarkdownContainer"] p,
.stApp form label,
.stApp form span {color:var(--tmq-text)!important;}
.stAlert [data-testid="stMarkdownContainer"] p{color:inherit!important;}


/* --------------------------------------------------------------------------
   TMQuality 4.0.3 — normalización visual completa de widgets Streamlit
   -------------------------------------------------------------------------- */

/* Selectbox / multiselect: siempre superficie blanca y texto oscuro */
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
div[data-testid="stMultiSelect"] div[data-baseweb="select"] > div,
div[data-baseweb="select"] > div {
    background:#FFFFFF !important;
    border:1px solid var(--tmq-border) !important;
    color:var(--tmq-text) !important;
    box-shadow:none !important;
}
div[data-testid="stSelectbox"] div[data-baseweb="select"] *,
div[data-testid="stMultiSelect"] div[data-baseweb="select"] *,
div[data-baseweb="select"] * {
    color:var(--tmq-text) !important;
    -webkit-text-fill-color:var(--tmq-text) !important;
}
div[data-baseweb="select"] svg {
    color:#66738A !important;
    fill:#66738A !important;
}

/* Menús desplegables */
ul[role="listbox"],
div[role="listbox"],
[data-baseweb="popover"],
[data-baseweb="menu"] {
    background:#FFFFFF !important;
    color:var(--tmq-text) !important;
}
li[role="option"],
div[role="option"] {
    background:#FFFFFF !important;
    color:var(--tmq-text) !important;
}
li[role="option"]:hover,
div[role="option"]:hover,
li[role="option"][aria-selected="true"],
div[role="option"][aria-selected="true"] {
    background:var(--tmq-blue-soft) !important;
    color:var(--tmq-blue) !important;
}

/* Inputs, text areas, date/time inputs */
div[data-testid="stTextInputRootElement"],
div[data-testid="stNumberInputContainer"],
div[data-baseweb="input"],
div[data-baseweb="textarea"],
div[data-testid="stDateInput"] > div > div,
div[data-testid="stTimeInput"] > div > div {
    background:#FFFFFF !important;
    color:var(--tmq-text) !important;
    border-color:var(--tmq-border) !important;
}
input, textarea {
    color:var(--tmq-text) !important;
    -webkit-text-fill-color:var(--tmq-text) !important;
}
input:disabled, textarea:disabled {
    color:#8792A6 !important;
    -webkit-text-fill-color:#8792A6 !important;
    opacity:1 !important;
}

/* Botones secundarios */
div.stButton > button,
div.stDownloadButton > button {
    background:#FFFFFF !important;
    color:var(--tmq-navy) !important;
    border:1px solid #D7DEE9 !important;
    box-shadow:0 1px 2px rgba(20,33,61,.03) !important;
}
div.stButton > button p,
div.stButton > button span,
div.stDownloadButton > button p,
div.stDownloadButton > button span {
    color:inherit !important;
}
div.stButton > button:hover:not(:disabled),
div.stDownloadButton > button:hover:not(:disabled) {
    background:#F5F8FD !important;
    color:var(--tmq-blue) !important;
    border-color:#B8CAE6 !important;
    box-shadow:0 4px 12px rgba(31,111,235,.08) !important;
}

/* Botón principal */
button[kind="primary"],
div.stButton > button[kind="primary"] {
    background:var(--tmq-blue) !important;
    color:#FFFFFF !important;
    border-color:var(--tmq-blue) !important;
}
button[kind="primary"] p,
button[kind="primary"] span {
    color:#FFFFFF !important;
}

/* Deshabilitados: gris claro, nunca negro */
button:disabled,
div.stButton > button:disabled,
div.stDownloadButton > button:disabled,
button[disabled] {
    background:#F1F4F8 !important;
    color:#8A95A8 !important;
    border-color:#E0E5EC !important;
    box-shadow:none !important;
    opacity:1 !important;
    cursor:not-allowed !important;
}
button:disabled p,
button:disabled span,
div.stButton > button:disabled p,
div.stButton > button:disabled span {
    color:#8A95A8 !important;
    -webkit-text-fill-color:#8A95A8 !important;
    opacity:1 !important;
}

/* Formularios y expanders */
[data-testid="stForm"],
[data-testid="stExpander"] {
    background:#FFFFFF !important;
    color:var(--tmq-text) !important;
}

/* Pestañas */
button[data-baseweb="tab"] {
    background:transparent !important;
    color:var(--tmq-muted) !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color:var(--tmq-blue) !important;
    font-weight:800 !important;
}

/* Dataframes / data editor. Mantener contenedor claro; el canvas interno de
   Streamlit conserva su propio contraste, pero no hereda negro del CSS global. */
[data-testid="stDataFrame"],
[data-testid="stDataEditor"] {
    background:#FFFFFF !important;
    color:var(--tmq-text) !important;
    border:1px solid var(--tmq-border) !important;
    border-radius:16px !important;
}
[data-testid="stDataFrame"] > div,
[data-testid="stDataEditor"] > div {
    background:#FFFFFF !important;
}

/* Radio, checkbox, toggle */
[data-testid="stRadio"] label,
[data-testid="stCheckbox"] label,
[data-testid="stToggle"] label {
    color:var(--tmq-text) !important;
}

/* Focus visible */
input:focus,
textarea:focus,
div[data-baseweb="select"] > div:focus-within {
    border-color:var(--tmq-blue) !important;
    box-shadow:0 0 0 3px rgba(31,111,235,.12) !important;
}

/* Sidebar: evitar que controles hereden fondo oscuro */
[data-testid="stSidebar"] div[data-baseweb="select"] > div,
[data-testid="stSidebar"] div[data-baseweb="input"],
[data-testid="stSidebar"] div[data-baseweb="textarea"] {
    background:#FFFFFF !important;
    color:var(--tmq-text) !important;
}


/* ==========================================================================
   TMQuality 4.0.4 — FORZADO DE TEMA CLARO EN CONTROLES NATIVOS DE STREAMLIT
   Streamlit puede conservar internamente el tema Dark aunque el layout de
   TMQuality sea claro. Estos selectores actúan directamente sobre combobox,
   inputs y controles BaseWeb para evitar superficies negras.
   ========================================================================== */

/* SELECTBOX — cubrir wrapper, combobox y TODOS los contenedores internos */
.stApp [data-testid="stSelectbox"] [data-baseweb="select"],
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] > div,
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] div[role="combobox"],
.stApp [data-testid="stSelectbox"] [role="combobox"],
.stApp [data-testid="stMultiSelect"] [data-baseweb="select"],
.stApp [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
.stApp [data-testid="stMultiSelect"] [role="combobox"] {
    background-color:#FFFFFF !important;
    background:#FFFFFF !important;
    color:#14213D !important;
    -webkit-text-fill-color:#14213D !important;
    border-color:#DDE3EC !important;
}

/* BaseWeb introduce varios div intermedios con background del tema */
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] > div > div,
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] > div > div > div,
.stApp [data-testid="stMultiSelect"] [data-baseweb="select"] > div > div,
.stApp [data-testid="stMultiSelect"] [data-baseweb="select"] > div > div > div {
    background-color:#FFFFFF !important;
    background:#FFFFFF !important;
    color:#14213D !important;
    -webkit-text-fill-color:#14213D !important;
}

/* Texto seleccionado y placeholder */
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] span,
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] p,
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] input,
.stApp [data-testid="stMultiSelect"] [data-baseweb="select"] span,
.stApp [data-testid="stMultiSelect"] [data-baseweb="select"] p,
.stApp [data-testid="stMultiSelect"] [data-baseweb="select"] input {
    color:#14213D !important;
    -webkit-text-fill-color:#14213D !important;
    opacity:1 !important;
}

/* Flechas de los selectores */
.stApp [data-testid="stSelectbox"] [data-baseweb="select"] svg,
.stApp [data-testid="stMultiSelect"] [data-baseweb="select"] svg {
    color:#657189 !important;
    fill:#657189 !important;
}

/* POPUP DEL SELECTOR */
body [data-baseweb="popover"],
body [data-baseweb="menu"],
body [role="listbox"],
body ul[role="listbox"] {
    background:#FFFFFF !important;
    color:#14213D !important;
}
body [role="option"],
body li[role="option"] {
    background:#FFFFFF !important;
    color:#14213D !important;
    -webkit-text-fill-color:#14213D !important;
}
body [role="option"] *,
body li[role="option"] * {
    color:#14213D !important;
    -webkit-text-fill-color:#14213D !important;
}
body [role="option"]:hover,
body li[role="option"]:hover,
body [role="option"][aria-selected="true"],
body li[role="option"][aria-selected="true"] {
    background:#EDF4FF !important;
    color:#1559A8 !important;
}

/* INPUTS — forzar también el contenedor exterior */
.stApp [data-testid="stTextInput"] [data-baseweb="input"],
.stApp [data-testid="stTextInput"] [data-baseweb="input"] > div,
.stApp [data-testid="stNumberInput"] [data-baseweb="input"],
.stApp [data-testid="stNumberInput"] [data-baseweb="input"] > div,
.stApp [data-testid="stTextArea"] [data-baseweb="textarea"],
.stApp [data-testid="stTextArea"] [data-baseweb="textarea"] > div {
    background:#FFFFFF !important;
    background-color:#FFFFFF !important;
    color:#14213D !important;
    border-color:#DDE3EC !important;
}
.stApp [data-testid="stTextInput"] input,
.stApp [data-testid="stNumberInput"] input,
.stApp [data-testid="stTextArea"] textarea {
    background:#FFFFFF !important;
    color:#14213D !important;
    -webkit-text-fill-color:#14213D !important;
}

/* Sidebar: prioridad máxima sobre cualquier tema oscuro persistente */
.stApp [data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"],
.stApp [data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] > div,
.stApp [data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] > div > div,
.stApp [data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"] {
    background:#FFFFFF !important;
    background-color:#FFFFFF !important;
    color:#14213D !important;
    -webkit-text-fill-color:#14213D !important;
}

/* Focus accesible */
.stApp [data-testid="stSelectbox"] [role="combobox"]:focus,
.stApp [data-testid="stSelectbox"] [data-baseweb="select"]:focus-within,
.stApp [data-testid="stTextInput"] [data-baseweb="input"]:focus-within {
    outline:none !important;
    border-color:#1F6FEB !important;
    box-shadow:0 0 0 3px rgba(31,111,235,.12) !important;
}

/* TMQuality 4.0.1 usa deliberadamente un único tema claro coherente. */

/* ==========================================================================
   TMQuality 5.2 — INTERFAZ PROFESIONAL CLARA
   ========================================================================== */
:root {
    --tmq-bg: #F7F9FC;
    --tmq-surface: #FFFFFF;
    --tmq-surface-soft: #FFF7FA;
    --tmq-border: #E4E9F1;
    --tmq-text: #182235;
    --tmq-muted: #6F7B8F;
    --tmq-accent: #F43F6B;
    --tmq-accent-dark: #D72E58;
    --tmq-accent-soft: #FFF0F4;
    --tmq-blue-soft: #EFF6FF;
    --tmq-success: #1FA86A;
    --tmq-warning: #D99800;
    --tmq-danger: #E5484D;
}

/* App shell */
html, body, [data-testid="stAppViewContainer"], .stApp {
    background: var(--tmq-bg) !important;
    color: var(--tmq-text) !important;
}
[data-testid="stHeader"] {
    background: rgba(255,255,255,.96) !important;
    border-bottom: 1px solid var(--tmq-border) !important;
}
[data-testid="stToolbar"] {
    background: transparent !important;
}
.main .block-container {
    max-width: 1460px !important;
    padding-top: 1.4rem !important;
    padding-bottom: 2rem !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: #FFFFFF !important;
    border-right: 1px solid var(--tmq-border) !important;
}
[data-testid="stSidebar"] * {
    color: var(--tmq-text) !important;
}
[data-testid="stSidebar"] hr {
    border-color: var(--tmq-border) !important;
}

/* Tipografía */
h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"] strong {
    color: var(--tmq-text) !important;
}
p, label, [data-testid="stCaptionContainer"] {
    color: var(--tmq-muted) !important;
}

/* Inputs y selects */
.stApp div[data-baseweb="input"],
.stApp div[data-baseweb="textarea"],
.stApp div[data-baseweb="select"] > div,
.stApp [role="combobox"],
.stApp [data-testid="stTextInputRootElement"],
.stApp [data-testid="stNumberInputContainer"] {
    background: #FFFFFF !important;
    color: var(--tmq-text) !important;
    border-color: #DCE3ED !important;
    box-shadow: none !important;
}
.stApp input,
.stApp textarea,
.stApp div[data-baseweb="select"] *,
.stApp [role="combobox"] * {
    color: var(--tmq-text) !important;
    -webkit-text-fill-color: var(--tmq-text) !important;
}
.stApp input::placeholder,
.stApp textarea::placeholder {
    color: #98A3B5 !important;
    -webkit-text-fill-color: #98A3B5 !important;
}
.stApp div[data-baseweb="select"] svg {
    color: #68758A !important;
    fill: #68758A !important;
}

/* Dropdown */
body [data-baseweb="popover"],
body [data-baseweb="menu"],
body [role="listbox"],
body [role="option"] {
    background: #FFFFFF !important;
    color: var(--tmq-text) !important;
}
body [role="option"]:hover,
body [role="option"][aria-selected="true"] {
    background: var(--tmq-accent-soft) !important;
    color: var(--tmq-accent-dark) !important;
}

/* Buttons */
div.stButton > button,
div.stDownloadButton > button,
button[kind="secondary"] {
    background: #FFFFFF !important;
    color: var(--tmq-text) !important;
    border: 1px solid #DCE3ED !important;
    border-radius: 10px !important;
    min-height: 46px !important;
    font-weight: 700 !important;
    box-shadow: none !important;
}
div.stButton > button:hover:not(:disabled),
div.stDownloadButton > button:hover:not(:disabled) {
    background: var(--tmq-accent-soft) !important;
    border-color: #F8A9BB !important;
    color: var(--tmq-accent-dark) !important;
}
button[kind="primary"],
div.stButton > button[kind="primary"],
div.stFormSubmitButton > button[kind="primary"] {
    background: linear-gradient(135deg, #F43F6B 0%, #F02D65 100%) !important;
    border-color: #F43F6B !important;
    color: #FFFFFF !important;
    border-radius: 10px !important;
    font-weight: 800 !important;
}
button[kind="primary"] *,
div.stFormSubmitButton > button[kind="primary"] * {
    color: #FFFFFF !important;
}
button:disabled,
div.stButton > button:disabled {
    background: #F2F4F8 !important;
    color: #9AA5B5 !important;
    border-color: #E3E7ED !important;
    opacity: 1 !important;
}
button:disabled * {
    color: #9AA5B5 !important;
}

/* Forms / cards / expanders */
[data-testid="stForm"],
[data-testid="stExpander"],
[data-testid="stDataFrame"],
[data-testid="stDataEditor"] {
    background: #FFFFFF !important;
    border: 1px solid var(--tmq-border) !important;
    border-radius: 16px !important;
    box-shadow: 0 8px 30px rgba(25, 39, 68, .04) !important;
}

/* Alerts */
[data-testid="stAlert"] {
    border-radius: 12px !important;
}
[data-testid="stAlert"] * {
    color: inherit !important;
}

/* Tabs */
button[data-baseweb="tab"] {
    color: var(--tmq-muted) !important;
    background: transparent !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: var(--tmq-accent) !important;
    font-weight: 800 !important;
}

/* Radio navigation */
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 9px 11px !important;
    border-radius: 10px !important;
    margin-bottom: 3px !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: var(--tmq-accent-soft) !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
    background: var(--tmq-accent-soft) !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p {
    color: var(--tmq-accent) !important;
    font-weight: 800 !important;
}

/* Login */
.tmq-auth-wrap {
    max-width: 1120px;
    margin: 18px auto 0 auto;
}
.tmq-auth-title {
    text-align: center;
    font-size: 31px;
    line-height: 1.2;
    font-weight: 850;
    color: var(--tmq-text);
    margin-bottom: 5px;
}
.tmq-auth-title span {
    color: var(--tmq-accent);
}
.tmq-auth-subtitle {
    text-align: center;
    color: var(--tmq-muted);
    font-size: 16px;
    margin-bottom: 26px;
}
.tmq-auth-card {
    background: #FFFFFF;
    border: 1px solid var(--tmq-border);
    border-radius: 18px;
    padding: 28px;
    box-shadow: 0 10px 34px rgba(26, 41, 72, .06);
}
.tmq-auth-panel {
    background: linear-gradient(145deg, #FFF7FA 0%, #FFF1F5 100%);
    border: 1px solid #FFE0E8;
    border-radius: 16px;
    padding: 22px 22px 18px 22px;
    min-height: 290px;
}
.tmq-auth-section-title {
    color: var(--tmq-accent);
    font-size: 16px;
    font-weight: 800;
    margin-bottom: 12px;
}
.tmq-auth-section-text {
    color: #5E697A;
    font-size: 14px;
    line-height: 1.55;
}
.tmq-info-box {
    max-width: 1120px;
    margin: 18px auto 0 auto;
    padding: 16px 20px;
    border: 1px solid #CFE0FA;
    border-radius: 13px;
    background: #F3F8FF;
    color: #31567E;
}
.tmq-info-box strong {
    color: #31567E !important;
}
.tmq-footer {
    max-width: 1120px;
    margin: 18px auto 0 auto;
    padding: 12px 4px 0 4px;
    border-top: 1px solid var(--tmq-border);
    display: flex;
    justify-content: space-between;
    color: #8993A3;
    font-size: 12px;
}

/* Organization badge */
.tmq-org-card {
    background: linear-gradient(145deg, #FFF7FA 0%, #FFF1F5 100%);
    border: 1px solid #FFE0E8;
    border-radius: 14px;
    padding: 14px;
    margin-top: 14px;
}

/* KPI / cards existentes */
.tmq-card, .tmq-kpi, .tmq-panel {
    background: #FFFFFF !important;
    border-color: var(--tmq-border) !important;
    box-shadow: 0 8px 28px rgba(25,39,68,.04) !important;
}

/* Evitar superficies negras residuales */
.stApp [style*="background-color: rgb(19, 23, 32)"],
.stApp [style*="background: rgb(19, 23, 32)"],
.stApp [style*="background-color: rgb(14, 17, 23)"] {
    background: #FFFFFF !important;
}


/* ==========================================================================
   TMQuality 5.2.1 — Sistema consistente de botones
   ========================================================================== */

/* Base común */
.stApp div.stButton > button,
.stApp div.stDownloadButton > button,
.stApp div.stFormSubmitButton > button {
    min-height: 44px !important;
    padding: 0.68rem 1.05rem !important;
    border-radius: 11px !important;
    font-size: 0.94rem !important;
    font-weight: 750 !important;
    letter-spacing: 0 !important;
    transition: all .16s ease !important;
    box-shadow: none !important;
}

/* Forzar SIEMPRE el color del texto y elementos internos */
.stApp div.stButton > button *,
.stApp div.stDownloadButton > button *,
.stApp div.stFormSubmitButton > button * {
    color: inherit !important;
    -webkit-text-fill-color: currentColor !important;
}

/* Botón primario */
.stApp button[kind="primary"],
.stApp div.stButton > button[kind="primary"],
.stApp div.stFormSubmitButton > button[kind="primary"] {
    background: linear-gradient(135deg, #F43F6B 0%, #E92E5F 100%) !important;
    color: #FFFFFF !important;
    border: 1px solid #E92E5F !important;
    box-shadow: 0 5px 14px rgba(244, 63, 107, .18) !important;
}
.stApp button[kind="primary"]:hover:not(:disabled),
.stApp div.stButton > button[kind="primary"]:hover:not(:disabled),
.stApp div.stFormSubmitButton > button[kind="primary"]:hover:not(:disabled) {
    background: linear-gradient(135deg, #E92E5F 0%, #D92556 100%) !important;
    color: #FFFFFF !important;
    border-color: #D92556 !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 7px 18px rgba(244, 63, 107, .24) !important;
}

/* Secundario / acciones normales */
.stApp div.stButton > button:not([kind="primary"]),
.stApp div.stDownloadButton > button {
    background: #FFFFFF !important;
    color: #26344D !important;
    border: 1px solid #D8E0EB !important;
    box-shadow: 0 2px 7px rgba(27, 42, 70, .035) !important;
}
.stApp div.stButton > button:not([kind="primary"]):hover:not(:disabled),
.stApp div.stDownloadButton > button:hover:not(:disabled) {
    background: #FFF4F7 !important;
    color: #D92D59 !important;
    border-color: #F1A8BA !important;
    transform: translateY(-1px) !important;
}

/* Botón deshabilitado */
.stApp button:disabled,
.stApp div.stButton > button:disabled,
.stApp div.stDownloadButton > button:disabled,
.stApp div.stFormSubmitButton > button:disabled {
    background: #F2F4F7 !important;
    color: #98A2B3 !important;
    border: 1px solid #E4E7EC !important;
    box-shadow: none !important;
    opacity: 1 !important;
    transform: none !important;
}

/* Evitar texto rosado dentro de botones rojos */
.stApp button[kind="primary"] p,
.stApp button[kind="primary"] span,
.stApp button[kind="primary"] div,
.stApp div.stFormSubmitButton > button[kind="primary"] p,
.stApp div.stFormSubmitButton > button[kind="primary"] span,
.stApp div.stFormSubmitButton > button[kind="primary"] div {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}

/* Tamaños y alineación */
.stApp div.stButton > button p,
.stApp div.stDownloadButton > button p,
.stApp div.stFormSubmitButton > button p {
    margin: 0 !important;
    line-height: 1.15 !important;
    font-weight: inherit !important;
}

/* Botones dentro de columnas: ocupación elegante */
.stApp [data-testid="column"] div.stButton > button,
.stApp [data-testid="column"] div.stDownloadButton > button {
    width: 100% !important;
}

/* Evitar aspecto excesivamente alto en botones de acción corta */
.stApp div.stButton > button[data-testid="baseButton-secondary"],
.stApp div.stButton > button[data-testid="baseButton-primary"] {
    min-height: 42px !important;
}

/* Acción peligrosa mediante texto reconocido */
.stApp div.stButton > button:has(p:is(
    :where(:not(:empty))
)) {
    text-decoration: none !important;
}

/* Botones en paneles y formularios */
[data-testid="stForm"] .stFormSubmitButton > button {
    margin-top: .3rem !important;
}

/* Foco accesible */
.stApp div.stButton > button:focus-visible,
.stApp div.stDownloadButton > button:focus-visible,
.stApp div.stFormSubmitButton > button:focus-visible {
    outline: none !important;
    box-shadow: 0 0 0 3px rgba(244,63,107,.16) !important;
}


/* ==========================================================================
   TMQuality 5.3 — UI inspirada en referencia aprobada
   ========================================================================== */
:root {
    --pink:#F52D63;
    --pink-dark:#D92556;
    --pink-soft:#FFF1F5;
    --navy:#182235;
    --muted:#707B8E;
    --line:#E4E9F1;
    --bg:#FAFBFD;
    --white:#FFFFFF;
    --blue-soft:#F3F8FF;
}

html, body, .stApp, [data-testid="stAppViewContainer"] {
    background:var(--bg) !important;
    color:var(--navy) !important;
}

[data-testid="stHeader"] {
    background:#FFFFFF !important;
    border-bottom:1px solid var(--line) !important;
    height:68px !important;
}

[data-testid="stToolbar"] {
    right:16px !important;
}

.main .block-container {
    max-width:1500px !important;
    padding:1.5rem 2rem 2rem 2rem !important;
}

/* SIDEBAR */
[data-testid="stSidebar"] {
    background:#FFFFFF !important;
    border-right:1px solid var(--line) !important;
}
[data-testid="stSidebar"] > div:first-child {
    padding-top:12px !important;
}
[data-testid="stSidebar"] * {
    color:var(--navy) !important;
}

.tmq-side-brand {
    display:flex;
    align-items:center;
    gap:10px;
    padding:8px 6px 12px 6px;
}
.tmq-side-brand img {
    width:46px;
    height:46px;
    object-fit:contain;
}
.tmq-side-brand-name {
    font-size:24px;
    font-weight:850;
    letter-spacing:-.02em;
    color:var(--navy);
}
.tmq-side-brand-sub {
    font-size:11px;
    color:var(--muted);
    margin-top:1px;
}
.tmq-side-version {
    font-size:11px;
    color:#9BA5B5;
    padding-left:6px;
    margin-bottom:8px;
}

[data-testid="stSidebar"] [data-testid="stRadio"] > div {
    gap:2px !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    min-height:42px !important;
    padding:9px 12px !important;
    margin:1px 0 !important;
    border-radius:10px !important;
    transition:.15s ease !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background:#FFF6F8 !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
    background:var(--pink-soft) !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p {
    color:var(--pink) !important;
    font-weight:800 !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] p {
    font-size:14px !important;
    font-weight:650 !important;
}

.tmq-org-card {
    background:linear-gradient(145deg,#FFF8FA,#FFF1F5);
    border:1px solid #FFE0E8;
    border-radius:14px;
    padding:15px;
    margin:16px 0 8px;
}
.tmq-org-kicker {
    color:var(--pink);
    font-size:11px;
    font-weight:800;
    text-transform:uppercase;
    letter-spacing:.05em;
}
.tmq-org-name {
    color:var(--navy);
    font-size:14px;
    font-weight:850;
    margin-top:5px;
}
.tmq-org-meta {
    color:var(--muted);
    font-size:12px;
    margin-top:4px;
}

/* TOP BAR / PAGE TITLE */
.tmq-topbar {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:18px;
    margin-bottom:22px;
}
.tmq-topbar-title {
    color:var(--navy);
    font-size:14px;
    font-weight:700;
}
.tmq-topbar-title span {
    color:var(--pink);
    font-weight:850;
}
.tmq-user-chip {
    display:inline-flex;
    align-items:center;
    gap:8px;
    border:1px solid var(--line);
    border-radius:10px;
    padding:8px 12px;
    background:#FFFFFF;
    color:var(--navy);
    font-size:13px;
    font-weight:700;
}

/* AUTH */
.tmq-auth-shell {
    max-width:1120px;
    margin:20px auto 0 auto;
}
.tmq-auth-heading {
    margin:4px 0 28px;
}
.tmq-auth-title {
    font-size:34px;
    line-height:1.15;
    color:var(--navy);
    font-weight:850;
    letter-spacing:-.025em;
}
.tmq-auth-title span { color:var(--pink); }
.tmq-auth-subtitle {
    color:var(--muted);
    font-size:17px;
    margin-top:8px;
}
.tmq-login-card {
    background:#FFFFFF;
    border:1px solid var(--line);
    border-radius:18px;
    padding:30px;
    box-shadow:0 10px 35px rgba(34,48,78,.045);
}
.tmq-login-panel {
    background:linear-gradient(145deg,#FFF9FB,#FFF2F6);
    border:1px solid #FFE3EA;
    border-radius:16px;
    padding:24px;
    min-height:318px;
}
.tmq-section-pink {
    color:var(--pink);
    font-size:16px;
    font-weight:850;
    margin-bottom:14px;
}
.tmq-platform-copy {
    color:#5F697A;
    font-size:14px;
    line-height:1.65;
}
.tmq-info {
    max-width:1120px;
    margin:18px auto 0;
    padding:18px 22px;
    background:var(--blue-soft);
    border:1px solid #CFE1FA;
    border-radius:13px;
    color:#365D88;
    font-size:13px;
    line-height:1.65;
}
.tmq-info strong { color:#2D66A0 !important; }
.tmq-app-footer {
    max-width:1120px;
    margin:18px auto 0;
    border-top:1px solid var(--line);
    padding:14px 2px 0;
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:12px;
    color:#8A94A4;
    font-size:12px;
}
.tmq-app-footer .version {
    color:var(--pink);
    font-weight:800;
}

/* COMPONENTS */
.stApp div[data-baseweb="input"],
.stApp div[data-baseweb="textarea"],
.stApp div[data-baseweb="select"] > div,
.stApp [role="combobox"],
.stApp [data-testid="stTextInputRootElement"],
.stApp [data-testid="stNumberInputContainer"] {
    background:#FFFFFF !important;
    color:var(--navy) !important;
    border:1px solid #DCE3ED !important;
    border-radius:9px !important;
    box-shadow:none !important;
}
.stApp input, .stApp textarea,
.stApp [role="combobox"] *,
.stApp div[data-baseweb="select"] * {
    color:var(--navy) !important;
    -webkit-text-fill-color:var(--navy) !important;
}
.stApp input::placeholder, .stApp textarea::placeholder {
    color:#98A3B5 !important;
    -webkit-text-fill-color:#98A3B5 !important;
}

/* BUTTONS */
.stApp div.stButton > button,
.stApp div.stDownloadButton > button,
.stApp div.stFormSubmitButton > button {
    min-height:44px !important;
    border-radius:9px !important;
    font-weight:780 !important;
}
.stApp button[kind="primary"],
.stApp div.stButton > button[kind="primary"],
.stApp div.stFormSubmitButton > button[kind="primary"] {
    background:linear-gradient(135deg,#F52D63,#EE245B) !important;
    border:1px solid #EE245B !important;
    color:#FFFFFF !important;
    box-shadow:0 6px 15px rgba(245,45,99,.16) !important;
}
.stApp button[kind="primary"] *,
.stApp div.stButton > button[kind="primary"] *,
.stApp div.stFormSubmitButton > button[kind="primary"] * {
    color:#FFFFFF !important;
    -webkit-text-fill-color:#FFFFFF !important;
}
.stApp div.stButton > button:not([kind="primary"]),
.stApp div.stDownloadButton > button {
    background:#FFFFFF !important;
    color:var(--navy) !important;
    border:1px solid #DCE3ED !important;
}
.stApp div.stButton > button:not([kind="primary"]):hover:not(:disabled),
.stApp div.stDownloadButton > button:hover:not(:disabled) {
    background:#FFF7F9 !important;
    border-color:#F4AFC0 !important;
    color:var(--pink-dark) !important;
}
.stApp button:disabled {
    background:#F3F5F8 !important;
    color:#98A2B3 !important;
    border-color:#E4E7EC !important;
    opacity:1 !important;
}

/* CARDS / TABLES */
[data-testid="stForm"],
[data-testid="stExpander"],
[data-testid="stDataFrame"],
[data-testid="stDataEditor"],
.tmq-card,.tmq-kpi,.tmq-panel {
    background:#FFFFFF !important;
    border:1px solid var(--line) !important;
    border-radius:14px !important;
    box-shadow:0 8px 28px rgba(29,43,70,.04) !important;
}

/* Tabs */
button[data-baseweb="tab"] {
    color:var(--muted) !important;
    background:transparent !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color:var(--pink) !important;
    font-weight:850 !important;
}

/* Explicitly eliminate dark residual surfaces */
.stApp [style*="background-color: rgb(19, 23, 32)"],
.stApp [style*="background-color: rgb(14, 17, 23)"],
.stApp [style*="background: rgb(19, 23, 32)"],
.stApp [style*="background: rgb(14, 17, 23)"] {
    background:#FFFFFF !important;
}

</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# BASE DE DATOS / ORGANIZACIONES
# -----------------------------------------------------------------------------
from database import (
    get_database_url,
    get_connection,
    execute,
    fetchone,
    fetchall_df,
    init_db,
    ensure_database_ready,
    current_org_id,
    current_organization,
    load_control_levels,
    control_level_names,
    sync_control_levels
)

# -----------------------------------------------------------------------------
# SEGURIDAD / USUARIOS
# -----------------------------------------------------------------------------
from auth import (
    hash_password,
    password_ok,
    audit,
    authenticate,
    create_user,
    change_password,
    active_admin_count,
    create_organization_with_admin,
    platform_admin_ui,
    bootstrap_admin_ui
)

# -----------------------------------------------------------------------------
# REGLAS DE WESTGARD Y MÉTRICAS
# -----------------------------------------------------------------------------
from services import (
    zscore,
    westgard_rules,
    state_from_rules,
    recalcular_reglas_lote,
    qc_statistics,
    parse_control_levels,
)

from modules import module_lots

# -----------------------------------------------------------------------------
# DATOS / CONSULTAS
# -----------------------------------------------------------------------------
def load_analytes(conn, only_active=True):
    org_id = current_org_id()
    if org_id is None:
        return pd.DataFrame()
    sql = "SELECT * FROM analitos WHERE organizacion_id=%s"
    params: list[Any] = [org_id]
    if only_active:
        sql += " AND activo=TRUE"
    sql += " ORDER BY nombre"
    return fetchall_df(conn, sql, params)


def load_equipment(conn, only_active=True):
    org_id = current_org_id()
    if org_id is None:
        return pd.DataFrame()
    sql = "SELECT * FROM equipos WHERE organizacion_id=%s"
    params: list[Any] = [org_id]
    if only_active:
        sql += " AND activo=TRUE"
    sql += " ORDER BY nombre"
    return fetchall_df(conn, sql, params)


def load_lots(conn, analyte_id: int, only_active=True):
    org_id = current_org_id()
    if org_id is None:
        return pd.DataFrame()
    sql = "SELECT * FROM lotes_control WHERE organizacion_id=%s AND analito_id=%s"
    params: list[Any] = [org_id, analyte_id]
    if only_active:
        sql += " AND vigente=TRUE"
    sql += " ORDER BY nivel, lote"
    return fetchall_df(conn, sql, params)


def load_results(conn, lot_id: int, limit: Optional[int] = None):
    org_id = current_org_id()
    if org_id is None:
        return pd.DataFrame()
    sql = """
    SELECT r.*, e.nombre AS equipo_nombre, u.nombre_completo AS usuario_nombre
    FROM resultados_cc r
    LEFT JOIN equipos e ON e.id=r.equipo_id AND e.organizacion_id=r.organizacion_id
    LEFT JOIN usuarios u ON u.id=r.usuario_id AND u.organizacion_id=r.organizacion_id
    WHERE r.organizacion_id=%s AND r.lote_control_id=%s
    ORDER BY r.fecha ASC, r.hora ASC, r.id ASC
    """
    if limit:
        sql += " LIMIT %s"
        return fetchall_df(conn, sql, (org_id, lot_id, limit))
    return fetchall_df(conn, sql, (org_id, lot_id))


def load_results_between(conn, lot_id: int, start_date: date, end_date: date):
    """Carga únicamente los resultados necesarios para un período."""
    org_id = current_org_id()
    if org_id is None:
        return pd.DataFrame()
    return fetchall_df(
        conn,
        """
        SELECT r.*, e.nombre AS equipo_nombre, u.nombre_completo AS usuario_nombre
        FROM resultados_cc r
        LEFT JOIN equipos e ON e.id=r.equipo_id AND e.organizacion_id=r.organizacion_id
        LEFT JOIN usuarios u ON u.id=r.usuario_id AND u.organizacion_id=r.organizacion_id
        WHERE r.organizacion_id=%s
          AND r.lote_control_id=%s
          AND r.fecha BETWEEN %s AND %s
        ORDER BY r.fecha ASC, r.hora ASC, r.id ASC
        """,
        (org_id, int(lot_id), start_date, end_date),
    )


def result_date_bounds(conn, lot_id: int) -> tuple[date, date]:
    """Obtiene solo las fechas mínima y máxima, sin descargar el historial."""
    org_id = current_org_id()
    if org_id is None:
        today = date.today()
        return today, today
    row = fetchone(
        conn,
        """
        SELECT MIN(fecha) AS min_fecha, MAX(fecha) AS max_fecha
        FROM resultados_cc
        WHERE organizacion_id=%s AND lote_control_id=%s
        """,
        (org_id, int(lot_id)),
    )
    today = date.today()
    if not row or not row.get("min_fecha"):
        return today, today
    return row["min_fecha"], row["max_fecha"]


def result_summary(conn, lot_id: int, target_mean: float, allowable_error: Optional[float]) -> dict:
    """Resumen estadístico calculado en PostgreSQL para no transferir todo el lote."""
    org_id = current_org_id()
    if org_id is None:
        return {
            "n": 0, "accepted": 0, "warnings": 0, "rejected": 0,
            "mean": None, "sd": None, "cv": None, "bias": None, "sigma": None,
        }

    row = fetchone(
        conn,
        """
        SELECT
            COUNT(*) AS n,
            COUNT(*) FILTER (WHERE estado='Aceptado') AS accepted,
            COUNT(*) FILTER (WHERE estado='Advertencia') AS warnings,
            COUNT(*) FILTER (WHERE estado='Rechazado') AS rejected,
            AVG(valor) AS mean,
            STDDEV_SAMP(valor) AS sd
        FROM resultados_cc
        WHERE organizacion_id=%s AND lote_control_id=%s
        """,
        (org_id, int(lot_id)),
    ) or {}

    n = int(row.get("n") or 0)
    mean = float(row["mean"]) if row.get("mean") is not None else None
    sd = float(row["sd"]) if row.get("sd") is not None else None
    cv = (sd / mean * 100) if sd is not None and mean not in (None, 0) else None
    bias = ((mean - target_mean) / target_mean * 100) if mean is not None and target_mean else None
    sigma = None
    if allowable_error is not None and cv not in (None, 0) and bias is not None:
        sigma = (float(allowable_error) - abs(bias)) / cv

    return {
        "n": n,
        "accepted": int(row.get("accepted") or 0),
        "warnings": int(row.get("warnings") or 0),
        "rejected": int(row.get("rejected") or 0),
        "mean": mean,
        "sd": sd,
        "cv": cv,
        "bias": bias,
        "sigma": sigma,
    }


def list_users(conn):
    org_id = current_org_id()
    if org_id is None:
        return pd.DataFrame()
    return fetchall_df(
        conn,
        """
        SELECT id,nombre_completo,username,rol,activo,cambio_password_requerido,
               intentos_fallidos,bloqueado_hasta,ultimo_acceso,fecha_creacion
        FROM usuarios
        WHERE organizacion_id=%s
        ORDER BY nombre_completo
        """,
        (org_id,),
    )


def list_audit(conn, limit=1000):
    org_id = current_org_id()
    if org_id is None:
        return pd.DataFrame()
    return fetchall_df(
        conn,
        "SELECT * FROM auditoria WHERE organizacion_id=%s ORDER BY fecha_hora DESC LIMIT %s",
        (org_id, limit),
    )

# -----------------------------------------------------------------------------
# GRÁFICOS Y PDF
# -----------------------------------------------------------------------------
def levey_jennings_figure(df: pd.DataFrame, mean: float, sd: float, unit: str):
    """Gráfico Levey–Jennings único, legible y con reglas Westgard en el hover.

    Los valores extremadamente alejados no deforman la escala del gráfico:
    se representan en el borde superior/inferior como puntos fuera de escala,
    conservando en el hover su valor real y las reglas infringidas.
    """
    df = df.tail(300).copy()
    mean = float(mean)
    sd = float(sd)

    fig = go.Figure()

    if df.empty:
        fig.update_layout(
            height=500,
            margin=dict(l=30, r=90, t=30, b=48),
            xaxis_title="Fecha",
            yaxis_title=unit,
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            font=dict(color="#14213d", family="Arial"),
            showlegend=False,
        )
        return fig

    plot_df = df.copy()
    plot_df["fecha_plot"] = pd.to_datetime(plot_df["fecha"], errors="coerce")
    plot_df["valor_real"] = pd.to_numeric(plot_df["valor"], errors="coerce")
    plot_df = plot_df.dropna(subset=["fecha_plot", "valor_real"]).copy()

    # Separar levemente resultados registrados el mismo día para evitar líneas verticales.
    if not plot_df.empty:
        duplicate_idx = plot_df.groupby("fecha_plot").cumcount()
        duplicate_count = plot_df.groupby("fecha_plot")["fecha_plot"].transform("size")
        offset_minutes = duplicate_idx - (duplicate_count - 1) / 2
        plot_df["fecha_plot"] = plot_df["fecha_plot"] + pd.to_timedelta(
            offset_minutes * 18, unit="m"
        )

    # Reglas Westgard para mostrar en el hover.
    if "reglas_violadas" in plot_df.columns:
        plot_df["reglas_hover"] = (
            plot_df["reglas_violadas"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace({"": "Ninguna", "None": "Ninguna", "nan": "Ninguna"})
        )
    else:
        plot_df["reglas_hover"] = "Ninguna"

    if "estado" not in plot_df.columns:
        plot_df["estado"] = "Pendiente"

    status_colors = {
        "Aceptado": "#0da778",
        "Advertencia": "#d99113",
        "Rechazado": "#ef334e",
        "Pendiente": "#1769d2",
    }
    plot_df["color"] = plot_df["estado"].map(status_colors).fillna("#1769d2")

    # Rango visual fijo alrededor de la zona útil de control.
    # Los valores extremos se muestran en el borde, pero su valor real permanece en hover.
    if sd > 0:
        visual_pad = max(sd * 0.55, abs(mean) * 0.015, 1e-6)
        visual_min = mean - 3 * sd - visual_pad
        visual_max = mean + 3 * sd + visual_pad

        plot_df["fuera_escala"] = (
            (plot_df["valor_real"] < visual_min)
            | (plot_df["valor_real"] > visual_max)
        )

        cap_margin = max(sd * 0.18, visual_pad * 0.35, 1e-6)
        plot_df["valor_plot"] = plot_df["valor_real"].clip(
            lower=visual_min + cap_margin,
            upper=visual_max - cap_margin,
        )

        plot_df["nota_escala"] = plot_df["fuera_escala"].map(
            {True: "Fuera de escala visual", False: "Dentro de escala"}
        )
    else:
        visual_min = float(plot_df["valor_real"].min())
        visual_max = float(plot_df["valor_real"].max())
        if visual_min == visual_max:
            visual_min -= 1
            visual_max += 1
        plot_df["fuera_escala"] = False
        plot_df["valor_plot"] = plot_df["valor_real"]
        plot_df["nota_escala"] = "Dentro de escala"

    # Línea de tendencia: no unir resultados rechazados ni puntos fuera de escala.
    trend_y = plot_df["valor_plot"].where(
        (plot_df["estado"] != "Rechazado") & (~plot_df["fuera_escala"])
    )
    fig.add_trace(
        go.Scatter(
            x=plot_df["fecha_plot"],
            y=trend_y,
            mode="lines",
            line=dict(width=2.1, color="#1769d2"),
            hoverinfo="skip",
            connectgaps=False,
            showlegend=False,
            name="Tendencia",
        )
    )

    # Símbolo especial para puntos fuera de escala.
    symbols = [
        "triangle-up" if outside and real > visual_max
        else "triangle-down" if outside
        else "circle"
        for outside, real in zip(plot_df["fuera_escala"], plot_df["valor_real"])
    ]
    sizes = [12 if outside else 9 for outside in plot_df["fuera_escala"]]

    customdata = plot_df[
        ["estado", "reglas_hover", "valor_real", "nota_escala"]
    ].to_numpy()

    fig.add_trace(
        go.Scatter(
            x=plot_df["fecha_plot"],
            y=plot_df["valor_plot"],
            mode="markers",
            marker=dict(
                size=sizes,
                symbol=symbols,
                color=plot_df["color"],
                line=dict(width=1.5, color="#ffffff"),
            ),
            customdata=customdata,
            hovertemplate=(
                "<b>%{x|%d-%m-%Y}</b><br>"
                "Resultado: <b>%{customdata[2]:.4f} " + unit + "</b><br>"
                "Estado: %{customdata[0]}<br>"
                "Regla(s) infringida(s): <b>%{customdata[1]}</b><br>"
                "%{customdata[3]}"
                "<extra></extra>"
            ),
            showlegend=False,
            name="Resultado",
        )
    )

    if sd > 0:
        # Bandas visuales de control.
        bands = [
            (-3, -2, "rgba(239,51,78,0.055)"),
            (-2, -1, "rgba(217,145,19,0.055)"),
            (-1,  1, "rgba(13,167,120,0.045)"),
            ( 1,  2, "rgba(217,145,19,0.055)"),
            ( 2,  3, "rgba(239,51,78,0.055)"),
        ]
        for low_mult, high_mult, fill in bands:
            fig.add_hrect(
                y0=mean + low_mult * sd,
                y1=mean + high_mult * sd,
                fillcolor=fill,
                line_width=0,
                layer="below",
            )

        levels = [
            (0,  "Media", "solid", "#13233f", 2.1),
            (1,  "+1 DE", "dot",   "#8da0b8", 1.2),
            (-1, "-1 DE", "dot",   "#8da0b8", 1.2),
            (2,  "+2 DE", "dash",  "#d99113", 1.4),
            (-2, "-2 DE", "dash",  "#d99113", 1.4),
            (3,  "+3 DE", "solid", "#ef334e", 1.5),
            (-3, "-3 DE", "solid", "#ef334e", 1.5),
        ]

        for mult, label, dash, color, width in levels:
            y_ref = mean + mult * sd
            fig.add_hline(
                y=y_ref,
                line_dash=dash,
                line_color=color,
                line_width=width,
            )
            fig.add_annotation(
                x=1.006,
                xref="paper",
                y=y_ref,
                yref="y",
                text=label,
                showarrow=False,
                xanchor="left",
                yanchor="middle",
                font=dict(size=11, color=color),
                bgcolor="rgba(255,255,255,0.82)",
                borderpad=2,
            )

        fig.update_yaxes(range=[visual_min, visual_max])

    # Anotar discretamente los puntos que fueron llevados al borde de la escala.
    extremes = plot_df[plot_df["fuera_escala"]]
    for _, r in extremes.iterrows():
        direction = "↑" if r["valor_real"] > visual_max else "↓"
        fig.add_annotation(
            x=r["fecha_plot"],
            y=r["valor_plot"],
            text=f"{direction} {r['valor_real']:.4f}",
            showarrow=False,
            yshift=16 if direction == "↑" else -16,
            font=dict(size=10, color="#b4233a"),
            bgcolor="rgba(255,255,255,0.88)",
        )

    fig.update_layout(
        height=520,
        margin=dict(l=30, r=90, t=28, b=48),
        hovermode="closest",
        showlegend=False,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#14213d", family="Arial"),
    )
    fig.update_xaxes(
        title_text="Fecha",
        gridcolor="#edf1f6",
        zeroline=False,
        tickfont=dict(color="#6d7890"),
        title_font=dict(color="#6d7890"),
        tickformat="%d-%m-%Y",
    )
    fig.update_yaxes(
        title_text=unit,
        gridcolor="#edf1f6",
        zeroline=False,
        tickfont=dict(color="#6d7890"),
        title_font=dict(color="#6d7890"),
    )

    return fig


def levey_jennings_pdf_image(results: pd.DataFrame, mean: float, sd: float, unit: str) -> BytesIO:
    """Genera una imagen PNG del gráfico Levey-Jennings para incrustarla en el PDF."""
    image_buffer = BytesIO()

    fig, ax = plt.subplots(figsize=(10.2, 4.4), dpi=170)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    if not results.empty:
        df_plot = results.copy()
        df_plot["fecha"] = pd.to_datetime(df_plot["fecha"], errors="coerce")
        df_plot = df_plot.dropna(subset=["fecha", "valor"]).sort_values(["fecha", "id"] if "id" in df_plot.columns else ["fecha"])
        x = list(range(len(df_plot)))
        y = pd.to_numeric(df_plot["valor"], errors="coerce").tolist()

        ax.plot(
            x, y,
            color="#1769D2",
            linewidth=2.0,
            marker="o",
            markersize=5.2,
            markerfacecolor="#FFFFFF",
            markeredgecolor="#1769D2",
            markeredgewidth=1.4,
            zorder=4,
        )

        # Resaltar visualmente advertencias y rechazos.
        for i, (_, row) in enumerate(df_plot.iterrows()):
            estado = str(row.get("estado", ""))
            if estado == "Rechazado":
                ax.scatter(i, row["valor"], s=46, color="#EF334E", edgecolor="white", linewidth=0.8, zorder=6)
            elif estado == "Advertencia":
                ax.scatter(i, row["valor"], s=46, color="#D99113", edgecolor="white", linewidth=0.8, zorder=6)

        labels = df_plot["fecha"].dt.strftime("%d-%m-%Y").tolist()
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=7.2)

    # Líneas de referencia Westgard / Levey-Jennings.
    reference_lines = [
        (0, "Media", "#13233F", "-", 1.7),
        (1, "+1 DE", "#8DA0B8", ":", 1.1),
        (-1, "-1 DE", "#8DA0B8", ":", 1.1),
        (2, "+2 DE", "#D99113", "--", 1.25),
        (-2, "-2 DE", "#D99113", "--", 1.25),
        (3, "+3 DE", "#EF334E", "-", 1.35),
        (-3, "-3 DE", "#EF334E", "-", 1.35),
    ]

    for mult, label, color, style, width in reference_lines:
        y_ref = mean + mult * sd
        ax.axhline(y_ref, color=color, linestyle=style, linewidth=width, zorder=1)
        ax.text(
            1.003, y_ref, label,
            transform=ax.get_yaxis_transform(),
            va="center", ha="left",
            fontsize=7.2, color=color,
        )

    ax.set_title("Gráfico de Levey-Jennings", loc="left", fontsize=12, fontweight="bold", color="#14213D", pad=10)
    ax.set_xlabel("Fecha", fontsize=8.5, color="#56647A")
    ax.set_ylabel(unit, fontsize=8.5, color="#56647A")
    ax.grid(axis="y", color="#E9EEF5", linewidth=0.8, alpha=0.95)
    ax.grid(axis="x", visible=False)
    ax.tick_params(colors="#68758A", labelsize=7.5)

    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#DDE3EC")

    # Asegurar espacio para etiquetas de referencia a la derecha.
    fig.subplots_adjust(left=0.075, right=0.91, top=0.86, bottom=0.26)
    fig.savefig(image_buffer, format="png", dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    image_buffer.seek(0)
    return image_buffer


def _generate_pdf_uncached(analyte: dict, lot: dict, results: pd.DataFrame, stats: dict) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=1.5*cm,
        leftMargin=1.5*cm,
        topMargin=1.3*cm,
        bottomMargin=1.3*cm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title2",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#14213D"),
        spaceAfter=4,
    )
    section = ParagraphStyle(
        "SectionTMQ",
        parent=styles["Heading2"],
        fontSize=11.5,
        leading=14,
        textColor=colors.HexColor("#14213D"),
        spaceBefore=4,
        spaceAfter=7,
    )

    story = [
        Paragraph(f"TMQuality {APP_VERSION} - Informe de Control de Calidad", title),
        Spacer(1, .25*cm),
        Paragraph(f"<b>Analito:</b> {analyte['nombre']} &nbsp;&nbsp; <b>Unidad:</b> {analyte['unidad']}", styles["BodyText"]),
        Paragraph(f"<b>Lote:</b> {lot['lote']} &nbsp;&nbsp; <b>Nivel:</b> {lot['nivel']}", styles["BodyText"]),
        Paragraph(
            f"<b>Límites:</b> {float(lot.get('limite_inferior') if lot.get('limite_inferior') is not None else lot['media_objetivo']-3*lot['de_objetivo']):.4f} / "
            f"{float(lot.get('nivel_medio') if lot.get('nivel_medio') is not None else lot['media_objetivo']):.4f} / "
            f"{float(lot.get('limite_superior') if lot.get('limite_superior') is not None else lot['media_objetivo']+3*lot['de_objetivo']):.4f} "
            f"(inferior / medio / superior)",
            styles["BodyText"],
        ),
        Spacer(1, .3*cm),
    ]

    summary = [
        ["Indicador", "Valor"],
        ["N", str(stats.get("n", 0))],
        ["Media observada", f"{stats['mean']:.4f}" if stats.get("mean") is not None else "-"],
        ["DE observada", f"{stats['sd']:.4f}" if stats.get("sd") is not None else "-"],
        ["CV%", f"{stats['cv']:.2f}%" if stats.get("cv") is not None else "-"],
        ["Sesgo%", f"{stats['bias']:.2f}%" if stats.get("bias") is not None else "-"],
        ["Sigma", f"{stats['sigma']:.2f}" if stats.get("sigma") is not None else "-"],
    ]
    t = Table(summary, colWidths=[6*cm, 5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#14213D")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), .3, colors.HexColor("#DDE3EC")),
        ("PADDING", (0,0), (-1,-1), 6),
        ("BACKGROUND", (0,1), (-1,-1), colors.white),
        ("TEXTCOLOR", (0,1), (-1,-1), colors.HexColor("#14213D")),
    ]))
    story.extend([t, Spacer(1, .4*cm)])

    # ------------------------------------------------------------------
    # Gráfico Levey-Jennings incluido en el informe PDF
    # ------------------------------------------------------------------
    story.append(Paragraph("Levey-Jennings del lote", section))
    chart_buffer = levey_jennings_pdf_image(
        results,
        float(lot["media_objetivo"]),
        float(lot["de_objetivo"]),
        str(analyte["unidad"]),
    )
    chart = Image(chart_buffer, width=17.2*cm, height=7.4*cm)
    story.extend([chart, Spacer(1, .45*cm)])

    if not results.empty:
        story.append(Paragraph("Resultados incluidos", section))
        cols = ["fecha", "turno", "operador", "valor", "estado", "reglas_violadas"]
        data = [["Fecha","Turno","Operador","Valor","Estado","Reglas"]]
        for _, r in results.tail(40).iterrows():
            data.append([str(r.get(c, ""))[:28] for c in cols])
        rt = Table(
            data,
            repeatRows=1,
            colWidths=[2.1*cm,1.7*cm,3.2*cm,2*cm,2.2*cm,4*cm],
        )
        rt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EAF0F8")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#14213D")),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), .25, colors.HexColor("#DDE3EC")),
            ("FONTSIZE", (0,0), (-1,-1), 7),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("BACKGROUND", (0,1), (-1,-1), colors.white),
        ]))
        story.append(rt)

    story.append(Spacer(1, .3*cm))
    story.append(Paragraph(f"Generado: {datetime.now():%d-%m-%Y %H:%M}", styles["BodyText"]))
    doc.build(story)
    buffer.seek(0)
    return buffer

# -----------------------------------------------------------------------------
# SESIÓN / LOGIN
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=20)
def _cached_pdf_bytes(
    analyte_items: tuple,
    lot_items: tuple,
    result_records: tuple,
    stats_items: tuple,
) -> bytes:
    analyte = dict(analyte_items)
    lot = dict(lot_items)
    stats = dict(stats_items)
    results = pd.DataFrame([dict(record) for record in result_records])
    return _generate_pdf_uncached(analyte, lot, results, stats).getvalue()


def generate_pdf(analyte: dict, lot: dict, results: pd.DataFrame, stats: dict) -> bytes:
    """Devuelve el PDF cacheado; evita reconstruir gráfico y tablas en cada rerun."""
    safe_results = results.copy()
    for col in safe_results.columns:
        if pd.api.types.is_datetime64_any_dtype(safe_results[col]):
            safe_results[col] = safe_results[col].astype(str)
    records = tuple(tuple(sorted(record.items())) for record in safe_results.to_dict("records"))
    return _cached_pdf_bytes(
        tuple(sorted(analyte.items())),
        tuple(sorted(lot.items())),
        records,
        tuple(sorted(stats.items())),
    )


def logout(conn):
    if st.session_state.get("user"):
        audit(conn, "LOGOUT", "usuarios", st.session_state.user["id"], "Cierre de sesión")
    st.session_state.clear()
    st.rerun()



def render_sidebar_brand():
    with st.sidebar:
        st.markdown(
            f"""
            <div class="tmq-side-brand">
                <img src="data:image/png;base64,{LOGO_ICON_B64}">
                <div>
                    <div class="tmq-side-brand-name">TM<span style="color:#F52D63;">Q</span>uality</div>
                    <div class="tmq-side-brand-sub">Control de calidad analítico</div>
                </div>
            </div>
            <div class="tmq-side-version">Versión {APP_VERSION}</div>
            """,
            unsafe_allow_html=True,
        )

def login_ui(conn):
    render_sidebar_brand()

    # Menú visual de referencia (solo informativo antes de iniciar sesión).
    with st.sidebar:
        st.markdown(
            """
            <div style="margin-top:8px;">
                <div style="padding:10px 12px;border-radius:10px;background:#FFF1F5;color:#F52D63;font-weight:800;margin-bottom:4px;">⌂ &nbsp; Inicio</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">▣ &nbsp; Resultados</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">□ &nbsp; Lotes de control</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">⌁ &nbsp; Gráficos Levey–Jennings</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">⌘ &nbsp; Reglas de Westgard</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">▤ &nbsp; Reportes</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">◇ &nbsp; Acciones correctivas</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">▦ &nbsp; Equipos</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">♙ &nbsp; Analitos</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">♧ &nbsp; Usuarios</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">▧ &nbsp; Auditoría</div>
                <div style="padding:9px 12px;color:#566174;font-weight:650;">⚙ &nbsp; Administración</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        org = fetchone(conn, "SELECT * FROM organizaciones WHERE activo=TRUE ORDER BY id LIMIT 1")
        if org:
            st.markdown(
                f"""
                <div class="tmq-org-card">
                    <div class="tmq-org-kicker">Organización activa</div>
                    <div class="tmq-org-name">{org['nombre']}</div>
                    <div class="tmq-org-meta">Código: {org.get('codigo') or '—'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        f"""
        <div class="tmq-topbar">
            <div class="tmq-topbar-title">Control de calidad analítico · <span>v{APP_VERSION}</span></div>
            <div class="tmq-user-chip">Administrador</div>
        </div>

        <div class="tmq-auth-shell">
            <div class="tmq-auth-heading">
                <div class="tmq-auth-title">Bienvenido a <span>TMQuality</span></div>
                <div class="tmq-auth-subtitle">Plataforma de control de calidad analítico para laboratorios</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([0.08, 0.84, 0.08])
    with center:
        st.markdown('<div class="tmq-login-card">', unsafe_allow_html=True)
        left, right = st.columns([1.08, 1], gap="large")

        with left:
            st.markdown('<div class="tmq-section-pink">♙ &nbsp; Iniciar sesión</div>', unsafe_allow_html=True)
            with st.form("login_form", clear_on_submit=False):
                username = st.text_input("Usuario", placeholder="Ingrese su usuario", autocomplete="username")
                password = st.text_input(
                    "Contraseña",
                    type="password",
                    placeholder="Ingrese su contraseña",
                    autocomplete="current-password",
                )
                submitted = st.form_submit_button("Ingresar", type="primary", use_container_width=True)

            if submitted:
                user, message = authenticate(conn, username, password)
                if user:
                    st.session_state.user = user
                    st.session_state.pop("platform_mode", None)
                    st.session_state.pop("platform_authenticated", None)
                    st.rerun()
                else:
                    st.error(message)

            st.markdown(
                '<div style="text-align:center;color:#F52D63;font-size:13px;margin-top:8px;">¿Olvidó su contraseña?</div>',
                unsafe_allow_html=True,
            )

        with right:
            st.markdown(
                """
                <div class="tmq-login-panel">
                    <div class="tmq-section-pink">♢ &nbsp; Acceso administrador de plataforma</div>
                    <div class="tmq-platform-copy">
                        Solo para el administrador general de TMQuality.<br><br>
                        Desde aquí podrás crear y gestionar laboratorios (organizaciones).
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
            if st.button("⚙  Administración de plataforma", use_container_width=True):
                st.session_state.platform_mode = True
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class="tmq-info">
            <strong>ⓘ &nbsp; Información</strong><br>
            Si eres administrador de un laboratorio, inicia sesión con tu usuario y contraseña.<br>
            Si necesitas acceso a la administración de plataforma, solicita el token al propietario de TMQuality.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="tmq-app-footer">
            <span class="version notranslate" translate="no">TMQuality® v{APP_VERSION}</span>
            <span>© 2026 TMQuality · Todos los derechos reservados</span>
            <span>Hecho con ♥ para laboratorios</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

def forced_password_change_ui(conn, user: dict):
    st.warning("Debes cambiar tu contraseña antes de continuar.")
    with st.form("forced_password"):
        p1 = st.text_input("Nueva contraseña", type="password")
        p2 = st.text_input("Repetir contraseña", type="password")
        submitted = st.form_submit_button("Actualizar contraseña", type="primary")
    if submitted:
        if p1 != p2:
            st.error("Las contraseñas no coinciden.")
        else:
            try:
                change_password(conn, user["id"], p1, actor=user, require_change=False)
                st.session_state.user = fetchone(conn, "SELECT * FROM usuarios WHERE id=%s AND organizacion_id=%s", (user["id"], current_org_id(user)))
                st.success("Contraseña actualizada.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.stop()

# -----------------------------------------------------------------------------
# COMPONENTES DE UI
# -----------------------------------------------------------------------------
def kpi(label: str, value: str, hint: str = "", tone: str = "info"):
    st.markdown(f"""<div class="tmq-kpi {tone}"><div class="label">{label}</div><div class="value">{value}</div><div class="hint">{hint}</div></div>""", unsafe_allow_html=True)


def selected_context_ui(conn, *, include_results: bool = True, result_limit: Optional[int] = None):
    analytes = load_analytes(conn)
    if analytes.empty:
        return None, None, None
    analyte_map = {f"{r.nombre} · {r.unidad}": int(r.id) for r in analytes.itertuples()}
    a_label = st.selectbox("Analito", list(analyte_map.keys()), key="global_analyte")
    analyte_id = analyte_map[a_label]
    analyte = fetchone(
        conn,
        "SELECT * FROM analitos WHERE id=%s AND organizacion_id=%s",
        (analyte_id, current_org_id()),
    )
    lots = load_lots(conn, analyte_id)
    if lots.empty:
        return analyte, None, None
    lot_map = {f"{r.nivel} · {r.lote}": int(r.id) for r in lots.itertuples()}
    l_label = st.selectbox("Lote de control", list(lot_map.keys()), key="global_lot")
    lot = fetchone(
        conn,
        "SELECT * FROM lotes_control WHERE id=%s AND organizacion_id=%s",
        (lot_map[l_label], current_org_id()),
    )
    results = load_results(conn, lot["id"], limit=result_limit) if include_results else None
    return analyte, lot, results

# -----------------------------------------------------------------------------
# MÓDULOS
# -----------------------------------------------------------------------------
def module_dashboard(conn, analyte, lot, results):
    if not analyte or not lot:
        st.info("Crea un analito y un lote para comenzar.")
        return

    stats = result_summary(
        conn, int(lot["id"]), float(lot["media_objetivo"]),
        analyte.get("error_total_permitido")
    )
    total_results = int(stats["n"])
    accepted = int(stats["accepted"])
    warn = int(stats["warnings"])
    reject = int(stats["rejected"])
    conform = accepted / total_results * 100 if total_results else 0

    if not total_results:
        state, state_cls = "SIN DATOS", ""
    elif reject:
        state, state_cls = "REVISAR LOTE", "bad"
    elif warn:
        state, state_cls = "EN ADVERTENCIA", ""
    else:
        state, state_cls = "EN CONTROL", "good"

    level_name = str(lot.get("nivel") or "—")
    level_display = level_name if level_name.lower().startswith("nivel") else f"Nivel {level_name}"

    latest = None
    if results is not None and not results.empty:
        recent_sorted = results.copy()
        recent_sorted["fecha_sort"] = pd.to_datetime(recent_sorted["fecha"], errors="coerce")
        sort_cols = ["fecha_sort"]
        if "hora" in recent_sorted.columns:
            sort_cols.append("hora")
        if "id" in recent_sorted.columns:
            sort_cols.append("id")
        latest = recent_sorted.sort_values(sort_cols).iloc[-1]

    expiry_value, expiry_hint, expiry_kind = "—", "Sin fecha de vencimiento", "info"
    if lot.get("fecha_vencimiento"):
        try:
            expiry_date = pd.to_datetime(lot["fecha_vencimiento"]).date()
            days_left = (expiry_date - date.today()).days
            expiry_value = expiry_date.strftime("%d-%m-%Y")
            if days_left < 0:
                expiry_hint, expiry_kind = f"Vencido hace {abs(days_left)} día(s)", "bad"
            elif days_left == 0:
                expiry_hint, expiry_kind = "Vence hoy", "bad"
            elif days_left <= 30:
                expiry_hint, expiry_kind = f"Vence en {days_left} día(s)", "warn"
            else:
                expiry_hint, expiry_kind = f"{days_left} días restantes", "good"
        except Exception:
            pass

    st.markdown('<div class="tmq-section">Resumen del lote</div>', unsafe_allow_html=True)
    a, b, c, d = st.columns([1.25, 1, 1, 1])

    with a:
        st.markdown(
            f"<div class='tmq-status {state_cls}'><div class='eyebrow'>Estado del lote</div>"
            f"<div class='big'>{state}</div>"
            f"<div class='small'>{analyte['nombre']} · {level_display} · Lote {lot['lote']}</div></div>",
            unsafe_allow_html=True,
        )

    with b:
        if latest is None:
            kpi("Último resultado", "—", "Aún no hay resultados", "info")
        else:
            latest_state = str(latest.get("estado") or "Pendiente")
            latest_rules = str(latest.get("reglas_violadas") or "").strip() or "Sin reglas infringidas"
            latest_date = pd.to_datetime(latest.get("fecha"), errors="coerce")
            date_txt = latest_date.strftime("%d-%m-%Y") if not pd.isna(latest_date) else "—"
            kind = "bad" if latest_state == "Rechazado" else "warn" if latest_state == "Advertencia" else "good"
            kpi("Último resultado", f"{float(latest['valor']):.4f}",
                f"{date_txt} · {latest_state} · {latest_rules}", kind)

    with c:
        kpi("Conformidad", f"{conform:.1f}%",
            f"{accepted} aceptado(s) · {warn} advertencia(s) · {reject} rechazo(s)",
            "good" if conform >= 90 and reject == 0 else "warn" if reject == 0 else "bad")

    with d:
        kpi("Vencimiento", expiry_value, expiry_hint, expiry_kind)

    if state in ("REVISAR LOTE", "EN ADVERTENCIA"):
        reasons = []
        if reject:
            reasons.append(f"{reject} resultado(s) rechazado(s)")
        if warn:
            reasons.append(f"{warn} advertencia(s)")
        reason_text = " · ".join(reasons)
        if reject:
            st.error(f"Este lote requiere revisión: {reason_text}. Revisa la secuencia y las reglas infringidas.")
        else:
            st.warning(f"Este lote presenta advertencias: {reason_text}. Revisa la secuencia y las reglas infringidas.")

    act1, act2, act3 = st.columns(3)
    with act1:
        if st.button("Ver resultados críticos", use_container_width=True,
                     key=f"review_results_{int(lot['id'])}", disabled=(warn + reject == 0)):
            st.session_state.pending_nav = "Resultados"
            st.rerun()

    with act2:
        if st.button("↻ Recalcular lote", use_container_width=True,
                     key=f"review_recalc_{int(lot['id'])}", disabled=(total_results == 0)):
            try:
                n_updated = recalcular_reglas_lote(
                    conn, int(lot["id"]), float(lot["media_objetivo"]), float(lot["de_objetivo"])
                )
                audit(conn, "LOTE_RECALCULADO", "resultados_cc", int(lot["id"]),
                      f"Reevaluación cronológica de {n_updated} resultado(s)")
                st.success(f"Se recalcularon {n_updated} resultado(s).")
                st.rerun()
            except Exception as exc:
                conn.rollback()
                st.error(f"No fue posible recalcular el lote: {exc}")

    with act3:
        user = st.session_state.get("user")
        if user and user["rol"] == "Administrador":
            if st.button("＋ Crear nuevo lote", use_container_width=True,
                         key=f"review_new_lot_{int(lot['id'])}"):
                st.session_state.new_lot_analyte_id = int(analyte["id"])
                st.session_state.pending_nav = "Lotes de control"
                st.rerun()
        else:
            st.button("＋ Crear nuevo lote", use_container_width=True,
                      key=f"review_new_lot_disabled_{int(lot['id'])}", disabled=True)

    st.markdown('<div class="tmq-section">Control de calidad reciente</div>', unsafe_allow_html=True)
    if results is None or results.empty:
        st.info("Aún no hay resultados para visualizar.")
    else:
        recent_chart = results.tail(30).copy()
        st.caption("Últimos 30 resultados. Pasa el cursor sobre un punto para ver estado y reglas infringidas.")
        st.plotly_chart(
            levey_jennings_figure(recent_chart, lot["media_objetivo"], lot["de_objetivo"], analyte["unidad"]),
            use_container_width=True, theme=None,
            config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
        )

    st.markdown('<div class="tmq-section">Requiere atención</div>', unsafe_allow_html=True)
    if results is None or results.empty:
        st.caption("No hay resultados registrados.")
    else:
        attention = results[results["estado"].isin(["Advertencia", "Rechazado"])].copy()
        if attention.empty:
            st.success("No hay resultados con advertencias o rechazos en el lote seleccionado.")
        else:
            attention["fecha"] = pd.to_datetime(attention["fecha"], errors="coerce")
            sort_cols = ["fecha"] + (["id"] if "id" in attention.columns else [])
            attention = attention.sort_values(sort_cols, ascending=False).head(6)
            cols = [x for x in ["fecha","valor","z_score","estado","reglas_violadas","operador"] if x in attention.columns]
            view = attention[cols].copy()
            view["fecha"] = view["fecha"].dt.strftime("%d-%m-%Y")
            view = view.rename(columns={
                "fecha":"Fecha", "valor":f"Resultado ({analyte['unidad']})",
                "z_score":"z-score", "estado":"Estado",
                "reglas_violadas":"Regla(s) infringida(s)", "operador":"Operador"
            })
            st.dataframe(view, use_container_width=True, hide_index=True)

    st.markdown('<div class="tmq-section">Verificación del lote</div>', unsafe_allow_html=True)
    if results is None or results.empty:
        st.caption("La verificación estará disponible cuando existan resultados.")
    else:
        check_df = results.copy()
        check_df["fecha_sort"] = pd.to_datetime(check_df["fecha"], errors="coerce")
        sort_cols = ["fecha_sort"]
        if "hora" in check_df.columns:
            sort_cols.append("hora")
        if "id" in check_df.columns:
            sort_cols.append("id")
        check_df = check_df.sort_values(sort_cols)

        previous_z, mismatches = [], []
        for _, r in check_df.iterrows():
            current_z = zscore(float(r["valor"]), float(lot["media_objetivo"]), float(lot["de_objetivo"]))
            rules_now = westgard_rules(previous_z + [current_z])
            state_now = state_from_rules(rules_now)
            stored_state = str(r.get("estado") or "")
            stored_rules = str(r.get("reglas_violadas") or "").strip()
            stored_set = {x.strip() for x in stored_rules.split(",") if x.strip()}
            current_set = {str(x).strip() for x in rules_now if str(x).strip()}

            if stored_state != state_now or stored_set != current_set:
                fdate = pd.to_datetime(r.get("fecha"), errors="coerce")
                mismatches.append({
                    "ID": int(r["id"]) if "id" in r and pd.notna(r["id"]) else "—",
                    "Fecha": fdate.strftime("%d-%m-%Y") if not pd.isna(fdate) else "—",
                    "Estado guardado": stored_state or "—",
                    "Estado recalculado": state_now,
                    "Reglas guardadas": stored_rules or "Ninguna",
                    "Reglas recalculadas": ", ".join(rules_now) if rules_now else "Ninguna",
                })
            previous_z.append(current_z)

        if mismatches:
            st.warning(f"Se encontraron {len(mismatches)} resultado(s) con diferencias entre lo guardado y el recálculo actual.")
            st.dataframe(pd.DataFrame(mismatches), use_container_width=True, hide_index=True)
        else:
            st.success("La clasificación almacenada coincide con el recálculo de la secuencia actual.")

        st.caption(
            "Esta comprobación verifica consistencia interna usando la implementación actual. "
            "Para validar técnicamente cada criterio Westgard también debe revisarse services.py."
        )

    st.markdown('<div class="tmq-section">Indicadores analíticos</div>', unsafe_allow_html=True)
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        kpi("CV", f"{stats['cv']:.2f}%" if stats['cv'] is not None else "—", "Imprecisión observada", "info")
    with c2:
        kpi("Sesgo", f"{stats['bias']:+.2f}%" if stats['bias'] is not None else "—", "Respecto de la media objetivo", "info")
    with c3:
        kpi("Sigma", f"{stats['sigma']:.2f} σ" if stats['sigma'] is not None else "—",
            "Requiere ET permitido", "good" if stats['sigma'] is not None and stats['sigma'] >= 4 else "info")
    with c4:
        kpi("Alertas", str(warn + reject), "Resultados que requieren atención",
            "bad" if reject else "warn" if warn else "good")


def module_register(conn, user, analyte, lot, results):
    st.subheader("Registrar resultado de control")
    if not analyte or not lot:
        st.info("Selecciona un analito y lote vigentes.")
        return
    equipment = load_equipment(conn)
    eq_map = {"Sin equipo asociado": None}
    if not equipment.empty:
        eq_map.update({f"{r.nombre} · {r.modelo or ''} · {r.numero_serie or ''}": int(r.id) for r in equipment.itertuples()})

    with st.form("register_qc", clear_on_submit=True):
        c1,c2,c3 = st.columns(3)
        with c1:
            f = st.date_input("Fecha", value=date.today())
            turno = st.selectbox("Turno", TURNOS)
        with c2:
            eq_label = st.selectbox("Equipo", list(eq_map.keys()))
            valor = st.number_input(f"Valor ({analyte['unidad']})", value=float(lot["media_objetivo"]), format="%.4f")
        with c3:
            comentario = st.text_area("Comentario", placeholder="Opcional")
        submitted = st.form_submit_button("Registrar y evaluar", type="primary", use_container_width=True)

    preview_z = zscore(float(valor), float(lot["media_objetivo"]), float(lot["de_objetivo"]))
    st.caption(f"z-score estimado: {preview_z:+.2f}")

    if submitted:
        previous_z = [] if results.empty else [float(x) for x in results["z_score"].dropna().tolist()]
        current_z = zscore(float(valor), lot["media_objetivo"], lot["de_objetivo"])
        rules = westgard_rules(previous_z + [current_z])
        state = state_from_rules(rules)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO resultados_cc
                (organizacion_id,lote_control_id,equipo_id,usuario_id,fecha,turno,operador,valor,z_score,reglas_violadas,estado,comentarios)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (current_org_id(user), lot["id"], eq_map[eq_label], user["id"], f, turno, user["nombre_completo"], valor, current_z,
                 ", ".join(rules) if rules else "", state, comentario.strip() or None),
            )
            rid = cur.fetchone()[0]
        conn.commit()
        audit(conn, "RESULTADO_REGISTRADO", "resultados_cc", rid,
              f"{analyte['nombre']}={valor} {analyte['unidad']} | Estado={state} | Reglas={','.join(rules) or 'ninguna'}")
        if state == "Aceptado": st.success("Resultado aceptado por las reglas configuradas.")
        elif state == "Advertencia": st.warning(f"Advertencia: {', '.join(rules)}")
        else: st.error(f"Resultado rechazado: {', '.join(rules)}")
        st.rerun()



def delete_qc_result(conn, result_id: int, user: dict, lot: dict) -> int:
    """Elimina definitivamente un resultado y recalcula cronológicamente el lote.

    Devuelve la cantidad de resultados reevaluados después de la eliminación.
    La acción queda registrada en auditoría con los datos esenciales del resultado.
    """
    org_id = current_org_id(user)
    row = fetchone(
        conn,
        """
        SELECT r.id, r.lote_control_id, r.fecha, r.turno, r.operador, r.valor,
               r.z_score, r.estado, r.reglas_violadas, r.comentarios,
               l.lote, l.nivel, a.nombre AS analito, a.unidad
        FROM resultados_cc r
        JOIN lotes_control l
          ON l.id=r.lote_control_id
         AND l.organizacion_id=r.organizacion_id
        JOIN analitos a
          ON a.id=l.analito_id
         AND a.organizacion_id=l.organizacion_id
        WHERE r.id=%s
          AND r.organizacion_id=%s
          AND r.lote_control_id=%s
        """,
        (int(result_id), org_id, int(lot["id"])),
    )
    if not row:
        raise ValueError("El resultado no existe o no pertenece al lote seleccionado.")

    detail = (
        f"{row['analito']} · {row['nivel']} · lote {row['lote']} · "
        f"fecha {row['fecha']} · valor {row['valor']} {row['unidad']} · "
        f"estado {row['estado']}"
    )

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM resultados_cc
                WHERE id=%s
                  AND organizacion_id=%s
                  AND lote_control_id=%s
                """,
                (int(result_id), org_id, int(lot["id"])),
            )
            if cur.rowcount != 1:
                raise ValueError("No fue posible identificar un único resultado para eliminar.")
        conn.commit()

        n_actualizados = recalcular_reglas_lote(
            conn,
            int(lot["id"]),
            float(lot["media_objetivo"]),
            float(lot["de_objetivo"]),
        )

        audit(
            conn,
            "RESULTADO_ELIMINADO",
            "resultados_cc",
            int(result_id),
            detail + f" · eliminación permanente · {n_actualizados} resultado(s) reevaluados",
        )
        return int(n_actualizados)

    except Exception:
        conn.rollback()
        raise


def module_history(conn, user, analyte, lot, results):
    st.subheader("Historial y acciones correctivas")
    if not lot or results.empty:
        st.info("No hay resultados registrados para este lote.")
        return

    # Herramienta de consistencia del lote.
    tool_left, tool_right = st.columns([3, 1])
    with tool_left:
        st.caption(
            "Si agregaste, corregiste o eliminaste resultados, recalcula el lote "
            "para volver a evaluar cronológicamente todas las reglas de Westgard."
        )
    with tool_right:
        if st.button(
            "↻ Recalcular lote",
            key=f"recalc_lot_{int(lot['id'])}",
            use_container_width=True,
            help="Recalcula z-score, reglas violadas y estado de todos los resultados del lote.",
        ):
            try:
                n_actualizados = recalcular_reglas_lote(
                    conn,
                    int(lot["id"]),
                    float(lot["media_objetivo"]),
                    float(lot["de_objetivo"]),
                )
                audit(
                    conn,
                    "LOTE_RECALCULADO",
                    "resultados_cc",
                    int(lot["id"]),
                    f"Reevaluación cronológica de {n_actualizados} resultado(s)",
                )
                st.success(f"Se recalcularon {n_actualizados} resultado(s) del lote.")
                st.rerun()
            except Exception as exc:
                conn.rollback()
                st.error(f"No fue posible recalcular el lote: {exc}")

    df = results.sort_values(["fecha","hora"], ascending=False).copy()
    if len(results) >= 500:
        st.caption(
            "Por rendimiento se muestran hasta 500 resultados recientes en esta vista. "
            "Los reportes por fecha consultan directamente el historial completo."
        )
    state_filter = st.multiselect("Estado", ESTADOS, default=[])
    if state_filter:
        df = df[df["estado"].isin(state_filter)]
    st.dataframe(df[[c for c in ["id","fecha","turno","operador","equipo_nombre","valor","z_score","estado","reglas_violadas","accion_correctiva","comentarios"] if c in df.columns]],
                 use_container_width=True, hide_index=True)

    st.markdown("#### Revisión de resultado")
    rid = st.selectbox("Resultado", df["id"].tolist(), format_func=lambda x: f"ID {x}")
    row = df[df["id"] == rid].iloc[0]
    with st.form("review_result"):
        action = st.text_area("Acción correctiva", value=str(row.get("accion_correctiva") or ""))
        comment = st.text_area("Comentario / fundamento", value=str(row.get("comentarios") or ""))
        save = st.form_submit_button("Guardar revisión", type="primary")
    if save:
        execute(conn, """
            UPDATE resultados_cc SET accion_correctiva=%s, comentarios=%s, revisado_por=%s,
            fecha_revision=CURRENT_TIMESTAMP, fecha_modificacion=CURRENT_TIMESTAMP WHERE id=%s
        """, (action.strip() or None, comment.strip() or None, user["id"], int(rid)))
        audit(conn, "RESULTADO_REVISADO", "resultados_cc", rid, "Acción correctiva/comentario actualizado")
        st.success("Revisión guardada.")
        st.rerun()

    if user["rol"] == "Administrador":
        st.divider()
        st.markdown("#### Eliminar resultado")
        st.warning(
            "La eliminación es permanente y no se puede deshacer. "
            "Al eliminar un resultado, TMQuality recalculará automáticamente "
            "las reglas de Westgard de todo el lote porque la secuencia cronológica cambia."
        )

        result_date = row.get("fecha")
        result_value = row.get("valor")
        result_state = row.get("estado") or "—"
        st.info(
            f"Resultado seleccionado: ID {int(rid)} · "
            f"{result_date} · {float(result_value):.4f} {analyte['unidad']} · "
            f"Estado: {result_state}"
        )

        confirm_delete = st.checkbox(
            "Confirmo que revisé el resultado seleccionado y deseo eliminarlo permanentemente.",
            key=f"confirm_delete_result_{int(rid)}",
        )

        typed_id = ""
        if confirm_delete:
            typed_id = st.text_input(
                f"Para confirmar, escribe exactamente el ID del resultado: {int(rid)}",
                key=f"type_delete_result_{int(rid)}",
            )

        if st.button(
            "Eliminar resultado definitivamente",
            type="primary",
            use_container_width=True,
            key=f"delete_result_{int(rid)}",
            disabled=(not confirm_delete or typed_id.strip() != str(int(rid))),
        ):
            try:
                n_actualizados = delete_qc_result(conn, int(rid), user, lot)
                st.success(
                    f"Resultado ID {int(rid)} eliminado. "
                    f"Se reevaluaron {n_actualizados} resultado(s) del lote."
                )
                st.rerun()
            except Exception as exc:
                conn.rollback()
                st.error(f"No fue posible eliminar el resultado: {exc}")
    else:
        st.caption(
            "La eliminación permanente de resultados está disponible solo para Administradores."
        )


def module_analytics(conn, analyte, lot, results):
    st.subheader("Analítica de desempeño")
    st.caption(
        "Resumen estadístico del lote y evolución de la precisión a través del tiempo."
    )

    if not analyte or not lot or results.empty:
        st.info("Se requieren resultados para calcular indicadores.")
        return

    stats = qc_statistics(
        results,
        lot["media_objetivo"],
        analyte.get("error_total_permitido"),
    )

    # ------------------------------------------------------------------
    # Indicadores principales
    # ------------------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Media observada",
        f"{stats['mean']:.4f}" if stats.get("mean") is not None else "—",
        help="Promedio de los resultados de control registrados para el lote seleccionado.",
    )
    c2.metric(
        "DE observada",
        f"{stats['sd']:.4f}" if stats.get("sd") is not None else "—",
        help="Desviación estándar observada de los resultados del lote.",
    )
    c3.metric(
        "CV%",
        f"{stats['cv']:.2f}%" if stats.get("cv") is not None else "—",
        help="Coeficiente de variación: DE / media × 100. Resume la imprecisión observada.",
    )
    c4.metric(
        "Sesgo%",
        f"{stats['bias']:.2f}%" if stats.get("bias") is not None else "—",
        help="Diferencia porcentual entre la media observada y el valor objetivo del lote.",
    )

    # Sigma ocupa su propia tarjeta porque depende del Error Total Permitido.
    st.markdown("##### Métrica Sigma")
    etp = analyte.get("error_total_permitido")
    if etp is None:
        st.info(
            "Define el Error Total Permitido (%) del analito para calcular la Métrica Sigma."
        )
    else:
        sigma = stats.get("sigma")
        sigma_col, info_col = st.columns([1, 3])

        with sigma_col:
            st.metric(
                "Sigma",
                f"{sigma:.2f}" if sigma is not None else "—",
                help="(Error Total Permitido − |sesgo|) / CV",
            )

        with info_col:
            if sigma is None:
                st.caption(
                    "No es posible calcular Sigma con los resultados disponibles."
                )
            elif sigma >= 6:
                st.success(
                    "Desempeño Sigma muy alto para los parámetros actualmente configurados."
                )
            elif sigma >= 4:
                st.info(
                    "Desempeño Sigma intermedio-alto para los parámetros actualmente configurados."
                )
            elif sigma >= 3:
                st.warning(
                    "Desempeño Sigma moderado. Conviene vigilar la precisión y el sesgo del método."
                )
            else:
                st.error(
                    "Sigma < 3 con los parámetros actualmente configurados. "
                    "Revisa precisión, sesgo y Error Total Permitido antes de interpretar el desempeño."
                )

    st.divider()

    # ------------------------------------------------------------------
    # Tendencia mensual del CV
    # ------------------------------------------------------------------
    st.markdown("##### Tendencia mensual del CV%")

    temp = results.copy()
    temp["fecha"] = pd.to_datetime(temp["fecha"], errors="coerce")
    temp["valor"] = pd.to_numeric(temp["valor"], errors="coerce")
    temp = temp.dropna(subset=["fecha", "valor"]).copy()

    if temp.empty:
        st.info("No hay resultados válidos suficientes para calcular la tendencia mensual.")
        return

    temp["mes_periodo"] = temp["fecha"].dt.to_period("M")

    monthly = (
        temp.groupby("mes_periodo")
        .agg(
            media=("valor", "mean"),
            de=("valor", "std"),
            n=("valor", "count"),
        )
        .reset_index()
        .sort_values("mes_periodo")
    )

    # El CV mensual requiere al menos 2 resultados dentro del mes para calcular DE.
    monthly["cv"] = monthly["de"] / monthly["media"] * 100
    monthly_valid = monthly[
        (monthly["n"] >= 2)
        & monthly["cv"].notna()
        & monthly["cv"].replace([float("inf"), float("-inf")], pd.NA).notna()
    ].copy()

    month_names = {
        1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
        5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
        9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
    }

    if not monthly_valid.empty:
        monthly_valid["mes_label"] = monthly_valid["mes_periodo"].apply(
            lambda p: f"{month_names.get(p.month, p.month)} {p.year}"
        )

    # Con un solo mes, el gráfico no representa una tendencia real.
    if len(monthly_valid) < 2:
        if len(monthly_valid) == 1:
            only = monthly_valid.iloc[0]
            st.info(
                f"Actualmente hay un solo mes con datos suficientes para calcular CV% "
                f"({only['mes_label']}: {only['cv']:.2f}%, n={int(only['n'])}). "
                "Se requieren al menos 2 meses con resultados para mostrar una tendencia."
            )
        else:
            st.info(
                "Se requieren al menos 2 meses con un mínimo de 2 resultados válidos por mes "
                "para mostrar la tendencia mensual del CV%."
            )
        return

    # Gráfico de línea: más adecuado que barras para visualizar tendencia.
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=monthly_valid["mes_label"],
            y=monthly_valid["cv"],
            mode="lines+markers",
            line=dict(width=2.5),
            marker=dict(size=9),
            customdata=monthly_valid[["n", "media", "de"]].to_numpy(),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "CV: <b>%{y:.2f}%</b><br>"
                "n: %{customdata[0]:.0f}<br>"
                "Media: %{customdata[1]:.4f}<br>"
                "DE: %{customdata[2]:.4f}"
                "<extra></extra>"
            ),
            name="CV%",
        )
    )

    fig.update_layout(
        height=390,
        margin=dict(l=30, r=25, t=18, b=45),
        xaxis_title="Mes",
        yaxis_title="CV%",
        hovermode="closest",
        showlegend=False,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#14213d", family="Arial"),
    )
    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=monthly_valid["mes_label"].tolist(),
        gridcolor="#edf1f6",
        tickfont=dict(color="#6d7890"),
        title_font=dict(color="#6d7890"),
    )
    fig.update_yaxes(
        rangemode="tozero",
        gridcolor="#edf1f6",
        zeroline=False,
        tickfont=dict(color="#6d7890"),
        title_font=dict(color="#6d7890"),
        ticksuffix="%",
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        theme=None,
        config={"displaylogo": False},
    )

    # Resumen simple de dirección de la tendencia, sin sustituir interpretación clínica.
    first_cv = float(monthly_valid.iloc[0]["cv"])
    last_cv = float(monthly_valid.iloc[-1]["cv"])
    delta_cv = last_cv - first_cv

    if abs(delta_cv) < 0.01:
        st.caption("El CV% se mantiene prácticamente estable entre el primer y el último mes mostrado.")
    elif delta_cv < 0:
        st.caption(
            f"El CV% disminuyó {abs(delta_cv):.2f} puntos porcentuales entre "
            "el primer y el último mes mostrado."
        )
    else:
        st.caption(
            f"El CV% aumentó {delta_cv:.2f} puntos porcentuales entre "
            "el primer y el último mes mostrado."
        )


def module_equipment(conn, user):
    st.subheader("Equipos")
    equipment = load_equipment(conn, only_active=False)
    if not equipment.empty:
        st.dataframe(equipment, use_container_width=True, hide_index=True)
    if user["rol"] not in ["Administrador","Supervisor"]:
        return
    with st.expander("➕ Registrar equipo"):
        with st.form("new_equipment"):
            c1,c2 = st.columns(2)
            with c1:
                name = st.text_input("Nombre del equipo")
                manufacturer = st.text_input("Fabricante")
                model = st.text_input("Modelo")
            with c2:
                serial = st.text_input("Número de serie")
                area = st.text_input("Área")
                location = st.text_input("Ubicación")
            submit = st.form_submit_button("Guardar equipo", type="primary")
        if submit:
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                    INSERT INTO equipos(organizacion_id,nombre,fabricante,modelo,numero_serie,area,ubicacion)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
                    """, (current_org_id(user), name.strip(), manufacturer.strip() or None, model.strip() or None, serial.strip() or None, area.strip() or None, location.strip() or None))
                    eid = cur.fetchone()[0]
                conn.commit()
                audit(conn, "EQUIPO_CREADO", "equipos", eid, name)
                st.success("Equipo registrado.")
                st.rerun()
            except IntegrityError:
                conn.rollback(); st.error("El número de serie ya existe.")



def generate_excel_report(analyte: dict, lot: dict, results: pd.DataFrame, stats: dict, start_date: date, end_date: date) -> bytes:
    """Crea un informe Excel profesional con resumen, resultados y gráfico."""
    output = BytesIO()
    df = results.copy()
    if not df.empty:
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
        df = df.sort_values(["fecha", "id"] if "id" in df.columns else ["fecha"])

    with pd.ExcelWriter(output, engine="xlsxwriter", datetime_format="dd-mm-yyyy") as writer:
        workbook = writer.book
        summary_ws = workbook.add_worksheet("Resumen")
        writer.sheets["Resumen"] = summary_ws

        title_fmt = workbook.add_format({"bold": True, "font_size": 18, "font_color": "#14213D"})
        section_fmt = workbook.add_format({"bold": True, "font_size": 11, "font_color": "#FFFFFF", "bg_color": "#F52D63", "border": 0})
        label_fmt = workbook.add_format({"bold": True, "font_color": "#475467", "bg_color": "#F8FAFC", "border": 1, "border_color": "#E4E9F1"})
        value_fmt = workbook.add_format({"font_color": "#14213D", "border": 1, "border_color": "#E4E9F1"})
        num_fmt = workbook.add_format({"num_format": "0.0000", "font_color": "#14213D", "border": 1, "border_color": "#E4E9F1"})
        pct_fmt = workbook.add_format({"num_format": "0.00%", "font_color": "#14213D", "border": 1, "border_color": "#E4E9F1"})

        summary_ws.set_column("A:A", 28)
        summary_ws.set_column("B:B", 30)
        summary_ws.merge_range("A1:B1", f"TMQuality {APP_VERSION} - Informe de Control de Calidad", title_fmt)
        summary_ws.write("A3", "Datos del reporte", section_fmt)
        summary_ws.write("B3", "", section_fmt)

        lower = float(lot.get("limite_inferior") if lot.get("limite_inferior") is not None else lot["media_objetivo"] - 3 * lot["de_objetivo"])
        middle = float(lot.get("nivel_medio") if lot.get("nivel_medio") is not None else lot["media_objetivo"])
        upper = float(lot.get("limite_superior") if lot.get("limite_superior") is not None else lot["media_objetivo"] + 3 * lot["de_objetivo"])
        info = [
            ("Analito", analyte["nombre"]),
            ("Unidad", analyte["unidad"]),
            ("Lote", lot["lote"]),
            ("Nivel del control", lot["nivel"]),
            ("Fecha inicial", start_date.strftime("%d-%m-%Y")),
            ("Fecha final", end_date.strftime("%d-%m-%Y")),
            ("Límite inferior", lower),
            ("Nivel medio", middle),
            ("Límite superior", upper),
            ("DE derivada", float(lot["de_objetivo"])),
        ]
        row = 3
        for label, value in info:
            summary_ws.write(row, 0, label, label_fmt)
            if isinstance(value, (int, float)):
                summary_ws.write_number(row, 1, float(value), num_fmt)
            else:
                summary_ws.write(row, 1, value, value_fmt)
            row += 1

        row += 1
        summary_ws.write(row, 0, "Indicadores", section_fmt)
        summary_ws.write(row, 1, "", section_fmt)
        row += 1
        metrics = [
            ("N", stats.get("n", 0), value_fmt),
            ("Media observada", stats.get("mean"), num_fmt),
            ("DE observada", stats.get("sd"), num_fmt),
            ("CV%", (stats.get("cv") / 100) if stats.get("cv") is not None else None, pct_fmt),
            ("Sesgo%", (stats.get("bias") / 100) if stats.get("bias") is not None else None, pct_fmt),
            ("Sigma", stats.get("sigma"), num_fmt),
        ]
        for label, value, fmt in metrics:
            summary_ws.write(row, 0, label, label_fmt)
            if value is None:
                summary_ws.write(row, 1, "—", value_fmt)
            elif isinstance(value, (int, float)):
                summary_ws.write_number(row, 1, float(value), fmt)
            else:
                summary_ws.write(row, 1, value, value_fmt)
            row += 1

        # Hoja de resultados.
        if df.empty:
            export_df = pd.DataFrame(columns=["fecha", "turno", "operador", "valor", "z_score", "estado", "reglas_violadas", "accion_correctiva", "comentarios"])
        else:
            wanted = ["fecha", "turno", "operador", "valor", "z_score", "estado", "reglas_violadas", "accion_correctiva", "comentarios", "equipo_nombre"]
            export_df = df[[c for c in wanted if c in df.columns]].copy()
            export_df["Media"] = middle
            export_df["+2 DE"] = middle + 2 * float(lot["de_objetivo"])
            export_df["-2 DE"] = middle - 2 * float(lot["de_objetivo"])
            export_df["+3 DE"] = upper
            export_df["-3 DE"] = lower

        export_df.to_excel(writer, sheet_name="Resultados", index=False, startrow=1)
        ws = writer.sheets["Resultados"]
        ws.freeze_panes(2, 0)
        ws.set_row(0, 26)
        ws.write(0, 0, f"Resultados {analyte['nombre']} · {lot['lote']} · {start_date:%d-%m-%Y} a {end_date:%d-%m-%Y}", title_fmt)
        header_fmt = workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#14213D", "border": 1, "border_color": "#FFFFFF"})
        for col_num, col_name in enumerate(export_df.columns):
            ws.write(1, col_num, col_name, header_fmt)
            width = min(max(len(str(col_name)) + 3, 12), 28)
            ws.set_column(col_num, col_num, width)
        if "fecha" in export_df.columns:
            date_col = export_df.columns.get_loc("fecha")
            ws.set_column(date_col, date_col, 13, workbook.add_format({"num_format": "dd-mm-yyyy"}))
        if "valor" in export_df.columns:
            value_col = export_df.columns.get_loc("valor")
            ws.set_column(value_col, value_col, 12, workbook.add_format({"num_format": "0.0000"}))

        if not export_df.empty and "fecha" in export_df.columns and "valor" in export_df.columns:
            chart = workbook.add_chart({"type": "line"})
            nrows = len(export_df)
            date_idx = export_df.columns.get_loc("fecha")
            for col_name, color, dash in [
                ("valor", "#1769D2", "solid"),
                ("Media", "#14213D", "dash"),
                ("+2 DE", "#D99113", "dash"),
                ("-2 DE", "#D99113", "dash"),
                ("+3 DE", "#EF334E", "dash"),
                ("-3 DE", "#EF334E", "dash"),
            ]:
                if col_name not in export_df.columns:
                    continue
                col_idx = export_df.columns.get_loc(col_name)
                series = {
                    "name": col_name,
                    "categories": ["Resultados", 2, date_idx, nrows + 1, date_idx],
                    "values": ["Resultados", 2, col_idx, nrows + 1, col_idx],
                    "line": {"color": color, "width": 2 if col_name == "valor" else 1.25, "dash_type": dash},
                }
                if col_name == "valor":
                    series["marker"] = {"type": "circle", "size": 4, "border": {"color": color}, "fill": {"color": "#FFFFFF"}}
                chart.add_series(series)
            chart.set_title({"name": "Levey-Jennings"})
            chart.set_x_axis({"name": "Fecha", "date_axis": True, "num_format": "dd-mm-yyyy", "label_position": "low"})
            chart.set_y_axis({"name": analyte["unidad"], "major_gridlines": {"visible": True, "line": {"color": "#E9EEF5"}}})
            chart.set_legend({"position": "bottom"})
            chart.set_size({"width": 900, "height": 420})
            ws.insert_chart("L3", chart)

    output.seek(0)
    return output.getvalue()


def archive_analyte(conn, analyte_id: int, user: dict) -> None:
    """Archiva un analito y sus lotes sin borrar ningún dato histórico."""
    row = fetchone(
        conn,
        """SELECT a.id,a.nombre,a.activo,
                  (SELECT COUNT(*) FROM lotes_control l WHERE l.analito_id=a.id) AS lotes,
                  (SELECT COUNT(*) FROM resultados_cc r
                   JOIN lotes_control l ON l.id=r.lote_control_id
                   WHERE l.analito_id=a.id) AS resultados
           FROM analitos a
           WHERE a.id=%s AND a.organizacion_id=%s""",
        (analyte_id, current_org_id(user)),
    )
    if not row:
        raise ValueError("El analito no existe o no pertenece a tu organización.")

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE analitos SET activo=FALSE WHERE id=%s AND organizacion_id=%s",
            (analyte_id, current_org_id(user)),
        )
        cur.execute(
            "UPDATE lotes_control SET vigente=FALSE WHERE analito_id=%s AND organizacion_id=%s",
            (analyte_id, current_org_id(user)),
        )
    conn.commit()

    audit(
        conn,
        "ANALITO_ARCHIVADO",
        "analitos",
        analyte_id,
        f"{row['nombre']} · {row['lotes']} lote(s) · {row['resultados']} resultado(s) conservados",
    )


def restore_analyte(conn, analyte_id: int, user: dict, restore_lots: bool = False) -> None:
    """Restaura un analito archivado. Opcionalmente reactiva sus lotes."""
    row = fetchone(
        conn,
        "SELECT id,nombre FROM analitos WHERE id=%s AND organizacion_id=%s",
        (analyte_id, current_org_id(user)),
    )
    if not row:
        raise ValueError("El analito no existe o no pertenece a tu organización.")

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE analitos SET activo=TRUE WHERE id=%s AND organizacion_id=%s",
            (analyte_id, current_org_id(user)),
        )
        if restore_lots:
            cur.execute(
                "UPDATE lotes_control SET vigente=TRUE WHERE analito_id=%s AND organizacion_id=%s",
                (analyte_id, current_org_id(user)),
            )
    conn.commit()

    audit(
        conn,
        "ANALITO_RESTAURADO",
        "analitos",
        analyte_id,
        f"{row['nombre']} · lotes {'reactivados' if restore_lots else 'conservados archivados'}",
    )


def module_reports(conn, analyte, lot, results=None):
    st.subheader("Reportes y exportación")
    if not analyte or not lot:
        st.info("Selecciona un analito y lote.")
        return

    min_date, max_date = result_date_bounds(conn, int(lot["id"]))

    st.markdown("#### Período del reporte")
    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input(
            "Desde",
            value=min_date,
            min_value=min_date,
            max_value=max_date,
            key=f"report_start_{lot['id']}",
        )
    with c2:
        end_date = st.date_input(
            "Hasta",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            key=f"report_end_{lot['id']}",
        )

    if start_date > end_date:
        st.error("La fecha inicial no puede ser posterior a la fecha final.")
        return

    # Solo esta consulta trae los resultados que realmente formarán el reporte.
    filtered = load_results_between(
        conn,
        int(lot["id"]),
        start_date,
        end_date,
    )

    st.caption(
        f"El reporte incluirá {len(filtered)} resultado(s) entre "
        f"{start_date:%d-%m-%Y} y {end_date:%d-%m-%Y}."
    )

    if filtered.empty:
        st.warning(
            "No existen resultados en el período seleccionado. "
            "El informe contendrá el resumen sin resultados."
        )

    stats = qc_statistics(
        filtered,
        lot["media_objetivo"],
        analyte.get("error_total_permitido"),
    )
    period = f"{start_date:%Y%m%d}_{end_date:%Y%m%d}"
    base_name = f"TMQuality_{analyte['nombre']}_{lot['lote']}_{period}".replace(" ", "_")

    c1, c2 = st.columns(2)
    with c1:
        pdf = generate_pdf(analyte, lot, filtered, stats)
        st.download_button(
            "📄 Descargar informe PDF",
            pdf,
            file_name=f"{base_name}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with c2:
        excel = generate_excel_report(
            analyte,
            lot,
            filtered,
            stats,
            start_date,
            end_date,
        )
        st.download_button(
            "📊 Descargar informe Excel",
            excel,
            file_name=f"{base_name}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    if not filtered.empty:
        st.markdown("#### Vista previa")
        preview_cols = [
            c for c in
            ["fecha", "turno", "operador", "valor", "z_score", "estado", "reglas_violadas"]
            if c in filtered.columns
        ]
        st.dataframe(
            filtered[preview_cols].tail(500),
            use_container_width=True,
            hide_index=True,
        )
        if len(filtered) > 500:
            st.caption(
                "La vista previa muestra los 500 registros más recientes. "
                "El PDF y Excel incluyen todo el período."
            )


def module_audit(conn):
    st.subheader("Auditoría")
    max_rows = st.selectbox("Eventos a cargar", [250, 500, 1000, 2500], index=1)
    df = list_audit(conn, int(max_rows))
    if df.empty:
        st.info("Aún no hay eventos de auditoría.")
        return
    c1,c2,c3 = st.columns(3)
    users = sorted([x for x in df["username"].dropna().unique().tolist()])
    actions = sorted(df["accion"].dropna().unique().tolist())
    with c1: uf = st.multiselect("Usuario", users)
    with c2: af = st.multiselect("Acción", actions)
    with c3: only_failed = st.checkbox("Solo eventos fallidos")
    filtered = df.copy()
    if uf: filtered = filtered[filtered["username"].isin(uf)]
    if af: filtered = filtered[filtered["accion"].isin(af)]
    if only_failed: filtered = filtered[filtered["exito"] == False]
    st.dataframe(filtered, use_container_width=True, hide_index=True)
    st.download_button("Exportar auditoría CSV", filtered.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"auditoria_TMQuality_{date.today()}.csv", mime="text/csv")



def module_admin(conn, user):
    st.subheader("Administración")
    if user["rol"] != "Administrador":
        st.info("Disponible solo para Administradores.")
        return
    org = current_organization(conn, user)
    if org:
        st.markdown("#### Organización")
        with st.form("organization_profile"):
            org_name = st.text_input("Nombre del laboratorio / institución", value=str(org.get("nombre") or ""))
            org_code = st.text_input("Código interno", value=str(org.get("codigo") or ""))
            org_rut = st.text_input("RUT (opcional)", value=str(org.get("rut") or ""))
            save_org = st.form_submit_button("Guardar organización", type="primary")
        if save_org:
            if not org_name.strip():
                st.error("El nombre de la organización es obligatorio.")
            else:
                execute(
                    conn,
                    """
                    UPDATE organizaciones
                    SET nombre=%s, codigo=%s, rut=%s, fecha_modificacion=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    (org_name.strip(), org_code.strip() or None, org_rut.strip() or None, current_org_id(user)),
                )
                audit(conn, "ORGANIZACION_ACTUALIZADA", "organizaciones", current_org_id(user), org_name.strip())
                st.success("Organización actualizada.")
                st.rerun()
        st.divider()

    users = list_users(conn)
    st.markdown("#### Usuarios")
    st.dataframe(users, use_container_width=True, hide_index=True)

    with st.expander("➕ Crear usuario"):
        with st.form("new_user"):
            nombre = st.text_input("Nombre completo")
            username = st.text_input("Usuario")
            role = st.selectbox("Rol", ROLES)
            temp_pw = st.text_input("Contraseña temporal", type="password")
            create = st.form_submit_button("Crear usuario", type="primary")
        if create:
            try:
                create_user(conn, nombre, username, temp_pw, role, require_change=True, actor=user)
                st.success("Usuario creado. Deberá cambiar su contraseña al ingresar.")
                st.rerun()
            except IntegrityError:
                conn.rollback(); st.error("Ese nombre de usuario ya existe.")
            except Exception as exc:
                st.error(str(exc))

    st.markdown("#### Gestionar usuario")
    if not users.empty:
        uid = st.selectbox("Usuario", users["id"].tolist(), format_func=lambda x: users.loc[users.id==x,"username"].iloc[0])
        target = users[users.id==uid].iloc[0].to_dict()
        c1,c2,c3 = st.columns(3)
        with c1:
            new_role = st.selectbox("Rol", ROLES, index=ROLES.index(target["rol"]) if target["rol"] in ROLES else 2, key="admin_role")
            if st.button("Actualizar rol", use_container_width=True):
                execute(conn, "UPDATE usuarios SET rol=%s, fecha_modificacion=CURRENT_TIMESTAMP WHERE id=%s AND organizacion_id=%s", (new_role, int(uid), current_org_id(user)))
                audit(conn, "ROL_CAMBIADO", "usuarios", uid, f"{target['rol']} → {new_role}")
                st.rerun()
        with c2:
            label = "Desactivar" if target["activo"] else "Reactivar"
            if st.button(label, use_container_width=True):
                if target["rol"] == "Administrador" and target["activo"] and active_admin_count(conn, current_org_id(user)) <= 1:
                    st.error("No se puede desactivar al último Administrador activo.")
                elif int(uid) == int(user["id"]) and target["activo"]:
                    st.error("No puedes desactivar tu propia sesión.")
                else:
                    execute(conn, "UPDATE usuarios SET activo=%s, fecha_modificacion=CURRENT_TIMESTAMP WHERE id=%s AND organizacion_id=%s", (not bool(target["activo"]), int(uid), current_org_id(user)))
                    audit(conn, "USUARIO_REACTIVADO" if not target["activo"] else "USUARIO_DESACTIVADO", "usuarios", uid, None)
                    st.rerun()
        with c3:
            reset_pw = st.text_input("Nueva contraseña temporal", type="password", key="reset_pw")
            if st.button("Restablecer contraseña", use_container_width=True):
                try:
                    change_password(conn, int(uid), reset_pw, actor=user, require_change=True)
                    st.success("Contraseña restablecida. Se exigirá cambio al próximo ingreso.")
                except Exception as exc:
                    st.error(str(exc))

    st.divider()
    st.markdown("#### Maestros de calidad")
    tab_a, tab_l = st.tabs(["Analitos", "Lotes de control"])
    with tab_a:
        analytes = load_analytes(conn, only_active=False)
        if not analytes.empty: st.dataframe(analytes, use_container_width=True, hide_index=True)
        with st.form("new_analyte"):
            n = st.text_input("Nombre")
            unit = st.text_input("Unidad")
            method = st.text_input("Metodología")
            tea = st.number_input("Error Total Permitido (%)", min_value=0.0, value=0.0, step=0.1, help="Usa 0 si aún no está definido.")
            raw_levels = st.text_area(
                "Niveles de control",
                value="Bajo, Normal, Alto",
                help="Separa los niveles por comas o líneas. Ej.: Nivel 1, Nivel 2.",
            )
            add = st.form_submit_button("Crear analito", type="primary")
        if add:
            try:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO analitos(organizacion_id,nombre,unidad,metodologia,error_total_permitido) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                                (current_org_id(user), n.strip(), unit.strip(), method.strip() or None, tea if tea > 0 else None))
                    aid = cur.fetchone()[0]
                conn.commit()
                configured_levels = parse_control_levels(raw_levels) or ["Bajo","Normal","Alto"]
                sync_control_levels(conn,int(aid),configured_levels)
                audit(conn,"ANALITO_CREADO","analitos",aid,
                      f"{n} · niveles: {', '.join(configured_levels)}")
                st.rerun()
            except IntegrityError:
                conn.rollback(); st.error("El analito ya existe.")

        if not analytes.empty:
            st.markdown("##### Configurar niveles de control")
            cfg_options={f"{r.nombre} ({r.unidad})":int(r.id) for r in analytes.itertuples()}
            cfg_label=st.selectbox("Analito para configurar niveles",list(cfg_options.keys()),key="control_levels_analyte")
            cfg_id=cfg_options[cfg_label]
            cfg_df=load_control_levels(conn,cfg_id,only_active=True)
            cfg_current=[] if cfg_df.empty else cfg_df["nombre"].astype(str).tolist()
            raw_cfg_levels=st.text_area(
                "Niveles activos",
                value=", ".join(cfg_current),
                key=f"control_levels_text_{cfg_id}",
                help="Cada analito puede usar su propia nomenclatura. Los niveles retirados se archivan, no se borran.",
            )
            if st.button("Guardar niveles del analito",type="primary",use_container_width=True,key=f"save_control_levels_{cfg_id}"):
                try:
                    saved=sync_control_levels(conn,cfg_id,parse_control_levels(raw_cfg_levels))
                    audit(conn,"NIVELES_CONTROL_ACTUALIZADOS","analitos",cfg_id,", ".join(saved))
                    st.success("Niveles de control actualizados.")
                    st.rerun()
                except Exception as exc:
                    conn.rollback(); st.error(str(exc))

            st.markdown("##### Archivar o restaurar analito")
            a_options = {
                f"{r.nombre} ({r.unidad}) · {'Activo' if bool(r.activo) else 'Archivado'}": int(r.id)
                for r in analytes.itertuples()
            }
            a_label = st.selectbox("Analito", list(a_options.keys()), key="manage_analyte_select")
            a_id = a_options[a_label]
            selected_analyte = analytes[analytes["id"] == a_id].iloc[0]
            counts = fetchone(
                conn,
                """SELECT
                       (SELECT COUNT(*) FROM lotes_control WHERE analito_id=%s) AS lotes,
                       (SELECT COUNT(*) FROM resultados_cc r
                        JOIN lotes_control l ON l.id=r.lote_control_id
                        WHERE l.analito_id=%s) AS resultados""",
                (a_id, a_id),
            )

            if bool(selected_analyte["activo"]):
                st.info(
                    f"Archivar este analito conservará sus {counts['lotes']} lote(s) "
                    f"y {counts['resultados']} resultado(s)."
                )
                confirm_archive = st.checkbox(
                    "Confirmo archivar este analito",
                    key=f"confirm_archive_analyte_{a_id}",
                )
                if st.button(
                    "Archivar analito",
                    disabled=not confirm_archive,
                    use_container_width=True,
                    key=f"archive_analyte_{a_id}",
                ):
                    try:
                        archive_analyte(conn, a_id, user)
                        st.success("Analito archivado. No se eliminó ningún dato.")
                        st.rerun()
                    except Exception as exc:
                        conn.rollback(); st.error(str(exc))
            else:
                restore_lots_too = st.checkbox(
                    "Restaurar también todos sus lotes",
                    value=False,
                    key=f"restore_analyte_lots_{a_id}",
                )
                if st.button(
                    "Restaurar analito",
                    use_container_width=True,
                    key=f"restore_analyte_{a_id}",
                ):
                    try:
                        restore_analyte(conn, a_id, user, restore_lots=restore_lots_too)
                        st.success("Analito restaurado.")
                        st.rerun()
                    except Exception as exc:
                        conn.rollback(); st.error(str(exc))
    with tab_l:
        st.info("La creación y gestión de lotes se realiza ahora en el módulo “Lotes de control”.")
        if st.button("Ir a Lotes de control",use_container_width=True,key="admin_go_lots"):
            st.session_state.pending_nav="Lotes de control"
            st.rerun()

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
ensure_database_ready(get_database_url())
conn = get_connection()
bootstrap_admin_ui(conn)

if st.session_state.get("platform_mode") and "user" not in st.session_state:
    platform_admin_ui(conn)
    st.stop()

if "user" not in st.session_state:
    login_ui(conn)
    st.stop()

user = st.session_state.user
# Refrescar estado del usuario cada ejecución (permite desactivación inmediata).
fresh = fetchone(conn, "SELECT * FROM usuarios WHERE id=%s AND organizacion_id=%s", (user["id"], current_org_id(user)))
if not fresh or not fresh["activo"]:
    st.session_state.clear()
    st.error("Tu cuenta ya no está activa.")
    st.stop()
st.session_state.user = fresh
user = fresh

if user.get("cambio_password_requerido"):
    forced_password_change_ui(conn, user)

with st.sidebar:
    st.markdown(
        f"""<div class="tmq-brand"><img src="data:image/png;base64,{LOGO_ICON_B64}"><div><div class="tmq-brand-name notranslate" translate="no">TMQuality</div><div class="tmq-brand-sub">Control de calidad analítico · v{APP_VERSION}</div></div></div>""",
        unsafe_allow_html=True,
    )
    org = current_organization(conn, user)
    if org:
        st.markdown(
            f"""<div class="tmq-org-card">
            <div style="font-size:11px;color:#F43F6B;font-weight:800;text-transform:uppercase;letter-spacing:.05em;">Organización activa</div>
            <div style="font-size:14px;color:#182235;font-weight:850;margin-top:4px;">{org['nombre']}</div>
            <div style="font-size:12px;color:#7A869A;margin-top:3px;">Código: {org.get('codigo') or '—'}</div>
            </div>""",
            unsafe_allow_html=True,
        )
    st.markdown(
        f"""<div class="tmq-topbar">
        <div class="tmq-topbar-title">Control de calidad analítico · <span>v{APP_VERSION}</span></div>
        <div class="tmq-user-chip">{user['rol']} · @{user['username']}</div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.markdown(f"**{user['nombre_completo']}**")
    st.caption(f"{user['rol']} · @{user['username']}")
    if user.get("ultimo_acceso"):
        st.caption(f"Último acceso · {user['ultimo_acceso']:%d-%m-%Y %H:%M}")
    if st.button("Cerrar sesión", use_container_width=True): logout(conn)
    st.divider()

    nav = ["Inicio", "Control de calidad", "Resultados", "Analítica", "Equipos", "Reportes"]
    if user["rol"] in ["Administrador","Supervisor"]:
        nav.append("Lotes de control")
        nav.append("Auditoría")
    if user["rol"] == "Administrador":
        nav.append("Administración")

    # Mantener una navegación controlable desde botones de acción.
    # Streamlit no permite modificar la clave de un widget después de haberlo
    # instanciado en el mismo rerun. Por eso las acciones guardan "pending_nav"
    # y aquí se aplica ANTES de crear el radio.
    if "pending_nav" in st.session_state:
        requested_page = st.session_state.pop("pending_nav")
        if requested_page in nav:
            st.session_state["main_nav"] = requested_page

    if "main_nav" not in st.session_state or st.session_state.main_nav not in nav:
        st.session_state["main_nav"] = "Inicio"

    page = st.radio("Navegación", nav, label_visibility="collapsed", key="main_nav")
    st.divider()
    # Cada pantalla solicita solo la cantidad de resultados que necesita.
    # Reportes hace su propia consulta por rango de fechas.
    page_result_limits = {
        "Inicio": 300,
        "Control de calidad": 30,
        "Resultados": 500,
        "Analítica": 1500,
    }
    include_results = page in page_result_limits
    analyte, lot, results = selected_context_ui(
        conn,
        include_results=include_results,
        result_limit=page_result_limits.get(page),
    )
    if analyte and lot:
        st.caption("PARÁMETROS OBJETIVO")
        st.markdown(f"**μ** {lot['media_objetivo']:.4f} {analyte['unidad']}  \n**DE** {lot['de_objetivo']:.4f} {analyte['unidad']}")
        if lot.get("fecha_vencimiento"):
            exp=lot["fecha_vencimiento"]
            if exp < date.today(): st.error(f"Lote vencido · {exp:%d-%m-%Y}")
            elif exp <= date.today()+timedelta(days=30): st.warning(f"Vence · {exp:%d-%m-%Y}")

st.markdown(f"""<div class="tmq-topbar"><div><h1>{'Control de Calidad Analítico' if page in ['Inicio','Control de calidad'] else page}</h1><p>{analyte['nombre'] + ' · ' + lot['lote'] if analyte and lot else 'Gestión y trazabilidad del laboratorio'}</p></div><div class="tmq-user-pill">● Sesión activa · {user['rol']}</div></div>""", unsafe_allow_html=True)

empty = results if results is not None else pd.DataFrame()
if page == "Inicio": module_dashboard(conn, analyte, lot, empty)
elif page == "Control de calidad": module_register(conn, user, analyte, lot, empty)
elif page == "Resultados": module_history(conn, user, analyte, lot, empty)
elif page == "Analítica": module_analytics(conn, analyte, lot, empty)
elif page == "Equipos": module_equipment(conn, user)
elif page == "Reportes": module_reports(conn, analyte, lot, empty)
elif page == "Lotes de control": module_lots(conn, user)
elif page == "Auditoría": module_audit(conn)
elif page == "Administración": module_admin(conn, user)

conn.close()
