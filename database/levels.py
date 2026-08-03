"""Acceso a niveles de control configurables por analito."""
from __future__ import annotations
from typing import Iterable
import pandas as pd
from .core import fetchall_df, current_org_id

def load_control_levels(conn, analyte_id: int, *, only_active: bool = True) -> pd.DataFrame:
    org_id = current_org_id()
    if org_id is None:
        return pd.DataFrame(columns=["id","analito_id","nombre","orden","activo"])
    sql = """
        SELECT id, analito_id, nombre, orden, activo
        FROM niveles_control
        WHERE organizacion_id=%s AND analito_id=%s
    """
    params = [org_id, int(analyte_id)]
    if only_active:
        sql += " AND activo=TRUE"
    sql += " ORDER BY orden, nombre"
    return fetchall_df(conn, sql, params)

def control_level_names(conn, analyte_id: int, *, only_active: bool = True) -> list[str]:
    df = load_control_levels(conn, analyte_id, only_active=only_active)
    return [] if df.empty else [str(x) for x in df["nombre"].tolist()]

def sync_control_levels(conn, analyte_id: int, names: Iterable[str]) -> list[str]:
    org_id = current_org_id()
    if org_id is None:
        raise ValueError("No existe una organización activa.")

    cleaned, seen = [], set()
    for raw in names:
        name = str(raw).strip()
        key = name.casefold()
        if name and key not in seen:
            cleaned.append(name)
            seen.add(key)

    if not cleaned:
        raise ValueError("Debes configurar al menos un nivel de control.")

    existing = load_control_levels(conn, analyte_id, only_active=False)
    existing_map = {
        str(r.nombre).casefold(): int(r.id)
        for r in existing.itertuples()
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE niveles_control
            SET activo=FALSE, fecha_modificacion=CURRENT_TIMESTAMP
            WHERE organizacion_id=%s AND analito_id=%s
            """,
            (org_id, int(analyte_id)),
        )

        for order, name in enumerate(cleaned, start=1):
            key = name.casefold()
            if key in existing_map:
                cur.execute(
                    """
                    UPDATE niveles_control
                    SET nombre=%s, orden=%s, activo=TRUE,
                        fecha_modificacion=CURRENT_TIMESTAMP
                    WHERE id=%s AND organizacion_id=%s
                    """,
                    (name, order, existing_map[key], org_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO niveles_control(
                        organizacion_id,analito_id,nombre,orden,activo
                    )
                    VALUES(%s,%s,%s,%s,TRUE)
                    """,
                    (org_id, int(analyte_id), name, order),
                )
    conn.commit()
    return cleaned
