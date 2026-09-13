"""Formato visual comun: numeros en es-AR, paleta fija y convenciones de graficos."""
import pandas as pd

from utils.data import CANCELADO, COBRADO, EN_PROCESO, EQUIPOS, POR_COBRAR, SERVICIO

# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------
VERDE, AZUL, AMBAR, GRIS, ROJO = "#2E7D32", "#1565C0", "#F9A825", "#90A4AE", "#C62828"

COLORES_UNIDAD = {SERVICIO: VERDE, EQUIPOS: AZUL}
COLORES_COBRO = {COBRADO: VERDE, POR_COBRAR: AMBAR, EN_PROCESO: GRIS, CANCELADO: ROJO}

# ---------------------------------------------------------------------------
# Graficos
# ---------------------------------------------------------------------------
PLOTLY_TEMPLATE = "plotly_white"
ALTO_GRAFICO = 380
SEPARADORES_PLOTLY = ",."  # decimal con coma, miles con punto
HOVER_MONEDA = "$,.0f"
# ".0s" redondea a 1 cifra significativa (150k -> "$200k", ticks repetidos);
# ".3~s" muestra $150k / $1,25M y recorta ceros sobrantes.
TICK_MONEDA = "$,.3~s"
ETIQUETA_MONEDA = "$,.3s"  # texto sobre barras / porciones: "$383k"
FORMATO_MONEDA_TABLA = "US$ %,.0f"
FECHA_PLOTLY = "%d/%m/%Y"
MES_PLOTLY = "%m/%Y"

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


def formatear_moneda_completa(valor) -> str:
    """Sin abreviar: 'US$ 1.563.036'."""
    if es_nulo(valor):
        return "—"
    v = float(valor)
    return f"{'-' if v < 0 else ''}US$ {formatear_numero(abs(v))}"


def formatear_porcentaje(valor) -> str:
    """0.756 -> '75,6 %'."""
    if es_nulo(valor):
        return "—"
    return f"{formatear_numero(float(valor) * 100, 1)} %"
