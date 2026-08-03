"""Utilidades para listas de niveles de control."""
def parse_control_levels(raw: str) -> list[str]:
    if raw is None:
        return []
    normalized = str(raw).replace("\n", ",").replace(";", ",")
    result, seen = [], set()
    for item in normalized.split(","):
        name = item.strip()
        key = name.casefold()
        if name and key not in seen:
            result.append(name)
            seen.add(key)
    return result
