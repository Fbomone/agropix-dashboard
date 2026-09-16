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


def test_private_key_des_escapa_los_saltos_de_linea(monkeypatch):
    """En los secrets la private_key llega con "\\n" literales, no con saltos reales."""
    escapada = f"-----BEGIN-----{BARRA_N}abc{BARRA_N}-----END-----{BARRA_N}"
    assert BARRA_N in escapada and "\n" not in escapada
    monkeypatch.setattr(settings, "_secrets", lambda: {
        "gcp_service_account": {"private_key": escapada}
    })

    clave = settings.credenciales_google()["private_key"]
    assert BARRA_N not in clave, "quedaron barras sin des-escapar"
    assert clave.count("\n") == 3
    assert clave.startswith("-----BEGIN-----\n")


def test_private_key_con_saltos_reales_no_se_toca(monkeypatch):
    real = "-----BEGIN-----\nabc\n-----END-----\n"
    monkeypatch.setattr(settings, "_secrets", lambda: {
        "gcp_service_account": {"private_key": real}
    })
    assert settings.credenciales_google()["private_key"] == real


def test_sin_service_account_en_secrets_devuelve_none(monkeypatch):
    monkeypatch.setattr(settings, "_secrets", lambda: {})
    assert settings.credenciales_google() is None
