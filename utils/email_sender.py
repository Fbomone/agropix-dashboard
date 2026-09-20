"""Envio de reportes por mail via SendGrid (plan gratis: 100 mails/dia).

Configuracion (variables de entorno en local, st.secrets en Streamlit Cloud):

    SENDGRID_API_KEY      = "SG.xxxxx"
    EMAIL_REMITENTE       = "reportes@agropix.com"   # Single Sender verificado
    EMAIL_DESTINATARIOS   = "dueno@agropix.com,gerente@agropix.com"

El remitente tiene que estar verificado en SendGrid (Settings -> Sender
Authentication), sino la API responde 403 aunque la key sea valida.

El import de sendgrid es diferido a proposito: la app corre igual si el paquete
no esta instalado, solo queda sin la funcion de mail.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime

from config.settings import EMAIL_DESTINATARIOS, EMAIL_REMITENTE, SENDGRID_API_KEY

_logger = logging.getLogger("agropix.email")

ASUNTO_POR_DEFECTO = "Agropix — Reporte de facturación"

CUERPO_HTML = """\
<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;color:#1F2933">
  <h2 style="color:#2E7D32;margin:0 0 .5rem 0">🌱 Agropix — Reporte de facturación</h2>
  <p>{intro}</p>
  <p style="margin:1rem 0"><strong>Período:</strong> {periodo}</p>
  <div style="border-left:4px solid #1565C0;background:#EEF4FB;color:#123B66;
              padding:.6rem .8rem;border-radius:4px;font-size:13px">
    <strong>CONFIDENCIAL</strong><br>
    Información de facturación de Agropix. No reenviar ni redistribuir.
  </div>
  <p style="color:#5F6B7A;font-size:12px;margin-top:1.25rem">
    Generado automáticamente el {momento} · soporte@agropix.com
  </p>
</div>
"""


class ErrorEnvioEmail(RuntimeError):
    """Falla de envio con un mensaje pensado para mostrarle al usuario."""


def configurado() -> tuple[bool, str]:
    """(listo, motivo). `listo` es False si falta configuracion; `motivo` lo explica."""
    if not SENDGRID_API_KEY:
        return False, "Falta SENDGRID_API_KEY en los secrets."
    if not EMAIL_REMITENTE:
        return False, "Falta EMAIL_REMITENTE (Single Sender verificado en SendGrid)."
    if not EMAIL_DESTINATARIOS:
        return False, "Falta EMAIL_DESTINATARIOS (lista separada por comas)."
    try:
        import sendgrid  # noqa: F401
    except ImportError:
        return False, "Falta el paquete sendgrid: pip install -r requirements.txt"
    return True, ""


def enviar_reporte(
    pdf_bytes: bytes,
    nombre_archivo: str,
    periodo: str = "",
    destinatarios: list[str] | None = None,
    asunto: str = ASUNTO_POR_DEFECTO,
    intro: str = "Adjuntamos el reporte del dashboard con los filtros aplicados.",
    html: str | None = None,
) -> list[str]:
    """Manda el PDF adjunto por SendGrid. Devuelve los destinatarios efectivos.

    html: cuerpo completo del mail. Si se omite se usa CUERPO_HTML con `intro` y
    `periodo`; el reporte semanal pasa el suyo, armado en utils/reporte_semanal.py.

    Levanta ErrorEnvioEmail con un texto legible si falta configuracion o si la
    API rechaza el envio.
    """
    listo, motivo = configurado()
    if not listo:
        raise ErrorEnvioEmail(f"El envío por mail no está configurado. {motivo}")
    if not pdf_bytes:
        raise ErrorEnvioEmail("No hay PDF para enviar: generá el reporte primero.")

    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import (
        Attachment, Disposition, FileContent, FileName, FileType, Mail,
    )

    destino = destinatarios or EMAIL_DESTINATARIOS
    mensaje = Mail(
        from_email=EMAIL_REMITENTE,
        to_emails=destino,
        subject=asunto,
        html_content=html or CUERPO_HTML.format(
            intro=intro,
            periodo=periodo or "todo el histórico",
            momento=datetime.now().strftime("%d/%m/%Y %H:%M"),
        ),
    )
    mensaje.attachment = Attachment(
        FileContent(base64.b64encode(pdf_bytes).decode()),
        FileName(nombre_archivo),
        FileType("application/pdf"),
        Disposition("attachment"),
    )

    try:
        respuesta = SendGridAPIClient(SENDGRID_API_KEY).send(mensaje)
    except Exception as e:  # la excepcion de sendgrid trae el body con el detalle
        _logger.error("Fallo el envio a %s: %s", destino, e)
        raise ErrorEnvioEmail(f"SendGrid rechazó el envío: {e}") from e

    if respuesta.status_code >= 300:
        raise ErrorEnvioEmail(f"SendGrid respondió {respuesta.status_code}.")
    _logger.info("Reporte enviado a %s (%s)", destino, respuesta.status_code)
    return list(destino)
