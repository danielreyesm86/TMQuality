"""TMQuality - Motor científico de control de calidad."""
from __future__ import annotations

from typing import Optional
import pandas as pd

from database import fetchall_df, current_org_id, execute

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


def recalcular_reglas_lote(conn, lote_control_id: int, media: float, de: float) -> int:
    """
    Recalcula cronológicamente todos los resultados de un lote.

    Actualiza:
    - z_score
    - reglas_violadas
    - estado

    Es especialmente útil después de agregar, modificar o eliminar resultados,
    ya que varias reglas de Westgard dependen de los puntos anteriores.
    """
    df = fetchall_df(
        conn,
        """
        SELECT id, fecha, valor
        FROM resultados_cc
        WHERE organizacion_id=%s AND lote_control_id=%s
        ORDER BY fecha ASC, id ASC
        """,
        (current_org_id(), int(lote_control_id)),
    )

    if df.empty:
        return 0

    z_acumulados: list[float] = []
    actualizaciones = []

    for _, row in df.iterrows():
        current_z = zscore(float(row["valor"]), float(media), float(de))
        z_acumulados.append(current_z)

        rules = westgard_rules(z_acumulados)
        estado = state_from_rules(rules)

        actualizaciones.append(
            (
                current_z,
                ", ".join(rules) if rules else "",
                estado,
                int(row["id"]),
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE resultados_cc
            SET z_score=%s,
                reglas_violadas=%s,
                estado=%s,
                fecha_modificacion=CURRENT_TIMESTAMP
            WHERE id=%s AND organizacion_id=%s
            """,
            [row[:-1] + (row[-1], current_org_id()) for row in actualizaciones],
        )
    conn.commit()
    return len(actualizaciones)


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

