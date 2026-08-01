"""
TMQuality 3.0
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

import hashlib
import hmac
import os
import secrets
from datetime import date, datetime, timedelta
from io import BytesIO
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
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

APP_VERSION = "3.0.0"
PBKDF2_ITERATIONS = 260_000
ROLES = ["Administrador", "Supervisor", "Operador"]
ESTADOS = ["Aceptado", "Advertencia", "Rechazado", "Pendiente"]
TURNOS = ["Mañana", "Tarde", "Noche", "Otro"]

# -----------------------------------------------------------------------------
# CONFIGURACIÓN Y ESTILO
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="TMQuality 3.0",
    page_icon="🩸",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
:root {
    --tmq-primary: var(--primary-color, #a61b2b);
    --tmq-bg: var(--background-color, #ffffff);
    --tmq-surface: var(--secondary-background-color, #f6f7f9);
    --tmq-text: var(--text-color, #17212b);
    --tmq-border: color-mix(in srgb, var(--tmq-text) 14%, transparent);
    --tmq-muted: color-mix(in srgb, var(--tmq-text) 65%, transparent);
    --tmq-shadow: 0 10px 30px rgba(0,0,0,.08);
}

[data-testid="stAppViewContainer"] {
    background: var(--tmq-bg);
    color: var(--tmq-text);
}
[data-testid="stSidebar"] {
    background: var(--tmq-surface);
    border-right: 1px solid var(--tmq-border);
}

.tmq-hero {
    padding: 1.15rem 1.3rem;
    border: 1px solid var(--tmq-border);
    border-radius: 18px;
    background: linear-gradient(135deg,
        color-mix(in srgb, var(--tmq-primary) 11%, var(--tmq-bg)),
        var(--tmq-bg));
    box-shadow: var(--tmq-shadow);
    margin-bottom: 1rem;
}
.tmq-hero h1 { margin:0; font-size:2rem; letter-spacing:-.03em; }
.tmq-hero p { margin:.35rem 0 0 0; color:var(--tmq-muted); }
.tmq-badge {
    display:inline-flex; align-items:center; gap:.35rem;
    padding:.28rem .62rem; border-radius:999px;
    border:1px solid var(--tmq-border); font-size:.78rem; font-weight:700;
}
.tmq-kpi {
    border: 1px solid var(--tmq-border);
    border-radius: 16px;
    padding: .95rem 1rem;
    background: var(--tmq-bg);
    box-shadow: 0 6px 20px rgba(0,0,0,.05);
    min-height: 106px;
}
.tmq-kpi .label { color:var(--tmq-muted); font-size:.8rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em; }
.tmq-kpi .value { font-size:1.75rem; font-weight:800; margin-top:.2rem; }
.tmq-kpi .hint { color:var(--tmq-muted); font-size:.78rem; margin-top:.25rem; }
.tmq-card {
    border:1px solid var(--tmq-border); border-radius:16px; padding:1rem;
    background:var(--tmq-bg); box-shadow:0 6px 20px rgba(0,0,0,.04);
}
.tmq-section-title { margin:.25rem 0 .8rem 0; font-weight:800; font-size:1.15rem; }
.tmq-muted { color:var(--tmq-muted); }
div[data-testid="stMetric"] { border:1px solid var(--tmq-border); border-radius:14px; padding:.7rem; }
button[kind="primary"], div.stButton > button[kind="primary"] { font-weight:700; }
[data-baseweb="tab-list"] { gap:.35rem; }
[data-baseweb="tab"] { border-radius:10px 10px 0 0; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# BASE DE DATOS
# -----------------------------------------------------------------------------
def get_database_url() -> str:
    try:
        return st.secrets["database"]["url"]
    except Exception:
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            return env_url
        st.error("No se encontró la conexión PostgreSQL. Configura [database].url en Streamlit Secrets.")
        st.stop()


def get_connection():
    try:
        return psycopg2.connect(get_database_url(), connect_timeout=12)
    except Exception as exc:
        st.error("No fue posible conectar TMQuality con Supabase.")
        st.code(str(exc))
        st.stop()


def execute(conn, sql: str, params: Optional[Iterable[Any]] = None, *, commit: bool = True):
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params or ()))
    if commit:
        conn.commit()


def fetchone(conn, sql: str, params: Optional[Iterable[Any]] = None) -> Optional[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, tuple(params or ()))
        row = cur.fetchone()
    return dict(row) if row else None


def fetchall_df(conn, sql: str, params: Optional[Iterable[Any]] = None) -> pd.DataFrame:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, tuple(params or ()))
        rows = cur.fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def init_db(conn):
    """Crea/migra el esquema sin borrar datos existentes."""
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS analitos (
            id BIGSERIAL PRIMARY KEY,
            nombre TEXT NOT NULL UNIQUE,
            unidad TEXT NOT NULL,
            metodologia TEXT,
            error_total_permitido DOUBLE PRECISION,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS equipos (
            id BIGSERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            fabricante TEXT,
            modelo TEXT,
            numero_serie TEXT UNIQUE,
            area TEXT,
            ubicacion TEXT,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS lotes_control (
            id BIGSERIAL PRIMARY KEY,
            analito_id BIGINT NOT NULL REFERENCES analitos(id) ON DELETE CASCADE,
            nivel TEXT NOT NULL,
            lote TEXT NOT NULL,
            fabricante TEXT,
            material_control TEXT,
            fecha_vencimiento DATE,
            media_objetivo DOUBLE PRECISION NOT NULL,
            de_objetivo DOUBLE PRECISION NOT NULL,
            vigente BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (analito_id, nivel, lote)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id BIGSERIAL PRIMARY KEY,
            nombre_completo TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            rol TEXT NOT NULL,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            cambio_password_requerido BOOLEAN NOT NULL DEFAULT TRUE,
            intentos_fallidos INTEGER NOT NULL DEFAULT 0,
            bloqueado_hasta TIMESTAMP,
            ultimo_acceso TIMESTAMP,
            fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_modificacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS resultados_cc (
            id BIGSERIAL PRIMARY KEY,
            lote_control_id BIGINT NOT NULL REFERENCES lotes_control(id) ON DELETE CASCADE,
            equipo_id BIGINT REFERENCES equipos(id) ON DELETE SET NULL,
            usuario_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
            fecha DATE NOT NULL,
            hora TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            turno TEXT NOT NULL,
            operador TEXT NOT NULL,
            valor DOUBLE PRECISION NOT NULL,
            z_score DOUBLE PRECISION,
            reglas_violadas TEXT,
            estado TEXT NOT NULL DEFAULT 'Pendiente',
            accion_correctiva TEXT,
            comentarios TEXT,
            revisado_por BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
            fecha_revision TIMESTAMP,
            fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_modificacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS auditoria (
            id BIGSERIAL PRIMARY KEY,
            fecha_hora TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            usuario_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
            username TEXT,
            rol TEXT,
            accion TEXT NOT NULL,
            entidad TEXT,
            entidad_id TEXT,
            detalle TEXT,
            exito BOOLEAN NOT NULL DEFAULT TRUE
        )
        """,
    ]
    for sql in ddl:
        execute(conn, sql)

    migrations = [
        "ALTER TABLE analitos ADD COLUMN IF NOT EXISTS metodologia TEXT",
        "ALTER TABLE analitos ADD COLUMN IF NOT EXISTS error_total_permitido DOUBLE PRECISION",
        "ALTER TABLE analitos ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE analitos ADD COLUMN IF NOT EXISTS fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE lotes_control ADD COLUMN IF NOT EXISTS fabricante TEXT",
        "ALTER TABLE lotes_control ADD COLUMN IF NOT EXISTS material_control TEXT",
        "ALTER TABLE lotes_control ADD COLUMN IF NOT EXISTS fecha_vencimiento DATE",
        "ALTER TABLE lotes_control ADD COLUMN IF NOT EXISTS fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS cambio_password_requerido BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS intentos_fallidos INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS bloqueado_hasta TIMESTAMP",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ultimo_acceso TIMESTAMP",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS fecha_modificacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE resultados_cc ADD COLUMN IF NOT EXISTS equipo_id BIGINT REFERENCES equipos(id) ON DELETE SET NULL",
        "ALTER TABLE resultados_cc ADD COLUMN IF NOT EXISTS usuario_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL",
        "ALTER TABLE resultados_cc ADD COLUMN IF NOT EXISTS hora TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE resultados_cc ADD COLUMN IF NOT EXISTS z_score DOUBLE PRECISION",
        "ALTER TABLE resultados_cc ADD COLUMN IF NOT EXISTS comentarios TEXT",
        "ALTER TABLE resultados_cc ADD COLUMN IF NOT EXISTS revisado_por BIGINT REFERENCES usuarios(id) ON DELETE SET NULL",
        "ALTER TABLE resultados_cc ADD COLUMN IF NOT EXISTS fecha_revision TIMESTAMP",
        "ALTER TABLE resultados_cc ADD COLUMN IF NOT EXISTS fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE resultados_cc ADD COLUMN IF NOT EXISTS fecha_modificacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS idx_lotes_analito ON lotes_control(analito_id)",
        "CREATE INDEX IF NOT EXISTS idx_resultados_lote_fecha ON resultados_cc(lote_control_id, fecha)",
        "CREATE INDEX IF NOT EXISTS idx_resultados_equipo ON resultados_cc(equipo_id)",
        "CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha_hora DESC)",
        "CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria(usuario_id)",
    ]
    for sql in migrations:
        try:
            execute(conn, sql)
        except Exception:
            conn.rollback()

    # Ajustar constraint de roles si proviene de una versión anterior.
    try:
        execute(conn, "ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_rol_check")
        execute(conn, "ALTER TABLE usuarios ADD CONSTRAINT usuarios_rol_check CHECK (rol IN ('Administrador','Supervisor','Operador'))")
    except Exception:
        conn.rollback()

    # Tablas solo se usan por conexión servidor-servidor. No se exponen por PostgREST.
    # Esto evita un falso sentido de seguridad por RLS sin políticas y reduce superficie pública.
    for table in ["analitos", "equipos", "lotes_control", "resultados_cc", "usuarios", "auditoria"]:
        for sql in [
            f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated",
        ]:
            try:
                execute(conn, sql)
            except Exception:
                conn.rollback()

# -----------------------------------------------------------------------------
# SEGURIDAD / USUARIOS
# -----------------------------------------------------------------------------
def hash_password(password: str, salt_hex: Optional[str] = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def password_ok(password: str) -> tuple[bool, str]:
    if len(password) < 10:
        return False, "La contraseña debe tener al menos 10 caracteres."
    if not any(c.isupper() for c in password):
        return False, "Debe incluir al menos una mayúscula."
    if not any(c.islower() for c in password):
        return False, "Debe incluir al menos una minúscula."
    if not any(c.isdigit() for c in password):
        return False, "Debe incluir al menos un número."
    return True, ""


def audit(conn, accion: str, entidad: Optional[str] = None, entidad_id: Optional[Any] = None,
          detalle: Optional[str] = None, exito: bool = True, user: Optional[dict] = None):
    user = user or st.session_state.get("user")
    execute(
        conn,
        """
        INSERT INTO auditoria (usuario_id, username, rol, accion, entidad, entidad_id, detalle, exito)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            user.get("id") if user else None,
            user.get("username") if user else None,
            user.get("rol") if user else None,
            accion, entidad, str(entidad_id) if entidad_id is not None else None, detalle, exito,
        ),
    )


def authenticate(conn, username: str, password: str) -> tuple[Optional[dict], str]:
    row = fetchone(conn, "SELECT * FROM usuarios WHERE lower(username)=lower(%s)", (username.strip(),))
    if not row:
        audit(conn, "LOGIN_FALLIDO", "usuarios", None, f"Usuario inexistente: {username}", False, None)
        return None, "Credenciales inválidas."
    if not row["activo"]:
        audit(conn, "LOGIN_FALLIDO", "usuarios", row["id"], "Cuenta inactiva", False, row)
        return None, "La cuenta está desactivada."
    if row.get("bloqueado_hasta") and row["bloqueado_hasta"] > datetime.now():
        return None, f"Cuenta temporalmente bloqueada hasta {row['bloqueado_hasta']:%H:%M}."

    candidate, _ = hash_password(password, row["salt"])
    if not hmac.compare_digest(candidate, row["password_hash"]):
        intentos = int(row.get("intentos_fallidos") or 0) + 1
        bloqueado = datetime.now() + timedelta(minutes=15) if intentos >= 5 else None
        execute(conn, "UPDATE usuarios SET intentos_fallidos=%s, bloqueado_hasta=%s WHERE id=%s", (intentos, bloqueado, row["id"]))
        audit(conn, "LOGIN_FALLIDO", "usuarios", row["id"], f"Contraseña incorrecta. Intento {intentos}", False, row)
        return None, "Credenciales inválidas." if not bloqueado else "Cuenta bloqueada 15 minutos por intentos fallidos."

    execute(conn, "UPDATE usuarios SET intentos_fallidos=0, bloqueado_hasta=NULL, ultimo_acceso=CURRENT_TIMESTAMP WHERE id=%s", (row["id"],))
    row = fetchone(conn, "SELECT * FROM usuarios WHERE id=%s", (row["id"],))
    audit(conn, "LOGIN_EXITOSO", "usuarios", row["id"], "Inicio de sesión", True, row)
    return row, ""


def create_user(conn, nombre: str, username: str, password: str, rol: str, *, require_change: bool = True,
                actor: Optional[dict] = None) -> int:
    ok, msg = password_ok(password)
    if not ok:
        raise ValueError(msg)
    ph, salt = hash_password(password)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO usuarios (nombre_completo, username, password_hash, salt, rol, activo, cambio_password_requerido)
            VALUES (%s,%s,%s,%s,%s,TRUE,%s) RETURNING id
            """,
            (nombre.strip(), username.strip(), ph, salt, rol, require_change),
        )
        user_id = cur.fetchone()[0]
    conn.commit()
    audit(conn, "USUARIO_CREADO", "usuarios", user_id, f"Rol: {rol}", True, actor)
    return user_id


def change_password(conn, user_id: int, new_password: str, *, actor: Optional[dict] = None, require_change: bool = False):
    ok, msg = password_ok(new_password)
    if not ok:
        raise ValueError(msg)
    ph, salt = hash_password(new_password)
    execute(conn,
            "UPDATE usuarios SET password_hash=%s, salt=%s, cambio_password_requerido=%s, fecha_modificacion=CURRENT_TIMESTAMP WHERE id=%s",
            (ph, salt, require_change, user_id))
    audit(conn, "PASSWORD_CAMBIADA", "usuarios", user_id, "Contraseña actualizada", True, actor)


def active_admin_count(conn) -> int:
    row = fetchone(conn, "SELECT COUNT(*) AS n FROM usuarios WHERE rol='Administrador' AND activo=TRUE")
    return int(row["n"] if row else 0)


def bootstrap_admin_ui(conn):
    if active_admin_count(conn) > 0:
        return
    st.warning("No existe un Administrador activo. Se requiere configuración inicial segura.")
    try:
        token_expected = st.secrets["security"]["bootstrap_token"]
    except Exception:
        st.error("Configura [security].bootstrap_token en Streamlit Secrets para crear el primer administrador.")
        st.stop()

    with st.form("bootstrap_admin"):
        st.subheader("Crear primer Administrador")
        token = st.text_input("Token de configuración", type="password")
        nombre = st.text_input("Nombre completo")
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        password2 = st.text_input("Repetir contraseña", type="password")
        submitted = st.form_submit_button("Crear Administrador", type="primary", use_container_width=True)
    if submitted:
        if not secrets.compare_digest(token, str(token_expected)):
            st.error("Token de configuración incorrecto.")
        elif password != password2:
            st.error("Las contraseñas no coinciden.")
        else:
            try:
                uid = create_user(conn, nombre, username, password, "Administrador", require_change=False, actor=None)
                audit(conn, "BOOTSTRAP_ADMIN", "usuarios", uid, "Primer administrador creado mediante token de configuración", True, None)
                st.success("Administrador creado. Ya puedes iniciar sesión.")
                st.rerun()
            except Exception as exc:
                conn.rollback()
                st.error(str(exc))
        st.stop()

# -----------------------------------------------------------------------------
# REGLAS DE WESTGARD Y MÉTRICAS
# -----------------------------------------------------------------------------
def zscore(value: float, mean: float, sd: float) -> float:
    return (value - mean) / sd if sd and sd > 0 else 0.0


def westgard_rules(z_values: list[float]) -> list[str]:
    """Evalúa reglas básicas sobre la secuencia cronológica de z-scores."""
    if not z_values:
        return []
    rules: list[str] = []
    z = z_values[-1]
    if abs(z) >= 3:
        rules.append("1_3s")
    elif abs(z) >= 2:
        rules.append("1_2s")
    if len(z_values) >= 2:
        a, b = z_values[-2], z_values[-1]
        if abs(a) >= 2 and abs(b) >= 2 and (a > 0) == (b > 0):
            rules.append("2_2s")
        if abs(a - b) >= 4:
            rules.append("R_4s")
    if len(z_values) >= 4:
        last4 = z_values[-4:]
        if all(abs(x) >= 1 for x in last4) and (all(x > 0 for x in last4) or all(x < 0 for x in last4)):
            rules.append("4_1s")
    if len(z_values) >= 10:
        last10 = z_values[-10:]
        if all(x > 0 for x in last10) or all(x < 0 for x in last10):
            rules.append("10x")
    return rules


def state_from_rules(rules: list[str]) -> str:
    if any(r in rules for r in ["1_3s", "2_2s", "R_4s", "4_1s", "10x"]):
        return "Rechazado"
    if "1_2s" in rules:
        return "Advertencia"
    return "Aceptado"


def qc_statistics(df: pd.DataFrame, target_mean: float, allowable_error: Optional[float]) -> dict:
    if df.empty:
        return {"n": 0, "mean": None, "sd": None, "cv": None, "bias": None, "sigma": None}
    vals = pd.to_numeric(df["valor"], errors="coerce").dropna()
    if vals.empty:
        return {"n": 0, "mean": None, "sd": None, "cv": None, "bias": None, "sigma": None}
    mean = float(vals.mean())
    sd = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    cv = (sd / mean * 100) if mean else None
    bias = ((mean - target_mean) / target_mean * 100) if target_mean else None
    sigma = ((allowable_error - abs(bias)) / cv) if allowable_error is not None and cv and cv > 0 and bias is not None else None
    return {"n": len(vals), "mean": mean, "sd": sd, "cv": cv, "bias": bias, "sigma": sigma}

# -----------------------------------------------------------------------------
# DATOS / CONSULTAS
# -----------------------------------------------------------------------------
def load_analytes(conn, only_active=True):
    sql = "SELECT * FROM analitos"
    if only_active:
        sql += " WHERE activo=TRUE"
    sql += " ORDER BY nombre"
    return fetchall_df(conn, sql)


def load_equipment(conn, only_active=True):
    sql = "SELECT * FROM equipos"
    if only_active:
        sql += " WHERE activo=TRUE"
    sql += " ORDER BY nombre"
    return fetchall_df(conn, sql)


def load_lots(conn, analyte_id: int, only_active=True):
    sql = "SELECT * FROM lotes_control WHERE analito_id=%s"
    params: list[Any] = [analyte_id]
    if only_active:
        sql += " AND vigente=TRUE"
    sql += " ORDER BY nivel, lote"
    return fetchall_df(conn, sql, params)


def load_results(conn, lot_id: int, limit: Optional[int] = None):
    sql = """
    SELECT r.*, e.nombre AS equipo_nombre, u.nombre_completo AS usuario_nombre
    FROM resultados_cc r
    LEFT JOIN equipos e ON e.id=r.equipo_id
    LEFT JOIN usuarios u ON u.id=r.usuario_id
    WHERE r.lote_control_id=%s
    ORDER BY r.fecha ASC, r.hora ASC, r.id ASC
    """
    if limit:
        sql += " LIMIT %s"
        return fetchall_df(conn, sql, (lot_id, limit))
    return fetchall_df(conn, sql, (lot_id,))


def list_users(conn):
    return fetchall_df(conn, "SELECT id,nombre_completo,username,rol,activo,cambio_password_requerido,intentos_fallidos,bloqueado_hasta,ultimo_acceso,fecha_creacion FROM usuarios ORDER BY nombre_completo")


def list_audit(conn, limit=1000):
    return fetchall_df(conn, "SELECT * FROM auditoria ORDER BY fecha_hora DESC LIMIT %s", (limit,))

# -----------------------------------------------------------------------------
# GRÁFICOS Y PDF
# -----------------------------------------------------------------------------
def levey_jennings_figure(df: pd.DataFrame, mean: float, sd: float, unit: str):
    fig = go.Figure()
    if not df.empty:
        x = pd.to_datetime(df["fecha"]).dt.strftime("%d-%m-%Y")
        fig.add_trace(go.Scatter(
            x=x, y=df["valor"], mode="lines+markers", name="Resultado",
            hovertemplate="%{x}<br>%{y:.4f} " + unit + "<extra></extra>",
        ))
    levels = [(0, "Media", "solid"), (1, "+1 DE", "dot"), (-1, "-1 DE", "dot"),
              (2, "+2 DE", "dash"), (-2, "-2 DE", "dash"), (3, "+3 DE", "solid"), (-3, "-3 DE", "solid")]
    for mult, label, dash in levels:
        fig.add_hline(y=mean + mult * sd, line_dash=dash, annotation_text=label, annotation_position="right")
    fig.update_layout(
        height=470, margin=dict(l=20,r=20,t=30,b=20),
        xaxis_title="Fecha", yaxis_title=unit,
        hovermode="x unified", legend_orientation="h",
    )
    return fig


def generate_pdf(analyte: dict, lot: dict, results: pd.DataFrame, stats: dict) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.3*cm, bottomMargin=1.3*cm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title2", parent=styles["Title"], fontSize=18, leading=22, textColor=colors.HexColor("#8E1B2D"))
    story = [
        Paragraph("TMQuality 3.0 — Informe de Control de Calidad", title),
        Spacer(1, .35*cm),
        Paragraph(f"<b>Analito:</b> {analyte['nombre']} &nbsp;&nbsp; <b>Unidad:</b> {analyte['unidad']}", styles["BodyText"]),
        Paragraph(f"<b>Lote:</b> {lot['lote']} &nbsp;&nbsp; <b>Nivel:</b> {lot['nivel']}", styles["BodyText"]),
        Paragraph(f"<b>Objetivo:</b> {lot['media_objetivo']:.4f} ± {lot['de_objetivo']:.4f}", styles["BodyText"]),
        Spacer(1, .3*cm),
    ]
    summary = [
        ["Indicador", "Valor"],
        ["N", str(stats.get("n", 0))],
        ["Media observada", f"{stats['mean']:.4f}" if stats.get("mean") is not None else "—"],
        ["DE observada", f"{stats['sd']:.4f}" if stats.get("sd") is not None else "—"],
        ["CV%", f"{stats['cv']:.2f}%" if stats.get("cv") is not None else "—"],
        ["Sesgo%", f"{stats['bias']:.2f}%" if stats.get("bias") is not None else "—"],
        ["Sigma", f"{stats['sigma']:.2f}" if stats.get("sigma") is not None else "—"],
    ]
    t = Table(summary, colWidths=[6*cm, 5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#8E1B2D")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), .3, colors.grey),
        ("PADDING", (0,0), (-1,-1), 6),
    ]))
    story.extend([t, Spacer(1, .4*cm)])

    if not results.empty:
        cols = ["fecha", "turno", "operador", "valor", "estado", "reglas_violadas"]
        data = [["Fecha","Turno","Operador","Valor","Estado","Reglas"]]
        for _, r in results.tail(40).iterrows():
            data.append([str(r.get(c, ""))[:28] for c in cols])
        rt = Table(data, repeatRows=1, colWidths=[2.1*cm,1.7*cm,3.2*cm,2*cm,2.2*cm,4*cm])
        rt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EDEFF2")),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), .25, colors.lightgrey),
            ("FONTSIZE", (0,0), (-1,-1), 7),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
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
def logout(conn):
    if st.session_state.get("user"):
        audit(conn, "LOGOUT", "usuarios", st.session_state.user["id"], "Cierre de sesión")
    st.session_state.clear()
    st.rerun()


def login_ui(conn):
    st.markdown("""
    <div class="tmq-hero">
      <h1>🩸 TMQuality 3.0</h1>
      <p>Control de calidad analítico · Westgard · Levey–Jennings · Trazabilidad</p>
    </div>
    """, unsafe_allow_html=True)
    left, center, right = st.columns([1,1.1,1])
    with center:
        st.markdown('<div class="tmq-card">', unsafe_allow_html=True)
        st.subheader("Acceso al sistema")
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        if st.button("Ingresar", type="primary", use_container_width=True):
            user, msg = authenticate(conn, username, password)
            if user:
                st.session_state.user = user
                st.rerun()
            st.error(msg)
        st.caption("Las credenciales son individuales. Los accesos y eventos críticos quedan registrados en auditoría.")
        st.markdown('</div>', unsafe_allow_html=True)


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
                st.session_state.user = fetchone(conn, "SELECT * FROM usuarios WHERE id=%s", (user["id"],))
                st.success("Contraseña actualizada.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.stop()

# -----------------------------------------------------------------------------
# COMPONENTES DE UI
# -----------------------------------------------------------------------------
def kpi(label: str, value: str, hint: str = ""):
    st.markdown(f"""
    <div class="tmq-kpi"><div class="label">{label}</div><div class="value">{value}</div><div class="hint">{hint}</div></div>
    """, unsafe_allow_html=True)


def selected_context_ui(conn):
    analytes = load_analytes(conn)
    if analytes.empty:
        return None, None, None
    analyte_map = {f"{r.nombre} · {r.unidad}": int(r.id) for r in analytes.itertuples()}
    a_label = st.selectbox("Analito", list(analyte_map.keys()), key="global_analyte")
    analyte_id = analyte_map[a_label]
    analyte = fetchone(conn, "SELECT * FROM analitos WHERE id=%s", (analyte_id,))
    lots = load_lots(conn, analyte_id)
    if lots.empty:
        return analyte, None, None
    lot_map = {f"{r.nivel} · {r.lote}": int(r.id) for r in lots.itertuples()}
    l_label = st.selectbox("Lote de control", list(lot_map.keys()), key="global_lot")
    lot = fetchone(conn, "SELECT * FROM lotes_control WHERE id=%s", (lot_map[l_label],))
    return analyte, lot, load_results(conn, lot["id"])

# -----------------------------------------------------------------------------
# MÓDULOS
# -----------------------------------------------------------------------------
def module_dashboard(conn, analyte, lot, results):
    st.subheader("Panel de control")
    if not analyte or not lot:
        st.info("Crea un analito y un lote para comenzar.")
        return
    stats = qc_statistics(results, lot["media_objetivo"], analyte.get("error_total_permitido"))
    accepted = int((results["estado"] == "Aceptado").sum()) if not results.empty else 0
    warn = int((results["estado"] == "Advertencia").sum()) if not results.empty else 0
    reject = int((results["estado"] == "Rechazado").sum()) if not results.empty else 0
    conform = accepted / len(results) * 100 if len(results) else 0

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: kpi("Resultados", str(len(results)), "Total del lote")
    with c2: kpi("Conformidad", f"{conform:.1f}%", "Aceptados / total")
    with c3: kpi("Advertencias", str(warn), "Regla 1₂s")
    with c4: kpi("Rechazos", str(reject), "Reglas críticas")
    with c5: kpi("CV", f"{stats['cv']:.2f}%" if stats['cv'] is not None else "—", "Imprecisión observada")
    with c6: kpi("Sigma", f"{stats['sigma']:.2f}" if stats['sigma'] is not None else "—", "Requiere ET permitido")

    st.plotly_chart(levey_jennings_figure(results, lot["media_objetivo"], lot["de_objetivo"], analyte["unidad"]),
                    use_container_width=True, theme="streamlit", config={"displaylogo": False})

    if not results.empty:
        recent = results.tail(10).copy()
        st.markdown("#### Últimos resultados")
        show = [c for c in ["fecha","turno","operador","equipo_nombre","valor","z_score","estado","reglas_violadas"] if c in recent.columns]
        st.dataframe(recent[show].sort_values(["fecha"], ascending=False), use_container_width=True, hide_index=True)


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
                (lote_control_id,equipo_id,usuario_id,fecha,turno,operador,valor,z_score,reglas_violadas,estado,comentarios)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (lot["id"], eq_map[eq_label], user["id"], f, turno, user["nombre_completo"], valor, current_z,
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


def module_history(conn, user, analyte, lot, results):
    st.subheader("Historial y acciones correctivas")
    if not lot or results.empty:
        st.info("No hay resultados registrados para este lote.")
        return
    df = results.sort_values(["fecha","hora"], ascending=False).copy()
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


def module_analytics(conn, analyte, lot, results):
    st.subheader("Analítica de desempeño")
    if not analyte or not lot or results.empty:
        st.info("Se requieren resultados para calcular indicadores.")
        return
    stats = qc_statistics(results, lot["media_objetivo"], analyte.get("error_total_permitido"))
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Media observada", f"{stats['mean']:.4f}")
    c2.metric("DE observada", f"{stats['sd']:.4f}")
    c3.metric("CV%", f"{stats['cv']:.2f}%" if stats['cv'] is not None else "—")
    c4.metric("Sesgo%", f"{stats['bias']:.2f}%" if stats['bias'] is not None else "—")
    if analyte.get("error_total_permitido") is None:
        st.info("Define el Error Total Permitido (%) del analito para calcular Sigma.")
    else:
        sigma = stats["sigma"]
        st.metric("Métrica Sigma", f"{sigma:.2f}" if sigma is not None else "—", help="(ET permitido − |sesgo|) / CV")

    temp = results.copy()
    temp["fecha"] = pd.to_datetime(temp["fecha"])
    temp["mes"] = temp["fecha"].dt.to_period("M").astype(str)
    monthly = temp.groupby("mes").agg(media=("valor","mean"), de=("valor","std"), n=("valor","count")).reset_index()
    monthly["cv"] = monthly["de"] / monthly["media"] * 100
    fig = go.Figure()
    fig.add_trace(go.Bar(x=monthly["mes"], y=monthly["cv"], name="CV%"))
    fig.update_layout(height=360, title="CV% por mes", yaxis_title="CV%")
    st.plotly_chart(fig, use_container_width=True, theme="streamlit", config={"displaylogo": False})


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
                    INSERT INTO equipos(nombre,fabricante,modelo,numero_serie,area,ubicacion)
                    VALUES (%s,%s,%s,%s,%s,%s) RETURNING id
                    """, (name.strip(), manufacturer.strip() or None, model.strip() or None, serial.strip() or None, area.strip() or None, location.strip() or None))
                    eid = cur.fetchone()[0]
                conn.commit()
                audit(conn, "EQUIPO_CREADO", "equipos", eid, name)
                st.success("Equipo registrado.")
                st.rerun()
            except IntegrityError:
                conn.rollback(); st.error("El número de serie ya existe.")


def module_reports(conn, analyte, lot, results):
    st.subheader("Reportes y exportación")
    if not analyte or not lot:
        st.info("Selecciona un analito y lote.")
        return
    stats = qc_statistics(results, lot["media_objetivo"], analyte.get("error_total_permitido"))
    c1,c2 = st.columns(2)
    with c1:
        pdf = generate_pdf(analyte, lot, results, stats)
        st.download_button("📄 Descargar informe PDF", pdf,
                           file_name=f"TMQuality_{analyte['nombre']}_{lot['lote']}.pdf".replace(" ","_"),
                           mime="application/pdf", use_container_width=True)
    with c2:
        csv = results.to_csv(index=False).encode("utf-8-sig") if not results.empty else b""
        st.download_button("📊 Descargar CSV", csv,
                           file_name=f"TMQuality_{analyte['nombre']}_{lot['lote']}.csv".replace(" ","_"),
                           mime="text/csv", use_container_width=True)


def module_audit(conn):
    st.subheader("Auditoría")
    df = list_audit(conn, 5000)
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
                execute(conn, "UPDATE usuarios SET rol=%s, fecha_modificacion=CURRENT_TIMESTAMP WHERE id=%s", (new_role, int(uid)))
                audit(conn, "ROL_CAMBIADO", "usuarios", uid, f"{target['rol']} → {new_role}")
                st.rerun()
        with c2:
            label = "Desactivar" if target["activo"] else "Reactivar"
            if st.button(label, use_container_width=True):
                if target["rol"] == "Administrador" and target["activo"] and active_admin_count(conn) <= 1:
                    st.error("No se puede desactivar al último Administrador activo.")
                elif int(uid) == int(user["id"]) and target["activo"]:
                    st.error("No puedes desactivar tu propia sesión.")
                else:
                    execute(conn, "UPDATE usuarios SET activo=%s, fecha_modificacion=CURRENT_TIMESTAMP WHERE id=%s", (not bool(target["activo"]), int(uid)))
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
            add = st.form_submit_button("Crear analito")
        if add:
            try:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO analitos(nombre,unidad,metodologia,error_total_permitido) VALUES(%s,%s,%s,%s) RETURNING id",
                                (n.strip(), unit.strip(), method.strip() or None, tea if tea > 0 else None))
                    aid = cur.fetchone()[0]
                conn.commit(); audit(conn,"ANALITO_CREADO","analitos",aid,n); st.rerun()
            except IntegrityError:
                conn.rollback(); st.error("El analito ya existe.")
    with tab_l:
        analytes = load_analytes(conn)
        if analytes.empty:
            st.info("Primero crea un analito.")
        else:
            amap = {f"{r.nombre} ({r.unidad})":int(r.id) for r in analytes.itertuples()}
            with st.form("new_lot"):
                al = st.selectbox("Analito", list(amap.keys()))
                level = st.selectbox("Nivel", ["Bajo","Normal","Alto"])
                lot_code = st.text_input("Lote")
                mfg = st.text_input("Fabricante")
                material = st.text_input("Material de control")
                expiry = st.date_input("Vencimiento", value=date.today()+timedelta(days=365))
                mean = st.number_input("Media objetivo", value=1.0, format="%.4f")
                sd = st.number_input("DE objetivo", min_value=0.000001, value=0.1, format="%.4f")
                create_lot = st.form_submit_button("Crear lote")
            if create_lot:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                        INSERT INTO lotes_control(analito_id,nivel,lote,fabricante,material_control,fecha_vencimiento,media_objetivo,de_objetivo)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                        """, (amap[al],level,lot_code.strip(),mfg.strip() or None,material.strip() or None,expiry,mean,sd))
                        lid=cur.fetchone()[0]
                    conn.commit(); audit(conn,"LOTE_CREADO","lotes_control",lid,lot_code); st.rerun()
                except IntegrityError:
                    conn.rollback(); st.error("Ese lote ya existe para el analito/nivel seleccionado.")

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
conn = get_connection()
init_db(conn)
bootstrap_admin_ui(conn)

if "user" not in st.session_state:
    login_ui(conn)
    st.stop()

user = st.session_state.user
# Refrescar estado del usuario cada ejecución (permite desactivación inmediata).
fresh = fetchone(conn, "SELECT * FROM usuarios WHERE id=%s", (user["id"],))
if not fresh or not fresh["activo"]:
    st.session_state.clear()
    st.error("Tu cuenta ya no está activa.")
    st.stop()
st.session_state.user = fresh
user = fresh

if user.get("cambio_password_requerido"):
    forced_password_change_ui(conn, user)

with st.sidebar:
    st.markdown("## 🩸 TMQuality")
    st.caption(f"Versión {APP_VERSION}")
    st.markdown(f"**{user['nombre_completo']}**")
    st.caption(f"{user['rol']} · @{user['username']}")
    if user.get("ultimo_acceso"):
        st.caption(f"Último acceso: {user['ultimo_acceso']:%d-%m-%Y %H:%M}")
    if st.button("Cerrar sesión", use_container_width=True):
        logout(conn)
    st.divider()
    analyte, lot, results = selected_context_ui(conn)
    if analyte and lot:
        st.markdown("##### Parámetros objetivo")
        st.write(f"**μ:** {lot['media_objetivo']:.4f} {analyte['unidad']}")
        st.write(f"**DE:** {lot['de_objetivo']:.4f} {analyte['unidad']}")
        if lot.get("fecha_vencimiento"):
            exp = lot["fecha_vencimiento"]
            if exp < date.today(): st.error(f"Lote vencido: {exp:%d-%m-%Y}")
            elif exp <= date.today()+timedelta(days=30): st.warning(f"Vence: {exp:%d-%m-%Y}")

st.markdown(f"""
<div class="tmq-hero">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap">
    <div><h1>TMQuality 3.0</h1><p>Control de calidad analítico · Westgard · Levey–Jennings · Sigma · Auditoría</p></div>
    <span class="tmq-badge">● Sesión activa · {user['rol']}</span>
  </div>
</div>
""", unsafe_allow_html=True)

modules = ["📊 Panel", "➕ Registrar", "📋 Historial", "📈 Analítica", "🧪 Equipos", "📄 Reportes"]
if user["rol"] in ["Administrador","Supervisor"]:
    modules.append("🧾 Auditoría")
if user["rol"] == "Administrador":
    modules.append("⚙️ Administración")

tabs = st.tabs(modules)
for label, tab in zip(modules, tabs):
    with tab:
        if label == "📊 Panel": module_dashboard(conn, analyte, lot, results if results is not None else pd.DataFrame())
        elif label == "➕ Registrar": module_register(conn, user, analyte, lot, results if results is not None else pd.DataFrame())
        elif label == "📋 Historial": module_history(conn, user, analyte, lot, results if results is not None else pd.DataFrame())
        elif label == "📈 Analítica": module_analytics(conn, analyte, lot, results if results is not None else pd.DataFrame())
        elif label == "🧪 Equipos": module_equipment(conn, user)
        elif label == "📄 Reportes": module_reports(conn, analyte, lot, results if results is not None else pd.DataFrame())
        elif label == "🧾 Auditoría": module_audit(conn)
        elif label == "⚙️ Administración": module_admin(conn, user)

conn.close()
