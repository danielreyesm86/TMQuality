"""
TMQuality - Capa de datos PostgreSQL / Supabase.

Etapa 1 de la modularización:
- conexión PostgreSQL
- helpers SQL
- inicialización/migraciones
- contexto de organización

Este módulo no contiene lógica de UI de negocio.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Iterable, Optional

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st

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
        return psycopg2.connect(
            get_database_url(),
            connect_timeout=8,
            application_name="TMQuality",
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
        )
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


def _column_exists(conn, table: str, column: str) -> bool:
    row = fetchone(
        conn,
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s AND column_name=%s
        ) AS ok
        """,
        (table, column),
    )
    return bool(row and row.get("ok"))


def _table_exists(conn, table: str) -> bool:
    row = fetchone(
        conn,
        "SELECT to_regclass(%s) IS NOT NULL AS ok",
        (f"public.{table}",),
    )
    return bool(row and row.get("ok"))


def init_db(conn):
    """Inicializa TMQuality sin bloquear los reruns de Streamlit.

    La versión 3.0 original ejecutaba ALTER TABLE, constraints y cambios de RLS
    en cada rerun. PostgreSQL puede requerir locks exclusivos para esas
    operaciones, por lo que una sesión concurrente podía dejar la app
    aparentemente cargando indefinidamente. Esta versión:
      * crea solo tablas que aún no existen;
      * agrega únicamente columnas realmente faltantes;
      * usa lock_timeout/statement_timeout cortos;
      * no modifica RLS ni privilegios durante el arranque normal.
    """
    try:
        execute(conn, "SET lock_timeout TO '3s'")
        execute(conn, "SET statement_timeout TO '12s'")
    except Exception:
        conn.rollback()

    ddl = [
        """
        CREATE TABLE IF NOT EXISTS organizaciones (
            id BIGSERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            codigo TEXT UNIQUE,
            rut TEXT,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_modificacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS analitos (
            id BIGSERIAL PRIMARY KEY,
            organizacion_id BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT,
            nombre TEXT NOT NULL,
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
            organizacion_id BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT,
            nombre TEXT NOT NULL,
            fabricante TEXT,
            modelo TEXT,
            numero_serie TEXT,
            area TEXT,
            ubicacion TEXT,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS lotes_control (
            id BIGSERIAL PRIMARY KEY,
            organizacion_id BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT,
            analito_id BIGINT NOT NULL REFERENCES analitos(id) ON DELETE CASCADE,
            nivel TEXT NOT NULL,
            lote TEXT NOT NULL,
            fabricante TEXT,
            material_control TEXT,
            fecha_vencimiento DATE,
            limite_inferior DOUBLE PRECISION,
            nivel_medio DOUBLE PRECISION,
            limite_superior DOUBLE PRECISION,
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
            organizacion_id BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT,
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
            organizacion_id BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT,
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
            organizacion_id BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT,
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
        try:
            execute(conn, sql)
        except Exception as exc:
            conn.rollback()
            st.error("No fue posible verificar/crear el esquema de TMQuality.")
            st.code(str(exc))
            st.stop()

    # Migraciones idempotentes: solo se ejecuta ALTER TABLE si falta la columna.
    missing_columns = [
        ("analitos", "organizacion_id", "BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT"),
        ("equipos", "organizacion_id", "BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT"),
        ("lotes_control", "organizacion_id", "BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT"),
        ("usuarios", "organizacion_id", "BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT"),
        ("resultados_cc", "organizacion_id", "BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT"),
        ("auditoria", "organizacion_id", "BIGINT REFERENCES organizaciones(id) ON DELETE RESTRICT"),
        ("analitos", "metodologia", "TEXT"),
        ("analitos", "error_total_permitido", "DOUBLE PRECISION"),
        ("analitos", "activo", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("analitos", "fecha_creacion", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("lotes_control", "fabricante", "TEXT"),
        ("lotes_control", "material_control", "TEXT"),
        ("lotes_control", "fecha_vencimiento", "DATE"),
        ("lotes_control", "limite_inferior", "DOUBLE PRECISION"),
        ("lotes_control", "nivel_medio", "DOUBLE PRECISION"),
        ("lotes_control", "limite_superior", "DOUBLE PRECISION"),
        ("lotes_control", "fecha_creacion", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("usuarios", "cambio_password_requerido", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("usuarios", "intentos_fallidos", "INTEGER NOT NULL DEFAULT 0"),
        ("usuarios", "bloqueado_hasta", "TIMESTAMP"),
        ("usuarios", "ultimo_acceso", "TIMESTAMP"),
        ("usuarios", "fecha_modificacion", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("resultados_cc", "equipo_id", "BIGINT REFERENCES equipos(id) ON DELETE SET NULL"),
        ("resultados_cc", "usuario_id", "BIGINT REFERENCES usuarios(id) ON DELETE SET NULL"),
        ("resultados_cc", "hora", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("resultados_cc", "z_score", "DOUBLE PRECISION"),
        ("resultados_cc", "comentarios", "TEXT"),
        ("resultados_cc", "revisado_por", "BIGINT REFERENCES usuarios(id) ON DELETE SET NULL"),
        ("resultados_cc", "fecha_revision", "TIMESTAMP"),
        ("resultados_cc", "fecha_creacion", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("resultados_cc", "fecha_modificacion", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]

    for table, column, definition in missing_columns:
        try:
            if not _column_exists(conn, table, column):
                execute(conn, f'ALTER TABLE public.{table} ADD COLUMN {column} {definition}')
        except Exception as exc:
            conn.rollback()
            st.error(f"La migración de la columna {table}.{column} no pudo completarse.")
            st.code(str(exc))
            st.info("Espera unos segundos, reinicia la app y vuelve a intentarlo. Si persiste, ejecuta la migración SQL una sola vez desde Supabase.")
            st.stop()

    # Completar los nuevos límites para lotes históricos. Se interpreta el
    # intervalo inferior-superior como ±3 DE alrededor del nivel medio.
    try:
        execute(
            conn,
            """
            UPDATE lotes_control
            SET nivel_medio = COALESCE(nivel_medio, media_objetivo),
                limite_inferior = COALESCE(limite_inferior, media_objetivo - 3 * de_objetivo),
                limite_superior = COALESCE(limite_superior, media_objetivo + 3 * de_objetivo)
            WHERE nivel_medio IS NULL
               OR limite_inferior IS NULL
               OR limite_superior IS NULL
            """,
        )
    except Exception as exc:
        conn.rollback()
        st.error("No fue posible completar los límites históricos de los lotes.")
        st.code(str(exc))
        st.stop()

    # -----------------------------------------------------------------
    # Migración multiinstitución inicial.
    # Crea una organización base una sola vez y asigna todos los datos
    # históricos que todavía no tengan organizacion_id.
    # -----------------------------------------------------------------
    try:
        org = fetchone(conn, "SELECT id FROM organizaciones ORDER BY id LIMIT 1")
        if not org:
            try:
                default_name = str(st.secrets["organization"]["name"])
            except Exception:
                default_name = "Laboratorio principal"
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO organizaciones(nombre, codigo)
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (default_name, "ORG-001"),
                )
                default_org_id = int(cur.fetchone()[0])
            conn.commit()
        else:
            default_org_id = int(org["id"])

        for table in ["usuarios", "equipos", "analitos", "lotes_control", "resultados_cc", "auditoria"]:
            execute(
                conn,
                f"UPDATE {table} SET organizacion_id=%s WHERE organizacion_id IS NULL",
                (default_org_id,),
            )

        # Retirar restricciones globales heredadas que impedirían que dos
        # laboratorios usen el mismo nombre de analito o número de serie.
        old_constraints = [
            ("analitos", "analitos_nombre_key"),
            ("equipos", "equipos_numero_serie_key"),
        ]
        for table, constraint in old_constraints:
            row = fetchone(
                conn,
                """
                SELECT EXISTS(
                    SELECT 1 FROM pg_constraint
                    WHERE conname=%s
                ) AS ok
                """,
                (constraint,),
            )
            if row and row.get("ok"):
                execute(conn, f'ALTER TABLE {table} DROP CONSTRAINT "{constraint}"')

    except Exception as exc:
        conn.rollback()
        st.error("No fue posible completar la migración multiinstitución.")
        st.code(str(exc))
        st.stop()

    index_sql = [
        "CREATE INDEX IF NOT EXISTS idx_usuarios_org ON usuarios(organizacion_id)",
        "CREATE INDEX IF NOT EXISTS idx_equipos_org ON equipos(organizacion_id)",
        "CREATE INDEX IF NOT EXISTS idx_analitos_org ON analitos(organizacion_id)",
        "CREATE INDEX IF NOT EXISTS idx_lotes_org ON lotes_control(organizacion_id)",
        "CREATE INDEX IF NOT EXISTS idx_resultados_org ON resultados_cc(organizacion_id)",
        "CREATE INDEX IF NOT EXISTS idx_auditoria_org ON auditoria(organizacion_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_analitos_org_nombre ON analitos(organizacion_id, lower(nombre))",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_equipos_org_serie ON equipos(organizacion_id, numero_serie) WHERE numero_serie IS NOT NULL AND numero_serie <> ''",
        "CREATE INDEX IF NOT EXISTS idx_lotes_analito ON lotes_control(analito_id)",
        "CREATE INDEX IF NOT EXISTS idx_resultados_lote_fecha ON resultados_cc(lote_control_id, fecha)",
        "CREATE INDEX IF NOT EXISTS idx_resultados_org_lote_fecha ON resultados_cc(organizacion_id, lote_control_id, fecha)",
        "CREATE INDEX IF NOT EXISTS idx_resultados_equipo ON resultados_cc(equipo_id)",
        "CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha_hora DESC)",
        "CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria(usuario_id)",
    ]
    for sql in index_sql:
        try:
            execute(conn, sql)
        except Exception:
            conn.rollback()

    # No modificar RLS, GRANT/REVOKE ni constraints globales durante un rerun.
    # Esas tareas administrativas deben hacerse una sola vez desde Supabase.

@st.cache_resource(show_spinner=False)
def ensure_database_ready(database_url: str) -> bool:
    """Ejecuta migraciones/verificaciones una sola vez por proceso Streamlit.

    Antes, init_db() corría en cada interacción (cada cambio de selectbox, botón
    o pestaña), generando decenas de consultas a information_schema.
    """
    conn = psycopg2.connect(
        database_url,
        connect_timeout=8,
        application_name="TMQuality-schema",
    )
    try:
        init_db(conn)
        return True
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# ORGANIZACIONES / MULTIINSTITUCIÓN
# -----------------------------------------------------------------------------
def current_org_id(user: Optional[dict] = None) -> Optional[int]:
    user = user or st.session_state.get("user")
    if not user:
        return None
    value = user.get("organizacion_id")
    return int(value) if value is not None else None


def current_organization(conn, user: Optional[dict] = None) -> Optional[dict]:
    org_id = current_org_id(user)
    if org_id is None:
        return None
    return fetchone(
        conn,
        "SELECT * FROM organizaciones WHERE id=%s AND activo=TRUE",
        (org_id,),
    )


