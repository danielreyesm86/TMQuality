"""Pantalla y operaciones de lotes de control."""
from __future__ import annotations
from datetime import date, timedelta
from io import BytesIO
import pandas as pd
import streamlit as st
from psycopg2 import IntegrityError
from auth import audit
from database import current_org_id, fetchall_df, fetchone, control_level_names

def _active_analytes(conn):
    org_id = current_org_id()
    if org_id is None:
        return pd.DataFrame()
    return fetchall_df(
        conn,
        "SELECT * FROM analitos WHERE organizacion_id=%s AND activo=TRUE ORDER BY nombre",
        (org_id,),
    )

def archive_lot(conn, lot_id: int, user: dict) -> None:
    row = fetchone(
        conn,
        """SELECT l.id,l.lote,l.nivel,a.nombre AS analito,
                  (SELECT COUNT(*) FROM resultados_cc r WHERE r.lote_control_id=l.id) AS resultados
           FROM lotes_control l
           JOIN analitos a ON a.id=l.analito_id
           WHERE l.id=%s AND l.organizacion_id=%s""",
        (lot_id, current_org_id(user)),
    )
    if not row:
        raise ValueError("El lote no existe o no pertenece a tu organización.")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE lotes_control SET vigente=FALSE WHERE id=%s AND organizacion_id=%s",
            (lot_id, current_org_id(user)),
        )
    conn.commit()
    audit(conn,"LOTE_ARCHIVADO","lotes_control",lot_id,
          f"{row['analito']} · {row['nivel']} · {row['lote']} · {row['resultados']} resultado(s) conservados")

def restore_lot(conn, lot_id: int, user: dict) -> None:
    row = fetchone(
        conn,
        """SELECT l.id,l.lote,l.nivel,a.nombre AS analito
           FROM lotes_control l
           JOIN analitos a ON a.id=l.analito_id
           WHERE l.id=%s AND l.organizacion_id=%s""",
        (lot_id, current_org_id(user)),
    )
    if not row:
        raise ValueError("El lote no existe o no pertenece a tu organización.")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE lotes_control SET vigente=TRUE WHERE id=%s AND organizacion_id=%s",
            (lot_id, current_org_id(user)),
        )
    conn.commit()
    audit(conn,"LOTE_RESTAURADO","lotes_control",lot_id,
          f"{row['analito']} · {row['nivel']} · {row['lote']}")

def _lot_backup_excel(conn, lot_id: int, user: dict) -> bytes:
    """Genera un respaldo Excel del lote y sus resultados antes de eliminar."""
    org_id = current_org_id(user)

    lot_df = fetchall_df(
        conn,
        """
        SELECT l.*, a.nombre AS analito, a.unidad, a.metodologia
        FROM lotes_control l
        JOIN analitos a ON a.id=l.analito_id
        WHERE l.id=%s AND l.organizacion_id=%s
        """,
        (lot_id, org_id),
    )

    results_df = fetchall_df(
        conn,
        """
        SELECT r.*
        FROM resultados_cc r
        JOIN lotes_control l ON l.id=r.lote_control_id
        WHERE r.lote_control_id=%s AND l.organizacion_id=%s
        ORDER BY r.fecha, r.id
        """,
        (lot_id, org_id),
    )

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        lot_df.to_excel(writer, sheet_name="Lote", index=False)
        results_df.to_excel(writer, sheet_name="Resultados", index=False)

    return output.getvalue()


def delete_lot(conn, lot_id: int, user: dict) -> None:
    """Elimina definitivamente un lote y sus resultados, dejando auditoría."""
    row = fetchone(
        conn,
        """
        SELECT l.id,l.lote,l.nivel,a.nombre AS analito,
               (SELECT COUNT(*) FROM resultados_cc r
                WHERE r.lote_control_id=l.id) AS resultados
        FROM lotes_control l
        JOIN analitos a ON a.id=l.analito_id
        WHERE l.id=%s AND l.organizacion_id=%s
        """,
        (lot_id, current_org_id(user)),
    )
    if not row:
        raise ValueError("El lote no existe o no pertenece a tu organización.")

    detail = (
        f"{row['analito']} · {row['nivel']} · {row['lote']} · "
        f"{row['resultados']} resultado(s)"
    )

    with conn.cursor() as cur:
        # Se eliminan primero los resultados para respetar integridad referencial.
        cur.execute(
            """
            DELETE FROM resultados_cc
            WHERE lote_control_id=%s
              AND EXISTS (
                  SELECT 1 FROM lotes_control l
                  WHERE l.id=%s AND l.organizacion_id=%s
              )
            """,
            (lot_id, lot_id, current_org_id(user)),
        )
        cur.execute(
            "DELETE FROM lotes_control WHERE id=%s AND organizacion_id=%s",
            (lot_id, current_org_id(user)),
        )
    conn.commit()

    # Auditoría posterior con descripción suficiente para trazabilidad.
    audit(
        conn,
        "LOTE_ELIMINADO",
        "lotes_control",
        lot_id,
        detail + " · eliminación permanente confirmada por el usuario",
    )


def module_lots(conn, user):
    st.subheader("Lotes de control")
    st.caption("Los niveles disponibles dependen de la configuración de cada analito.")

    analytes_all = _active_analytes(conn)
    if analytes_all.empty:
        st.info("Primero debes crear al menos un analito.")
        return

    lots_df = fetchall_df(
        conn,
        """
        SELECT l.id,a.nombre AS analito,a.unidad,l.analito_id,l.nivel,l.lote,
               l.fabricante,l.material_control,l.limite_inferior,l.nivel_medio,
               l.limite_superior,l.media_objetivo,l.de_objetivo,l.fecha_vencimiento,
               l.vigente,l.fecha_creacion,
               (SELECT COUNT(*) FROM resultados_cc r WHERE r.lote_control_id=l.id) AS resultados
        FROM lotes_control l
        JOIN analitos a ON a.id=l.analito_id AND a.organizacion_id=l.organizacion_id
        WHERE l.organizacion_id=%s
        ORDER BY a.nombre,l.nivel,l.fecha_creacion DESC
        """,
        (current_org_id(user),),
    )

    if not lots_df.empty:
        view = lots_df.copy()
        view["fecha_vencimiento"] = pd.to_datetime(view["fecha_vencimiento"], errors="coerce")
        view["estado"] = view["vigente"].map({True:"Vigente",False:"Archivado"})
        expired = view["fecha_vencimiento"].notna() & (view["fecha_vencimiento"].dt.date < date.today()) & view["vigente"]
        view.loc[expired,"estado"] = "Vencido"
        st.dataframe(
            view[["analito","nivel","lote","limite_inferior","nivel_medio","limite_superior","de_objetivo","fecha_vencimiento","resultados","estado"]],
            use_container_width=True, hide_index=True
        )

    if user["rol"] != "Administrador":
        st.info("La creación, archivado y restauración de lotes está disponible para Administradores.")
        return

    st.divider()
    st.markdown("#### Crear nuevo lote")
    amap = {
        f"{r.nombre} · {r.unidad}":{"id":int(r.id),"nombre":str(r.nombre)}
        for r in analytes_all.itertuples()
    }
    labels = list(amap.keys())
    default_index = 0
    preferred = st.session_state.get("new_lot_analyte_id")
    if preferred:
        for i,label in enumerate(labels):
            if amap[label]["id"] == int(preferred):
                default_index=i
                break

    selected_label = st.selectbox("Analito", labels, index=default_index, key="lot_new_analyte")
    selected = amap[selected_label]
    levels = control_level_names(conn, selected["id"], only_active=True)

    if not levels:
        st.error("Este analito no tiene niveles activos. Configúralos en Administración → Analitos.")
        return

    st.caption("Niveles configurados: " + " · ".join(levels))

    with st.form("new_lot_main", clear_on_submit=True):
        c1,c2 = st.columns(2)
        with c1:
            level = st.selectbox("Nivel del control", levels)
            lot_code = st.text_input("Código / número de lote")
            mfg = st.text_input("Fabricante")
            material = st.text_input("Material de control")
            expiry = st.date_input("Fecha de vencimiento", value=date.today()+timedelta(days=365))
        with c2:
            lower = st.number_input("Límite inferior", value=0.7000, step=0.0001, format="%.4f")
            middle = st.number_input("Nivel medio / valor objetivo", value=1.0000, step=0.0001, format="%.4f")
            upper = st.number_input("Límite superior", value=1.3000, step=0.0001, format="%.4f")
            deactivate_previous = st.checkbox("Desactivar lotes vigentes del mismo analito y nivel")
        create_lot = st.form_submit_button("Crear lote de control", type="primary", use_container_width=True)

    if create_lot:
        if not lot_code.strip():
            st.error("Debes ingresar el código o número de lote.")
        elif not (lower < middle < upper):
            st.error("Debe cumplirse: límite inferior < nivel medio < límite superior.")
        else:
            sd = (float(upper)-float(lower))/6.0
            try:
                with conn.cursor() as cur:
                    if deactivate_previous:
                        cur.execute(
                            """UPDATE lotes_control SET vigente=FALSE
                               WHERE organizacion_id=%s AND analito_id=%s AND nivel=%s AND vigente=TRUE""",
                            (current_org_id(user),selected["id"],level)
                        )
                    cur.execute(
                        """INSERT INTO lotes_control(
                           organizacion_id,analito_id,nivel,lote,fabricante,material_control,
                           fecha_vencimiento,limite_inferior,nivel_medio,limite_superior,
                           media_objetivo,de_objetivo,vigente)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING id""",
                        (current_org_id(user),selected["id"],level,lot_code.strip(),
                         mfg.strip() or None,material.strip() or None,expiry,
                         float(lower),float(middle),float(upper),float(middle),sd)
                    )
                    lid=cur.fetchone()[0]
                conn.commit()
                audit(conn,"LOTE_CREADO","lotes_control",lid,
                      f"{selected['nombre']} · {level} · {lot_code.strip()}")
                st.session_state.pop("new_lot_analyte_id",None)
                st.success(f"Lote creado. DE calculada: {sd:.6f}")
                st.rerun()
            except IntegrityError:
                conn.rollback()
                st.error("Ese lote ya existe para el analito y nivel seleccionados.")
            except Exception as exc:
                conn.rollback()
                st.error(f"No fue posible crear el lote: {exc}")

    if not lots_df.empty:
        st.divider()
        st.markdown("#### Gestionar lote")
        options = {
            f"{r.analito} · {r.nivel} · {r.lote}": int(r.id)
            for r in lots_df.itertuples()
        }
        label = st.selectbox("Lote", list(options.keys()), key="lot_manage_select")
        lot_id = options[label]
        row = lots_df[lots_df.id == lot_id].iloc[0]

        c1, c2 = st.columns(2)
        with c1:
            if bool(row.vigente):
                if st.button(
                    "Archivar lote",
                    use_container_width=True,
                    key=f"archive_lot_{lot_id}",
                ):
                    archive_lot(conn, lot_id, user)
                    st.success("Lote archivado. Sus resultados permanecen intactos.")
                    st.rerun()
            else:
                if st.button(
                    "Restaurar lote",
                    use_container_width=True,
                    key=f"restore_lot_{lot_id}",
                ):
                    restore_lot(conn, lot_id, user)
                    st.success("Lote restaurado.")
                    st.rerun()

        with c2:
            if bool(row.vigente):
                st.info(
                    f"Archivar conserva los {int(row.resultados)} resultado(s) del lote."
                )
            else:
                st.caption(
                    "Este lote está archivado y puede restaurarse en cualquier momento."
                )

        st.markdown("##### Eliminar lote")
        st.warning(
            "La eliminación es permanente y no se puede deshacer. "
            "Antes de continuar, descarga y guarda la información del lote y sus "
            "resultados para mantener un respaldo del control de calidad."
        )

        try:
            backup_bytes = _lot_backup_excel(conn, lot_id, user)
            safe_name = (
                f"{row.analito}_{row.nivel}_{row.lote}"
                .replace("/", "-")
                .replace("\\", "-")
                .replace(" ", "_")
            )
            st.download_button(
                "Descargar respaldo del lote en Excel",
                data=backup_bytes,
                file_name=f"respaldo_{safe_name}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key=f"backup_lot_{lot_id}",
            )
        except Exception as exc:
            st.error(f"No fue posible generar el respaldo: {exc}")

        if int(row.resultados) > 0:
            st.error(
                f"Este lote contiene {int(row.resultados)} resultado(s). "
                "Si lo eliminas, esos resultados también serán eliminados. "
                "Descarga el respaldo antes de continuar."
            )

        confirm_backup = st.checkbox(
            "Confirmo que guardé la información necesaria y comprendo que esta acción es permanente.",
            key=f"confirm_delete_lot_{lot_id}",
        )

        if confirm_backup:
            typed = st.text_input(
                f'Para confirmar, escribe exactamente el código del lote: {row.lote}',
                key=f"type_delete_lot_{lot_id}",
            )
            if st.button(
                "Eliminar definitivamente",
                type="primary",
                use_container_width=True,
                key=f"delete_lot_{lot_id}",
                disabled=(typed.strip() != str(row.lote).strip()),
            ):
                try:
                    delete_lot(conn, lot_id, user)
                    st.success("El lote fue eliminado definitivamente.")
                    st.rerun()
                except Exception as exc:
                    conn.rollback()
                    st.error(f"No fue posible eliminar el lote: {exc}")

