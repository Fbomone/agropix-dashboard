"""Formato visual comun: numeros en es-AR, paleta fija y convenciones de graficos."""
from dataclasses import dataclass

import pandas as pd

from utils.data import CANCELADO, COBRADO, EN_PROCESO, EQUIPOS, POR_COBRAR, SERVICIO

# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------
VERDE, AZUL, AMBAR, GRIS, ROJO = "#2E7D32", "#1565C0", "#F9A825", "#90A4AE", "#C62828"

COLORES_UNIDAD = {SERVICIO: VERDE, EQUIPOS: AZUL}
# Marcas de equipos: los Agras T son el volumen del negocio, Mavic el complemento
COLORES_MARCA = {"Agras T": AZUL, "Mavic": "#00838F", "Accesorio": GRIS, "Otro": "#6A1B9A"}
COLORES_COBRO = {COBRADO: VERDE, POR_COBRAR: AMBAR, EN_PROCESO: GRIS, CANCELADO: ROJO}

# Tarjetas de KPI del Reporte General: gradientes (claro, oscuro) por metrica.
# Son colores de fondo con texto blanco encima, asi que el tono claro tiene que
# mantener contraste suficiente: el #90EE90 de la especificacion original daba
# 1.4:1 con blanco (ilegible), por eso las hectareas van en verde oscuro.
GRADIENTES_KPI = {
    "cobradas": ("#00A651", "#00803E"),
    "generadas": ("#1F77B4", "#155C8D"),
    "por_cobrar": ("#E4700B", "#B85700"),
    "hectareas": ("#3F7D3F", "#2C5C2C"),
    "neutro": ("#546E7A", "#3E5561"),
}

# ---------------------------------------------------------------------------
# Graficos
# ---------------------------------------------------------------------------
PLOTLY_TEMPLATE = "plotly_white"
ALTO_GRAFICO = 380
SEPARADORES_PLOTLY = ",."  # decimal con coma, miles con punto
# El tooltip muestra el valor exacto con centavos: el eje y las etiquetas van
# abreviados ("$500k") y el hover es donde se ve el numero real.
HOVER_MONEDA = "$,.2f"
# ".0s" redondea a 1 cifra significativa (150k -> "$200k", ticks repetidos);
# ".3~s" muestra $150k / $1,25M y recorta ceros sobrantes.
TICK_MONEDA = "$,.3~s"
ETIQUETA_MONEDA = "$,.3s"  # texto sobre barras / porciones: "$383k"
FORMATO_MONEDA_TABLA = "US$ %,.0f"

# Las hectareas siguen las mismas convenciones que la plata: eje y etiqueta
# abreviados ("16,5k"), tooltip con el numero exacto. Sin "$" y con " ha".
TICK_HAS = ",.3~s"
ETIQUETA_HAS = ",.3s"
HOVER_HAS = ",.1f"

FECHA_PLOTLY = "%d/%m/%Y"
MES_PLOTLY = "%m/%Y"
FECHA_CORTA_PLOTLY = "%d/%m"  # eje semanal: la etiqueta es el lunes de la semana


# ---------------------------------------------------------------------------
# Unidad de medida de un grafico de barras
# ---------------------------------------------------------------------------
# Los mismos cuatro cortes de Venta de Servicios (producto, trabajo, cultivo,
# cliente) se leen distinto segun lo que se mida. Un cliente puede ser el que
# mas factura y no el que mas superficie da: un ensayo caro en pocas hectareas
# contra una pulverizacion grande a tarifa baja. Por eso el grafico no fija la
# magnitud, la recibe.
@dataclass(frozen=True)
class Medida:
    columna: str    # de donde sale el valor en el DataFrame
    etiqueta: str   # como se llama el eje
    tick: str       # formato de los ticks del eje
    texto: str      # formato del numero sobre la barra
    hover: str      # formato del numero exacto en el tooltip
    sufijo: str = ""


MEDIDA_PLATA = Medida("monto", "US$", TICK_MONEDA, ETIQUETA_MONEDA, HOVER_MONEDA)
MEDIDA_SUPERFICIE = Medida("hectareas", "Has", TICK_HAS, ETIQUETA_HAS, HOVER_HAS, sufijo=" ha")

# El orden manda en el selector; la plata va primero porque es el default
MEDIDAS: dict[str, Medida] = {"US$": MEDIDA_PLATA, "Hectáreas": MEDIDA_SUPERFICIE}

# ---------------------------------------------------------------------------
# Numeros
# ---------------------------------------------------------------------------


def es_nulo(valor) -> bool:
    return valor is None or (pd.api.types.is_scalar(valor) and bool(pd.isna(valor)))


def formatear_numero(valor, decimales: int = 0) -> str:
    """1234567.8 -> '1.234.568' (es-AR: miles con punto, decimal con coma)."""
    if es_nulo(valor):
        return "—"
    return f"{float(valor):,.{decimales}f}".translate(str.maketrans({",": ".", ".": ","}))


def formatear_moneda(valor) -> str:
    """Abreviado para KPIs: 'US$ 1,56 M', 'US$ 660,4 k', 'US$ 842'."""
    if es_nulo(valor):
        return "—"
    v = float(valor)
    signo, a = ("-" if v < 0 else ""), abs(v)
    # se compara ya redondeado para que 999.960 no quede como "1.000,0 k"
    if round(a / 1_000, 1) >= 1_000:
        return f"{signo}US$ {formatear_numero(a / 1_000_000, 2)} M"
    if round(a) >= 1_000:
        return f"{signo}US$ {formatear_numero(a / 1_000, 1)} k"
    return f"{signo}US$ {formatear_numero(a)}"


def formatear_moneda_completa(valor, decimales: int = 0) -> str:
    """Sin abreviar: 'US$ 1.563.036' o, con decimales=2, 'US$ 1.563.036,00'."""
    if es_nulo(valor):
        return "—"
    v = float(valor)
    return f"{'-' if v < 0 else ''}US$ {formatear_numero(abs(v), decimales)}"


def formatear_moneda_card(valor) -> str:
    """Para las tarjetas de KPI: el numero exacto con centavos, sin abreviar.

    Las tarjetas son el dato que se lee y se anota; los graficos si van
    abreviados porque ahi el valor exacto lo da el tooltip.
    """
    return formatear_moneda_completa(valor, 2)


def formatear_porcentaje(valor) -> str:
    """0.756 -> '75,6 %'."""
    if es_nulo(valor):
        return "—"
    return f"{formatear_numero(float(valor) * 100, 1)} %"
