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


SMTP, SENDGRID = "smtp", "sendgrid"


def transporte() -> str | None:
    """Que via de envio esta configurada: SMTP, SENDGRID o None.

    SMTP tiene prioridad porque no depende de una cuenta de terceros: si estan
    los dos cargados, gana el que anda seguro.
    """
    from utils import email_smtp

    if email_smtp.configurado()[0]:
        return SMTP
    if SENDGRID_API_KEY and EMAIL_REMITENTE:
        return SENDGRID
    return None


def configurado() -> tuple[bool, str]:
    """(listo, motivo). `listo` es False si falta configuracion; `motivo` lo explica."""
    via = transporte()
    if via is None:
        return False, ("No hay vía de envío configurada. Cargá SMTP_USER + SMTP_PASSWORD "
                       "(App Password de Gmail) o SENDGRID_API_KEY + EMAIL_REMITENTE.")
    if via == SENDGRID:
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

    destino = destinatarios or EMAIL_DESTINATARIOS
    if not destino:
        raise ErrorEnvioEmail("No hay destinatarios: cargá EMAIL_DESTINATARIOS en los secrets.")
    cuerpo = html or CUERPO_HTML.format(
        intro=intro,
        periodo=periodo or "todo el histórico",
        momento=datetime.now().strftime("%d/%m/%Y %H:%M"),
    )

    if transporte() == SMTP:
        from utils import email_smtp

        try:
            return email_smtp.enviar(destino, asunto, cuerpo, pdf_bytes, nombre_archivo,
                                     remitente=EMAIL_REMITENTE)
        except RuntimeError as e:
            raise ErrorEnvioEmail(str(e)) from e

    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import (
        Attachment, Disposition, FileContent, FileName, FileType, Mail,
    )

    mensaje = Mail(from_email=EMAIL_REMITENTE, to_emails=destino, subject=asunto,
                   html_content=cuerpo)
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


# ---------------------------------------------------------------------------
# Validacion de la configuracion (panel de administracion)
# ---------------------------------------------------------------------------
def validar_conexion() -> dict:
    """Comprueba contra la API de SendGrid que la key y el remitente sirvan.

    No manda ningun mail: consulta los Verified Senders. Es el equivalente al
    "probar conexion" de SMTP, pero para una API HTTP: lo que puede fallar es la
    key (401/403) o que el remitente no este verificado, que es el motivo mas
    comun de un 403 al enviar con una key valida.

    Devuelve {exitoso, mensaje, detalles} para pintarlo directo en pantalla.
    """
    listo, motivo = configurado()
    if not listo:
        return {"exitoso": False, "mensaje": motivo,
                "detalles": {"configuracion": "incompleta"}}

    if transporte() == SMTP:
        from utils import email_smtp

        return email_smtp.validar_conexion()

    detalles = {
        "proveedor": "SendGrid (HTTPS, API v3)",
        "remitente": EMAIL_REMITENTE,
        "destinatarios": len(EMAIL_DESTINATARIOS),
        "api_key": f"{SENDGRID_API_KEY[:6]}…{SENDGRID_API_KEY[-4:]}",
        "verificado": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }

    from python_http_client.exceptions import HTTPError
    from sendgrid import SendGridAPIClient

    try:
        respuesta = SendGridAPIClient(SENDGRID_API_KEY).client.verified_senders.get()
    except HTTPError as e:
        codigo = getattr(e, "status_code", "?")
        mensaje = {
            401: "La API key de SendGrid es inválida o fue revocada.",
            403: "La API key no tiene permiso para leer los remitentes verificados. "
                 "Puede servir igual para enviar: probá con un envío a un solo destinatario.",
        }.get(codigo, f"SendGrid respondió {codigo}.")
        detalles["error"] = f"HTTP {codigo}"
        return {"exitoso": False, "mensaje": mensaje, "detalles": detalles}
    except Exception as e:
        detalles["error"] = type(e).__name__
        return {"exitoso": False, "mensaje": f"No se pudo contactar a SendGrid: {e}",
                "detalles": detalles}

    remitentes = _emails_verificados(respuesta)
    detalles["remitentes_verificados"] = ", ".join(remitentes) or "ninguno"
    if remitentes and EMAIL_REMITENTE.lower() not in {r.lower() for r in remitentes}:
        return {
            "exitoso": False,
            "mensaje": f"La API key funciona, pero «{EMAIL_REMITENTE}» no está entre los "
                       "remitentes verificados: SendGrid va a rechazar el envío con 403. "
                       "Verificalo en Settings → Sender Authentication.",
            "detalles": detalles,
        }
    return {"exitoso": True, "mensaje": "API key válida y remitente verificado.",
            "detalles": detalles}


def _emails_verificados(respuesta) -> list[str]:
    """Extrae los emails de la respuesta de verified_senders, sin asumir su forma."""
    import json

    try:
        cuerpo = json.loads(respuesta.body.decode() if isinstance(respuesta.body, bytes)
                            else respuesta.body)
    except Exception:
        return []
    items = cuerpo.get("results", cuerpo) if isinstance(cuerpo, dict) else cuerpo
    if not isinstance(items, list):
        return []
    return [str(i.get("from_email")) for i in items
            if isinstance(i, dict) and i.get("from_email")]


def enviar_individual(
    pdf_bytes: bytes,
    nombre_archivo: str,
    destinatarios: list[str],
    asunto: str = ASUNTO_POR_DEFECTO,
    html: str | None = None,
    periodo: str = "",
) -> dict:
    """Manda un mail por destinatario y devuelve el resultado de cada uno.

    Un envio con varios "to" es una sola llamada: si falla, falla para todos y no
    se sabe quien recibio. Uno por uno cuesta N llamadas pero permite decir
    exactamente a quien llego, que es lo que necesita el panel de envios.
    El plan gratis admite 100 mails por dia: 7 destinatarios no lo mueven.
    """
    detalle = []
    for email in destinatarios:
        momento = datetime.now().isoformat(timespec="seconds")
        try:
            enviar_reporte(pdf_bytes, nombre_archivo, periodo=periodo,
                           destinatarios=[email], asunto=asunto, html=html)
            detalle.append({"email": email, "exitoso": True, "momento": momento})
        except ErrorEnvioEmail as e:
            _logger.error("Falló el envío a %s: %s", email, e)
            detalle.append({"email": email, "exitoso": False, "momento": momento,
                            "error": str(e)})

    exitosos = sum(1 for d in detalle if d["exitoso"])
    return {
        "exitosos": exitosos,
        "fallidos": len(detalle) - exitosos,
        "total": len(detalle),
        "detalle": detalle,
    }
