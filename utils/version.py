"""Version de la app y datos del entorno.

Las versiones se leen en tiempo de ejecucion con importlib.metadata y no se
escriben a mano: un numero hardcodeado miente en cuanto Streamlit Cloud resuelve
otra version del interprete o de una libreria, que es justo lo que uno quiere
saber cuando algo se rompe solo en produccion.
"""
from __future__ import annotations

import platform
import sys
from importlib.metadata import PackageNotFoundError, version as _version

VERSION = "v2.0.0"
FECHA_VERSION = "2026-09-20"

# Lo que importa cuando hay que diagnosticar: el resto lo da el reporte tecnico
PAQUETES = ("streamlit", "pandas", "numpy", "plotly", "gspread", "reportlab", "kaleido", "sendgrid")


def version_paquete(nombre: str) -> str:
    """Version instalada, o 'no instalado' si el paquete no esta."""
    try:
        return _version(nombre)
    except PackageNotFoundError:
        return "no instalado"


def resumen_entorno() -> dict[str, str]:
    """Version de la app, del interprete y de las librerias que importan."""
    return {
        "Versión de la app": VERSION,
        "Fecha de la versión": FECHA_VERSION,
        "Python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "Sistema": platform.system(),
        **{nombre: version_paquete(nombre) for nombre in PAQUETES},
    }
