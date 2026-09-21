"""Envio por SMTP (Gmail). Alternativa a SendGrid, sin cuenta de terceros.

Configuracion (variables de entorno o st.secrets, tabla [smtp] o claves planas):

    SMTP_HOST      = "smtp.gmail.com"        # default
    SMTP_PORT      = 587                     # default (STARTTLS)
    SMTP_USER      = "infoagropix@gmail.com"
    SMTP_PASSWORD  = "xxxx xxxx xxxx xxxx"   # App Password de 16 caracteres

La contrasena NO es la de la cuenta de Google: es un App Password, que se saca
en https://myaccount.google.com/apppasswords y requiere tener activada la
verificacion en dos pasos. Google rechaza la contrasena normal desde 2022.

Gmail permite unos 500 destinatarios por dia en una cuenta gratuita: de sobra
para 7 personas una vez por semana.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from config.settings import SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

_logger = logging.getLogger("agropix.smtp")

TIMEOUT = 20  # segundos: si Gmail no responde, mejor fallar que colgar la app


def configurado() -> tuple[bool, str]:
    """(listo, motivo). Igual forma que email_sender.configurado()."""
    if not SMTP_USER:
        return False, "Falta SMTP_USER (la casilla de Gmail que envía)."
    if not SMTP_PASSWORD:
        return False, ("Falta SMTP_PASSWORD. Tiene que ser un App Password de Google "
                       "(16 caracteres), no la contraseña de la cuenta.")
    return True, ""


def _conectar() -> smtplib.SMTP:
    """Abre la conexion con STARTTLS y autentica. El caller cierra con quit()."""
    servidor = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT)
    servidor.starttls(context=ssl.create_default_context())
    servidor.login(SMTP_USER, SMTP_PASSWORD)
    return servidor


def validar_conexion() -> dict:
    """Prueba conectar y autenticar sin mandar ningun mail.

    Distingue los tres casos que importan: falta configuracion, la contrasena no
    sirve (tipicamente por usar la del correo en vez de un App Password) y no se
    puede llegar al servidor.
    """
    listo, motivo = configurado()
    if not listo:
        return {"exitoso": False, "mensaje": motivo, "detalles": {"configuracion": "incompleta"}}

    detalles = {
        "proveedor": f"SMTP · {SMTP_HOST}:{SMTP_PORT}",
        "usuario": SMTP_USER,
        "cifrado": "STARTTLS",
        "contraseña": f"{'•' * 12} ({len(SMTP_PASSWORD)} caracteres)",
    }
    try:
        servidor = _conectar()
        servidor.quit()
    except smtplib.SMTPAuthenticationError as e:
        detalles["error"] = f"SMTP {e.smtp_code}"
        return {
            "exitoso": False,
            "mensaje": "Usuario o contraseña rechazados. Casi siempre es porque la contraseña "
                       "no es un App Password: generá uno en myaccount.google.com/apppasswords "
                       "(requiere verificación en dos pasos activada).",
            "detalles": detalles,
        }
    except (OSError, smtplib.SMTPException) as e:
        detalles["error"] = type(e).__name__
        return {"exitoso": False, "mensaje": f"No se pudo conectar con {SMTP_HOST}: {e}",
                "detalles": detalles}

    return {"exitoso": True, "mensaje": "Conexión y autenticación correctas.", "detalles": detalles}


def enviar(destinatarios: list[str], asunto: str, html: str,
           pdf_bytes: bytes | None = None, nombre_archivo: str = "reporte.pdf",
           remitente: str = "") -> list[str]:
    """Manda un mail con el PDF adjunto. Devuelve los destinatarios efectivos.

    Levanta RuntimeError con un texto legible si falla; el caller lo traduce a
    ErrorEnvioEmail para que el resto del codigo no distinga el transporte.
    """
    listo, motivo = configurado()
    if not listo:
        raise RuntimeError(motivo)

    mensaje = EmailMessage()
    mensaje["From"] = remitente or SMTP_USER
    mensaje["To"] = ", ".join(destinatarios)
    mensaje["Subject"] = asunto
    # Alternativa en texto plano: algunos clientes y filtros antispam la piden
    mensaje.set_content("Este reporte se ve mejor en un cliente que soporte HTML. "
                        "El PDF con el detalle va adjunto.")
    mensaje.add_alternative(html, subtype="html")

    if pdf_bytes:
        mensaje.add_attachment(pdf_bytes, maintype="application", subtype="pdf",
                               filename=nombre_archivo)

    try:
        servidor = _conectar()
        try:
            servidor.send_message(mensaje)
        finally:
            servidor.quit()
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError("Gmail rechazó usuario o contraseña. Revisá que sea un App Password.")
    except (OSError, smtplib.SMTPException) as e:
        raise RuntimeError(f"Falló el envío por SMTP: {e}") from e

    _logger.info("Enviado por SMTP a %s", destinatarios)
    return list(destinatarios)
