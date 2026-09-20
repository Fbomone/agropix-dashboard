"""Historial de envios de reportes por mail.

Guarda una linea JSON por envio (formato JSONL: un objeto por linea) para poder
agregar sin releer ni reescribir el archivo entero, y para que un archivo
truncado a la mitad no arruine todo el historial.

Persistencia
------------
En Streamlit Cloud el filesystem es EFIMERO: este archivo se borra en cada
reinicio del contenedor. El historial sirve para la sesion en curso y para el
uso local; lo que queda de verdad son los logs de consola (Manage app -> Logs) y
el Activity Feed de SendGrid. Si el historial tiene que sobrevivir, hay que
llevarlo a un Sheet o una base.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")
ARCHIVO = Path(os.getenv("AGROPIX_ENVIO_LOG", "data/envios.jsonl"))

MANUAL, AUTOMATICO, PRUEBA = "MANUAL", "AUTOMATICO", "PRUEBA"

_logger = logging.getLogger("agropix.envios")


def registrar(resultado: dict, tipo: str = MANUAL, periodo: str = "",
              usuario: str = "-", archivo: Path | None = None) -> dict:
    """Agrega un envio al historial y devuelve la entrada guardada.

    resultado: salida de email_sender.enviar_individual() — exitosos, fallidos,
    total y el detalle por destinatario.
    """
    entrada = {
        "momento": datetime.now(TZ_ARGENTINA).isoformat(timespec="seconds"),
        "tipo": tipo,
        "periodo": periodo,
        "usuario": usuario,
        "exitosos": int(resultado.get("exitosos", 0)),
        "fallidos": int(resultado.get("fallidos", 0)),
        "total": int(resultado.get("total", 0)),
        "estado": estado(resultado),
        "detalle": resultado.get("detalle", []),
    }
    _logger.info("ENVIO %s %s %s/%s", tipo, entrada["estado"], entrada["exitosos"], entrada["total"])

    destino = archivo or ARCHIVO
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    except OSError as e:
        _logger.warning("No se pudo escribir el historial de envios: %s", e)
    return entrada


def estado(resultado: dict) -> str:
    """OK si todos llegaron, PARCIAL si algunos, ERROR si ninguno."""
    exitosos = int(resultado.get("exitosos", 0))
    fallidos = int(resultado.get("fallidos", 0))
    if exitosos and not fallidos:
        return "OK"
    if exitosos and fallidos:
        return "PARCIAL"
    return "ERROR"


def historial(limite: int = 50, archivo: Path | None = None) -> list[dict]:
    """Los ultimos `limite` envios, del mas reciente al mas viejo.

    Una linea corrupta se saltea en vez de romper la lectura: el historial es
    informativo y vale mas mostrar lo que se pueda leer que fallar entero.
    """
    origen = archivo or ARCHIVO
    try:
        lineas = origen.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    entradas = []
    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue
        try:
            entradas.append(json.loads(linea))
        except json.JSONDecodeError:
            _logger.warning("Línea ilegible en el historial de envíos, se saltea.")
    return list(reversed(entradas))[:limite]


def resumen(entradas: list[dict]) -> dict:
    """Totales para mostrar arriba del historial."""
    return {
        "envios": len(entradas),
        "ok": sum(1 for e in entradas if e.get("estado") == "OK"),
        "parciales": sum(1 for e in entradas if e.get("estado") == "PARCIAL"),
        "errores": sum(1 for e in entradas if e.get("estado") == "ERROR"),
        "ultimo": entradas[0]["momento"] if entradas else None,
    }
