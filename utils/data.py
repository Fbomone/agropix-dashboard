"""Carga y transformacion compartida del dashboard Agropix.

Fuente: Google Sheets en vivo via src/google_sheets_connector.py. Las reglas de
negocio y los chequeos de calidad son funciones puras sobre DataFrames para
poder testearlas sin Streamlit.
"""
import collections
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from config.settings import CRM_SHEET_ID, CRM_TAB, PRECIOS_PATH, VENTAS_SHEET_ID, VENTAS_TAB
from src.google_sheets_connector import GoogleSheetsConnector

SERVICIO, EQUIPOS = "Servicio", "Equipos"
COBRADO, POR_COBRAR, EN_PROCESO, CANCELADO = "Cobrado", "Por cobrar", "En proceso", "Cancelado"
ESTADOS_COBRO = [COBRADO, POR_COBRAR, EN_PROCESO, CANCELADO]
SIN_MODELO = "Sin modelo"

# Estados que no cuentan como venta en KPIs ni graficos (si en las tablas de detalle)
ESTADOS_FUERA_DE_VENTA = {CANCELADO}

ESQUEMA_UNIFICADO = {
    "fecha": "datetime64[ns]",
    "cliente": "string",
    "unidad_negocio": "string",
    "monto": "float64",
    "estado_cobro": "string",
}
DOMINIOS_UNIFICADO = {"unidad_negocio": [SERVICIO, EQUIPOS], "estado_cobro": ESTADOS_COBRO}

# Valores de "Última acción" (estado del trabajo). El matcheo ignora tildes y mayusculas:
# en el Sheet llegan como "Envio de presupuesto" y "Trabajo Cancelado".
ESTADOS_TRABAJO = [
    "Cobro recibido", "Facturado esperando cobro", "Trabajo realizado", "Trabajo pendiente",
    "Envío de presupuesto", "Contrato enviado", "Consulta", "Aviso para realizar prueba", "Trabajo Cancelado",
]
# Trabajo efectivamente ejecutado: seleccion por defecto del filtro
ESTADOS_TRABAJO_EJECUTADO = ["Cobro recibido", "Facturado esperando cobro", "Trabajo realizado"]
SIN_ESTADO = "(sin estado)"

GRANULARIDADES = {"Semanal": "W-SUN", "Mensual": "M", "Trimestral": "Q", "Anual": "Y"}

# Columnas que consume el codigo: campo interno -> nombres aceptados en el Sheet.
# El matcheo ignora tildes, mayusculas y espacios de mas (ver col()).
COLUMNAS_CRM = {
    "fecha_trabajo": ("Fecha trabajo",),
    "fecha_contacto": ("Fecha de contacto",),
    "id_orden": ("ID Orden de trabajo",),
    "cliente": ("Nombre del cliente",),
    "id_cliente": ("Id Cliente",),
    "servicio": ("Producto/servicio de interés",),
    "trabajo": ("Trabajo",),
    "cultivo": ("Cultivo",),
    "ultima_accion": ("Última acción",),
    "hectareas": ("Has trabajadas",),
    "valor_ha": ("Valor por ha USD",),
    "monto": ("Valor total de ventas", "Valor total de venta"),
}
COLUMNAS_VENTAS = {
    "fecha": ("Fecha venta",),
    "fecha_entrega": ("Fecha de entrega", "Fecha entrega"),
    "cliente": ("Nombre",),
    "id_cliente": ("ID",),
    "modelos": ("Modelo",),
    "condicion": ("Condición",),
    "canal": ("Origen del leas", "Origen del lead"),
    "forma_pago": ("Forma de pago",),
    "estado": ("Estado",),
    "proveedor": ("Proveedor",),
    "vendedor": ("Vendedor",),
    "factura": ("Factura s/IVA",),
    "comision": ("Comisión $",),
    "cobrado": ("Cobrado",),
}


# ---------------------------------------------------------------------------
# Helpers de limpieza
# ---------------------------------------------------------------------------

def es_vacio(valor) -> bool:
    """None, NaN, NA o NaT (pd.NA no cuenta como escalar para numpy)."""
    return valor is None or (pd.api.types.is_scalar(valor) and bool(pd.isna(valor)))


def es_vacio_o_blanco(valor) -> bool:
    return es_vacio(valor) or (isinstance(valor, str) and not valor.strip())


def normalizar(valor) -> str:
    """Texto comparable: sin tildes, minusculas y espacios simples."""
    if es_vacio(valor):
        return ""
    txt = unicodedata.normalize("NFKD", str(valor))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return " ".join(txt.casefold().split())


def texto(serie) -> pd.Series:
    """Strings sin espacios de borde y vacios como NA."""
    s = pd.Series(serie).reset_index(drop=True).astype("string").str.strip()
    return s.mask(s == "", pd.NA)


# ---------------------------------------------------------------------------
# Columnas
# ---------------------------------------------------------------------------

def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """Headers con strip y espacios internos colapsados.

    El nombre original queda en df.attrs["columnas_originales"] ({limpio: original}).
    El matcheo sin tildes ni mayusculas lo resuelven buscar_columna() y col().
    """
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    originales = list(df.columns)
    out.columns = [" ".join(str(c).split()) for c in originales]
    out.attrs["columnas_originales"] = dict(zip(out.columns, originales))
    return out


def buscar_columna(df: pd.DataFrame, *nombres):
    """Nombre real de la primera columna que matchee alguno de `nombres`, o None."""
    reales = {}
    for c in df.columns:
        reales.setdefault(normalizar(c), c)
    for n in nombres:
        clave = normalizar(n)
        if clave in reales:
            return reales[clave]
    return None


def col(df: pd.DataFrame, *nombres) -> pd.Series:
    """Primera columna que matchee (sin tildes/mayusculas/espacios), o serie de NA."""
    real = buscar_columna(df, *nombres)
    if real is None:
        return pd.Series([pd.NA] * len(df), dtype=object)
    c = df[real]
    # si hay columnas duplicadas, df[real] devuelve DataFrame
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    return c.reset_index(drop=True)


def columnas_faltantes(df: pd.DataFrame, especificacion: dict) -> list:
    return [" / ".join(alias) for alias in especificacion.values() if buscar_columna(df, *alias) is None]


def filas_sheet(df: pd.DataFrame) -> pd.Series:
    """Numero de fila en el Sheet (el conector lo deja como indice)."""
    return pd.to_numeric(pd.Series(np.asarray(df.index)), errors="coerce").astype("Int64")


# ---------------------------------------------------------------------------
# Parseo
# ---------------------------------------------------------------------------

# Rango de negocio: cualquier fecha fuera de esto se considera basura de carga
FECHA_MIN = pd.Timestamp("2015-01-01")
FECHA_MAX = pd.Timestamp("2035-12-31 23:59:59")
_ORIGEN_SHEETS = pd.Timestamp("1899-12-30")
_SERIAL_MIN = (FECHA_MIN - _ORIGEN_SHEETS).days
_SERIAL_MAX = (FECHA_MAX - _ORIGEN_SHEETS).days + 1
# yyyy-mm-dd va aparte: con dayfirst=True, "2025-03-05" se leeria como 3 de mayo
_ISO = r"^\s*\d{4}-\d{1,2}-\d{1,2}"


def _en_rango_ns(fechas: pd.Series) -> pd.Series:
    """NaT fuera de rango y recien despues a datetime64[ns].

    En pandas 3 to_datetime devuelve datetime64[us]/[s], donde "225-02-11" es
    representable; convertir a ns antes de filtrar desborda (OutOfBoundsDatetime).
    """
    fechas = pd.to_datetime(fechas, errors="coerce")
    fuera = (fechas < FECHA_MIN) | (fechas > FECHA_MAX)
    return fechas.mask(fuera).dt.as_unit("ns")


def _parse_fecha_valor(v):
    """Camino lento, celda por celda. Nunca lanza."""
    try:
        if es_vacio(v):
            return pd.NaT
        if isinstance(v, (datetime, date)):
            ts = pd.Timestamp(v)
        elif isinstance(v, (int, float, np.number)) and not isinstance(v, bool):
            ts = _ORIGEN_SHEETS + pd.Timedelta(days=float(v)) if _SERIAL_MIN <= v <= _SERIAL_MAX else pd.NaT
        else:
            txt = str(v).strip()
            if re.match(_ISO, txt):
                ts = pd.to_datetime(txt, format="ISO8601", errors="coerce")
            else:
                ts = pd.to_datetime(txt, dayfirst=True, errors="coerce")
        return ts if FECHA_MIN <= ts <= FECHA_MAX else pd.NaT
    except Exception:
        return pd.NaT


def _parse_fecha_vectorizado(serie: pd.Series) -> pd.Series:
    # Camino 1: objetos fecha
    es_fecha = serie.map(lambda v: isinstance(v, (datetime, date)))
    directas = _en_rango_ns(serie.where(es_fecha))

    # Camino 2: serial de Google Sheets (dias desde 1899-12-30), solo si cae en rango
    numeros = pd.to_numeric(serie.where(~es_fecha), errors="coerce")
    numeros = numeros.where(numeros.between(_SERIAL_MIN, _SERIAL_MAX))
    desde_num = _en_rango_ns(pd.to_datetime(numeros, unit="D", origin=_ORIGEN_SHEETS, errors="coerce"))

    # Camino 3: texto ISO yyyy-mm-dd
    textos = serie.where(serie.map(lambda v: isinstance(v, str)))
    es_iso = textos.str.match(_ISO, na=False).astype(bool)
    desde_iso = _en_rango_ns(
        pd.to_datetime(textos.where(es_iso).str.strip(), format="ISO8601", errors="coerce")
    )

    # Camino 4: resto del texto, dd/mm/yyyy
    desde_local = _en_rango_ns(
        pd.to_datetime(textos.where(~es_iso), dayfirst=True, errors="coerce", format="mixed")
    )

    return directas.combine_first(desde_num).combine_first(desde_iso).combine_first(desde_local)


def parse_fecha(serie) -> pd.Series:
    """Fechas, seriales de Sheets o texto -> datetime64[ns].

    Todo lo que no parsea o cae fuera de FECHA_MIN..FECHA_MAX queda NaT. Nunca lanza.
    """
    serie = pd.Series(serie, dtype=object).reset_index(drop=True)
    if serie.empty:
        return pd.Series(dtype="datetime64[ns]")
    try:
        return _parse_fecha_vectorizado(serie)
    except Exception:
        return pd.Series([_parse_fecha_valor(v) for v in serie], dtype="datetime64[ns]")


def parse_monto(serie) -> pd.Series:
    """Numeros tal cual; texto en formato local ('$ 1.234,50'). Vacios -> 0."""
    serie = pd.Series(serie, dtype=object).reset_index(drop=True)
    if serie.empty:
        return pd.Series(dtype=float)
    es_num = serie.map(lambda v: isinstance(v, (int, float, np.number)) and not isinstance(v, bool))
    directo = pd.to_numeric(serie.where(es_num), errors="coerce")
    limpio = (
        serie.map(lambda v: "" if es_vacio(v) or isinstance(v, (int, float, np.number)) else str(v))
        .str.replace(r"[^\d,.\-]", "", regex=True)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    desde_txt = pd.to_numeric(limpio, errors="coerce")
    return directo.astype(float).combine_first(desde_txt.astype(float)).fillna(0.0)


def parse_id(serie) -> pd.Series:
    """Convierte IDs a string, sin '.0' de floats y con vacios como NA."""
    serie = pd.Series(serie).reset_index(drop=True)
    texto = (
        serie.astype("string")
        .str.strip()
        .str.replace(r"\.0+$", "", regex=True)
    )
    return texto.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})


def es_si(valor) -> bool:
    return normalizar(valor) in {"si", "s", "true", "yes"}


# ---------------------------------------------------------------------------
# Estado de cobro
# ---------------------------------------------------------------------------

_ACCION_A_COBRO = {
    "cobro recibido": COBRADO,
    "facturado esperando cobro": POR_COBRAR,
    "trabajo realizado": POR_COBRAR,
    "trabajo cancelado": CANCELADO,
}


def estado_cobro_servicio(ultima_accion) -> str:
    return _ACCION_A_COBRO.get(normalizar(ultima_accion), EN_PROCESO)


def estado_cobro_equipo(estado, cobrado) -> str:
    if normalizar(estado) == "devuelto":
        return CANCELADO
    if es_si(cobrado):
        return COBRADO
    return POR_COBRAR


# ---------------------------------------------------------------------------
# Precios de lista
# ---------------------------------------------------------------------------
# TODO: completar precio de lista de T50, T55, RTK, MIXER JR y Pix4D
#       (en precios_lista.json o desde la pagina Configuracion).
# TODO: confirmar si el "T55" de la base corresponde a T551, T552 o T553.
#       Si es uno solo, alcanza con cargarle a "T55" el mismo precio.

def precios_de_secrets() -> dict:
    """Precios cargados en st.secrets["precios_lista"], o {} si no hay.

    Es la unica forma de que un precio sobreviva en Streamlit Cloud: lo que se
    guarda con guardar_precios() va a precios_lista.json, dentro del contenedor,
    y ese disco se borra en cada reinicio. Un precio en los secrets persiste y
    ademas tiene efecto sin necesidad de redeployar.
    """
    try:
        import streamlit as st

        return dict(st.secrets.get("precios_lista") or {})
    except Exception:
        return {}


def _normalizar_precio(precio) -> float | None:
    valido = isinstance(precio, (int, float)) and not isinstance(precio, bool) and precio > 0
    return float(precio) if valido else None


def cargar_precios(path: Path = PRECIOS_PATH) -> dict:
    """{modelo: precio}; precio None = pendiente de confirmar.

    Los precios de st.secrets["precios_lista"] pisan a los del archivo: en Cloud
    son los unicos que no se pierden al reiniciarse el contenedor.
    """
    crudo = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    precios = {}
    for modelo, precio in crudo.items():
        modelo = str(modelo).strip()
        if modelo:
            precios[modelo] = _normalizar_precio(precio)

    for modelo, precio in precios_de_secrets().items():
        modelo = str(modelo).strip()
        if modelo:
            precios[modelo] = _normalizar_precio(precio)
    return precios


def guardar_precios(precios: dict, path: Path = PRECIOS_PATH) -> None:
    orden = sorted(precios.items(), key=lambda kv: (kv[1] is None, kv[0].casefold()))
    salida = {
        m: (int(p) if p is not None and float(p).is_integer() else p) for m, p in orden
    }
    path.write_text(json.dumps(salida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Transformaciones
# ---------------------------------------------------------------------------

def transformar_servicios(crm: pd.DataFrame) -> pd.DataFrame:
    df = crm if crm is not None else pd.DataFrame()

    def c(campo):
        return col(df, *COLUMNAS_CRM[campo])

    out = pd.DataFrame({
        "fila_sheet": filas_sheet(df),
        "fecha": parse_fecha(c("fecha_trabajo")).combine_first(parse_fecha(c("fecha_contacto"))),
        "id_orden": texto(c("id_orden")),
        "cliente": texto(c("cliente")),
        "id_cliente": parse_id(c("id_cliente")),
        "servicio": texto(c("servicio")),
        "trabajo": texto(c("trabajo")),
        "cultivo": texto(c("cultivo")),
        "ultima_accion": texto(c("ultima_accion")),
        "hectareas": parse_monto(c("hectareas")),
        "valor_ha": parse_monto(c("valor_ha")),
        "monto": parse_monto(c("monto")),
    })
    out["estado_cobro"] = pd.array([estado_cobro_servicio(a) for a in out["ultima_accion"]], dtype="string")
    out["unidad_negocio"] = pd.array([SERVICIO] * len(out), dtype="string")
    out = out[(out["monto"] > 0) | out["fecha"].notna()]
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Operadores (pares "Operador N" / "HasN")
# ---------------------------------------------------------------------------

_PATRON_OPERADOR = re.compile(r"^operador\s*(\d+)$")
_PATRON_HAS = re.compile(r"^has\s*(\d+)$")

COLUMNAS_OPERADORES = [
    "fila_sheet", "orden", "fecha", "cliente", "trabajo", "cultivo", "ultima_accion", "estado_cobro",
    "operador", "has_operador", "has_totales_trabajo", "cantidad_operadores_en_trabajo",
]


def pares_operador(df: pd.DataFrame) -> list:
    """[(n, columna_operador, columna_has | None)] detectados en los headers, ordenados por n."""
    operadores, has = {}, {}
    for c in df.columns:
        clave = normalizar(c)
        if m := _PATRON_OPERADOR.match(clave):
            operadores.setdefault(int(m.group(1)), c)
        elif m := _PATRON_HAS.match(clave):
            has.setdefault(int(m.group(1)), c)
    return [(n, operadores[n], has.get(n)) for n in sorted(operadores)]


def _operadores_vacio() -> pd.DataFrame:
    tipos = {"fila_sheet": "Int64", "fecha": "datetime64[ns]", "has_operador": "float64",
             "has_totales_trabajo": "float64", "cantidad_operadores_en_trabajo": "int64"}
    return pd.DataFrame({c: pd.Series(dtype=tipos.get(c, "string")) for c in COLUMNAS_OPERADORES})


def despivotar_operadores(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por (trabajo, operador) a partir de los pares Operador N / HasN del Sheet.

    La cantidad de pares se detecta de los headers. Cada operador registra las has que el
    ejecuto: la suma entre operadores no tiene por que coincidir con las has del trabajo.
    Pares con operador vacio se descartan; has vacias quedan NaN (operador sin has cargadas).
    """
    df = df if df is not None else pd.DataFrame()
    pares = pares_operador(df)
    if df.empty or not pares:
        return _operadores_vacio()

    def c(campo):
        return col(df, *COLUMNAS_CRM[campo])

    base = pd.DataFrame({
        "fila_sheet": filas_sheet(df),
        "orden": texto(c("id_orden")),
        "fecha": parse_fecha(c("fecha_trabajo")).combine_first(parse_fecha(c("fecha_contacto"))),
        "cliente": texto(c("cliente")),
        "trabajo": texto(c("trabajo")),
        "cultivo": texto(c("cultivo")),
        "ultima_accion": texto(c("ultima_accion")),
        "has_totales_trabajo": parse_monto(c("hectareas")),
    })
    base["estado_cobro"] = pd.array([estado_cobro_servicio(a) for a in base["ultima_accion"]], dtype="string")
    base["_trabajo"] = range(len(base))

    partes = []
    for _, columna_operador, columna_has in pares:
        if columna_has is None:
            has = pd.Series(np.nan, index=base.index)
        else:
            crudo = col(df, columna_has)
            has = parse_monto(crudo).where(~crudo.map(es_vacio_o_blanco).astype(bool))
        partes.append(base.assign(operador=texto(col(df, columna_operador)), has_operador=has))

    largo = pd.concat(partes, ignore_index=True)
    largo = largo[largo["operador"].notna()].copy()
    if largo.empty:
        return _operadores_vacio()

    # misma persona con distinta grafia ("Guido galetto" / "Guido Galetto"): queda el nombre mas usado
    clave = largo["operador"].map(normalizar)
    nombre = largo.groupby(clave)["operador"].agg(lambda s: s.value_counts().index[0])
    largo["operador"] = clave.map(nombre).astype("string")
    largo["cantidad_operadores_en_trabajo"] = (
        largo.groupby("_trabajo")["operador"].transform("size").astype("int64")
    )

    largo = largo.sort_values(["fecha", "_trabajo"], na_position="last")
    return largo[COLUMNAS_OPERADORES].reset_index(drop=True)


def resumen_operadores(largo: pd.DataFrame) -> pd.DataFrame:
    """Por operador: has, trabajos y cuantos hizo solo vs acompañado (con %)."""
    columnas = ["operador", "has", "trabajos", "trabajos_solo", "trabajos_acompanado",
                "pct_solo", "pct_acompanado"]
    if largo.empty:
        return pd.DataFrame(columns=columnas)
    l = largo.assign(operador=largo["operador"].astype(str),
                     solo=largo["cantidad_operadores_en_trabajo"] == 1)
    r = pd.DataFrame({
        "has": l.groupby("operador")["has_operador"].sum(),
        "trabajos": l.groupby("operador")["fila_sheet"].nunique(),
        "trabajos_solo": l[l["solo"]].groupby("operador")["fila_sheet"].nunique(),
        "trabajos_acompanado": l[~l["solo"]].groupby("operador")["fila_sheet"].nunique(),
    }).fillna(0)
    r = r.astype({"trabajos": "int64", "trabajos_solo": "int64", "trabajos_acompanado": "int64"})
    r["pct_solo"] = r["trabajos_solo"] / r["trabajos"]
    r["pct_acompanado"] = r["trabajos_acompanado"] / r["trabajos"]
    r = r.rename_axis("operador").reset_index()
    return r.sort_values(["has", "trabajos"], ascending=False).reset_index(drop=True)[columnas]


def separar_modelos(celda) -> list:
    """'T100, Mavic 3M' -> ['T100', 'Mavic 3M']; celda vacia -> ['Sin modelo']."""
    if es_vacio(celda):
        return [SIN_MODELO]
    partes = [p.strip() for p in str(celda).split(",") if p.strip()]
    return partes or [SIN_MODELO]


def desagregar_modelos(ops: pd.DataFrame, precios: dict) -> pd.DataFrame:
    """Una fila por equipo vendido, con la factura prorrateada por precio de lista.

    Solo afecta el analisis por modelo: la venta total sale de la factura de la operacion.
    Si algun modelo de la operacion no tiene precio, toda la operacion queda
    pendiente_precio=True y sin monto asignado (no se prorratea con datos parciales).
    """
    primeras = ["id_operacion", "modelo", "precio_lista", "peso", "monto_asignado", "pendiente_precio"]
    if ops.empty:
        return pd.DataFrame(columns=primeras + [c for c in ops.columns if c not in primeras])

    lookup = {normalizar(m): (m, p) for m, p in precios.items()}

    u = ops.copy()
    u["modelo"] = pd.Series([separar_modelos(c) for c in u["modelos"]], index=u.index, dtype=object)
    u = u.explode("modelo", ignore_index=True)

    encontrados = [lookup.get(normalizar(m)) for m in u["modelo"]]
    u["modelo"] = [e[0] if e else m for m, e in zip(u["modelo"], encontrados)]
    u["precio_lista"] = pd.to_numeric(
        pd.Series([e[1] if e else None for e in encontrados], dtype=object), errors="coerce"
    )

    grupo = u.groupby("id_operacion")["precio_lista"]
    falta_precio = u["precio_lista"].isna().groupby(u["id_operacion"]).transform("any")
    suma = grupo.transform("sum")
    u["pendiente_precio"] = (falta_precio | (suma <= 0)).astype(bool)
    u["peso"] = (u["precio_lista"] / suma).where(~u["pendiente_precio"])
    u["monto_asignado"] = u["peso"] * u["factura"]

    return u[primeras + [c for c in u.columns if c not in primeras]]


def transformar_equipos(ventas: pd.DataFrame, precios: dict) -> tuple:
    """Devuelve (operaciones, unidades): una fila por venta y una por equipo."""
    df = ventas if ventas is not None else pd.DataFrame()

    def c(campo):
        return col(df, *COLUMNAS_VENTAS[campo])

    ops = pd.DataFrame({
        "fila_sheet": filas_sheet(df),
        "fecha": parse_fecha(c("fecha")),
        "fecha_entrega": parse_fecha(c("fecha_entrega")),
        "cliente": texto(c("cliente")),
        "id_cliente": parse_id(c("id_cliente")),
        "modelos": texto(c("modelos")),
        "condicion": texto(c("condicion")),
        "canal": texto(c("canal")),
        "forma_pago": texto(c("forma_pago")),
        "estado": texto(c("estado")),
        "proveedor": texto(c("proveedor")),
        "vendedor": texto(c("vendedor")),
        "factura": parse_monto(c("factura")),
        "comision": parse_monto(c("comision")),
        "cobrado_raw": c("cobrado"),
    })
    ops = ops[ops["modelos"].notna() | (ops["factura"] > 0) | ops["fecha"].notna()]
    ops = ops.reset_index(drop=True)
    ops.insert(0, "id_operacion", range(1, len(ops) + 1))
    ops["cobrado"] = [es_si(v) for v in ops["cobrado_raw"]]
    ops["estado_cobro"] = pd.array(
        [estado_cobro_equipo(e, v) for e, v in zip(ops["estado"], ops["cobrado_raw"])], dtype="string"
    )
    ops["unidad_negocio"] = pd.array([EQUIPOS] * len(ops), dtype="string")
    ops = ops.drop(columns="cobrado_raw")

    unidades = desagregar_modelos(ops, precios)
    if ops.empty:
        ops["unidades"] = pd.Series(dtype=int)
        ops["pendiente_precio"] = pd.Series(dtype=bool)
    else:
        resumen = unidades.groupby("id_operacion").agg(
            unidades=("modelo", "size"), pendiente_precio=("pendiente_precio", "first")
        )
        ops = ops.join(resumen, on="id_operacion")
    return ops, unidades


def castear_esquema(df: pd.DataFrame, esquema: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for c, tipo in esquema.items():
        s = df[c] if c in df.columns else pd.Series([pd.NA] * len(df), index=df.index, dtype=object)
        if tipo.startswith("datetime64"):
            out[c] = _en_rango_ns(s)
        elif tipo == "float64":
            out[c] = pd.to_numeric(s, errors="coerce").fillna(0.0).astype("float64")
        else:
            out[c] = s.astype(tipo)
    return out


def unificar(servicios: pd.DataFrame, ops: pd.DataFrame) -> pd.DataFrame:
    """ventas_unificadas con ESQUEMA_UNIFICADO. Equipos: monto = Factura s/IVA por operacion."""
    cols = list(ESQUEMA_UNIFICADO)
    partes = [
        servicios.reindex(columns=cols),
        ops.rename(columns={"factura": "monto"}).reindex(columns=cols),
    ]
    partes = [p for p in partes if not p.empty]
    u = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=cols)
    u = castear_esquema(u, ESQUEMA_UNIFICADO)
    return u.sort_values("fecha", na_position="last").reset_index(drop=True)


def validar_esquema(df: pd.DataFrame, esquema: dict, dominios: dict | None = None) -> list:
    """Lista de problemas legibles; vacia si el DataFrame cumple el esquema."""
    problemas = []
    faltan = [c for c in esquema if c not in df.columns]
    sobran = [c for c in df.columns if c not in esquema]
    if faltan:
        problemas.append(f"faltan columnas: {', '.join(faltan)}")
    if sobran:
        problemas.append(f"columnas de más: {', '.join(map(str, sobran))}")
    for c, tipo in esquema.items():
        if c in df.columns and str(df[c].dtype) != tipo:
            problemas.append(f"`{c}` es {df[c].dtype}, se esperaba {tipo}")
    for c, validos in (dominios or {}).items():
        if c in df.columns:
            raros = sorted(set(map(str, df[c].dropna().unique())) - set(validos))
            if raros:
                problemas.append(f"`{c}` tiene valores fuera de {validos}: {raros}")
    return problemas


# ---------------------------------------------------------------------------
# Calidad de datos
# ---------------------------------------------------------------------------

def perfil_columnas(df: pd.DataFrame, especificacion: dict) -> pd.DataFrame:
    """Una fila por columna tal como llega del Sheet."""
    usadas = {}
    for campo, alias in especificacion.items():
        real = buscar_columna(df, *alias)
        if real is not None:
            usadas.setdefault(real, campo)

    filas = []
    for i, nombre in enumerate(df.columns):
        s = df.iloc[:, i]
        llenos = [v for v in s if not es_vacio_o_blanco(v)]
        tipos = collections.Counter(type(v).__name__ for v in llenos)
        filas.append({
            "columna": repr(nombre),
            "dtype": str(s.dtype),
            "tipos_python": ", ".join(f"{t} ({n})" for t, n in tipos.most_common()),
            "pct_nulos": 1 - len(llenos) / len(s) if len(s) else 0.0,
            "unicos": len({repr(v) for v in llenos}),
            "ejemplos": " | ".join(repr(v) for v in list(dict.fromkeys(llenos))[:3]),
            "usada_como": usadas.get(nombre, ""),
        })
    return pd.DataFrame(filas, columns=["columna", "dtype", "tipos_python", "pct_nulos", "unicos",
                                        "ejemplos", "usada_como"])


def _valor_crudo(v) -> str:
    return "(vacío)" if es_vacio_o_blanco(v) else repr(v)


def _serial_como_fecha(v) -> str:
    """Como se leeria un serial sin limitar el rango (para entender la basura)."""
    if isinstance(v, (int, float, np.number)) and not isinstance(v, bool) and not es_vacio(v):
        try:
            d = datetime(1899, 12, 30) + timedelta(days=float(v))
            return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
        except (OverflowError, ValueError):
            return "fuera de calendario"
    return ""


def _concat(frames: list) -> pd.DataFrame:
    no_vacios = [f for f in frames if not f.empty]
    return pd.concat(no_vacios, ignore_index=True) if no_vacios else frames[0]


def fechas_invalidas(df: pd.DataFrame, origen: str, especificacion: dict, campos: tuple) -> pd.DataFrame:
    """Celdas de fecha con contenido que no parsea o cae fuera de rango."""
    filas = []
    for campo in campos:
        real = buscar_columna(df, *especificacion[campo])
        if real is None:
            continue
        crudo = col(df, real)
        mask = ~crudo.map(es_vacio_o_blanco).astype(bool) & parse_fecha(crudo).isna()
        for fila, v in zip(filas_sheet(df)[mask], crudo[mask]):
            filas.append({"origen": origen, "columna": real, "fila_sheet": fila,
                          "valor_crudo": _valor_crudo(v), "leido_como": _serial_como_fecha(v)})
    out = pd.DataFrame(filas, columns=["origen", "columna", "fila_sheet", "valor_crudo", "leido_como"])
    return out.astype({"fila_sheet": "Int64"})


def montos_cero(df: pd.DataFrame, origen: str, especificacion: dict, campos_fecha: tuple,
                campo_monto: str, campo_estado: str) -> pd.DataFrame:
    """Filas con fecha y cliente pero monto 0: monto sin cargar o parseo fallido."""
    columnas = ["origen", "fila_sheet", "fecha", "cliente", "estado", "columna_monto", "valor_crudo"]
    real = buscar_columna(df, *especificacion[campo_monto])
    if real is None:  # la falta ya se informa en columnas_faltantes
        return pd.DataFrame(columns=columnas)

    fecha = parse_fecha(col(df, *especificacion[campos_fecha[0]]))
    for extra in campos_fecha[1:]:
        fecha = fecha.combine_first(parse_fecha(col(df, *especificacion[extra])))
    cliente = texto(col(df, *especificacion["cliente"]))
    crudo = col(df, real)

    tabla = pd.DataFrame({
        "origen": origen,
        "fila_sheet": filas_sheet(df),
        "fecha": fecha,
        "cliente": cliente,
        "estado": texto(col(df, *especificacion[campo_estado])),
        "columna_monto": real,
        "valor_crudo": [_valor_crudo(v) for v in crudo],
    }, columns=columnas)
    mask = (parse_monto(crudo) == 0) & fecha.notna() & cliente.notna()
    return tabla[mask.astype(bool)].reset_index(drop=True)


def modelos_sin_precio(unidades: pd.DataFrame) -> pd.DataFrame:
    if unidades.empty:
        return pd.DataFrame(columns=["modelo", "unidades", "operaciones"])
    u = unidades[unidades["precio_lista"].isna()]
    r = u.groupby("modelo", as_index=False).agg(
        unidades=("modelo", "size"), operaciones=("id_operacion", "nunique")
    )
    return r.sort_values("unidades", ascending=False).reset_index(drop=True)


def alertas_calidad(crm: pd.DataFrame, ventas: pd.DataFrame, unidades: pd.DataFrame) -> dict:
    return {
        "columnas_faltantes": {
            "CRM": columnas_faltantes(crm, COLUMNAS_CRM),
            "Ventas": columnas_faltantes(ventas, COLUMNAS_VENTAS),
        },
        "fechas_invalidas": _concat([
            fechas_invalidas(crm, "CRM", COLUMNAS_CRM, ("fecha_trabajo", "fecha_contacto")),
            fechas_invalidas(ventas, "Ventas", COLUMNAS_VENTAS, ("fecha", "fecha_entrega")),
        ]),
        "montos_cero": _concat([
            montos_cero(crm, "CRM", COLUMNAS_CRM, ("fecha_trabajo", "fecha_contacto"), "monto", "ultima_accion"),
            montos_cero(ventas, "Ventas", COLUMNAS_VENTAS, ("fecha",), "factura", "estado"),
        ]),
        "modelos_sin_precio": modelos_sin_precio(unidades),
    }


def cantidad_alertas(calidad: dict) -> int:
    """Cuantos tipos de alerta estan activos (0 a 4)."""
    return (
        int(any(calidad["columnas_faltantes"].values()))
        + int(not calidad["fechas_invalidas"].empty)
        + int(not calidad["montos_cero"].empty)
        + int(not calidad["modelos_sin_precio"].empty)
    )


# ---------------------------------------------------------------------------
# Carga (cacheada)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner="Leyendo Google Sheets...")
def cargar_crudos() -> tuple:
    """(crm_trabajos, ventas) tal como llegan; el indice es la fila del Sheet."""
    conn = GoogleSheetsConnector()
    return conn.read_tab(CRM_SHEET_ID, CRM_TAB), conn.read_tab(VENTAS_SHEET_ID, VENTAS_TAB)


@st.cache_data(show_spinner="Procesando...")
def construir_datos(crm: pd.DataFrame, ventas: pd.DataFrame, precios_items: tuple) -> dict:
    precios = dict(precios_items)
    crm_n, ventas_n = normalizar_columnas(crm), normalizar_columnas(ventas)
    servicios = transformar_servicios(crm_n)
    ops, unidades = transformar_equipos(ventas_n, precios)
    unificadas = unificar(servicios, ops)
    return {
        "servicios": servicios,
        "equipos": ops,
        "unidades": unidades,
        "ventas_unificadas": unificadas,
        "operadores": despivotar_operadores(crm_n),
        "perfil": {
            "CRM": {"filas": len(crm), "tabla": perfil_columnas(crm, COLUMNAS_CRM)},
            "Ventas": {"filas": len(ventas), "tabla": perfil_columnas(ventas, COLUMNAS_VENTAS)},
        },
        "calidad": alertas_calidad(crm_n, ventas_n, unidades),
        # Validacion final del modelo unificado; app.py la muestra como warning
        "problemas_esquema": validar_esquema(unificadas, ESQUEMA_UNIFICADO, DOMINIOS_UNIFICADO),
    }


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

def rango_fechas(datos: dict) -> tuple:
    fechas = pd.concat([datos["servicios"]["fecha"], datos["equipos"]["fecha"]]).dropna()
    if fechas.empty:
        return None, None
    return fechas.min().date(), fechas.max().date()


def filtrar_por_fecha(df: pd.DataFrame, desde, hasta) -> pd.DataFrame:
    if desde is None or hasta is None or df.empty or "fecha" not in df.columns:
        return df
    f = df["fecha"]
    mask = (f >= pd.Timestamp(desde)) & (f < pd.Timestamp(hasta) + pd.Timedelta(days=1))
    return df[mask].reset_index(drop=True)


def filtrar_datos(datos: dict, desde, hasta) -> dict:
    return {
        k: filtrar_por_fecha(v, desde, hasta) if isinstance(v, pd.DataFrame) else v
        for k, v in datos.items()
    }


def opciones_estado_trabajo(servicios: pd.DataFrame) -> list:
    """Estados conocidos + cualquier otro valor del Sheet (+ '(sin estado)' si hay vacios)."""
    opciones = list(ESTADOS_TRABAJO)
    if "ultima_accion" not in servicios.columns:
        return opciones
    conocidos = {normalizar(e) for e in ESTADOS_TRABAJO}
    extras = {}
    for valor in servicios["ultima_accion"].dropna():
        if normalizar(valor) not in conocidos:
            extras.setdefault(normalizar(valor), str(valor))
    opciones += sorted(extras.values(), key=normalizar)
    if servicios["ultima_accion"].isna().any():
        opciones.append(SIN_ESTADO)
    return opciones


def filtrar_por_estado_trabajo(df: pd.DataFrame, estados) -> pd.DataFrame:
    """Filtra por 'Última acción' sin distinguir tildes ni mayusculas. estados=None no filtra."""
    if estados is None or df.empty or "ultima_accion" not in df.columns:
        return df
    claves = {normalizar(e) for e in estados if e != SIN_ESTADO}
    norm = df["ultima_accion"].map(normalizar)
    mask = norm.isin(claves)
    if SIN_ESTADO in estados:
        mask = mask | (norm == "")
    return df[mask.astype(bool)].reset_index(drop=True)


def aplicar_filtros(datos: dict, desde, hasta, estados_trabajo=None) -> dict:
    """Periodo global + estado del trabajo (servicios y operadores).

    Rearma ventas_unificadas para que el Reporte General respete el mismo filtro de estado.
    """
    out = filtrar_datos(datos, desde, hasta)
    for clave in ("servicios", "operadores"):
        if clave in out:
            out[clave] = filtrar_por_estado_trabajo(out[clave], estados_trabajo)
    out["ventas_unificadas"] = unificar(out["servicios"], out["equipos"])
    return out


# ---------------------------------------------------------------------------
# Metricas
# ---------------------------------------------------------------------------

def vigentes(df: pd.DataFrame) -> pd.DataFrame:
    """Excluye cancelados/devueltos."""
    if df.empty:
        return df
    return df[~df["estado_cobro"].isin(ESTADOS_FUERA_DE_VENTA)]


def columna_mes(fechas: pd.Series) -> pd.Series:
    return fechas.dt.to_period("M").dt.to_timestamp()


def ticket_promedio(montos: pd.Series) -> float:
    m = montos[montos > 0]
    return float(m.mean()) if not m.empty else 0.0


def clientes_unicos(clientes: pd.Series) -> int:
    n = pd.Series([normalizar(c) for c in clientes])
    return int(n[n != ""].nunique())


def kpis_general(unif: pd.DataFrame) -> dict:
    """Venta total = Valor total de ventas (servicio) + Factura s/IVA (equipos), con o sin precio de lista."""
    v = vigentes(unif)
    total = float(v["monto"].sum())
    cobrado = float(v.loc[v["estado_cobro"] == COBRADO, "monto"].sum())
    por_cobrar = float(v.loc[v["estado_cobro"] == POR_COBRAR, "monto"].sum())
    en_proceso = float(v.loc[v["estado_cobro"] == EN_PROCESO, "monto"].sum())
    return {
        "venta_total": total,
        "cobrado": cobrado,
        "por_cobrar": por_cobrar,
        "en_proceso": en_proceso,
        "pct_cobrado": cobrado / total if total else 0.0,
        "pct_por_cobrar": por_cobrar / total if total else 0.0,
        "ticket_promedio": ticket_promedio(v["monto"]),
        "clientes": clientes_unicos(v.loc[v["monto"] > 0, "cliente"]),
    }


def ticket_por_mes(unif: pd.DataFrame) -> pd.DataFrame:
    v = vigentes(unif)
    v = v[(v["monto"] > 0) & v["fecha"].notna()]
    if v.empty:
        return pd.DataFrame()
    v = v.assign(mes=columna_mes(v["fecha"]), unidad_negocio=v["unidad_negocio"].astype(str))
    t = v.pivot_table(index="mes", columns="unidad_negocio", values="monto", aggfunc="mean")
    t["General"] = v.groupby("mes")["monto"].mean()
    t = t.sort_index().reset_index()
    t.columns.name = None
    t["mes"] = t["mes"].dt.strftime("%Y-%m")
    return t


def kpis_servicios(servicios: pd.DataFrame, solo_vigentes: bool = True) -> dict:
    """solo_vigentes=False respeta tal cual el filtro de estado elegido (incluso cancelados).

    `trabajos` es el divisor del ticket: los trabajos con monto cargado. Los que
    todavia no lo tienen (hoy 8, ver las alertas de Configuracion) quedan fuera
    del promedio; contarlos como $0 lo hundiria sin que haya bajado ninguna
    tarifa. `trabajos_totales` los incluye, para poder ver la diferencia.
    """
    v = vigentes(servicios) if solo_vigentes else servicios
    con_monto = v[v["monto"] > 0]
    ventas = float(v["monto"].sum())
    return {
        "ventas": ventas,
        "hectareas": float(v["hectareas"].sum()),
        # Todos los clientes con un trabajo, tenga o no el monto cargado: si no,
        # un cliente desaparece del KPI solo porque falta cargarle el importe
        "clientes": clientes_unicos(v["cliente"]),
        "trabajos": int(len(con_monto)),
        "trabajos_totales": int(len(v)),
        "trabajos_sin_monto": int(len(v) - len(con_monto)),
        "ticket_promedio": ventas / len(con_monto) if len(con_monto) else 0.0,
    }


def kpis_equipos(ops: pd.DataFrame, unidades: pd.DataFrame) -> dict:
    """El monto sale de Factura s/IVA; el prorrateo por modelo no lo afecta."""
    v = vigentes(ops)
    pendientes = v[v["pendiente_precio"].astype(bool)] if not v.empty else v
    return {
        "unidades": len(vigentes(unidades)),
        "operaciones": len(v),
        "monto": float(v["factura"].sum()),
        "comision_cobrada": float(v.loc[v["cobrado"].astype(bool), "comision"].sum()) if not v.empty else 0.0,
        "comision_por_cobrar": float(v.loc[~v["cobrado"].astype(bool), "comision"].sum()) if not v.empty else 0.0,
        "ticket_promedio": ticket_promedio(v["factura"]),
        "ops_pendientes": len(pendientes),
        "monto_pendiente": float(pendientes["factura"].sum()),
    }


def resumen_por_modelo(unidades: pd.DataFrame) -> pd.DataFrame:
    u = vigentes(unidades)
    if u.empty:
        return pd.DataFrame()
    u = u.assign(prorrateada=~u["pendiente_precio"].astype(bool))
    r = u.groupby("modelo", as_index=False).agg(
        precio_lista=("precio_lista", "first"),
        unidades=("modelo", "size"),
        unidades_prorrateadas=("prorrateada", "sum"),
        monto_asignado=("monto_asignado", lambda s: s.sum(min_count=1)),
    )
    r["unidades_pendientes"] = r["unidades"] - r["unidades_prorrateadas"]
    r["estado_precio"] = np.where(r["precio_lista"].notna(), "Con precio", "Precio pendiente")
    return r.sort_values(["unidades", "monto_asignado"], ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Reporte consolidado: ingreso real de Agropix
# ---------------------------------------------------------------------------
# Servicios: Agropix se queda con lo facturado (Valor total de ventas).
# Equipos: solo con la comision; Factura s/IVA es volumen intermediado, no ingreso.

def kpis_consolidado(servicios: pd.DataFrame, ops: pd.DataFrame) -> dict:
    s, e = vigentes(servicios), vigentes(ops)
    ventas_servicios = float(s["monto"].sum()) if not s.empty else 0.0
    cobrada = float(e.loc[e["cobrado"].astype(bool), "comision"].sum()) if not e.empty else 0.0
    por_cobrar = float(e.loc[~e["cobrado"].astype(bool), "comision"].sum()) if not e.empty else 0.0
    comision = cobrada + por_cobrar
    ingreso = ventas_servicios + comision
    return {
        "ingreso_total": ingreso,
        "ventas_servicios": ventas_servicios,
        "comision_total": comision,
        "comision_cobrada": cobrada,
        "comision_por_cobrar": por_cobrar,
        "facturado_equipos": float(e["factura"].sum()) if not e.empty else 0.0,
        "hectareas": float(s["hectareas"].sum()) if not s.empty else 0.0,
        "pct_servicios": ventas_servicios / ingreso if ingreso else 0.0,
        "pct_equipos": comision / ingreso if ingreso else 0.0,
    }


def columna_periodo(fechas: pd.Series, granularidad: str = "Mensual") -> pd.Series:
    return fechas.dt.to_period(GRANULARIDADES[granularidad]).dt.to_timestamp()


def etiqueta_periodo(periodos: pd.Series, granularidad: str = "Mensual") -> pd.Series:
    """'Sem 08/09', '03/2025', 'T1 2025' o '2025'."""
    p = pd.to_datetime(pd.Series(periodos)).reset_index(drop=True)
    if granularidad == "Semanal":
        # to_timestamp() de un periodo W-SUN devuelve el lunes de esa semana
        return "Sem " + p.dt.strftime("%d/%m")
    if granularidad == "Trimestral":
        return "T" + p.dt.quarter.astype(str) + " " + p.dt.year.astype(str)
    if granularidad == "Anual":
        return p.dt.year.astype(str)
    return p.dt.strftime("%m/%Y")


def ingresos_por_periodo(servicios: pd.DataFrame, ops: pd.DataFrame, granularidad: str = "Mensual") -> pd.DataFrame:
    """Ingreso real por periodo: servicios (Valor total de ventas) y equipos (Comision $), mas has."""
    columnas = ["periodo", "periodo_label", "ingreso_servicios", "ingreso_equipos", "total",
                "pct_servicios", "pct_equipos", "has_trabajadas"]
    s, e = vigentes(servicios), vigentes(ops)
    s = s[s["fecha"].notna()] if not s.empty else s
    e = e[e["fecha"].notna()] if not e.empty else e
    if s.empty and e.empty:
        return pd.DataFrame(columns=columnas)

    series = {}
    if not s.empty:
        clave = columna_periodo(s["fecha"], granularidad)
        series["ingreso_servicios"] = s.groupby(clave)["monto"].sum()
        series["has_trabajadas"] = s.groupby(clave)["hectareas"].sum()
    if not e.empty:
        series["ingreso_equipos"] = e.groupby(columna_periodo(e["fecha"], granularidad))["comision"].sum()

    t = (pd.DataFrame(series)
         .reindex(columns=["ingreso_servicios", "ingreso_equipos", "has_trabajadas"])
         .fillna(0.0)
         .sort_index())
    t.index.name = "periodo"
    t = t.reset_index()
    t["total"] = t["ingreso_servicios"] + t["ingreso_equipos"]
    base = t["total"].where(t["total"] > 0)
    t["pct_servicios"] = (t["ingreso_servicios"] / base).fillna(0.0)
    t["pct_equipos"] = (t["ingreso_equipos"] / base).fillna(0.0)
    t["periodo_label"] = etiqueta_periodo(t["periodo"], granularidad).values
    return t[columnas]
