"""Configuración de niveles de control por analito."""

DEFAULT_CONTROL_LEVELS = ["Bajo", "Normal", "Alto"]

SPECIAL_CONTROL_LEVELS = {
    "troponina": ["Nivel 1", "Nivel 2"],
}


def control_levels_for(analyte_name: str) -> list[str]:
    key = (analyte_name or "").strip().casefold()
    return SPECIAL_CONTROL_LEVELS.get(key, DEFAULT_CONTROL_LEVELS.copy())
