"""Lectura de configuracion: variables de entorno y las dos formas de secrets."""
from config import settings


def test_sendgrid_lee_la_tabla_anidada(monkeypatch):
    monkeypatch.setattr(settings, "_secrets", lambda: {
        "sendgrid": {"api_key": "SG.desde-tabla", "from_email": "reportes@agropix.com"}
    })
    assert settings._sendgrid("api_key") == "SG.desde-tabla"
    assert settings._sendgrid("from_email") == "reportes@agropix.com"
    assert settings._sendgrid("destinatarios") == ""


def test_sendgrid_sin_tabla_no_rompe(monkeypatch):
    monkeypatch.setattr(settings, "_secrets", lambda: {})
    assert settings._sendgrid("api_key") == ""


def test_la_variable_de_entorno_gana_sobre_secrets(monkeypatch):
    monkeypatch.setenv("CRM_SHEET_ID", "desde-entorno")
    monkeypatch.setattr(settings, "_secrets", lambda: {"CRM_SHEET_ID": "desde-secrets"})
    assert settings._cfg("CRM_SHEET_ID") == "desde-entorno"


def test_sin_entorno_se_usa_secrets(monkeypatch):
    monkeypatch.delenv("CRM_TAB", raising=False)
    monkeypatch.setattr(settings, "_secrets", lambda: {"CRM_TAB": "OtraHoja"})
    assert settings._cfg("CRM_TAB", "Trabajos") == "OtraHoja"


def test_default_si_no_hay_nada(monkeypatch):
    monkeypatch.delenv("CRM_TAB", raising=False)
    monkeypatch.setattr(settings, "_secrets", lambda: {})
    assert settings._cfg("CRM_TAB", "Trabajos") == "Trabajos"


BARRA_N = chr(92) + "n"  # los dos caracteres \ y n, como los guarda TOML


def service_account(private_key: str) -> dict:
    """Service account completo (el resto de los campos no son lo que se prueba)."""
    return {
        "type": "service_account",
        "project_id": "agropix",
        "private_key": private_key,
        "client_email": "bot@agropix.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def test_private_key_des_escapa_los_saltos_de_linea(monkeypatch):
    """En los secrets la private_key llega con "\\n" literales, no con saltos reales."""
    escapada = (f"-----BEGIN PRIVATE KEY-----{BARRA_N}abc{BARRA_N}"
                f"-----END PRIVATE KEY-----{BARRA_N}")
    assert BARRA_N in escapada and "\n" not in escapada
    monkeypatch.setattr(settings, "_secrets",
                        lambda: {"gcp_service_account": service_account(escapada)})

    clave = settings.credenciales_google()["private_key"]
    assert BARRA_N not in clave, "quedaron barras sin des-escapar"
    assert clave.count("\n") == 3
    assert clave.startswith("-----BEGIN PRIVATE KEY-----\n")


def test_private_key_con_saltos_reales_no_se_toca(monkeypatch):
    real = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
    monkeypatch.setattr(settings, "_secrets",
                        lambda: {"gcp_service_account": service_account(real)})
    assert settings.credenciales_google()["private_key"] == real


def test_sin_service_account_en_secrets_devuelve_none(monkeypatch):
    monkeypatch.setattr(settings, "_secrets", lambda: {})
    assert settings.credenciales_google() is None


# ---------------------------------------------------------------------------
# Placeholders: los secrets de ejemplo no deben pasar por credenciales reales
# ---------------------------------------------------------------------------
SERVICE_ACCOUNT_PLACEHOLDER = {
    "type": "service_account",
    "project_id": "placeholder_project",
    "private_key_id": "placeholder",
    "private_key": "placeholder",
    "client_email": "placeholder@placeholder.iam.gserviceaccount.com",
}


def test_service_account_de_relleno_se_ignora(monkeypatch):
    """Con el bloque placeholder, local tiene que seguir usando credentials.json."""
    monkeypatch.setattr(settings, "_secrets",
                        lambda: {"gcp_service_account": dict(SERVICE_ACCOUNT_PLACEHOLDER)})
    assert settings.credenciales_google() is None


def test_service_account_sin_token_uri_se_ignora(monkeypatch):
    info = dict(SERVICE_ACCOUNT_PLACEHOLDER)
    info["private_key"] = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
    monkeypatch.setattr(settings, "_secrets", lambda: {"gcp_service_account": info})
    assert settings.credenciales_google() is None, "falta token_uri: no es usable"


def test_service_account_completo_si_se_usa(monkeypatch):
    info = dict(SERVICE_ACCOUNT_PLACEHOLDER)
    info["private_key"] = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
    info["token_uri"] = "https://oauth2.googleapis.com/token"
    monkeypatch.setattr(settings, "_secrets", lambda: {"gcp_service_account": info})
    assert settings.credenciales_google()["client_email"] == info["client_email"]


def test_api_key_de_relleno_de_sendgrid_cuenta_como_vacia(monkeypatch):
    monkeypatch.setattr(settings, "_secrets", lambda: {
        "sendgrid": {"api_key": "placeholder_sendgrid_key", "from_email": "reportes@agropix.com"}
    })
    assert settings._sendgrid("api_key") == ""
    assert settings._sendgrid("from_email") == "reportes@agropix.com"
