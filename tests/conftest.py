"""Configuracion comun de los tests.

El objetivo es que la suite de un mismo resultado en cualquier maquina: sin
esto, tener `.streamlit/secrets.toml` con credenciales reales cambiaba el
camino que tomaba el codigo y algunos tests pasaban en CI pero fallaban en
local (o al reves).
"""
import pytest


@pytest.fixture(autouse=True)
def sin_credenciales_reales(monkeypatch):
    """Apaga toda via de envio antes de cada test.

    Ningun test deberia depender de que el que lo corre tenga (o no) un App
    Password cargado. El que necesite un transporte, lo prende explicitamente.
    """
    from utils import email_sender, email_smtp

    monkeypatch.setattr(email_smtp, "SMTP_USER", "", raising=False)
    monkeypatch.setattr(email_smtp, "SMTP_PASSWORD", "", raising=False)
    monkeypatch.setattr(email_sender, "SENDGRID_API_KEY", "", raising=False)
    monkeypatch.setattr(email_sender, "EMAIL_REMITENTE", "", raising=False)
    monkeypatch.setattr(email_sender, "EMAIL_DESTINATARIOS", [], raising=False)


@pytest.fixture(autouse=True)
def sin_secrets_de_streamlit(monkeypatch):
    """st.secrets vacio: los precios y los usuarios los pone cada test."""
    from utils import auth, data

    monkeypatch.setattr(auth, "_seccion_secrets", lambda _n: {}, raising=False)
    monkeypatch.setattr(auth, "_password_comun", lambda: "", raising=False)
    monkeypatch.setattr(data, "precios_de_secrets", lambda: {}, raising=False)
