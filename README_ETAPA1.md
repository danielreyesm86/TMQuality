# TMQuality 5.6.0 — Modularización etapa 1

En esta etapa se separó únicamente la capa de base de datos.

## Archivos nuevos

```text
database/
├── __init__.py
└── core.py
```

`TMQuality.py` ahora importa desde `database`:

- conexión PostgreSQL / Supabase
- helpers `execute`, `fetchone`, `fetchall_df`
- inicialización y migraciones
- organización actual

No se modificó todavía:
- autenticación
- reglas de Westgard
- reportes
- módulos/pantallas

## Para usar en GitHub

1. Reemplaza `TMQuality.py`.
2. Crea la carpeta `database`.
3. Sube `database/__init__.py`.
4. Sube `database/core.py`.
5. No cambies `requirements.txt`.
6. Haz Reboot app en Streamlit.

## Para ejecutar localmente en VS Code

Desde la raíz del proyecto:

```bash
pip install -r requirements.txt
streamlit run TMQuality.py
```

Para usar Supabase localmente, crea `.streamlit/secrets.toml` con tu conexión.
No subas `secrets.toml` a GitHub.
