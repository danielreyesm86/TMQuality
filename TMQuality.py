"""
Sistema de Control de Calidad - Laboratorio (Medicina Transfusional)
======================================================================
Módulo de Control de Calidad con reglas de Westgard y gráficos
de Levey-Jennings.

Cómo correr:
    pip install streamlit plotly pandas matplotlib reportlab
    streamlit run app.py

La base de datos (SQLite) se crea automáticamente en la primera
ejecución, en el mismo directorio (qc_lab.db).
"""

import sqlite3
from datetime import datetime, date
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
)

DB_PATH = Path(__file__).parent / "qc_lab.db"

# ----------------------------------------------------------------------
# LOGO (incrustado en base64 para que el archivo sea autocontenido)
# ----------------------------------------------------------------------
LOGO_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAgAAAAIACAYAAAD0eNT6AAAABmJLR0QA/wD/AP+gvaeTAAAgAElEQVR4nOzdd3gd1Z0+8PfM3HvV"
    "q4sk997kgi33KmNbtoxtMGAINfSS5BeS0JPsQsJCyEISSCgBsgkLbAotSzUGt2BswL032cbGvcnq5ZY5vz+MWWNcpDvlzJ15P88z"
    "zz5raWbeiHtnvnPOnHMAIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIi"
    "IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIi"
    "IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIrLIrtLS6btKS6erzkFEagjVAYjIedtKSlqH"
    "AoG1ADQjFhvQac6c/aozEZGzNNUBiMhZEhBJgcCfAeQBaKXp+ouSDwNEvsMCgMhndk+d+iMDuEAC+Gor+XLq1B+qzkVEzmLVT+Qj"
    "uyZPLoSuLwOQcsqPGmOaNqzLu++uUZGLiJzHFgAin/iiuDhZavpfIZGCkx7/v9qS9Jjx192zZp1aGBCRR7EAIPIJPSXtMQH0P8uv"
    "9DFqax91LBARKcUuACIf2D116hRDyvdx7u+8hBAzOr7//rtO5CIidVgAEHnctpKS1kFdXwegdRN3ORgC+hXMnn3YzlxEpBa7AIg8"
    "Lqjrz6DpN38AyAtL+YJdeYjIHVgAEHnYrtLSmwFc0uwdhbhwZ2npDdYnIiK3YBcAkUftLCnpDF1fAyAjzkPU6oZxXvs5c7ZZmYuI"
    "3IEtAEQeJB98UBO6/iLiv/kDQFpM016Us2bpFsUiIhdhAUDkQbs+//x+CYy14FCjvqypucuC4xCRy7ALgMhjdpaWDgTwGYCQRYcM"
    "G4YxtMucOZwlkMhD2AJA5CFlpaVJUuK/IRE6zWx/8W4hTWicJZDIY1gAEHlIyMCjAuhnw6H7xGpqHrLhuESkCLsAiDxi15QpEyTE"
    "h7CvsDcgtYmd5ry3wKbjE5GDWAAQecD2iROztEBwHYD2Np9qV1Sgf/fZs6tsPg8R2YxdAEQeoAVCT8D+mz8AdNSl+K0D5yEim7EF"
    "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"
)


# ----------------------------------------------------------------------
# ACCESO CON CONTRASEÑA
# ----------------------------------------------------------------------
# La contraseña se lee desde Streamlit secrets (archivo .streamlit/secrets.toml
# en local, o la sección "Secrets" del panel de Streamlit Cloud al desplegar).
# Si no encuentra ningún secreto configurado, usa este valor por defecto
# SOLO para pruebas locales rápidas — cámbialo o, mejor, configura el secreto.
def obtener_logo():
    """Decodifica el logo embebido y lo devuelve como imagen PIL,
    lista para usar en st.image o como page_icon."""
    import base64
    from PIL import Image
    return Image.open(BytesIO(base64.b64decode(LOGO_B64)))


def verificar_acceso():
    """Muestra una pantalla de acceso con usuario + contraseña, con la
    marca TMQuality. Si las credenciales son correctas, guarda los
    datos del usuario en la sesión y deja continuar; si no, detiene
    la ejecución del resto de la app."""
    if st.session_state.get("usuario_actual"):
        return

    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            background: linear-gradient(180deg, #FFFFFF 0%, #F4F7F9 100%);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col_izq, col_centro, col_der = st.columns([1, 1.3, 1])
    with col_centro:
        st.markdown("<div style='height: 4vh'></div>", unsafe_allow_html=True)
        st.image(obtener_logo(), width=120)
        st.markdown(
            """
            <h1 style='text-align:center; color:#A81F2E; margin-bottom:0;
                       font-size:2.6rem;'>TMQuality</h1>
            <p style='text-align:center; color:#5A6A72; margin-top:0.2rem;
                      font-size:1.05rem;'>
                Control de Calidad · Laboratorio Clínico y Medicina Transfusional
            </p>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height: 2vh'></div>", unsafe_allow_html=True)

        def _intentar_login():
            usuario_input = st.session_state.get("username_login", "").strip()
            clave = st.session_state.get("clave_login", "")
            conn_login = get_connection()
            usuario = autenticar_usuario(conn_login, usuario_input, clave)
            conn_login.close()
            if usuario:
                st.session_state["usuario_actual"] = usuario
                st.session_state["login_error"] = False
            else:
                st.session_state["login_error"] = True

        st.text_input(
            "Usuario", key="username_login",
            placeholder="Usuario", label_visibility="collapsed",
        )
        # Usamos on_change (no st.form) para que presionar Enter dentro
        # del campo de contraseña dispare el login de inmediato, sin
        # necesidad de hacer clic aparte en el botón.
        st.text_input(
            "Contraseña", type="password",
            key="clave_login", on_change=_intentar_login,
            placeholder="Contraseña", label_visibility="collapsed",
        )
        st.button("Ingresar →", use_container_width=True, on_click=_intentar_login)

        if st.session_state.get("login_error"):
            st.error("Usuario o contraseña incorrectos. Inténtalo de nuevo.")

        st.markdown(
            """
            <p style='text-align:center; color:#9AA5AA; font-size:0.8rem;
                      margin-top:1.5rem;'>
                Acceso restringido · Sistema interno de calidad
            </p>
            """,
            unsafe_allow_html=True,
        )
    st.stop()

# ----------------------------------------------------------------------
# BASE DE DATOS
# ----------------------------------------------------------------------

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS analitos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            unidad TEXT NOT NULL,
            UNIQUE(nombre)
        )
    """)

    # Media y DE "objetivo" definidas por lote de control (fabricante o
    # calculadas internamente con datos históricos, ej. 20 puntos).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lotes_control (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analito_id INTEGER NOT NULL,
            nivel TEXT NOT NULL CHECK(nivel IN ('Bajo','Normal','Alto')),
            lote TEXT NOT NULL,
            media_objetivo REAL NOT NULL,
            de_objetivo REAL NOT NULL,
            vigente INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(analito_id) REFERENCES analitos(id),
            UNIQUE(analito_id, nivel, lote)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS resultados_cc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lote_control_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            turno TEXT NOT NULL,
            operador TEXT NOT NULL,
            valor REAL NOT NULL,
            reglas_violadas TEXT,
            estado TEXT NOT NULL DEFAULT 'Pendiente',
            accion_correctiva TEXT,
            FOREIGN KEY(lote_control_id) REFERENCES lotes_control(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_completo TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            rol TEXT NOT NULL CHECK(rol IN ('Administrador','Supervisor')),
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_creacion TEXT NOT NULL
        )
    """)

    conn.commit()

    # Datos semilla, solo si la tabla está vacía (para que el prototipo
    # se pueda explorar de inmediato)
    cur.execute("SELECT COUNT(*) FROM analitos")
    if cur.fetchone()[0] == 0:
        seed_demo_data(conn)

    # Usuario administrador por defecto, solo si no existe ningún usuario
    # todavía. La clave inicial se puede definir en Streamlit secrets
    # (admin_password); si no, usa "admin123" — CÁMBIALA de inmediato
    # desde "Gestión de usuarios" una vez que inicies sesión.
    cur.execute("SELECT COUNT(*) FROM usuarios")
    if cur.fetchone()[0] == 0:
        try:
            clave_inicial = st.secrets["admin_password"]
        except Exception:
            clave_inicial = "admin123"
        crear_usuario(conn, "Administrador", "admin", clave_inicial, "Administrador")

    conn.close()


def seed_demo_data(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO analitos (nombre, unidad) VALUES (?, ?)",
                ("Hemoglobina", "g/dL"))
    analito_id = cur.lastrowid

    cur.execute("""
        INSERT INTO lotes_control (analito_id, nivel, lote, media_objetivo, de_objetivo)
        VALUES (?, 'Normal', 'LOTE-2026-01', 12.0, 0.3)
    """, (analito_id,))
    lote_id = cur.lastrowid

    # Serie de ejemplo con una violación 1_3s intencional para mostrar
    # cómo se ve una alerta
    demo_valores = [12.1, 11.9, 12.2, 12.0, 11.8, 12.3, 12.0, 12.05,
                    12.9, 11.95, 12.1]
    base_date = date(2026, 7, 1)
    for i, valor in enumerate(demo_valores):
        cur.execute("""
            INSERT INTO resultados_cc
                (lote_control_id, fecha, turno, operador, valor, estado)
            VALUES (?, ?, 'Largo', 'Demo', ?, 'Pendiente')
        """, (lote_id, str(base_date.replace(day=1 + i)), valor))

    conn.commit()


# ----------------------------------------------------------------------
# USUARIOS (autenticación con hash + salt)
# ----------------------------------------------------------------------

def _hash_password(password, salt_hex=None):
    """Genera hash PBKDF2-SHA256 de la contraseña. Si no se pasa salt,
    genera uno nuevo (para crear usuario); si se pasa, lo reutiliza
    (para verificar login)."""
    import hashlib
    import secrets as secrets_module

    if salt_hex is None:
        salt_hex = secrets_module.token_hex(16)

    salt_bytes = bytes.fromhex(salt_hex)
    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_bytes, 100_000
    )
    return hash_bytes.hex(), salt_hex


def crear_usuario(conn, nombre_completo, username, password, rol):
    """Crea un nuevo usuario. Lanza sqlite3.IntegrityError si el
    username ya existe (para que el llamador lo maneje)."""
    hash_hex, salt_hex = _hash_password(password)
    conn.execute("""
        INSERT INTO usuarios
            (nombre_completo, username, password_hash, salt, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, 1, ?)
    """, (nombre_completo, username, hash_hex, salt_hex, rol, str(datetime.now())))
    conn.commit()


def autenticar_usuario(conn, username, password):
    """Devuelve un dict con los datos del usuario si la contraseña es
    correcta y la cuenta está activa; None en caso contrario."""
    fila = conn.execute("""
        SELECT id, nombre_completo, username, password_hash, salt, rol, activo
        FROM usuarios WHERE username = ?
    """, (username,)).fetchone()

    if fila is None:
        return None

    user_id, nombre_completo, uname, hash_guardado, salt, rol, activo = fila
    if not activo:
        return None

    hash_calculado, _ = _hash_password(password, salt)
    if hash_calculado != hash_guardado:
        return None

    return {"id": user_id, "nombre_completo": nombre_completo,
            "username": uname, "rol": rol}


def listar_usuarios(conn):
    return pd.read_sql("""
        SELECT id, nombre_completo, username, rol, activo, fecha_creacion
        FROM usuarios ORDER BY fecha_creacion ASC
    """, conn)


def cambiar_password(conn, user_id, nueva_password):
    hash_hex, salt_hex = _hash_password(nueva_password)
    conn.execute(
        "UPDATE usuarios SET password_hash = ?, salt = ? WHERE id = ?",
        (hash_hex, salt_hex, user_id)
    )
    conn.commit()


def set_usuario_activo(conn, user_id, activo: bool):
    conn.execute("UPDATE usuarios SET activo = ? WHERE id = ?",
                 (1 if activo else 0, user_id))
    conn.commit()
# ----------------------------------------------------------------------
# Cada función recibe la serie completa de z-scores (valor - media) / DE,
# en orden cronológico, y evalúa si el ÚLTIMO punto dispara la regla.

def z_scores(valores, media, de):
    return [(v - media) / de for v in valores]


def regla_1_2s(z):
    """Advertencia: 1 punto fuera de ±2DE. No rechaza por sí sola."""
    return abs(z[-1]) > 2


def regla_1_3s(z):
    """Rechazo: 1 punto fuera de ±3DE. Error aleatorio grave."""
    return abs(z[-1]) > 3


def regla_2_2s(z):
    """Rechazo: 2 puntos consecutivos fuera de ±2DE, mismo lado."""
    if len(z) < 2:
        return False
    a, b = z[-2], z[-1]
    return (a > 2 and b > 2) or (a < -2 and b < -2)


def regla_r_4s(z):
    """Rechazo: diferencia entre 2 puntos consecutivos > 4DE (lados opuestos)."""
    if len(z) < 2:
        return False
    return abs(z[-1] - z[-2]) > 4


def regla_4_1s(z):
    """Rechazo: 4 puntos consecutivos fuera de ±1DE, mismo lado. Error sistemático."""
    if len(z) < 4:
        return False
    ultimos = z[-4:]
    return all(v > 1 for v in ultimos) or all(v < -1 for v in ultimos)


def regla_10x(z):
    """Rechazo: 10 puntos consecutivos al mismo lado de la media. Error sistemático."""
    if len(z) < 10:
        return False
    ultimos = z[-10:]
    return all(v > 0 for v in ultimos) or all(v < 0 for v in ultimos)


REGLAS = {
    "1_2s (advertencia)": (regla_1_2s, "advertencia"),
    "1_3s": (regla_1_3s, "rechazo"),
    "2_2s": (regla_2_2s, "rechazo"),
    "R_4s": (regla_r_4s, "rechazo"),
    "4_1s": (regla_4_1s, "rechazo"),
    "10x": (regla_10x, "rechazo"),
}


def evaluar_westgard(valores, media, de):
    """Devuelve lista de nombres de reglas violadas por el último punto."""
    z = z_scores(valores, media, de)
    violadas = []
    for nombre, (fn, tipo) in REGLAS.items():
        try:
            if fn(z):
                violadas.append(nombre)
        except Exception:
            pass
    return violadas


def recalcular_reglas_lote(conn, lote_control_id, media, de):
    """
    Recorre todos los resultados del lote en orden cronológico y
    recalcula reglas_violadas + estado desde cero. Útil después de
    eliminar o corregir resultados, para que las series de Westgard
    (que dependen de puntos anteriores) queden consistentes.
    Devuelve la cantidad de filas actualizadas.
    """
    df = pd.read_sql("""
        SELECT id, valor FROM resultados_cc
        WHERE lote_control_id = ?
        ORDER BY fecha ASC, id ASC
    """, conn, params=(lote_control_id,))

    valores_acumulados = []
    actualizaciones = []
    for _, row in df.iterrows():
        valores_acumulados.append(row["valor"])
        violadas = evaluar_westgard(valores_acumulados, media, de)
        hay_rechazo = any(REGLAS[r][1] == "rechazo" for r in violadas)
        estado = "Rechazado" if hay_rechazo else ("Advertencia" if violadas else "Aceptado")
        actualizaciones.append((
            ", ".join(violadas) if violadas else None,
            estado,
            int(row["id"]),
        ))

    conn.executemany(
        "UPDATE resultados_cc SET reglas_violadas = ?, estado = ? WHERE id = ?",
        actualizaciones
    )
    conn.commit()
    return len(actualizaciones)


# ----------------------------------------------------------------------
# CONSULTAS
# ----------------------------------------------------------------------

def cargar_analitos(conn):
    return pd.read_sql("SELECT * FROM analitos ORDER BY nombre", conn)


def cargar_lotes(conn, analito_id):
    return pd.read_sql(
        "SELECT * FROM lotes_control WHERE analito_id = ? AND vigente = 1",
        conn, params=(analito_id,)
    )


def cargar_resultados(conn, lote_control_id):
    return pd.read_sql("""
        SELECT * FROM resultados_cc
        WHERE lote_control_id = ?
        ORDER BY fecha ASC, id ASC
    """, conn, params=(lote_control_id,))


# ----------------------------------------------------------------------
# GENERACIÓN DE PDF
# ----------------------------------------------------------------------

def generar_grafico_lj_png(resultados_df, media, de, unidad):
    """Genera el gráfico de Levey-Jennings como imagen PNG (para el PDF)."""
    colores = {
        "Aceptado": "green",
        "Advertencia": "orange",
        "Rechazado": "red",
        "Pendiente": "gray",
    }

    fig, ax = plt.subplots(figsize=(9, 4.5))

    for n, alpha in [(1, 0.10), (2, 0.08), (3, 0.06)]:
        ax.axhspan(media + (n - 1) * de, media + n * de, color="orange", alpha=alpha)
        ax.axhspan(media - n * de, media - (n - 1) * de, color="orange", alpha=alpha)

    for n, style in [(1, "dotted"), (2, "dashed"), (3, "solid")]:
        ax.axhline(media + n * de, color="gray", linestyle=style, linewidth=0.8)
        ax.axhline(media - n * de, color="gray", linestyle=style, linewidth=0.8)
    ax.axhline(media, color="black", linewidth=1)

    x = resultados_df["fecha"]
    y = resultados_df["valor"]
    puntos_color = resultados_df["estado"].map(colores).fillna("gray")

    ax.plot(x, y, color="lightblue", linewidth=1, zorder=1)
    ax.scatter(x, y, c=puntos_color, edgecolors="black", s=40, zorder=2)

    ax.set_ylabel(f"Valor ({unidad})")
    ax.set_xlabel("Fecha")
    fig.autofmt_xdate()
    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def generar_pdf_reporte(analito_nombre, lote_label, media, de, unidad, resultados_df):
    """Construye un PDF con encabezado, gráfico de Levey-Jennings y la
    tabla completa de resultados. Devuelve los bytes del PDF."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    elementos = []

    elementos.append(Paragraph("Reporte de Control de Calidad", styles["Title"]))
    elementos.append(Spacer(1, 0.3 * cm))
    elementos.append(Paragraph(f"<b>Analito:</b> {analito_nombre}", styles["Normal"]))
    elementos.append(Paragraph(f"<b>Lote de control:</b> {lote_label}", styles["Normal"]))
    elementos.append(Paragraph(f"<b>Media objetivo:</b> {media} {unidad}", styles["Normal"]))
    elementos.append(Paragraph(f"<b>DE objetivo:</b> {de} {unidad}", styles["Normal"]))
    elementos.append(Paragraph(
        f"<b>Generado:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]
    ))
    elementos.append(Spacer(1, 0.5 * cm))

    if not resultados_df.empty:
        grafico_buf = generar_grafico_lj_png(resultados_df, media, de, unidad)
        elementos.append(Image(grafico_buf, width=17 * cm, height=8.5 * cm))
        elementos.append(Spacer(1, 0.5 * cm))

        elementos.append(Paragraph("Historial de resultados", styles["Heading2"]))

        encabezados = ["Fecha", "Turno", "Operador", "Valor", "Estado", "Reglas violadas"]
        filas = [encabezados]
        for _, row in resultados_df.iterrows():
            filas.append([
                str(row["fecha"].date()) if hasattr(row["fecha"], "date") else str(row["fecha"]),
                row["turno"],
                row["operador"],
                f"{row['valor']:.4f}",
                row["estado"],
                row["reglas_violadas"] or "-",
            ])

        tabla = Table(filas, repeatRows=1, hAlign="LEFT")
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elementos.append(tabla)
    else:
        elementos.append(Paragraph("No hay resultados registrados para este lote.", styles["Normal"]))

    doc.build(elementos)
    buffer.seek(0)
    return buffer


# ----------------------------------------------------------------------
# INTERFAZ
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# INTERFAZ
# ----------------------------------------------------------------------

st.set_page_config(
    page_title="TMQuality — Control de Calidad",
    page_icon=obtener_logo(),
    layout="wide",
    initial_sidebar_state="expanded",
)


def aplicar_estilos():
    st.markdown(
        """
        <style>
        :root {
            --tm-primary: #8F1D2C;
            --tm-primary-dark: #6F1320;
            --tm-accent: #C94A5B;
            --tm-soft: #F8EEF0;
            --tm-surface: #FFFFFF;
            --tm-bg: #F5F7FA;
            --tm-text: #24313A;
            --tm-muted: #697780;
            --tm-success: #21845A;
            --tm-warning: #C77A16;
            --tm-danger: #C0392B;
            --tm-border: #E5E9ED;
        }

        [data-testid="stAppViewContainer"] {
            background: linear-gradient(180deg, #FBFCFD 0%, var(--tm-bg) 100%);
        }
        [data-testid="stHeader"] { background: rgba(255,255,255,0.88); }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #FFFFFF 0%, #F8F3F4 100%);
            border-right: 1px solid var(--tm-border);
        }
        .block-container {
            max-width: 1500px;
            padding-top: 1.25rem;
            padding-bottom: 3rem;
        }
        h1, h2, h3 { color: var(--tm-text); letter-spacing: -0.02em; }
        div[data-testid="stMetric"] {
            background: var(--tm-surface);
            border: 1px solid var(--tm-border);
            border-radius: 16px;
            padding: 1rem 1.15rem;
            box-shadow: 0 7px 24px rgba(32, 43, 53, 0.06);
        }
        div[data-testid="stMetric"] label { color: var(--tm-muted); }
        div[data-testid="stMetricValue"] { color: var(--tm-text); }
        div[data-testid="stForm"] {
            background: var(--tm-surface);
            border: 1px solid var(--tm-border);
            border-radius: 18px;
            padding: 1rem;
            box-shadow: 0 8px 28px rgba(32, 43, 53, 0.05);
        }
        div[data-testid="stExpander"] {
            border: 1px solid var(--tm-border);
            border-radius: 14px;
            background: rgba(255,255,255,0.78);
        }
        .stButton > button, .stDownloadButton > button {
            border-radius: 10px;
            font-weight: 650;
            transition: transform .15s ease, box-shadow .15s ease;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 5px 14px rgba(37,49,58,.12);
        }
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, var(--tm-primary), var(--tm-accent));
            border: none;
        }
        .tm-hero {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            padding: 1.25rem 1.4rem;
            background: linear-gradient(135deg, #FFFFFF 0%, #FAF0F2 100%);
            border: 1px solid #EAD8DC;
            border-radius: 20px;
            box-shadow: 0 10px 34px rgba(80, 36, 44, .08);
            margin-bottom: 1.1rem;
        }
        .tm-hero h1 { margin: 0; font-size: 2rem; }
        .tm-hero p { margin: .25rem 0 0; color: var(--tm-muted); }
        .tm-badge {
            display: inline-flex;
            align-items: center;
            gap: .4rem;
            padding: .42rem .75rem;
            border-radius: 999px;
            background: #FFFFFF;
            border: 1px solid #E8D4D8;
            color: var(--tm-primary-dark);
            font-size: .85rem;
            font-weight: 700;
            white-space: nowrap;
        }
        .tm-section {
            background: var(--tm-surface);
            border: 1px solid var(--tm-border);
            border-radius: 18px;
            padding: 1rem 1.15rem;
            box-shadow: 0 8px 28px rgba(32,43,53,.05);
            margin-bottom: 1rem;
        }
        .tm-status {
            border-radius: 14px;
            padding: .85rem 1rem;
            font-weight: 650;
            border: 1px solid transparent;
        }
        .tm-ok { background:#EDF8F3; color:#176843; border-color:#C9E9DA; }
        .tm-warn { background:#FFF7E8; color:#93590D; border-color:#F1D9A9; }
        .tm-bad { background:#FFF0EE; color:#9D2A20; border-color:#F0C5BF; }
        .tm-muted-card { background:#F7F9FA; color:#5F6B73; border-color:#E3E8EB; }
        .tm-mini-title { color: var(--tm-muted); font-size: .82rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
        .tm-mini-value { color: var(--tm-text); font-size: 1.12rem; font-weight: 750; margin-top: .2rem; }
        div[data-baseweb="tab-list"] { gap: .4rem; }
        button[data-baseweb="tab"] {
            border-radius: 10px;
            padding: .65rem 1rem;
            color: var(--tm-muted) !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            color: var(--tm-primary) !important;
            font-weight: 750 !important;
        }

        /* Corrección de contraste frente a temas oscuros del navegador/Streamlit */
        html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
            color-scheme: light !important;
        }
        [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] * {
            --text-color: var(--tm-text);
        }
        .stApp, .stApp p, .stApp span, .stApp label,
        .stApp div[data-testid="stMarkdownContainer"],
        .stApp div[data-testid="stMarkdownContainer"] p,
        .stApp div[data-testid="stMarkdownContainer"] li {
            color: var(--tm-text);
        }
        .tm-hero h1, .tm-hero p, .tm-badge,
        .tm-section, .tm-section *, .tm-status, .tm-status * {
            opacity: 1 !important;
        }
        .tm-hero h1 { color: var(--tm-primary-dark) !important; }
        .tm-hero p { color: var(--tm-muted) !important; }
        .tm-badge { color: var(--tm-primary-dark) !important; }
        .tm-ok { color:#176843 !important; }
        .tm-warn { color:#93590D !important; }
        .tm-bad { color:#9D2A20 !important; }
        .tm-muted-card { color:#5F6B73 !important; }

        [data-testid="stSidebar"] *,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--tm-text) !important;
            opacity: 1 !important;
        }
        [data-testid="stSidebar"] div[data-baseweb="select"] > div,
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea {
            background: #FFFFFF !important;
            color: var(--tm-text) !important;
            border-color: var(--tm-border) !important;
        }
        [data-testid="stSidebar"] .stButton > button,
        [data-testid="stSidebar"] .stDownloadButton > button {
            color: var(--tm-text) !important;
            background: #FFFFFF !important;
            border: 1px solid var(--tm-border) !important;
        }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {
            color: #FFFFFF !important;
            background: linear-gradient(135deg, var(--tm-primary), var(--tm-accent)) !important;
            border: none !important;
        }
        [data-testid="stSidebar"] button:disabled,
        [data-testid="stSidebar"] input:disabled {
            color: #76838B !important;
            background: #F3F5F6 !important;
            opacity: 1 !important;
        }
        div[data-testid="stMetric"] *,
        div[data-testid="stMetric"] label,
        div[data-testid="stMetricValue"] {
            color: var(--tm-text) !important;
            opacity: 1 !important;
        }
        div[data-testid="stMetric"] label { color: var(--tm-muted) !important; }
        div[data-testid="stMetricDelta"] * { color: var(--tm-success) !important; }
        [data-testid="stWidgetLabel"] p { color: var(--tm-text) !important; }
        div[data-baseweb="select"] > div,
        input, textarea {
            color: var(--tm-text) !important;
            background-color: #FFFFFF !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


init_db()
verificar_acceso()
aplicar_estilos()
conn = get_connection()
usuario_actual = st.session_state["usuario_actual"]

# Encabezado principal
col_logo, col_hero = st.columns([0.7, 9.3], vertical_alignment="center")
with col_logo:
    st.image(obtener_logo(), width=72)
with col_hero:
    st.markdown(
        f"""
        <div class="tm-hero">
            <div>
                <h1>TMQuality</h1>
                <p>Control de calidad analítico · Reglas de Westgard · Levey–Jennings</p>
            </div>
            <div class="tm-badge">● Sesión activa · {usuario_actual['rol']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Barra lateral
with st.sidebar:
    st.image(obtener_logo(), width=78)
    st.markdown(f"### {usuario_actual['nombre_completo']}")
    st.caption(f"{usuario_actual['rol']} · @{usuario_actual['username']}")

    if st.button("Cerrar sesión", icon="🚪", use_container_width=True):
        st.session_state["usuario_actual"] = None
        st.rerun()

    with st.expander("Seguridad y acceso", icon="🔐"):
        nueva_clave1 = st.text_input("Nueva contraseña", type="password", key="nueva_clave1")
        nueva_clave2 = st.text_input("Repetir contraseña", type="password", key="nueva_clave2")
        if st.button("Actualizar contraseña", use_container_width=True):
            if not nueva_clave1:
                st.warning("La contraseña no puede estar vacía.")
            elif nueva_clave1 != nueva_clave2:
                st.error("Las contraseñas no coinciden.")
            else:
                cambiar_password(conn, usuario_actual["id"], nueva_clave1)
                st.success("Contraseña actualizada.")

    if usuario_actual["rol"] == "Administrador":
        with st.expander("Gestión de usuarios", icon="👥"):
            with st.form("form_usuario", clear_on_submit=True):
                nombre_nuevo_usr = st.text_input("Nombre completo")
                username_nuevo = st.text_input("Usuario")
                password_nuevo = st.text_input("Contraseña inicial", type="password")
                rol_nuevo = st.selectbox("Rol", ["Supervisor", "Administrador"])
                crear_usr = st.form_submit_button("Crear usuario", use_container_width=True)
            if crear_usr:
                if not (nombre_nuevo_usr and username_nuevo and password_nuevo):
                    st.warning("Completa todos los campos.")
                else:
                    try:
                        crear_usuario(conn, nombre_nuevo_usr, username_nuevo.strip(), password_nuevo, rol_nuevo)
                        st.success(f"Usuario '{username_nuevo}' creado.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Ese nombre de usuario ya existe.")

            st.markdown("**Usuarios existentes**")
            usuarios_df = listar_usuarios(conn)
            for _, u in usuarios_df.iterrows():
                estado_icono = "🟢" if u["activo"] else "⚪"
                st.caption(f"{estado_icono} {u['nombre_completo']} · {u['rol']}")
                if u["activo"]:
                    if st.button("Desactivar", key=f"desact_{u['id']}", use_container_width=True):
                        if u["id"] == usuario_actual["id"]:
                            st.error("No puedes desactivar tu propia cuenta.")
                        else:
                            set_usuario_activo(conn, int(u["id"]), False)
                            st.rerun()
                else:
                    if st.button("Reactivar", key=f"react_{u['id']}", use_container_width=True):
                        set_usuario_activo(conn, int(u["id"]), True)
                        st.rerun()

    st.divider()
    st.markdown("### Contexto de análisis")
    analitos_df = cargar_analitos(conn)

    with st.expander("Nuevo analito", icon="➕"):
        with st.form("form_analito", clear_on_submit=True):
            nuevo_nombre = st.text_input("Nombre del analito")
            nueva_unidad = st.text_input("Unidad", placeholder="g/dL, %, mg/dL…")
            guardar_analito = st.form_submit_button("Guardar analito", use_container_width=True)
        if guardar_analito:
            if nuevo_nombre and nueva_unidad:
                try:
                    conn.execute("INSERT INTO analitos (nombre, unidad) VALUES (?, ?)", (nuevo_nombre, nueva_unidad))
                    conn.commit()
                    st.success(f"Analito '{nuevo_nombre}' agregado.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.warning("Ese analito ya existe.")
            else:
                st.warning("Completa nombre y unidad.")

    if analitos_df.empty:
        st.info("Agrega un analito para comenzar.")
        st.stop()

    analito_sel = st.selectbox("Analito", analitos_df["nombre"])
    analito_id = int(analitos_df[analitos_df.nombre == analito_sel]["id"].iloc[0])
    unidad = analitos_df[analitos_df.nombre == analito_sel]["unidad"].iloc[0]
    lotes_df = cargar_lotes(conn, analito_id)

    with st.expander("Nuevo lote de control", icon="🧪"):
        with st.form("form_lote", clear_on_submit=True):
            nivel_nuevo = st.selectbox("Nivel", ["Bajo", "Normal", "Alto"])
            lote_nuevo = st.text_input("Identificador de lote")
            media_nueva = st.number_input("Media objetivo", format="%.4f")
            de_nueva = st.number_input("DE objetivo", format="%.4f", min_value=0.0001)
            guardar_lote = st.form_submit_button("Guardar lote", use_container_width=True)
        if guardar_lote:
            if lote_nuevo:
                try:
                    conn.execute(
                        """INSERT INTO lotes_control
                           (analito_id, nivel, lote, media_objetivo, de_objetivo)
                           VALUES (?, ?, ?, ?, ?)""",
                        (analito_id, nivel_nuevo, lote_nuevo, media_nueva, de_nueva),
                    )
                    conn.commit()
                    st.success("Lote agregado.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.warning("Ese lote/nivel ya existe para este analito.")
            else:
                st.warning("Ingresa un identificador de lote.")

    if lotes_df.empty:
        st.info("Agrega un lote de control para este analito.")
        st.stop()

    lotes_df["etiqueta"] = lotes_df["nivel"] + " — " + lotes_df["lote"]
    lote_sel_label = st.selectbox("Lote de control", lotes_df["etiqueta"])
    lote_row = lotes_df[lotes_df.etiqueta == lote_sel_label].iloc[0]
    lote_id = int(lote_row["id"])
    media = float(lote_row["media_objetivo"])
    de = float(lote_row["de_objetivo"])

    st.markdown(
        f"""
        <div class="tm-section">
          <div class="tm-mini-title">Parámetros objetivo</div>
          <div class="tm-mini-value">μ {media:.4f} {unidad}</div>
          <div class="tm-mini-value">σ {de:.4f} {unidad}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Herramientas del lote", icon="⚙️"):
        n_resultados_lote = conn.execute(
            "SELECT COUNT(*) FROM resultados_cc WHERE lote_control_id = ?", (lote_id,)
        ).fetchone()[0]
        st.caption(f"Este lote contiene {n_resultados_lote} resultado(s).")
        if st.button("Recalcular reglas", key=f"recalc_{lote_id}", use_container_width=True):
            n_actualizados = recalcular_reglas_lote(conn, lote_id, media, de)
            st.success(f"Se recalcularon {n_actualizados} resultado(s).")
            st.rerun()
        confirmar_lote = st.checkbox("Confirmo eliminación permanente", key=f"confirmar_lote_{lote_id}")
        if st.button("Eliminar lote", key=f"del_lote_{lote_id}", disabled=not confirmar_lote, use_container_width=True):
            conn.execute("DELETE FROM resultados_cc WHERE lote_control_id = ?", (lote_id,))
            conn.execute("DELETE FROM lotes_control WHERE id = ?", (lote_id,))
            conn.commit()
            st.success("Lote eliminado.")
            st.rerun()

# Datos del lote seleccionado
resultados_df = cargar_resultados(conn, lote_id)
if not resultados_df.empty:
    resultados_df["fecha"] = pd.to_datetime(resultados_df["fecha"])
    resultados_df = resultados_df.sort_values(["fecha", "id"])

n_total = len(resultados_df)
n_aceptados = int((resultados_df["estado"] == "Aceptado").sum()) if n_total else 0
n_advertencias = int((resultados_df["estado"] == "Advertencia").sum()) if n_total else 0
n_rechazados = int((resultados_df["estado"] == "Rechazado").sum()) if n_total else 0
conformidad = (n_aceptados / n_total * 100) if n_total else 0
ultimo_valor = float(resultados_df.iloc[-1]["valor"]) if n_total else None
ultimo_z = ((ultimo_valor - media) / de) if ultimo_valor is not None and de else None

# Indicadores rápidos
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Resultados", n_total)
m2.metric("Aceptados", n_aceptados, delta=f"{conformidad:.1f}% conformidad" if n_total else None)
m3.metric("Advertencias", n_advertencias)
m4.metric("Rechazados", n_rechazados)
m5.metric("Último z-score", f"{ultimo_z:+.2f}" if ultimo_z is not None else "—")

if n_total:
    ultimo_estado = resultados_df.iloc[-1]["estado"]
    ultimo_reglas = resultados_df.iloc[-1]["reglas_violadas"] or "Sin reglas violadas"
    clase_estado = {"Aceptado": "tm-ok", "Advertencia": "tm-warn", "Rechazado": "tm-bad"}.get(ultimo_estado, "tm-muted-card")
    st.markdown(
        f'<div class="tm-status {clase_estado}">Último resultado: {ultimo_estado} · {ultimo_valor:.4f} {unidad} · {ultimo_reglas}</div>',
        unsafe_allow_html=True,
    )

# Navegación principal
tab_panel, tab_registro, tab_historial, tab_reportes = st.tabs(
    ["📊 Panel de control", "➕ Registrar resultado", "🧾 Historial y acciones", "📥 Reportes"]
)

with tab_panel:
    st.markdown("### Gráfico de Levey–Jennings")
    if resultados_df.empty:
        st.info("Aún no hay resultados registrados para este lote.")
    else:
        fig = go.Figure()
        bandas = [
            (-3, -2, "rgba(192,57,43,0.11)"), (-2, -1, "rgba(199,122,22,0.10)"),
            (-1, 1, "rgba(33,132,90,0.10)"), (1, 2, "rgba(199,122,22,0.10)"),
            (2, 3, "rgba(192,57,43,0.11)"),
        ]
        for z0, z1, color in bandas:
            fig.add_hrect(y0=media + z0 * de, y1=media + z1 * de, fillcolor=color, line_width=0)

        for n, dash, color in [(1, "dot", "#81909A"), (2, "dash", "#A16A15"), (3, "solid", "#A52A20")]:
            fig.add_hline(y=media + n * de, line_dash=dash, line_color=color, line_width=1)
            fig.add_hline(y=media - n * de, line_dash=dash, line_color=color, line_width=1)
        fig.add_hline(y=media, line_color="#26333B", line_width=2, annotation_text="Media")

        color_map = {"Aceptado": "#21845A", "Advertencia": "#D98A1A", "Rechazado": "#C0392B", "Pendiente": "#87949C"}
        symbol_map = {"Aceptado": "circle", "Advertencia": "diamond", "Rechazado": "x", "Pendiente": "circle-open"}
        point_colors = resultados_df["estado"].map(color_map).fillna("#87949C")
        point_symbols = resultados_df["estado"].map(symbol_map).fillna("circle")

        fig.add_trace(go.Scatter(
            x=resultados_df["fecha"], y=resultados_df["valor"], mode="lines+markers",
            marker=dict(color=point_colors, symbol=point_symbols, size=11, line=dict(width=1.5, color="white")),
            line=dict(color="#6FA8BD", width=2.5),
            customdata=resultados_df[["estado", "turno", "operador", "reglas_violadas"]].fillna(""),
            hovertemplate=(
                "<b>%{x|%d-%m-%Y}</b><br>Valor: %{y:.4f} " + unidad +
                "<br>Estado: %{customdata[0]}<br>Turno: %{customdata[1]}" +
                "<br>Operador: %{customdata[2]}<br>Reglas: %{customdata[3]}<extra></extra>"
            ),
            name="Resultados",
        ))
        fig.update_layout(
            height=540, margin=dict(l=20, r=20, t=25, b=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FFFFFF",
            font=dict(color="#24313A", family="Arial, sans-serif"),
            xaxis=dict(title="Fecha", showgrid=False, rangeslider=dict(visible=True, thickness=0.06), tickfont=dict(color="#52616B"), title_font=dict(color="#24313A")),
            yaxis=dict(title=f"Valor ({unidad})", gridcolor="#E8EDF0", tickfont=dict(color="#52616B"), title_font=dict(color="#24313A")),
            hoverlabel=dict(bgcolor="#FFFFFF", font_color="#24313A", bordercolor="#DDE3E7"),
            hovermode="x unified", showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})

        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown("#### Distribución por estado")
            estado_counts = resultados_df["estado"].value_counts().reindex(["Aceptado", "Advertencia", "Rechazado", "Pendiente"]).fillna(0)
            fig_estado = go.Figure(go.Bar(
                x=estado_counts.index, y=estado_counts.values,
                marker_color=[color_map.get(x, "#87949C") for x in estado_counts.index],
                text=estado_counts.values, textposition="auto",
            ))
            fig_estado.update_layout(
                height=300, margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FFFFFF",
                font=dict(color="#24313A", family="Arial, sans-serif"),
                xaxis=dict(tickfont=dict(color="#52616B")),
                yaxis=dict(title="Cantidad", tickfont=dict(color="#52616B"), title_font=dict(color="#24313A"), gridcolor="#E8EDF0"),
            )
            st.plotly_chart(fig_estado, use_container_width=True, config={"displayModeBar": False})
        with c2:
            st.markdown("#### Lectura rápida")
            st.markdown(
                f"""
                <div class="tm-section">
                  <div class="tm-mini-title">Analito</div><div class="tm-mini-value">{analito_sel}</div><br>
                  <div class="tm-mini-title">Lote</div><div class="tm-mini-value">{lote_sel_label}</div><br>
                  <div class="tm-mini-title">Rango ±3 DE</div><div class="tm-mini-value">{media-3*de:.4f} – {media+3*de:.4f} {unidad}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

with tab_registro:
    st.markdown("### Registrar nuevo resultado")
    st.caption("El sistema evaluará automáticamente la serie completa y aplicará las reglas de Westgard.")
    with st.form("form_resultado", clear_on_submit=False):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            fecha_ing = st.date_input("Fecha", value=date.today())
        with col2:
            turno_ing = st.selectbox("Turno", ["Mañana", "Tarde", "Noche"])
        with col3:
            st.text_input("Operador", value=usuario_actual["nombre_completo"], disabled=True)
            operador_ing = usuario_actual["nombre_completo"]
        with col4:
            valor_ing = st.number_input(f"Valor ({unidad})", format="%.4f")

        z_preview = (valor_ing - media) / de if de else 0
        if abs(z_preview) > 3:
            st.markdown(f'<div class="tm-status tm-bad">Vista previa: {z_preview:+.2f} DE · fuera de ±3 DE</div>', unsafe_allow_html=True)
        elif abs(z_preview) > 2:
            st.markdown(f'<div class="tm-status tm-warn">Vista previa: {z_preview:+.2f} DE · zona de advertencia</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="tm-status tm-ok">Vista previa: {z_preview:+.2f} DE · dentro del rango esperado</div>', unsafe_allow_html=True)

        registrar = st.form_submit_button("Registrar y evaluar resultado", type="primary", use_container_width=True)

    if registrar:
        hist_df = cargar_resultados(conn, lote_id)
        valores_previos = hist_df["valor"].tolist() if not hist_df.empty else []
        serie_completa = valores_previos + [valor_ing]
        violadas = evaluar_westgard(serie_completa, media, de)
        hay_rechazo = any(REGLAS[r][1] == "rechazo" for r in violadas)
        estado = "Rechazado" if hay_rechazo else ("Advertencia" if violadas else "Aceptado")
        conn.execute(
            """INSERT INTO resultados_cc
               (lote_control_id, fecha, turno, operador, valor, reglas_violadas, estado)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (lote_id, str(fecha_ing), turno_ing, operador_ing, valor_ing,
             ", ".join(violadas) if violadas else None, estado),
        )
        conn.commit()
        st.session_state["ultimo_registro_mensaje"] = (estado, violadas)
        st.rerun()

    if st.session_state.get("ultimo_registro_mensaje"):
        estado_msg, violadas_msg = st.session_state.pop("ultimo_registro_mensaje")
        if estado_msg == "Rechazado":
            st.error(f"Corrida rechazada. Reglas violadas: {', '.join(violadas_msg)}")
        elif estado_msg == "Advertencia":
            st.warning(f"Resultado con advertencia: {', '.join(violadas_msg)}")
        else:
            st.success("Resultado registrado dentro de control.")

with tab_historial:
    st.markdown("### Historial y acciones correctivas")
    if resultados_df.empty:
        st.info("No hay resultados disponibles.")
    else:
        f1, f2, f3 = st.columns([1, 1, 2])
        with f1:
            filtro_estado = st.multiselect("Estado", ["Aceptado", "Advertencia", "Rechazado", "Pendiente"], default=["Aceptado", "Advertencia", "Rechazado", "Pendiente"])
        with f2:
            filtro_turno = st.multiselect("Turno", sorted(resultados_df["turno"].dropna().unique()), default=sorted(resultados_df["turno"].dropna().unique()))
        with f3:
            buscar_operador = st.text_input("Buscar operador", placeholder="Nombre del operador")

        filtrados = resultados_df[resultados_df["estado"].isin(filtro_estado) & resultados_df["turno"].isin(filtro_turno)].copy()
        if buscar_operador:
            filtrados = filtrados[filtrados["operador"].str.contains(buscar_operador, case=False, na=False)]

        st.dataframe(
            filtrados[["fecha", "turno", "operador", "valor", "estado", "reglas_violadas", "accion_correctiva"]],
            use_container_width=True, hide_index=True,
            column_config={
                "fecha": st.column_config.DatetimeColumn("Fecha", format="DD-MM-YYYY"),
                "valor": st.column_config.NumberColumn(f"Valor ({unidad})", format="%.4f"),
                "estado": st.column_config.TextColumn("Estado"),
            },
        )

        no_conformes = resultados_df[resultados_df["estado"].isin(["Rechazado", "Advertencia"])].sort_values("fecha", ascending=False)
        st.markdown("#### No conformidades y seguimiento")
        if no_conformes.empty:
            st.success("No hay advertencias ni rechazos pendientes de revisión.")
        for _, row in no_conformes.iterrows():
            icono = "⛔" if row["estado"] == "Rechazado" else "⚠️"
            with st.expander(f"{icono} {row['fecha'].date()} · {row['estado']} · {row['valor']:.4f} {unidad}"):
                st.caption(f"Operador: {row['operador']} · Turno: {row['turno']} · Reglas: {row['reglas_violadas']}")
                nueva_accion = st.text_area("Acción correctiva / observación", value=row["accion_correctiva"] or "", key=f"accion_{row['id']}")
                ca, cb = st.columns([3, 1])
                with ca:
                    if st.button("Guardar acción", key=f"btn_accion_{row['id']}", use_container_width=True):
                        conn.execute("UPDATE resultados_cc SET accion_correctiva = ? WHERE id = ?", (nueva_accion, int(row["id"])))
                        conn.commit()
                        st.success("Acción guardada.")
                        st.rerun()
                with cb:
                    if st.button("Eliminar", key=f"del_result_{row['id']}", use_container_width=True):
                        conn.execute("DELETE FROM resultados_cc WHERE id = ?", (int(row["id"]),))
                        conn.commit()
                        st.rerun()

        with st.expander("Eliminación masiva de resultados", icon="🗑️"):
            tabla_editable = resultados_df[["id", "fecha", "turno", "operador", "valor", "estado", "reglas_violadas", "accion_correctiva"]].copy()
            tabla_editable.insert(0, "Eliminar", False)
            tabla_resultado = st.data_editor(
                tabla_editable, use_container_width=True, hide_index=True,
                disabled=["id", "fecha", "turno", "operador", "valor", "estado", "reglas_violadas", "accion_correctiva"],
                key="editor_resultados",
            )
            ids_a_eliminar = tabla_resultado.loc[tabla_resultado["Eliminar"], "id"].tolist()
            if ids_a_eliminar:
                st.warning(f"Se eliminarán {len(ids_a_eliminar)} resultado(s).")
                if st.button("Confirmar eliminación", key="confirmar_delete_masivo", type="primary"):
                    conn.executemany("DELETE FROM resultados_cc WHERE id = ?", [(int(i),) for i in ids_a_eliminar])
                    conn.commit()
                    st.rerun()

with tab_reportes:
    st.markdown("### Reportes y exportación")
    if resultados_df.empty:
        st.info("Registra resultados antes de generar reportes.")
    else:
        st.caption("Exporta el análisis seleccionado para respaldo, auditoría o revisión del supervisor.")
        col_pdf, col_csv = st.columns(2)
        with col_pdf:
            pdf_buffer = generar_pdf_reporte(analito_sel, lote_sel_label, media, de, unidad, resultados_df)
            st.download_button(
                "Descargar reporte PDF", data=pdf_buffer,
                file_name=f"reporte_cc_{analito_sel}_{lote_sel_label}.pdf".replace(" ", "_"),
                mime="application/pdf", use_container_width=True,
            )
        with col_csv:
            csv_data = resultados_df[["fecha", "turno", "operador", "valor", "estado", "reglas_violadas", "accion_correctiva"]].to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Descargar base CSV", data=csv_data,
                file_name=f"tabla_cc_{analito_sel}_{lote_sel_label}.csv".replace(" ", "_"),
                mime="text/csv", use_container_width=True,
            )

        st.markdown("#### Resumen del lote")
        resumen = pd.DataFrame({
            "Indicador": ["Analito", "Lote", "Media objetivo", "DE objetivo", "Resultados", "Aceptados", "Advertencias", "Rechazados", "Conformidad"],
            "Valor": [analito_sel, lote_sel_label, f"{media:.4f} {unidad}", f"{de:.4f} {unidad}", n_total, n_aceptados, n_advertencias, n_rechazados, f"{conformidad:.1f}%"],
        })
        st.dataframe(resumen, use_container_width=True, hide_index=True)

conn.close()
