#!/usr/bin/env python
"""Genera y envia el reporte semanal de Agropix. Corre fuera de Streamlit.

Lo dispara .github/workflows/reporte-semanal.yml los viernes 18:00 ART. Tambien
se puede correr a mano:

    # Sin enviar nada: imprime los numeros y guarda el PDF en ./salida/
    python scripts/enviar_reporte_semanal.py --dry-run

    # Semana puntual
    python scripts/enviar_reporte_semanal.py --desde 2026-09-08 --hasta 2026-09-14

    # Envio real
    python scripts/enviar_reporte_semanal.py

Configuracion (variables de entorno o .streamlit/secrets.toml):
    CRM_SHEET_ID, VENTAS_SHEET_ID, CRM_TAB, VENTAS_TAB
    GOOGLE_CREDENTIALS_JSON o credentials.json en la raiz
    SENDGRID_API_KEY, EMAIL_REMITENTE  (o la tabla [sendgrid])
    EMAIL_DESTINATARIOS               (opcional: reemplaza la lista por defecto)

Codigo de salida distinto de 0 si algo falla, para que Actions lo marque en rojo.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from utils.data import aplicar_filtros, cargar_precios, construir_datos  # noqa: E402
from utils import envio_log  # noqa: E402
from utils.email_sender import configurado, enviar_individual  # noqa: E402
from utils.reporte_semanal import (  # noqa: E402
    AVISO_DE_ERROR, MODO_PRUEBA, MODO_SEMANAL, TZ_ARGENTINA, asunto, cuerpo_html,
    destinatarios,
    etiqueta_periodo, kpis_semana, nombre_pdf, semana_reporte, top_clientes_semana,
)

log = logging.getLogger("agropix.reporte")


def argumentos(argv=None):
    p = argparse.ArgumentParser(description="Reporte semanal de Agropix por mail")
    p.add_argument("--modo", choices=[MODO_SEMANAL, MODO_PRUEBA], default=MODO_SEMANAL,
                   help="semanal: a toda la lista. prueba: solo Franco y Matías, "
                        "con el asunto prefijado [PRUEBA]")
    p.add_argument("--fecha-corte", type=_fecha, dest="fecha_corte",
                   help="viernes de cierre a simular (YYYY-MM-DD). Si no es viernes se "
                        "toma el viernes anterior más cercano")
    p.add_argument("--desde", type=_fecha, help="inicio del período (YYYY-MM-DD)")
    p.add_argument("--hasta", type=_fecha, help="fin del período (YYYY-MM-DD)")
    p.add_argument("--destinatarios", help="lista separada por comas; reemplaza la de por defecto")
    p.add_argument("--dry-run", action="store_true", help="no envía: imprime y guarda el PDF")
    p.add_argument("--tipo", choices=[envio_log.AUTOMATICO, envio_log.MANUAL, envio_log.PRUEBA],
                   help="cómo queda registrado en el historial; por defecto se deduce del entorno")
    p.add_argument("--salida", default="salida", help="carpeta donde guardar el PDF en dry-run")
    p.add_argument("--notificar-error", dest="notificar_error", metavar="URL_DE_LA_CORRIDA",
                   help="no genera reporte: avisa a Franco que el envío automático falló")
    return p.parse_args(argv)


def _fecha(txt: str) -> date:
    return datetime.strptime(txt, "%Y-%m-%d").date()


def cargar(desde: date, hasta: date) -> dict:
    """Datos del dashboard filtrados al período, leyendo los Sheets en vivo."""
    from utils.data import cargar_crudos

    log.info("Leyendo Google Sheets…")
    crm, ventas = cargar_crudos()
    completos = construir_datos(crm, ventas, tuple(sorted(cargar_precios().items())))
    # estados_trabajo=None: entran todos los estados y vigentes() descarta los cancelados
    return aplicar_filtros(completos, desde, hasta, None)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = argumentos(argv)

    if args.notificar_error:
        return _avisar_error(args.notificar_error)

    if bool(args.desde) != bool(args.hasta):
        log.error("--desde y --hasta van juntos o no van.")
        return 2
    # --desde/--hasta mandan; si no, el periodo sale de semana_reporte() sobre la
    # fecha de corte (o sobre hoy en Argentina)
    if args.desde:
        desde, hasta = args.desde, args.hasta
    else:
        desde, hasta = semana_reporte(args.fecha_corte)
    if desde > hasta:
        log.error("--desde (%s) es posterior a --hasta (%s).", desde, hasta)
        return 2
    log.info("Modo: %s", args.modo)
    log.info("Período: %s (%s a %s)", etiqueta_periodo(desde, hasta), desde, hasta)

    # Se avisa temprano si falta configuracion, antes de leer Sheets y armar el PDF
    listo, motivo = configurado()
    if not listo and not args.dry_run:
        log.error("Envío no configurado: %s", motivo)
        return 3

    try:
        datos = cargar(desde, hasta)
    except Exception as e:
        log.error("No se pudieron leer los datos: %s", e)
        return 4

    k = kpis_semana(datos)
    clientes = top_clientes_semana(datos)
    log.info("Comisiones cobradas: %.2f | generadas: %.2f | por cobrar: %.2f",
             k["comision_cobrada"], k["comision_generada"], k["por_cobrar"])
    log.info("Has trabajadas: %.1f en %d trabajos | %d clientes",
             k["hectareas"], k["cantidad_servicios"], k["clientes"])

    if k["comision_generada"] == 0 and k["cantidad_servicios"] == 0:
        # No es un error: puede ser una semana sin movimiento. Se manda igual para
        # que el silencio no se confunda con un envio que fallo.
        log.warning("La semana no tiene movimiento en las planillas.")

    try:
        log.info("Generando PDF…")
        from utils.pdf import generar_pdf

        pdf = generar_pdf(datos, {
            "desde": desde, "hasta": hasta, "estados_trabajo": None,
            "estados_opciones": [], "granularidad": "Mensual",
        })
    except Exception as e:
        log.error("Falló la generación del PDF: %s", e)
        return 5
    log.info("PDF: %s bytes", f"{len(pdf):,}")

    destino = _destinatarios(args.destinatarios, args.modo)
    if not destino:
        log.error('No quedó ningún destinatario después de aplicar el filtro.')
        return 7
    # GITHUB_ACTIONS lo define el runner: distingue el envio del cron de una
    # corrida a mano sin que haya que acordarse de pasar --tipo
    tipo = args.tipo or (envio_log.AUTOMATICO if os.getenv("GITHUB_ACTIONS")
                         else envio_log.MANUAL)
    archivo = nombre_pdf(hasta)
    html = cuerpo_html(k, desde, hasta, clientes)

    if args.dry_run:
        carpeta = Path(args.salida)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / archivo).write_bytes(pdf)
        (carpeta / archivo.replace(".pdf", ".html")).write_text(html, encoding="utf-8")
        log.info("DRY-RUN: nada enviado. PDF y HTML en %s/", carpeta)
        log.info("DRY-RUN: se habría enviado a %s", ", ".join(destino))
        return 0

    # enviar_individual manda uno por uno: si alguno falla, se sabe cual. Un envio
    # con varios "to" falla para todos o para ninguno.
    resultado = enviar_individual(pdf, archivo, destino,
                                  asunto=asunto(desde, hasta, args.modo),
                                  html=html, periodo=etiqueta_periodo(desde, hasta))
    envio_log.registrar(resultado, tipo=tipo, periodo=etiqueta_periodo(desde, hasta),
                        usuario="scripts/enviar_reporte_semanal.py")

    for d in resultado["detalle"]:
        if d["exitoso"]:
            log.info("  OK      %s", d["email"])
        else:
            log.error("  FALLO   %s — %s", d["email"], d.get("error", ""))

    if resultado["fallidos"]:
        log.error("Enviado a %d de %d destinatarios.",
                  resultado["exitosos"], resultado["total"])
        # Parcial tambien es fallo: si Actions lo marca verde, nadie se entera
        return 6
    log.info("Enviado a %d destinatarios: %s", resultado["exitosos"], ", ".join(destino))
    return 0


def _avisar_error(url_corrida: str) -> int:
    """Le avisa SOLO a Franco que el envío automático falló.

    Un mail de error al equipo entero no le sirve a nadie: el unico que puede
    arreglarlo es quien tiene acceso a los secrets y a Actions.
    """
    from utils.email_sender import ErrorEnvioEmail, configurado, enviar_reporte

    listo, motivo = configurado()
    if not listo:
        # Si lo que fallo fue justamente la configuracion del envio, no hay forma
        # de avisar por mail. Queda el rojo del workflow.
        log.error("No se puede avisar por mail: %s", motivo)
        return 8

    momento = datetime.now(TZ_ARGENTINA).strftime("%d/%m/%Y %H:%M")
    html = f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1B2631">
  <h2 style="color:#C62828;margin:0 0 8px 0">⚠️ El reporte semanal no se envió</h2>
  <p>La corrida automática del {momento} (hora Argentina) falló, así que
     <strong>el equipo no recibió el reporte</strong>.</p>
  <p>Revisá el log de la corrida:<br>
     <a href="{url_corrida}" style="color:#1565C0;word-break:break-all">{url_corrida}</a></p>
  <p style="color:#5D6D7E;font-size:12px">
    Se puede reintentar a mano desde Actions → Reporte semanal Agropix → Run workflow.
  </p>
</div>"""
    try:
        enviar_reporte(b"%PDF-1.4 sin reporte", "sin-reporte.pdf",
                       destinatarios=[AVISO_DE_ERROR],
                       asunto="⚠️ Agropix — falló el envío del reporte semanal",
                       html=html)
    except ErrorEnvioEmail as e:
        log.error("Tampoco se pudo avisar del error: %s", e)
        return 8
    log.info("Aviso de falla enviado a %s", AVISO_DE_ERROR)
    return 0


def _destinatarios(crudo: str | None, modo: str) -> list[str]:
    """La lista final, siempre pasada por el filtro de destinatarios().

    Ni --destinatarios ni EMAIL_DESTINATARIOS pueden saltearse la exclusion:
    el filtro se aplica despues de elegir la fuente, no antes.
    """
    from config.settings import EMAIL_DESTINATARIOS

    if crudo:
        lista = [d.strip() for d in crudo.split(",") if d.strip()]
    elif modo == MODO_SEMANAL and EMAIL_DESTINATARIOS:
        lista = EMAIL_DESTINATARIOS
    else:
        lista = None
    return destinatarios(modo, lista)


if __name__ == "__main__":
    raise SystemExit(main())
