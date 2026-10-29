"""Herramientas del Asistente IA (ver docs/ASISTENTE_IA.md).

El LLM nunca ve las planillas ni calcula: elige una herramienta de HERRAMIENTAS,
ejecutar() la corre con las funciones de utils/data.py y utils/comisiones.py y
el modelo redacta con el resultado. Asi los numeros del chat son los mismos que
los de las tarjetas.

Reglas de los resultados
------------------------
- dict serializable a JSON, chico: listas de MAX_FILAS como maximo.
- Montos redondeados a 2 decimales; porcentajes (claves pct*) como fraccion
  con 4 decimales, para no perder precision (0.8734, no 0.87).
- Siempre traen "periodo" con el desde/hasta efectivo.
- Sin datos: {"sin_datos": True, "periodo": ...}. Argumentos invalidos o un
  calculo que falla: {"error": "..."}; ejecutar() nunca lanza.
- Solo agregados: nunca filas crudas de las planillas.

Las funciones de herramienta son puras (reciben `datos`, sin st.*). De donde
salen esos datos lo resuelve ejecutar() con el `contexto` que arma la pagina.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime

import numpy as np
import pandas as pd

from utils import comisiones as cm
from utils.data import (
    GRANULARIDADES, POR_COBRAR, aplicar_filtros, cantidad_alertas, es_vacio, kpis_servicios, normalizar,
    rango_fechas, vigentes,
)
from utils.data import ingresos_por_periodo as _ingresos_por_periodo
from utils.data import resumen_operadores as _resumen_operadores

MAX_FILAS = 15
MAX_COINCIDENCIAS = 10
TOP_DEFAULT, TOP_MAX = 10, 15

# agrupar_por de resumen_servicios -> columna de servicios. "estado" es el
# estado del trabajo (Ultima accion), el mismo del filtro de la izquierda.
AGRUPACIONES_SERVICIOS = {
    "servicio": "servicio",
    "cultivo": "cultivo",
    "trabajo": "trabajo",
    "estado": "ultima_accion",
}

# Lo que pide la spec para kpis_generales, en este orden
CLAVES_KPIS = (
    "ingresos", "comision_cobrada", "por_cobrar", "pct_cobranza",
    "generada_equipos", "cobrada_equipos", "generado_servicios", "cobrado_servicios",
    "volumen_equipos", "hectareas", "cantidad_servicios", "clientes",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _limpio(valor, clave: str = ""):
    """Tipos de pandas/numpy -> JSON. Montos a 2 decimales, pct* a 4, NaN -> None."""
    if isinstance(valor, dict):
        return {str(k): _limpio(v, str(k)) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpio(v, clave) for v in valor]
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return None
    if isinstance(valor, (bool, np.bool_)):
        return bool(valor)
    if isinstance(valor, (int, np.integer)):
        return int(valor)
    if isinstance(valor, (float, np.floating)):
        valor = float(valor)
        if math.isnan(valor) or math.isinf(valor):
            return None
        return round(valor, 4 if clave.startswith("pct") else 2)
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%Y-%m-%d")
    if es_vacio(valor):
        return None
    return valor if isinstance(valor, str) else str(valor)


def _filas(df: pd.DataFrame, columnas: list) -> list:
    """Primeras MAX_FILAS filas como lista de dicts (solo las columnas pedidas)."""
    if df.empty:
        return []
    return df[columnas].head(MAX_FILAS).to_dict("records")


def _sin_datos() -> dict:
    return {"sin_datos": True}


def _sin_ventas(datos: dict) -> bool:
    return vigentes(datos["servicios"]).empty and vigentes(datos["equipos"]).empty


# ---------------------------------------------------------------------------
# Herramientas (funciones puras)
# ---------------------------------------------------------------------------

def kpis_generales(datos: dict) -> dict:
    """Los KPIs del Reporte General: kpis_comisiones() tal cual."""
    if _sin_ventas(datos):
        return _sin_datos()
    k = cm.kpis_comisiones(datos["servicios"], datos["equipos"])
    out = {c: k[c] for c in CLAVES_KPIS}
    out["nota"] = ("ingresos = servicios facturados + comisión de equipos. comision_cobrada y "
                   "por_cobrar son el total de ambas unidades. volumen_equipos es informativo, no ingreso.")
    return out


def ingresos_por_periodo(datos: dict, granularidad: str = "Mensual") -> dict:
    """Ingreso real por periodo (servicios + comision de equipos) y hectareas."""
    t = _ingresos_por_periodo(datos["servicios"], datos["equipos"], granularidad)
    if t.empty:
        return _sin_datos()
    return {
        "granularidad": granularidad,
        "periodos_totales": int(len(t)),
        "mostrando": f"últimos {min(len(t), MAX_FILAS)}",
        "filas": _filas(t.tail(MAX_FILAS), ["periodo_label", "ingreso_servicios", "ingreso_equipos",
                                             "total", "has_trabajadas"]),
    }


def top_clientes(datos: dict, n: int = TOP_DEFAULT) -> dict:
    """Clientes por ingreso de Agropix: comisiones.top_clientes()."""
    t = cm.top_clientes(datos["servicios"], datos["equipos"], top=n)
    if t.empty:
        return _sin_datos()
    return {"filas": _filas(t, ["cliente", "servicios", "equipos", "ingreso"]),
            "nota": "ingreso = servicios facturados + comisión de equipos (no la factura del equipo)."}


def _corte_comisiones(t: pd.DataFrame, columna: str, nota: str) -> dict:
    if t.empty:
        return _sin_datos()
    return {
        "cantidad": int(len(t)),
        "filas": _filas(t, [columna, "comision_cobrada", "comision_generada", "por_cobrar", "pct_cobranza",
                            "operaciones", "unidades", "volumen"]),
        "nota": nota,
    }


def ranking_vendedores(datos: dict) -> dict:
    """Vendedores de equipos por comision cobrada (servicios no tienen vendedor)."""
    return _corte_comisiones(cm.ranking_vendedores(datos["equipos"]), "vendedor",
                             "Solo equipos: los servicios no tienen vendedor. Ordenado por comisión cobrada.")


def comisiones_por_canal(datos: dict) -> dict:
    """Comision de equipos por origen del lead."""
    return _corte_comisiones(cm.comisiones_por_canal(datos["equipos"]), "canal",
                             "Solo equipos. volumen = factura intermediada, no ingreso.")


def equipos_por_modelo(datos: dict, solo_principales: bool = True) -> dict:
    """Unidades y comision atribuida por modelo, con la cobertura del reparto."""
    t = cm.equipos_por_modelo(datos["unidades"], solo_principales)
    if t.empty:
        return _sin_datos()
    cobertura = cm.cobertura_atribucion(datos["unidades"])
    return {
        "solo_principales": solo_principales,
        "filas": _filas(t, ["modelo", "marca", "unidades", "comision_atribuida", "unidades_sin_atribuir"]),
        "cobertura": cobertura,
        "cobertura_completa": cobertura["atribuibles"] == cobertura["unidades"],
        "nota": ("comision_atribuida reparte la comisión de cada venta por precio de lista; "
                 "las unidades de modelos sin precio quedan sin atribuir (comision_atribuida null)."),
    }


def resumen_servicios(datos: dict, agrupar_por: str = "servicio") -> dict:
    """kpis_servicios() + cantidad, hectareas y monto por la columna pedida."""
    s = vigentes(datos["servicios"])
    if s.empty:
        return _sin_datos()
    columna = AGRUPACIONES_SERVICIOS[agrupar_por]
    g = (s.assign(_grupo=s[columna].astype("string").fillna("Sin dato"))
         .groupby("_grupo", as_index=False)
         .agg(cantidad=("monto", "size"), hectareas=("hectareas", "sum"), monto=("monto", "sum"))
         .rename(columns={"_grupo": agrupar_por})
         .sort_values(["monto", "cantidad"], ascending=False))
    return {
        "kpis": kpis_servicios(datos["servicios"]),
        "agrupado_por": agrupar_por,
        "grupos_totales": int(len(g)),
        "filas": _filas(g, [agrupar_por, "cantidad", "hectareas", "monto"]),
    }


def pendientes_de_cobro(datos: dict) -> dict:
    """Por cliente: servicios Por cobrar y comision de equipos no cobrada."""
    s, e = vigentes(datos["servicios"]), vigentes(datos["equipos"])
    partes = []
    if not s.empty:
        sp = s[s["estado_cobro"] == POR_COBRAR]
        partes.append(pd.DataFrame({"cliente": sp["cliente"].astype("string").fillna("Sin cliente"),
                                    "servicios_pendiente": sp["monto"], "comision_pendiente": 0.0}))
    if not e.empty:
        ep = e[~e["cobrado"].astype(bool)]
        partes.append(pd.DataFrame({"cliente": ep["cliente"].astype("string").fillna("Sin cliente"),
                                    "servicios_pendiente": 0.0, "comision_pendiente": ep["comision"]}))
    partes = [p for p in partes if not p.empty]
    if not partes:
        return _sin_datos()

    r = pd.concat(partes, ignore_index=True).groupby("cliente", as_index=False).sum()
    r["total_pendiente"] = r["servicios_pendiente"] + r["comision_pendiente"]
    r = r[r["total_pendiente"] > 0].sort_values("total_pendiente", ascending=False)
    if r.empty:
        return _sin_datos()
    return {
        "total_pendiente": float(r["total_pendiente"].sum()),
        "total_servicios": float(r["servicios_pendiente"].sum()),
        "total_comision_equipos": float(r["comision_pendiente"].sum()),
        "clientes_con_pendiente": int(len(r)),
        "filas": _filas(r, ["cliente", "servicios_pendiente", "comision_pendiente", "total_pendiente"]),
    }


def buscar_cliente(datos: dict, nombre: str) -> dict:
    """Resumen de un cliente; si el nombre es ambiguo, la lista de candidatos."""
    buscado = normalizar(nombre)
    s, e = vigentes(datos["servicios"]), vigentes(datos["equipos"])
    nombres = pd.concat([s["cliente"], e["cliente"]], ignore_index=True).dropna().astype(str)
    claves = nombres.map(normalizar)
    candidatos = nombres[claves.str.contains(buscado, regex=False)]
    if candidatos.empty:
        return {"sin_datos": True, "motivo": f"No hay clientes que coincidan con «{nombre}» en el período."}

    # misma persona con distinta grafia: se agrupa por nombre normalizado y se
    # muestra la grafia mas usada
    por_clave = candidatos.groupby(candidatos.map(normalizar)).agg(lambda x: x.value_counts().index[0])
    if buscado in por_clave.index:
        clave = buscado
    elif len(por_clave) == 1:
        clave = por_clave.index[0]
    else:
        return {
            "ambiguo": True,
            "coincidencias": sorted(por_clave.tolist(), key=normalizar)[:MAX_COINCIDENCIAS],
            "total_coincidencias": int(len(por_clave)),
            "nota": "Hay varios clientes con ese nombre: pedile al usuario que aclare cuál.",
        }

    sc = s[s["cliente"].map(normalizar) == clave] if not s.empty else s
    ec = e[e["cliente"].map(normalizar) == clave] if not e.empty else e
    pend_sv = float(sc.loc[sc["estado_cobro"] == POR_COBRAR, "monto"].sum()) if not sc.empty else 0.0
    pend_eq = float(ec.loc[~ec["cobrado"].astype(bool), "comision"].sum()) if not ec.empty else 0.0
    return {
        "cliente": por_clave[clave],
        "trabajos": int(len(sc)),
        "hectareas": float(sc["hectareas"].sum()) if not sc.empty else 0.0,
        "monto_servicios": float(sc["monto"].sum()) if not sc.empty else 0.0,
        "operaciones_equipos": int(len(ec)),
        "equipos_comprados": int(ec["unidades"].sum()) if not ec.empty else 0,
        "comision_equipos": float(ec["comision"].sum()) if not ec.empty else 0.0,
        "pendiente_servicios": pend_sv,
        "pendiente_comision_equipos": pend_eq,
        "pendiente_total": pend_sv + pend_eq,
    }


def resumen_operadores(datos: dict) -> dict:
    """Hectareas y trabajos por operador (solo/acompañado)."""
    t = _resumen_operadores(datos["operadores"])
    if t.empty:
        return _sin_datos()
    return {
        "operadores_totales": int(len(t)),
        "filas": _filas(t, ["operador", "has", "trabajos", "trabajos_solo", "trabajos_acompanado",
                            "pct_solo", "pct_acompanado"]),
        "nota": "Las has por operador pueden sumar más que las del trabajo: trabajan en simultáneo.",
    }


def calidad_de_datos(datos: dict) -> dict:
    """Cantidad de alertas por tipo. Sin filas: nombres de cliente ni valores crudos."""
    c = datos["calidad"]
    sin_precio = c["modelos_sin_precio"]
    return {
        "tipos_de_alerta_activos": cantidad_alertas(c),
        "columnas_faltantes": {origen: list(cols) for origen, cols in c["columnas_faltantes"].items()},
        "fechas_invalidas": int(len(c["fechas_invalidas"])),
        "montos_cero": int(len(c["montos_cero"])),
        "modelos_sin_precio": _filas(sin_precio, ["modelo", "unidades"]) if not sin_precio.empty else [],
        "nota": "El detalle fila por fila está en la página Configuración.",
    }


FUNCIONES = {
    "kpis_generales": kpis_generales,
    "ingresos_por_periodo": ingresos_por_periodo,
    "top_clientes": top_clientes,
    "ranking_vendedores": ranking_vendedores,
    "comisiones_por_canal": comisiones_por_canal,
    "equipos_por_modelo": equipos_por_modelo,
    "resumen_servicios": resumen_servicios,
    "pendientes_de_cobro": pendientes_de_cobro,
    "buscar_cliente": buscar_cliente,
    "resumen_operadores": resumen_operadores,
    "calidad_de_datos": calidad_de_datos,
}


# ---------------------------------------------------------------------------
# Esquemas para el LLM (formato OpenAI)
# ---------------------------------------------------------------------------

_PERIODO = {
    "desde": {"type": "string", "description": "Inicio del período, YYYY-MM-DD. Omitir para usar el filtro actual."},
    "hasta": {"type": "string", "description": "Fin del período (inclusive), YYYY-MM-DD. Omitir para usar el filtro actual."},
}


def _esquema(nombre: str, descripcion: str, propiedades: dict | None = None, requeridos=(),
             con_periodo: bool = True) -> dict:
    props = dict(propiedades or {})
    if con_periodo:
        props.update(_PERIODO)
    return {"type": "function", "function": {
        "name": nombre,
        "description": descripcion,
        "parameters": {"type": "object", "properties": props, "required": list(requeridos)},
    }}


HERRAMIENTAS = [
    _esquema("kpis_generales",
             "Totales del período: ingresos de Agropix, cobrado, por cobrar, % de cobranza, desglose "
             "servicios/equipos, volumen intermediado, hectáreas, cantidad de servicios y clientes. "
             "Usar para: cuánto facturamos, cuánto ingresó, ingresos totales, cuánto cobramos, "
             "hectáreas trabajadas, cuántos clientes."),
    _esquema("ingresos_por_periodo",
             "Evolución del ingreso (servicios + comisión de equipos) y hectáreas por período. "
             "Usar para: cómo vienen los ingresos mes a mes, por semana, trimestre o año, tendencia, "
             "mejor/peor mes.",
             {"granularidad": {"type": "string", "enum": list(GRANULARIDADES),
                               "description": "Agrupación temporal. Por defecto Mensual."}}),
    _esquema("top_clientes",
             "Ranking de clientes por ingreso para Agropix (servicios facturados + comisión de equipos). "
             "Usar para: mejores clientes, quién compró más, clientes más importantes.",
             {"n": {"type": "integer", "minimum": 1, "maximum": TOP_MAX,
                    "description": f"Cuántos clientes (1 a {TOP_MAX}). Por defecto {TOP_DEFAULT}."}}),
    _esquema("ranking_vendedores",
             "Vendedores de equipos ordenados por comisión cobrada, con generada, por cobrar, operaciones "
             "y unidades. Usar para: quién vendió más, mejor vendedor, desempeño de vendedores."),
    _esquema("comisiones_por_canal",
             "Comisión de equipos por origen del lead (canal). Usar para: de dónde vienen las ventas, "
             "qué canal rinde más."),
    _esquema("equipos_por_modelo",
             "Unidades vendidas y comisión atribuida por modelo de equipo, con la cobertura del reparto "
             "por precio de lista. Usar para: qué drones se venden más, cuántos T50/Mavic vendimos, "
             "comisión por modelo.",
             {"solo_principales": {"type": "boolean",
                                   "description": "true (defecto): solo drones Agras T y Mavic. "
                                                  "false: incluye accesorios (MIXER JR, RTK, PIX4D)."}}),
    _esquema("resumen_servicios",
             "KPIs de servicios (ventas, hectáreas, trabajos, ticket promedio) y desglose por servicio, "
             "cultivo, trabajo o estado del trabajo. Usar para: qué servicios hacemos más, hectáreas "
             "por cultivo, cuántos trabajos por estado.",
             {"agrupar_por": {"type": "string", "enum": list(AGRUPACIONES_SERVICIOS),
                              "description": "Columna de agrupación. Por defecto servicio."}}),
    _esquema("pendientes_de_cobro",
             "Lo que falta cobrar por cliente: servicios facturados o realizados sin cobrar y comisión "
             "de equipos no cobrada, con totales. Usar para: qué está pendiente de cobro, quién nos debe, "
             "deudores."),
    _esquema("buscar_cliente",
             "Resumen de un cliente: trabajos, hectáreas, monto de servicios, equipos comprados, comisión "
             "y pendiente. Ignora tildes y mayúsculas; si hay varios parecidos devuelve la lista para "
             "pedir aclaración. Usar para: preguntas sobre un cliente puntual.",
             {"nombre": {"type": "string", "description": "Nombre o parte del nombre del cliente."}},
             requeridos=("nombre",), con_periodo=False),
    _esquema("resumen_operadores",
             "Hectáreas y trabajos por operador de drones, solos o acompañados. Usar para: quién trabajó "
             "más, hectáreas por operador."),
    _esquema("calidad_de_datos",
             "Cantidad de alertas de calidad de las planillas (fechas inválidas, montos en cero, modelos "
             "sin precio de lista, columnas faltantes). Usar para: hay errores en los datos, qué falta "
             "cargar.",
             con_periodo=False),
]


# ---------------------------------------------------------------------------
# Despachador
# ---------------------------------------------------------------------------

class _ArgumentoInvalido(ValueError):
    pass


def _fecha(valor, campo: str) -> date | None:
    if valor is None or valor == "":
        return None
    try:
        return date.fromisoformat(str(valor).strip())
    except ValueError:
        raise _ArgumentoInvalido(f"'{campo}' debe ser una fecha YYYY-MM-DD (llegó {valor!r}).") from None


def _validar(nombre: str, args: dict) -> dict:
    """Parametros de la funcion pura, validados. Lanza _ArgumentoInvalido."""
    params = {}
    if nombre == "ingresos_por_periodo":
        g = args.get("granularidad") or "Mensual"
        opciones = {normalizar(o): o for o in GRANULARIDADES}
        if normalizar(g) not in opciones:
            raise _ArgumentoInvalido(f"granularidad debe ser una de {list(GRANULARIDADES)}.")
        params["granularidad"] = opciones[normalizar(g)]
    elif nombre == "top_clientes":
        n = args.get("n", TOP_DEFAULT)
        if isinstance(n, float) and n.is_integer():
            n = int(n)
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= TOP_MAX:
            raise _ArgumentoInvalido(f"n debe ser un entero entre 1 y {TOP_MAX}.")
        params["n"] = n
    elif nombre == "equipos_por_modelo":
        solo = args.get("solo_principales", True)
        if not isinstance(solo, bool):
            raise _ArgumentoInvalido("solo_principales debe ser true o false.")
        params["solo_principales"] = solo
    elif nombre == "resumen_servicios":
        agrupar = args.get("agrupar_por") or "servicio"
        if agrupar not in AGRUPACIONES_SERVICIOS:
            raise _ArgumentoInvalido(f"agrupar_por debe ser uno de {list(AGRUPACIONES_SERVICIOS)}.")
        params["agrupar_por"] = agrupar
    elif nombre == "buscar_cliente":
        texto = args.get("nombre")
        if not isinstance(texto, str) or not normalizar(texto):
            raise _ArgumentoInvalido("Falta el nombre del cliente a buscar.")
        params["nombre"] = texto
    return params


def _resolver_datos(args: dict, contexto: dict) -> tuple:
    """(datos, desde, hasta) segun la regla de la spec (seccion 3)."""
    desde, hasta = _fecha(args.get("desde"), "desde"), _fecha(args.get("hasta"), "hasta")
    if desde is None and hasta is None:
        datos = contexto["datos"]
        d, h = contexto.get("desde"), contexto.get("hasta")
        if d is None or h is None:
            d, h = rango_fechas(datos)
        return datos, d, h

    completos = contexto["datos_completos"]
    fmin, fmax = rango_fechas(completos)
    desde = desde or fmin or hasta
    hasta = hasta or fmax or desde
    if desde > hasta:
        raise _ArgumentoInvalido("'desde' no puede ser posterior a 'hasta'.")
    return aplicar_filtros(completos, desde, hasta, contexto.get("estados_trabajo")), desde, hasta


def ejecutar(nombre: str, argumentos, contexto: dict) -> dict:
    """Corre la herramienta `nombre` y devuelve su resultado JSON-able. Nunca lanza.

    `argumentos`: dict o el string JSON tal como lo manda el modelo.
    `contexto`: {"datos", "datos_completos", "estados_trabajo", "desde", "hasta"}
    (desde/hasta = periodo del filtro de la izquierda).
    """
    funcion = FUNCIONES.get(nombre)
    if funcion is None:
        return {"error": f"No existe la herramienta '{nombre}'."}
    if isinstance(argumentos, str):
        try:
            argumentos = json.loads(argumentos) if argumentos.strip() else {}
        except json.JSONDecodeError:
            return {"error": "Los argumentos no son JSON válido."}
    if not isinstance(argumentos, dict):
        return {"error": "Los argumentos deben ser un objeto JSON."}

    try:
        params = _validar(nombre, argumentos)
        datos, desde, hasta = _resolver_datos(argumentos, contexto)
    except _ArgumentoInvalido as e:
        return {"error": str(e)}

    try:
        resultado = funcion(datos, **params)
    except Exception as e:  # el chat no muestra tracebacks
        return {"error": f"No se pudo calcular {nombre} ({type(e).__name__})."}

    resultado["periodo"] = {"desde": desde, "hasta": hasta,
                            "estados_trabajo": list(contexto.get("estados_trabajo") or [])}
    return _limpio(resultado)
