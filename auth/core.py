"""TMQuality - Seguridad y gestión de usuarios."""
from __future__ import annotations
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional
import pandas as pd
import streamlit as st
from database import execute, fetchone, fetchall_df, current_org_id

# Parámetros propios del motor de autenticación.
PBKDF2_ITERATIONS = 260_000
LEGACY_PBKDF2_ITERATIONS = 100_000

def hash_password(password: str, salt_hex: Optional[str] = None, iterations: int = PBKDF2_ITERATIONS) -> tuple[str, str]:
    """Genera PBKDF2-SHA256.

    ``iterations`` permite validar cuentas creadas por versiones anteriores de
    TMQuality y migrarlas automáticamente al esquema actual.
    """
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
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
        INSERT INTO auditoria (organizacion_id, usuario_id, username, rol, accion, entidad, entidad_id, detalle, exito)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            current_org_id(user),
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

    org = fetchone(
        conn,
        "SELECT id, nombre, activo FROM organizaciones WHERE id=%s",
        (row.get("organizacion_id"),),
    )
    if not org or not org.get("activo"):
        audit(conn, "LOGIN_FALLIDO", "usuarios", row["id"], "Organización inactiva", False, row)
        return None, "La organización asociada a esta cuenta está inactiva."

    if row.get("bloqueado_hasta") and row["bloqueado_hasta"] > datetime.now():
        return None, f"Cuenta temporalmente bloqueada hasta {row['bloqueado_hasta']:%H:%M}."

    # Primero valida con el esquema actual (260.000 iteraciones).
    candidate, _ = hash_password(password, row["salt"], PBKDF2_ITERATIONS)
    password_valid = hmac.compare_digest(candidate, row["password_hash"])
    migrated_legacy_hash = False

    # Compatibilidad con usuarios creados por TMQuality 1.x / 2.x, que usaban
    # PBKDF2-SHA256 con 100.000 iteraciones. Si la contraseña coincide, se
    # re-hashea inmediatamente con el esquema nuevo sin que el usuario tenga
    # que cambiarla ni que un administrador intervenga.
    if not password_valid:
        legacy_candidate, _ = hash_password(password, row["salt"], LEGACY_PBKDF2_ITERATIONS)
        password_valid = hmac.compare_digest(legacy_candidate, row["password_hash"])
        migrated_legacy_hash = password_valid

    if not password_valid:
        intentos = int(row.get("intentos_fallidos") or 0) + 1
        bloqueado = datetime.now() + timedelta(minutes=15) if intentos >= 5 else None
        execute(conn, "UPDATE usuarios SET intentos_fallidos=%s, bloqueado_hasta=%s WHERE id=%s", (intentos, bloqueado, row["id"]))
        audit(conn, "LOGIN_FALLIDO", "usuarios", row["id"], f"Contraseña incorrecta. Intento {intentos}", False, row)
        return None, "Credenciales inválidas." if not bloqueado else "Cuenta bloqueada 15 minutos por intentos fallidos."

    if migrated_legacy_hash:
        new_hash, new_salt = hash_password(password)
        execute(
            conn,
            "UPDATE usuarios SET password_hash=%s, salt=%s WHERE id=%s",
            (new_hash, new_salt, row["id"]),
        )
        audit(conn, "HASH_PASSWORD_ACTUALIZADO", "usuarios", row["id"],
              "Hash de contraseña migrado automáticamente al esquema PBKDF2 actual", True, row)

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
            INSERT INTO usuarios (organizacion_id, nombre_completo, username, password_hash, salt, rol, activo, cambio_password_requerido)
            VALUES (%s,%s,%s,%s,%s,%s,TRUE,%s) RETURNING id
            """,
            (
                current_org_id(actor)
                or int(fetchone(conn, "SELECT id FROM organizaciones ORDER BY id LIMIT 1")["id"]),
                nombre.strip(), username.strip(), ph, salt, rol, require_change
            ),
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


def active_admin_count(conn, org_id: Optional[int] = None) -> int:
    org_id = org_id or current_org_id()
    if org_id is None:
        row = fetchone(conn, "SELECT COUNT(*) AS n FROM usuarios WHERE rol='Administrador' AND activo=TRUE")
    else:
        row = fetchone(
            conn,
            "SELECT COUNT(*) AS n FROM usuarios WHERE organizacion_id=%s AND rol='Administrador' AND activo=TRUE",
            (org_id,),
        )
    return int(row["n"] if row else 0)



def create_organization_with_admin(
    conn,
    organization_name: str,
    organization_code: str,
    organization_rut: str,
    admin_name: str,
    admin_username: str,
    temporary_password: str,
) -> tuple[int, int]:
    """Crea una organización y su primer Administrador en una sola transacción."""
    organization_name = organization_name.strip()
    organization_code = organization_code.strip().upper()
    organization_rut = organization_rut.strip()
    admin_name = admin_name.strip()
    admin_username = admin_username.strip()

    if not organization_name:
        raise ValueError("El nombre de la organización es obligatorio.")
    if not organization_code:
        raise ValueError("El código de la organización es obligatorio.")
    if not re.fullmatch(r"[A-Z0-9_-]{2,30}", organization_code):
        raise ValueError("El código solo puede contener letras, números, guion y guion bajo.")
    if not admin_name or not admin_username:
        raise ValueError("Debes completar el nombre y usuario del Administrador.")

    ok, msg = password_ok(temporary_password)
    if not ok:
        raise ValueError(msg)

    password_hash, salt = hash_password(temporary_password)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO organizaciones(nombre, codigo, rut, activo)
                VALUES (%s,%s,%s,TRUE)
                RETURNING id
                """,
                (
                    organization_name,
                    organization_code,
                    organization_rut or None,
                ),
            )
            organization_id = int(cur.fetchone()[0])

            cur.execute(
                """
                INSERT INTO usuarios(
                    organizacion_id,nombre_completo,username,password_hash,salt,
                    rol,activo,cambio_password_requerido
                )
                VALUES(%s,%s,%s,%s,%s,'Administrador',TRUE,TRUE)
                RETURNING id
                """,
                (
                    organization_id,
                    admin_name,
                    admin_username,
                    password_hash,
                    salt,
                ),
            )
            admin_id = int(cur.fetchone()[0])

            cur.execute(
                """
                INSERT INTO auditoria(
                    organizacion_id,usuario_id,username,rol,accion,
                    entidad,entidad_id,detalle,exito
                )
                VALUES(%s,%s,%s,'Administrador','ORGANIZACION_CREADA',
                       'organizaciones',%s,%s,TRUE)
                """,
                (
                    organization_id,
                    admin_id,
                    admin_username,
                    str(organization_id),
                    f"{organization_name} · código {organization_code}",
                ),
            )

        conn.commit()
        return organization_id, admin_id
    except Exception:
        conn.rollback()
        raise


def platform_admin_ui(conn):
    """Panel propietario para crear y activar/desactivar instituciones."""
    st.markdown(
        f"""
        <div class="tmq-auth-wrap">
            <div style="text-align:center;margin-bottom:10px;">
                <img src="data:image/png;base64,{LOGO_FULL_B64}" style="max-width:170px;width:100%;height:auto;">
            </div>
            <div class="tmq-auth-title">Administración de <span>plataforma</span></div>
            <div class="tmq-auth-subtitle">Alta y gestión de organizaciones · TMQuality</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    try:
        token_expected = str(st.secrets["platform"]["admin_token"])
    except Exception:
        st.error("Falta configurar `[platform].admin_token` en los Secrets de Streamlit.")
        if st.button("Volver al inicio de sesión", use_container_width=True):
            st.session_state.pop("platform_mode", None)
            st.session_state.pop("platform_authenticated", None)
            st.rerun()
        st.stop()

    if not st.session_state.get("platform_authenticated"):
        _, center, _ = st.columns([1, 1.15, 1])
        with center:
            with st.form("platform_auth"):
                st.markdown("#### Acceso del propietario")
                token = st.text_input("Token de plataforma", type="password")
                submitted = st.form_submit_button(
                    "Ingresar al panel",
                    type="primary",
                    use_container_width=True,
                )
            if submitted:
                if secrets.compare_digest(token, token_expected):
                    st.session_state.platform_authenticated = True
                    st.rerun()
                else:
                    st.error("Token de plataforma incorrecto.")

            if st.button("← Volver al inicio de sesión", use_container_width=True):
                st.session_state.pop("platform_mode", None)
                st.rerun()
        st.stop()

    top1, top2 = st.columns([4, 1])
    with top1:
        st.subheader("Organizaciones")
        st.caption(
            "Este panel pertenece al propietario de TMQuality. "
            "Los Administradores de laboratorio no tienen acceso a esta sección."
        )
    with top2:
        if st.button("Cerrar panel", use_container_width=True):
            st.session_state.pop("platform_authenticated", None)
            st.session_state.pop("platform_mode", None)
            st.rerun()

    orgs = fetchall_df(
        conn,
        """
        SELECT
            o.id,
            o.nombre,
            o.codigo,
            o.rut,
            o.activo,
            o.fecha_creacion,
            COUNT(u.id) FILTER (WHERE u.activo=TRUE) AS usuarios_activos,
            COUNT(u.id) FILTER (
                WHERE u.activo=TRUE AND u.rol='Administrador'
            ) AS administradores_activos
        FROM organizaciones o
        LEFT JOIN usuarios u ON u.organizacion_id=o.id
        GROUP BY o.id,o.nombre,o.codigo,o.rut,o.activo,o.fecha_creacion
        ORDER BY o.fecha_creacion DESC, o.id DESC
        """
    )

    if not orgs.empty:
        show = orgs.copy()
        show["estado"] = show["activo"].map({True: "Activa", False: "Inactiva"})
        st.dataframe(
            show[
                [
                    "nombre","codigo","rut","estado",
                    "usuarios_activos","administradores_activos","fecha_creacion"
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.markdown("### Dar de alta un laboratorio")

    with st.form("new_organization", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            organization_name = st.text_input(
                "Nombre del laboratorio / institución",
                placeholder="Ej.: Laboratorio Central Concepción",
            )
            organization_code = st.text_input(
                "Código interno",
                placeholder="Ej.: LAB-CONCE-01",
                help="Será único dentro de TMQuality.",
            )
            organization_rut = st.text_input(
                "RUT (opcional)",
                placeholder="Ej.: 76.123.456-7",
            )
        with c2:
            admin_name = st.text_input(
                "Nombre del Administrador inicial",
                placeholder="Ej.: Ana Pérez",
            )
            admin_username = st.text_input(
                "Usuario inicial",
                placeholder="Ej.: aperez.lab",
                help="Por ahora el nombre de usuario debe ser único en toda la plataforma.",
            )
            temporary_password = st.text_input(
                "Contraseña temporal",
                type="password",
                help="El Administrador deberá cambiarla en su primer ingreso.",
            )

        create_org = st.form_submit_button(
            "Crear organización y Administrador",
            type="primary",
            use_container_width=True,
        )

    if create_org:
        try:
            organization_id, admin_id = create_organization_with_admin(
                conn,
                organization_name,
                organization_code,
                organization_rut,
                admin_name,
                admin_username,
                temporary_password,
            )
            st.success(
                f"Organización creada correctamente. ID {organization_id}. "
                "El Administrador deberá cambiar su contraseña al ingresar."
            )
            st.rerun()
        except IntegrityError as exc:
            conn.rollback()
            message = str(exc).lower()
            if "organizaciones_codigo_key" in message or "codigo" in message:
                st.error("Ya existe una organización con ese código.")
            elif "usuarios_username_key" in message or "username" in message:
                st.error("Ese nombre de usuario ya está siendo utilizado.")
            else:
                st.error("No fue posible crear la organización por una restricción de datos.")
        except Exception as exc:
            conn.rollback()
            st.error(str(exc))

    if not orgs.empty:
        st.divider()
        st.markdown("### Estado de una organización")

        org_map = {
            f"{r.nombre} · {r.codigo or 'sin código'}": int(r.id)
            for r in orgs.itertuples()
        }
        selected_label = st.selectbox(
            "Organización",
            list(org_map.keys()),
            key="platform_org_select",
        )
        selected_id = org_map[selected_label]
        selected = orgs[orgs["id"] == selected_id].iloc[0].to_dict()

        st.caption(
            "Desactivar una organización bloquea el ingreso de todos sus usuarios, "
            "pero no elimina ningún dato."
        )

        label = "Desactivar organización" if selected["activo"] else "Reactivar organización"
        if st.button(label, use_container_width=True):
            new_state = not bool(selected["activo"])
            execute(
                conn,
                """
                UPDATE organizaciones
                SET activo=%s, fecha_modificacion=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                (new_state, selected_id),
            )
            st.success(
                "Organización reactivada."
                if new_state
                else "Organización desactivada. Sus datos se conservan."
            )
            st.rerun()


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

