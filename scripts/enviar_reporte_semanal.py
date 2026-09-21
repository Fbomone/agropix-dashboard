#!/usr/bin/env python
"""Genera y envia el reporte semanal de Agropix. Corre fuera de Streamlit.

Lo dispara .github/workflows/reporte-semanal.yml los lunes 8:00 ART. Tambien
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
    DESTINATARIOS, asunto, cuerpo_html, etiqueta_periodo, kpis_semana, nombre_pdf,
    semana_cerrada, top_clientes_semana,
)

log = logging.getLogger("agropix.reporte")


def argumentos(argv=None):
    p = argparse.ArgumentParser(description="Reporte semanal de Agropix por mail")
    p.add_argument("--desde", type=_fecha, help="inicio del período (YYYY-MM-DD)")
    p.add_argument("--hasta", type=_fecha, help="fin del período (YYYY-MM-DD)")
    p.add_argument("--destinatarios", help="lista separada por comas; reemplaza la de por defecto")
    p.add_argument("--dry-run", action="store_true", help="no envía: imprime y guarda el PDF")
    p.add_argument("--tipo", choices=[envio_log.AUTOMATICO, envio_log.MANUAL, envio_log.PRUEBA],
                   help="cómo queda registrado en el historial; por defecto se deduce del entorno")
    p.add_argument("--salida", default="salida", help="carpeta donde guardar el PDF en dry-run")
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

    if bool(args.desde) != bool(args.hasta):
        log.error("--desde y --hasta van juntos o no van.")
        return 2
    desde, hasta = (args.desde, args.hasta) if args.desde else semana_cerrada()
    if desde > hasta:
        log.error("--desde (%s) es posterior a --hasta (%s).", desde, hasta)
        return 2
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

    destino = _destinatarios(args.destinatarios)
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
    resultado = enviar_individual(pdf, archivo, destino, asunto=asunto(desde, hasta),
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


def _destinatarios(crudo: str | None) -> list[str]:
    if crudo:
        return [d.strip() for d in crudo.split(",") if d.strip()]
    from config.settings import EMAIL_DESTINATARIOS

    return EMAIL_DESTINATARIOS or list(DESTINATARIOS)


if __name__ == "__main__":
    raise SystemExit(main())
