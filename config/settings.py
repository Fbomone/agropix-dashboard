"""Configuracion del dashboard.

Dos entornos, una sola fuente de verdad:

- Local: .env (variables de entorno) + credentials.json en la raiz.
- Streamlit Cloud: st.secrets (Settings -> Secrets), porque el contenedor no
  tiene ni .env ni credentials.json. Ver .streamlit/secrets.toml.example.

Las variables de entorno tienen prioridad sobre los secrets, asi se puede
apuntar a otro Sheet en local sin tocar la configuracion del deploy.
"""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_log = logging.getLogger("agropix.config")

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

# Link del boton "Ver reporte completo" en el mail semanal. Se cambia desde los
# secrets si la app se redeploya con otro nombre, sin tocar codigo. El default es
# la URL larga que asigna Streamlit Cloud, que no depende del nombre corto.
URL_APP = _cfg("URL_APP", "https://agropix-dashboard-rlugsmacrmmzqtonnbqw9.streamlit.app")

# SendGrid (envio automatico de reportes). Se aceptan las dos formas de secrets:
# claves planas (SENDGRID_API_KEY) o la tabla [sendgrid] con api_key/from_email.
def _sendgrid(clave: str) -> str:
    try:
        tabla = _secrets().get("sendgrid") or {}
        valor = str(dict(tabla).get(clave, "")).strip()
    except Exception:
        return ""
    # "placeholder_sendgrid_key" y companía no son credenciales: tratarlas como
    # vacias evita que aparezca el boton de mail para despues fallar con un 403.
    return "" if valor.lower().startswith("placeholder") else valor


# SMTP (Gmail). Alternativa a SendGrid: no necesita cuenta de terceros, sirve la
# casilla de Gmail que ya existe con un App Password.
def _smtp(clave: str) -> str:
    try:
        tabla = _secrets().get("smtp") or {}
        valor = str(dict(tabla).get(clave, "")).strip()
    except Exception:
        return ""
    return "" if valor.lower().startswith("placeholder") else valor


SMTP_HOST = _cfg("SMTP_HOST") or _smtp("host") or "smtp.gmail.com"
SMTP_PORT = int(_cfg("SMTP_PORT") or _smtp("port") or 587)
SMTP_USER = _cfg("SMTP_USER") or _smtp("user")
SMTP_PASSWORD = _cfg("SMTP_PASSWORD") or _smtp("password")

SENDGRID_API_KEY = _cfg("SENDGRID_API_KEY") or _sendgrid("api_key")
EMAIL_REMITENTE = (_cfg("EMAIL_REMITENTE") or _sendgrid("from_email") or SMTP_USER
                   or "reportes@agropix.com")
EMAIL_DESTINATARIOS = [
    d.strip()
    for d in (_cfg("EMAIL_DESTINATARIOS") or _sendgrid("destinatarios")).split(",")
    if d.strip()
]


def _service_account_usable(info: dict) -> bool:
    """False si la tabla es un placeholder o esta incompleta.

    Es comun dejar [gcp_service_account] con valores de relleno mientras se
    configura el resto de los secrets. Si lo diera por bueno, en local se
    dejaria de usar credentials.json y Google Sheets fallaria.
    """
    requeridos = ("type", "project_id", "private_key", "client_email", "token_uri")
    if any(not str(info.get(c, "")).strip() for c in requeridos):
        return False
    return "PRIVATE KEY" in str(info["private_key"])


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
    if not _service_account_usable(info):
        _log.warning(
            "[gcp_service_account] incompleto o de relleno en los secrets: "
            "se ignora y se usa credentials.json si existe."
        )
        return None
    return info
