"""Chequeo de arranque: que los modulos tengan lo que las paginas esperan.

Por que existe
--------------
Streamlit Cloud recarga el archivo de la pagina cuando cambia, pero NO reimporta
los modulos que ya tenia en memoria. Si un deploy toca una pagina y un modulo a
la vez, la pagina nueva puede quedar corriendo contra el modulo viejo y reventar
con un KeyError sobre una clave que en el repositorio si existe.

Paso tres veces (comision_generada, ingresos, trabajos) y cada vez la app se caia
con un traceback que no dice nada util. Esto lo convierte en un mensaje que dice
exactamente que hacer: reiniciar.

No reemplaza a los tests: es una red de seguridad de despliegue, no de logica.
"""
from __future__ import annotations

import pandas as pd

# Lo que cada funcion tiene que devolver para que las paginas no rompan.
# Agregar aca una clave nueva es parte de agregarla al modulo.
CONTRATO: dict[str, tuple[str, ...]] = {
    "utils.comisiones:kpis_comisiones": (
        "ingresos", "comision_cobrada", "comision_generada", "por_cobrar", "pct_cobranza",
        "generada_equipos", "cobrada_equipos", "generado_servicios", "cobrado_servicios",
        "volumen_equipos", "hectareas", "cantidad_servicios", "clientes",
    ),
    "utils.comisiones:ticket_promedio_equipos": (
        "cantidad", "comision_cobrada", "comision_generada", "ticket_cobrado", "ticket_generado",
    ),
    "utils.comisiones:ticket_promedio_servicios": (
        "cantidad", "ingreso", "ticket", "hectareas", "valor_por_ha",
    ),
    "utils.data:kpis_servicios": (
        "ventas", "hectareas", "clientes", "trabajos", "trabajos_totales",
        "trabajos_sin_monto", "ticket_promedio",
    ),
    "utils.data:kpis_equipos": (
        "unidades", "operaciones", "monto", "comision_cobrada", "comision_por_cobrar",
        "ticket_promedio", "ops_pendientes", "monto_pendiente",
    ),
}

_COLUMNAS_SERVICIOS = ["fecha", "cliente", "monto", "hectareas", "estado_cobro",
                       "unidad_negocio", "ultima_accion"]
_COLUMNAS_EQUIPOS = ["id_operacion", "fecha", "cliente", "comision", "factura", "cobrado",
                     "estado_cobro", "unidad_negocio", "unidades", "canal", "vendedor",
                     "pendiente_precio"]
_COLUMNAS_UNIDADES = ["id_operacion", "modelo", "precio_lista", "peso", "monto_asignado",
                      "pendiente_precio", "comision", "cobrado", "estado_cobro"]


def _vacio(columnas: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columnas})


def faltantes() -> dict[str, list[str]]:
    """{funcion: claves que faltan}. Vacio si todo esta al dia.

    Se llama a cada funcion con DataFrames vacios: no toca Google Sheets, no
    depende de que haya datos y tarda microsegundos.
    """
    from utils.comisiones import (
        kpis_comisiones, ticket_promedio_equipos, ticket_promedio_servicios,
    )
    from utils.data import kpis_equipos, kpis_servicios

    sv, eq, un = (_vacio(_COLUMNAS_SERVICIOS), _vacio(_COLUMNAS_EQUIPOS),
                  _vacio(_COLUMNAS_UNIDADES))
    resultados = {
        "utils.comisiones:kpis_comisiones": lambda: kpis_comisiones(sv, eq),
        "utils.comisiones:ticket_promedio_equipos": lambda: ticket_promedio_equipos(eq, un),
        "utils.comisiones:ticket_promedio_servicios": lambda: ticket_promedio_servicios(sv),
        "utils.data:kpis_servicios": lambda: kpis_servicios(sv),
        "utils.data:kpis_equipos": lambda: kpis_equipos(eq, un),
    }

    problemas = {}
    for nombre, llamar in resultados.items():
        try:
            devuelto = llamar()
        except Exception as e:
            problemas[nombre] = [f"no se pudo ejecutar: {type(e).__name__}"]
            continue
        faltan = [c for c in CONTRATO[nombre] if c not in devuelto]
        if faltan:
            problemas[nombre] = faltan
    return problemas


def verificar(st) -> None:
    """Corta la app con un mensaje accionable si los modulos quedaron viejos."""
    problemas = faltantes()
    if not problemas:
        return
    detalle = "\n".join(f"- `{f}` → falta {', '.join(c)}" for f, c in problemas.items())
    st.error(
        "**La app quedó con módulos viejos en memoria.**\n\n"
        "Esto pasa cuando un deploy actualiza una página pero el servidor sigue con "
        "la versión anterior de un módulo ya importado. El código del repositorio "
        "está bien; lo que hay que hacer es reiniciar.\n\n"
        "**Solución:** *Manage app* (abajo a la derecha) → **Reboot app**. "
        "Tarda un minuto y no se pierde nada.\n\n"
        f"Detalle técnico:\n{detalle}",
        icon="🔄",
    )
    st.stop()
