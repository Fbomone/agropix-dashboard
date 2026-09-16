"""Tests del envio por SendGrid. No se hace ninguna llamada real a la API."""
import base64

import pytest

from utils import email_sender


@pytest.fixture
def configurado(monkeypatch):
    monkeypatch.setattr(email_sender, "SENDGRID_API_KEY", "SG.de-prueba")
    monkeypatch.setattr(email_sender, "EMAIL_REMITENTE", "reportes@agropix.com")
    monkeypatch.setattr(email_sender, "EMAIL_DESTINATARIOS", ["dueno@agropix.com"])


@pytest.fixture
def cliente_falso(monkeypatch):
    """Intercepta SendGridAPIClient y guarda el mensaje que se habria enviado."""
    sendgrid = pytest.importorskip("sendgrid")
    enviados = []

    class Respuesta:
        status_code = 202

    class ClienteFalso:
        def __init__(self, api_key):
            enviados.append(("key", api_key))

        def send(self, mensaje):
            enviados.append(("mail", mensaje.get()))
            return Respuesta()

    monkeypatch.setattr(sendgrid, "SendGridAPIClient", ClienteFalso)
    return enviados


@pytest.mark.parametrize("faltante", ["SENDGRID_API_KEY", "EMAIL_REMITENTE", "EMAIL_DESTINATARIOS"])
def test_sin_configuracion_no_esta_listo(configurado, monkeypatch, faltante):
    monkeypatch.setattr(email_sender, faltante, "" if "EMAIL_DEST" not in faltante else [])
    listo, motivo = email_sender.configurado()
    assert listo is False
    assert motivo


def test_configuracion_completa(configurado):
    assert email_sender.configurado() == (True, "")


def test_sin_configurar_levanta_error_legible(monkeypatch):
    monkeypatch.setattr(email_sender, "SENDGRID_API_KEY", "")
    with pytest.raises(email_sender.ErrorEnvioEmail, match="no está configurado"):
        email_sender.enviar_reporte(b"%PDF-1.4", "reporte.pdf")


def test_pdf_vacio_no_se_envia(configurado):
    with pytest.raises(email_sender.ErrorEnvioEmail, match="No hay PDF"):
        email_sender.enviar_reporte(b"", "reporte.pdf")


def test_envio_adjunta_el_pdf_en_base64(configurado, cliente_falso):
    pdf = b"%PDF-1.4 contenido de prueba"
    destinos = email_sender.enviar_reporte(pdf, "reporte_agropix.pdf", periodo="01/09 a 16/09")

    assert destinos == ["dueno@agropix.com"]
    assert ("key", "SG.de-prueba") in cliente_falso
    cuerpo = dict(cliente_falso)["mail"]
    adjunto = cuerpo["attachments"][0]
    assert base64.b64decode(adjunto["content"]) == pdf
    assert adjunto["filename"] == "reporte_agropix.pdf"
    assert adjunto["type"] == "application/pdf"
    assert cuerpo["from"]["email"] == "reportes@agropix.com"
    html = cuerpo["content"][0]["value"]
    assert "CONFIDENCIAL" in html and "01/09 a 16/09" in html


def test_respuesta_de_error_de_la_api_se_traduce(configurado, monkeypatch):
    sendgrid = pytest.importorskip("sendgrid")

    class Respuesta:
        status_code = 403

    class ClienteRechaza:
        def __init__(self, _key):
            pass

        def send(self, _mensaje):
            return Respuesta()

    monkeypatch.setattr(sendgrid, "SendGridAPIClient", ClienteRechaza)
    with pytest.raises(email_sender.ErrorEnvioEmail, match="403"):
        email_sender.enviar_reporte(b"%PDF-1.4", "reporte.pdf")
