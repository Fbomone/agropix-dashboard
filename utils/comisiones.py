"""Comisiones: la metrica de verdad del negocio Agropix.

Por que este modulo
-------------------
Agropix cobra de dos formas distintas y no son comparables:

- SERVICIOS: se queda con todo lo facturado ("Valor total de ventas").
- EQUIPOS  : se queda solo con la comision ("Comision $"). La "Factura s/IVA"
             es plata del cliente al proveedor: volumen intermediado, no ingreso.

Las funciones de utils/data.py ya calculan el ingreso consolidado. Este modulo
agrega la vista que faltaba: comisiones GENERADAS vs COBRADAS vs POR COBRAR,
clasificacion por marca (Agras T / Mavic / accesorios), ticket promedio medido
en comision y cortes por canal y vendedor.

Reglas que vienen de los datos, no de supuestos
-----------------------------------------------
- "Comision %" y "Comision cobrada" estan VACIAS en el Sheet de Ventas. Las
  unicas fuentes reales son "Comision $" y "Cobrado" (si/no).
- La comision esta a nivel OPERACION, no por equipo. Una venta puede incluir
  varios modelos ("T100, Mavic 3M, RTK"), asi que atribuir comision a un modelo
  exige prorratear por precio de lista, y hay modelos sin precio cargado. Todo
  lo que se puede prorratear se marca; el resto se informa como no atribuible.
  Ver cobertura_atribucion().
- Los servicios no tienen vendedor: el CRM trae Operador 1..4, que es quien
  ejecuta el trabajo. Por eso el ranking de vendedores es solo de equipos.
- Cancelados (trabajos) y devueltos (equipos) nunca suman: se filtran con
  vigentes() de utils/data.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from utils.data import clientes_unicos, columna_mes, normalizar, vigentes

# ---------------------------------------------------------------------------
# Clasificacion de modelos
# ---------------------------------------------------------------------------
AGRAS_T = "Agras T"
MAVIC = "Mavic"
ACCESORIO = "Accesorio"
OTRO = "Otro"

# Marcas que el negocio mira: son los drones. El resto de lo que aparece en la
# columna Modelo son accesorios y software que se venden junto al equipo.
MARCAS_PRINCIPALES = (AGRAS_T, MAVIC)

# Modelos que NO son drones, por mas que esten en la misma celda que uno.
ACCESORIOS = ("MIXER JR", "RTK", "PIX4D")


def clasificar_modelo(modelo) -> str:
    """Agras T / Mavic / Accesorio / Otro.

    Los Agras se reconocen por empezar con T seguido de numero (T50, T70, T100):
    un startswith("T") pelado tambien atraparia cualquier modelo futuro con T,
    asi que se exige el digito.
    """
    nombre = normalizar(modelo).upper()
    if not nombre:
        return OTRO
    if any(nombre.startswith(normalizar(a).upper()) for a in ACCESORIOS):
        return ACCESORIO
    if nombre.startswith("MAVIC"):
        return MAVIC
    if len(nombre) > 1 and nombre[0] == "T" and nombre[1].isdigit():
        return AGRAS_T
    return OTRO


def con_marca(unidades: pd.DataFrame) -> pd.DataFrame:
    """unidades + columna `marca` (una fila por equipo vendido)."""
    u = vigentes(unidades)
    if u.empty:
        return u.assign(marca=pd.Series(dtype="string"))
    return u.assign(marca=pd.array([clasificar_modelo(m) for m in u["modelo"]], dtype="string"))


def es_principal(unidades: pd.DataFrame) -> pd.Series:
    """True para las unidades que son drones Agras T o Mavic."""
    marcas = con_marca(unidades)["marca"] if "marca" not in unidades.columns else unidades["marca"]
    return marcas.isin(MARCAS_PRINCIPALES)


# ---------------------------------------------------------------------------
# KPIs de comisiones
# ---------------------------------------------------------------------------
def kpis_comisiones(servicios: pd.DataFrame, ops: pd.DataFrame) -> dict:
    """Comisiones generadas / cobradas / por cobrar, y el ingreso consolidado.

    Para equipos "comision" es literalmente la columna Comision $.
    Para servicios no hay comision: el ingreso es lo facturado, y el estado de
    cobro sale de "Ultima accion" (Cobro recibido = cobrado).
    """
    s, e = vigentes(servicios), vigentes(ops)

    cobrada_eq = _suma(e.loc[_cobrado(e), "comision"]) if not e.empty else 0.0
    por_cobrar_eq = _suma(e.loc[~_cobrado(e), "comision"]) if not e.empty else 0.0
    generada_eq = cobrada_eq + por_cobrar_eq

    if s.empty:
        cobrado_sv = por_cobrar_sv = generado_sv = 0.0
    else:
        from utils.data import COBRADO

        generado_sv = _suma(s["monto"])
        cobrado_sv = _suma(s.loc[s["estado_cobro"] == COBRADO, "monto"])
        por_cobrar_sv = generado_sv - cobrado_sv

    generada = generada_eq + generado_sv
    cobrada = cobrada_eq + cobrado_sv
    por_cobrar = por_cobrar_eq + por_cobrar_sv

    return {
        # Consolidado: es lo que va en los KPIs grandes del Reporte General
        "comision_generada": generada,
        "comision_cobrada": cobrada,
        "por_cobrar": por_cobrar,
        "pct_cobranza": cobrada / generada if generada else 0.0,
        # Desglose por unidad de negocio
        "generada_equipos": generada_eq,
        "cobrada_equipos": cobrada_eq,
        "por_cobrar_equipos": por_cobrar_eq,
        "generado_servicios": generado_sv,
        "cobrado_servicios": cobrado_sv,
        "por_cobrar_servicios": por_cobrar_sv,
        "pct_equipos": cobrada_eq / cobrada if cobrada else 0.0,
        "pct_servicios": cobrado_sv / cobrada if cobrada else 0.0,
        # Volumen intermediado: informativo, NO es ingreso de Agropix
        "volumen_equipos": _suma(e["factura"]) if not e.empty else 0.0,
        # Servicios
        "hectareas": _suma(s["hectareas"]) if not s.empty else 0.0,
        "cantidad_servicios": int(len(s)),
        "clientes": _clientes(s, e),
    }


def _suma(serie: pd.Series) -> float:
    return float(pd.to_numeric(serie, errors="coerce").fillna(0).sum())


def _cobrado(ops: pd.DataFrame) -> pd.Series:
    return ops["cobrado"].astype(bool)


def _clientes(servicios: pd.DataFrame, ops: pd.DataFrame) -> int:
    partes = [df["cliente"] for df in (servicios, ops) if not df.empty and "cliente" in df.columns]
    return clientes_unicos(pd.concat(partes, ignore_index=True)) if partes else 0


# ---------------------------------------------------------------------------
# Ticket promedio medido en comision
# ---------------------------------------------------------------------------
def ticket_promedio_equipos(ops: pd.DataFrame, unidades: pd.DataFrame,
                            solo_principales: bool = True) -> dict:
    """Comision cobrada por equipo vendido.

    El divisor son UNIDADES, no operaciones: una venta puede llevar 3 drones y
    contarla como una sola distorsionaria el ticket. Por defecto solo cuenta
    Agras T y Mavic, que es lo que el negocio considera "equipo".
    """
    e = vigentes(ops)
    u = con_marca(unidades)
    if solo_principales and not u.empty:
        u = u[u["marca"].isin(MARCAS_PRINCIPALES)]

    cantidad = int(len(u))
    cobrada = _suma(e.loc[_cobrado(e), "comision"]) if not e.empty else 0.0
    generada = _suma(e["comision"]) if not e.empty else 0.0
    return {
        "cantidad": cantidad,
        "comision_cobrada": cobrada,
        "comision_generada": generada,
        "ticket_cobrado": cobrada / cantidad if cantidad else 0.0,
        "ticket_generado": generada / cantidad if cantidad else 0.0,
    }


def ticket_promedio_servicios(servicios: pd.DataFrame) -> dict:
    """Ingreso por trabajo. En servicios el ingreso ES lo facturado."""
    s = vigentes(servicios)
    cantidad = int(len(s))
    total = _suma(s["monto"]) if not s.empty else 0.0
    hectareas = _suma(s["hectareas"]) if not s.empty else 0.0
    return {
        "cantidad": cantidad,
        "ingreso": total,
        "ticket": total / cantidad if cantidad else 0.0,
        "hectareas": hectareas,
        "valor_por_ha": total / hectareas if hectareas else 0.0,
    }


# ---------------------------------------------------------------------------
# Equipos por marca
# ---------------------------------------------------------------------------
def equipos_por_marca(unidades: pd.DataFrame) -> pd.DataFrame:
    """Cantidad de unidades por marca (Agras T, Mavic, Accesorio, Otro)."""
    u = con_marca(unidades)
    if u.empty:
        return pd.DataFrame(columns=["marca", "unidades", "operaciones", "principal"])
    r = u.groupby("marca", as_index=False).agg(
        unidades=("modelo", "size"), operaciones=("id_operacion", "nunique")
    )
    r["principal"] = r["marca"].isin(MARCAS_PRINCIPALES)
    return r.sort_values(["principal", "unidades"], ascending=False).reset_index(drop=True)


def equipos_por_modelo(unidades: pd.DataFrame, solo_principales: bool = True) -> pd.DataFrame:
    """Unidades y comision atribuida por modelo.

    `comision_atribuida` prorratea la comision de cada operacion entre sus
    modelos usando el peso por precio de lista (el mismo que utils/data.py usa
    para la factura). Las unidades de operaciones sin todos los precios de lista
    cargados quedan con comision NA: no se reparte con datos parciales.
    `unidades_sin_atribuir` dice cuantas son.
    """
    u = con_marca(unidades)
    if u.empty:
        return pd.DataFrame(columns=["modelo", "marca", "unidades", "comision_atribuida",
                                     "unidades_sin_atribuir"])
    if solo_principales:
        u = u[u["marca"].isin(MARCAS_PRINCIPALES)]
    if u.empty:
        return pd.DataFrame(columns=["modelo", "marca", "unidades", "comision_atribuida",
                                     "unidades_sin_atribuir"])

    peso = pd.to_numeric(u["peso"], errors="coerce")
    comision = pd.to_numeric(u["comision"], errors="coerce")
    u = u.assign(comision_unidad=peso * comision, sin_atribuir=peso.isna())

    r = u.groupby(["modelo", "marca"], as_index=False, observed=True).agg(
        unidades=("modelo", "size"),
        comision_atribuida=("comision_unidad", lambda s: s.sum(min_count=1)),
        unidades_sin_atribuir=("sin_atribuir", "sum"),
    )
    return r.sort_values(["unidades", "comision_atribuida"], ascending=False).reset_index(drop=True)


def cobertura_atribucion(unidades: pd.DataFrame) -> dict:
    """Cuanta comision se puede atribuir a un modelo y cuanta no.

    Sirve para avisar en pantalla en vez de mostrar un grafico que suma menos
    que el total sin explicar por que.
    """
    u = con_marca(unidades)
    if u.empty:
        return {"unidades": 0, "atribuibles": 0, "pct": 0.0, "modelos_sin_precio": []}
    atribuibles = int((~pd.to_numeric(u["peso"], errors="coerce").isna()).sum())
    sin_precio = sorted(
        u.loc[pd.to_numeric(u["precio_lista"], errors="coerce").isna(), "modelo"]
        .dropna().astype(str).unique().tolist()
    )
    total = int(len(u))
    return {
        "unidades": total,
        "atribuibles": atribuibles,
        "pct": atribuibles / total if total else 0.0,
        "modelos_sin_precio": sin_precio,
    }


# ---------------------------------------------------------------------------
# Cortes: canal y vendedor
# ---------------------------------------------------------------------------
def comisiones_por_canal(ops: pd.DataFrame) -> pd.DataFrame:
    """Comision por origen del lead. El volumen (Factura s/IVA) va como secundario."""
    return _agrupar_comisiones(ops, "canal", "Sin canal")


def ranking_vendedores(ops: pd.DataFrame) -> pd.DataFrame:
    """Vendedores ordenados por comision COBRADA (dinero, no cantidad).

    Solo equipos: el CRM de servicios no tiene vendedor (trae Operador 1..4,
    que es quien ejecuta el trabajo).
    """
    return _agrupar_comisiones(ops, "vendedor", "Sin vendedor")


def _agrupar_comisiones(ops: pd.DataFrame, columna: str, relleno: str) -> pd.DataFrame:
    cols = [columna, "comision_cobrada", "comision_generada", "por_cobrar",
            "pct_cobranza", "operaciones", "unidades", "volumen"]
    e = vigentes(ops)
    if e.empty or columna not in e.columns:
        return pd.DataFrame(columns=cols)

    e = e.assign(
        **{columna: e[columna].astype("string").fillna(relleno)},
        _cobrada=pd.to_numeric(e["comision"], errors="coerce").fillna(0) * _cobrado(e),
        _comision=pd.to_numeric(e["comision"], errors="coerce").fillna(0),
    )
    r = e.groupby(columna, as_index=False).agg(
        comision_cobrada=("_cobrada", "sum"),
        comision_generada=("_comision", "sum"),
        operaciones=("id_operacion", "size"),
        unidades=("unidades", "sum"),
        volumen=("factura", "sum"),
    )
    r["por_cobrar"] = r["comision_generada"] - r["comision_cobrada"]
    r["pct_cobranza"] = np.where(
        r["comision_generada"] > 0, r["comision_cobrada"] / r["comision_generada"], 0.0
    )
    return r[cols].sort_values("comision_cobrada", ascending=False).reset_index(drop=True)


def top_clientes(servicios: pd.DataFrame, ops: pd.DataFrame, top: int = 10) -> pd.DataFrame:
    """Clientes ordenados por ingreso real de Agropix (comision en equipos, facturado en servicios)."""
    partes = []
    s, e = vigentes(servicios), vigentes(ops)
    if not s.empty:
        partes.append(pd.DataFrame({
            "cliente": s["cliente"].astype("string").fillna("Sin cliente"),
            "servicios": pd.to_numeric(s["monto"], errors="coerce").fillna(0),
            "equipos": 0.0,
        }))
    if not e.empty:
        partes.append(pd.DataFrame({
            "cliente": e["cliente"].astype("string").fillna("Sin cliente"),
            "servicios": 0.0,
            "equipos": pd.to_numeric(e["comision"], errors="coerce").fillna(0),
        }))
    if not partes:
        return pd.DataFrame(columns=["cliente", "servicios", "equipos", "ingreso"])

    r = pd.concat(partes, ignore_index=True).groupby("cliente", as_index=False).sum()
    r["ingreso"] = r["servicios"] + r["equipos"]
    r = r[r["ingreso"] > 0].sort_values("ingreso", ascending=False)
    return r.head(top).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Evolucion temporal
# ---------------------------------------------------------------------------
def comisiones_por_mes(servicios: pd.DataFrame, ops: pd.DataFrame) -> pd.DataFrame:
    """Serie mensual de comision cobrada y por cobrar, para el grafico de evolucion."""
    filas = []
    s, e = vigentes(servicios), vigentes(ops)

    if not e.empty:
        eq = e[e["fecha"].notna()]
        if not eq.empty:
            comision = pd.to_numeric(eq["comision"], errors="coerce").fillna(0)
            filas.append(pd.DataFrame({
                "mes": columna_mes(eq["fecha"]),
                "cobrada": comision * _cobrado(eq),
                "generada": comision,
            }))
    if not s.empty:
        from utils.data import COBRADO

        sv = s[s["fecha"].notna()]
        if not sv.empty:
            monto = pd.to_numeric(sv["monto"], errors="coerce").fillna(0)
            filas.append(pd.DataFrame({
                "mes": columna_mes(sv["fecha"]),
                "cobrada": monto * (sv["estado_cobro"] == COBRADO).to_numpy(),
                "generada": monto,
            }))
    if not filas:
        return pd.DataFrame(columns=["mes", "cobrada", "generada", "por_cobrar"])

    r = pd.concat(filas, ignore_index=True).groupby("mes", as_index=False).sum()
    r["por_cobrar"] = r["generada"] - r["cobrada"]
    return r.sort_values("mes").reset_index(drop=True)
