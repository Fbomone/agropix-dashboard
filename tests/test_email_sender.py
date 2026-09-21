"""Tests del envio por SendGrid. No se hace ninguna llamada real a la API."""
import base64

import pytest

from utils import email_sender


@pytest.fixture
def configurado(monkeypatch):
    """SendGrid configurado y SMTP apagado: es el camino que prueban estos tests."""
    from utils import email_smtp

    monkeypatch.setattr(email_smtp, "SMTP_USER", "")
    monkeypatch.setattr(email_smtp, "SMTP_PASSWORD", "")
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


@pytest.mark.parametrize("faltante", ["SENDGRID_API_KEY", "EMAIL_REMITENTE"])
def test_sin_via_de_envio_no_esta_listo(configurado, monkeypatch, faltante):
    monkeypatch.setattr(email_sender, faltante, "")
    listo, motivo = email_sender.configurado()
    assert listo is False
    assert motivo


def test_la_lista_global_de_destinatarios_no_hace_falta_para_estar_configurado(
        configurado, monkeypatch):
    """El panel de administración elige los destinatarios en cada envío."""
    monkeypatch.setattr(email_sender, "EMAIL_DESTINATARIOS", [])
    assert email_sender.configurado() == (True, "")


def test_enviar_sin_destinatarios_falla_al_enviar(configurado, monkeypatch):
    monkeypatch.setattr(email_sender, "EMAIL_DESTINATARIOS", [])
    with pytest.raises(email_sender.ErrorEnvioEmail, match="No hay destinatarios"):
        email_sender.enviar_reporte(b"%PDF-1.4", "r.pdf")


# ---------------------------------------------------------------------------
# Eleccion de transporte
# ---------------------------------------------------------------------------
def test_con_smtp_configurado_gana_smtp(configurado, monkeypatch):
    """SMTP primero: no depende de una cuenta de terceros."""
    from utils import email_smtp

    monkeypatch.setattr(email_smtp, "SMTP_USER", "infoagropix@gmail.com")
    monkeypatch.setattr(email_smtp, "SMTP_PASSWORD", "abcd efgh ijkl mnop")
    assert email_sender.transporte() == email_sender.SMTP


def test_sin_smtp_se_usa_sendgrid(configurado, monkeypatch):
    from utils import email_smtp

    monkeypatch.setattr(email_smtp, "SMTP_USER", "")
    monkeypatch.setattr(email_smtp, "SMTP_PASSWORD", "")
    assert email_sender.transporte() == email_sender.SENDGRID


def test_sin_ninguno_no_hay_transporte(monkeypatch):
    from utils import email_smtp

    monkeypatch.setattr(email_smtp, "SMTP_USER", "")
    monkeypatch.setattr(email_smtp, "SMTP_PASSWORD", "")
    monkeypatch.setattr(email_sender, "SENDGRID_API_KEY", "")
    assert email_sender.transporte() is None
    listo, motivo = email_sender.configurado()
    assert listo is False
    assert "SMTP_USER" in motivo and "SENDGRID_API_KEY" in motivo


def test_el_envio_por_smtp_usa_el_modulo_smtp(configurado, monkeypatch):
    from utils import email_smtp

    monkeypatch.setattr(email_smtp, "SMTP_USER", "infoagropix@gmail.com")
    monkeypatch.setattr(email_smtp, "SMTP_PASSWORD", "abcd efgh ijkl mnop")
    llamadas = {}

    def falso(destinatarios, asunto, html, pdf_bytes=None, nombre_archivo="", remitente=""):
        llamadas.update(destinatarios=destinatarios, asunto=asunto, html=html,
                        pdf=pdf_bytes, archivo=nombre_archivo)
        return list(destinatarios)

    monkeypatch.setattr(email_smtp, "enviar", falso)
    enviados = email_sender.enviar_reporte(b"%PDF-1.4", "reporte.pdf",
                                           destinatarios=["uno@agropix.com"],
                                           asunto="Prueba", html="<p>hola</p>")
    assert enviados == ["uno@agropix.com"]
    assert llamadas["asunto"] == "Prueba"
    assert llamadas["archivo"] == "reporte.pdf"
    assert llamadas["pdf"] == b"%PDF-1.4"


def test_un_error_de_smtp_se_traduce_a_error_de_envio(configurado, monkeypatch):
    """El resto del código no debería tener que distinguir el transporte."""
    from utils import email_smtp

    monkeypatch.setattr(email_smtp, "SMTP_USER", "infoagropix@gmail.com")
    monkeypatch.setattr(email_smtp, "SMTP_PASSWORD", "abcd efgh ijkl mnop")

    def falla(*_a, **_k):
        raise RuntimeError("Gmail rechazó usuario o contraseña.")

    monkeypatch.setattr(email_smtp, "enviar", falla)
    with pytest.raises(email_sender.ErrorEnvioEmail, match="App Password|contraseña"):
        email_sender.enviar_reporte(b"%PDF-1.4", "r.pdf", destinatarios=["x@agropix.com"])


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
