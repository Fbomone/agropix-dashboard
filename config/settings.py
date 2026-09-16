"""Configuracion del dashboard.

Dos entornos, una sola fuente de verdad:

- Local: .env (variables de entorno) + credentials.json en la raiz.
- Streamlit Cloud: st.secrets (Settings -> Secrets), porque el contenedor no
  tiene ni .env ni credentials.json. Ver .streamlit/secrets.toml.example.

Las variables de entorno tienen prioridad sobre los secrets, asi se puede
apuntar a otro Sheet en local sin tocar la configuracion del deploy.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = BASE_DIR / "credentials.json"
PRECIOS_PATH = BASE_DIR / "precios_lista.json"


def _secrets():
    """st.secrets o {} si no hay archivo de secrets (importar streamlit no falla nunca)."""
    try:
        import streamlit as st

        return st.secrets
    except Exception:
        return {}


def _cfg(clave: str, default: str = "") -> str:
    """Valor de configuracion: primero variable de entorno, despues st.secrets."""
    valor = os.getenv(clave)
    if valor:
        return valor
    try:
        return str(_secrets().get(clave, default))
    except Exception:
        return default


CRM_SHEET_ID = _cfg("CRM_SHEET_ID")
VENTAS_SHEET_ID = _cfg("VENTAS_SHEET_ID")
CRM_TAB = _cfg("CRM_TAB", "Trabajos")
VENTAS_TAB = _cfg("VENTAS_TAB", "Ventas")

COHERE_API_KEY = _cfg("COHERE_API_KEY")

# SendGrid (envio automatico de reportes). Se aceptan las dos formas de secrets:
# claves planas (SENDGRID_API_KEY) o la tabla [sendgrid] con api_key/from_email.
def _sendgrid(clave: str) -> str:
    try:
        tabla = _secrets().get("sendgrid") or {}
        return str(dict(tabla).get(clave, ""))
    except Exception:
        return ""


SENDGRID_API_KEY = _cfg("SENDGRID_API_KEY") or _sendgrid("api_key")
EMAIL_REMITENTE = _cfg("EMAIL_REMITENTE") or _sendgrid("from_email") or "reportes@agropix.com"
EMAIL_DESTINATARIOS = [
    d.strip()
    for d in (_cfg("EMAIL_DESTINATARIOS") or _sendgrid("destinatarios")).split(",")
    if d.strip()
]


def credenciales_google() -> dict | None:
    """Service account desde st.secrets["gcp_service_account"], o None si va por archivo.

    En Streamlit Cloud se pega el contenido de credentials.json como tabla TOML;
    la private_key queda con "\\n" escapados y hay que volverlos saltos reales.
    """
    try:
        info = _secrets().get("gcp_service_account")
    except Exception:
        return None
    if not info:
        return None
    info = dict(info)
    if isinstance(info.get("private_key"), str):
        info["private_key"] = info["private_key"].replace("\\n", "\n")
    return info
