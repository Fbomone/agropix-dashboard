"""Componentes de Streamlit comunes a todas las paginas."""
import math

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.format import (
    ALTO_GRAFICO, AMBAR, AZUL, FORMATO_MONEDA_TABLA, GRADIENTES_KPI, GRIS, MEDIDA_PLATA,
    MEDIDAS, PLOTLY_TEMPLATE, SEPARADORES_PLOTLY, TICK_MONEDA, VERDE, Medida,
)

SIN_DATOS = "No hay datos para el período seleccionado"

MONEDA = st.column_config.NumberColumn(format=FORMATO_MONEDA_TABLA)
FECHA = st.column_config.DateColumn(format="DD/MM/YYYY")


def columna_moneda(label: str):
    return st.column_config.NumberColumn(label, format=FORMATO_MONEDA_TABLA)


def aplicar_tema():
    px.defaults.template = PLOTLY_TEMPLATE
    px.defaults.color_discrete_sequence = [VERDE, AZUL, AMBAR, "#6A1B9A", "#00838F", GRIS]


def leyenda_estados(estados, opciones) -> str:
    """Una linea que aclara que estados de 'Última acción' entran en los numeros."""
    if estados is None:
        return "Estados del trabajo incluidos: todos."
    if not estados:
        return "Ningún estado del trabajo seleccionado: no se muestran servicios."
    if opciones and set(estados) >= set(opciones):
        return "Estados del trabajo incluidos: todos."
    return "Estados del trabajo incluidos: " + ", ".join(estados) + "."


def periodo_vacio(*dataframes) -> bool:
    """True si ninguno de los DataFrames tiene filas."""
    return all(df is None or len(df) == 0 for df in dataframes)


def aviso_sin_datos(*dataframes, que: str = "movimiento") -> bool:
    """Un unico aviso cuando el periodo no tiene nada, y True para cortar la pagina.

    Sin esto cada grafico avisaba por su cuenta y una pagina vacia mostraba el
    mismo mensaje trece veces, que es ruido y no informacion.
    """
    if not periodo_vacio(*dataframes):
        return False
    st.info(
        f"**No hay {que} en el período elegido.** Probá ampliar el rango de fechas o "
        "revisar el filtro *Estado del trabajo* en la barra lateral.",
        icon="📭",
    )
    return True


def hay_datos(df) -> bool:
    """False (con aviso) si no hay nada que mostrar: la seccion se saltea sin romper la pagina."""
    if df is None or len(df) == 0:
        st.info(SIN_DATOS)
        return False
    return True


def metricas(items: list, por_fila: int = 4):
    """KPIs en filas de a lo sumo `por_fila`; 5 KPIs -> 3 + 2 con el mismo ancho.

    items: dicts con los argumentos de st.metric (label, value, help, delta...).
    """
    if not items:
        return
    filas = math.ceil(len(items) / por_fila)
    ancho = math.ceil(len(items) / filas)
    for i in range(0, len(items), ancho):
        for columna, item in zip(st.columns(ancho), items[i:i + ancho]):
            columna.metric(**item)


def _cantidad_series(fig) -> int:
    n = 0
    for traza in fig.data:
        if traza.type == "pie":
            n += len(traza.labels) if traza.labels is not None else 0
        elif traza.showlegend is not False:
            n += 1
    return n


# Aire por caracter de la etiqueta, en fraccion del rango del eje. Sale de medir
# el caso peor: una barra que ocupa todo el ancho con el rotulo mas largo al
# lado. Plotly dibuja la etiqueta "outside" aunque no entre (cliponaxis=False),
# y lo que sobra lo recorta el contenedor: el texto no se encoge, desaparece.
AIRE_POR_CARACTER = 0.04


def espacio_para_etiquetas(fig, maximo: float, eje: str = "x", caracteres: int = 6):
    """Deja aire despues de la barra mas larga para que la etiqueta 'outside' no se corte.

    `caracteres` es el largo estimado del rotulo: "$193k" son 5 y "6,46k ha"
    son 8. Con un factor fijo, agregarle un sufijo a la etiqueta corta el
    sufijo, que es justo la parte que dice en que unidad esta el numero.
    """
    if maximo and maximo > 0:
        rango = [0, float(maximo) * (1 + AIRE_POR_CARACTER * max(caracteres, 5))]
        fig.update_xaxes(range=rango) if eje == "x" else fig.update_yaxes(range=rango)


def grafico(fig, key: str, eje_moneda: str | None = "y", alto: int = ALTO_GRAFICO):
    """Estilo comun: plotly_white, altura fija, separadores es-AR, sin titulo interno.

    eje_moneda: "y", "x" o None para aplicar tickformat de moneda a ese eje.
    """
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        height=alto,
        separators=SEPARADORES_PLOTLY,
        margin=dict(l=10, r=10, t=10, b=10),
        legend_title_text="",
    )
    if eje_moneda == "y":
        fig.update_yaxes(tickformat=TICK_MONEDA)
    elif eje_moneda == "x":
        fig.update_xaxes(tickformat=TICK_MONEDA)
    if _cantidad_series(fig) > 3:
        fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0))
    st.plotly_chart(fig, width="stretch", key=key, config={"displaylogo": False})


def selector_medida(key: str, etiqueta: str = "Unidad de medida") -> Medida:
    """Segmentado US$ / Hectareas. Devuelve la Medida elegida, plata por defecto.

    Streamlit borra el estado de un widget al cambiar de pagina, asi que el
    selector vuelve solo a US$ cuando se sale y se entra. Es lo que conviene:
    el default tiene que ser siempre el mismo para que nadie lea hectareas
    creyendo que lee plata.
    """
    elegida = st.segmented_control(etiqueta, list(MEDIDAS), default=list(MEDIDAS)[0], key=key)
    return MEDIDAS.get(elegida or "", MEDIDA_PLATA)


def barras_por(df: pd.DataFrame, columna: str, medida: Medida = MEDIDA_PLATA,
               horizontal: bool = False, top: int | None = None, color: str = VERDE):
    """Suma la medida por `columna`, de mayor a menor. Horizontal: el mayor queda arriba."""
    if not hay_datos(df) or medida.columna not in df.columns:
        return
    valor = medida.columna
    g = (
        df.assign(**{columna: df[columna].astype("string").fillna("Sin dato")})
        .groupby(columna, as_index=False)[valor].sum()
        .sort_values(valor, ascending=False)
    )
    g = g[g[valor] > 0]
    total_categorias = len(g)
    if top:
        g = g.head(top)
    if not hay_datos(g):
        st.caption(f"Ningún registro tiene {medida.etiqueta.lower()} cargado en este período.")
        return

    labels = {valor: medida.etiqueta, columna: ""}
    eje = "x" if horizontal else "y"
    if horizontal:
        fig = px.bar(g, x=valor, y=columna, orientation="h", labels=labels)
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_traces(
            texttemplate=f"%{{x:{medida.texto}}}{medida.sufijo}",
            hovertemplate=f"%{{y}}<br>%{{x:{medida.hover}}}{medida.sufijo}<extra></extra>")
    else:
        fig = px.bar(g, x=columna, y=valor, labels=labels)
        fig.update_xaxes(categoryorder="total descending")
        fig.update_traces(
            texttemplate=f"%{{y:{medida.texto}}}{medida.sufijo}",
            hovertemplate=f"%{{x}}<br>%{{y:{medida.hover}}}{medida.sufijo}<extra></extra>")
    fig.update_traces(marker_color=color, textposition="outside", cliponaxis=False)
    # "$1,25M" son 6 caracteres; "1,25M ha", 8. El sufijo cambia cuanto aire hace falta
    espacio_para_etiquetas(fig, g[valor].max(), eje=eje, caracteres=6 + len(medida.sufijo))
    # El tickformat lo pone la medida, asi que grafico() no tiene que adivinarlo
    (fig.update_xaxes if horizontal else fig.update_yaxes)(tickformat=medida.tick)
    # key explicita: dos graficos con los mismos datos chocarian en el ID automatico
    grafico(fig, key=f"barras_{columna}_{valor}", eje_moneda=None)
    if top and total_categorias > top:
        st.caption(f"Top {top} de {total_categorias}")


# ---------------------------------------------------------------------------
# Tarjetas de KPI (jerarquia visual del Reporte General)
# ---------------------------------------------------------------------------
# st.metric no permite pintar el fondo, y las metricas de comisiones son las que
# el negocio mira primero: van como tarjetas con gradiente y texto blanco.
# El grid es responsive de verdad (auto-fit + minmax): 4 columnas en desktop,
# 2 en tablet y 1 apilada abajo de 420px, sin necesidad de detectar el ancho de
# pantalla desde Python (Streamlit no expone esa informacion).
_CSS_TARJETAS = """
<style>
  .agpx-kpis {{
    display: grid; gap: .75rem; margin: .25rem 0 1rem 0;
    grid-template-columns: {columnas};
  }}
  .agpx-kpi {{
    border-radius: 12px; padding: .9rem 1rem; color: #FFFFFF;
    box-shadow: 0 2px 8px rgba(16,24,40,.12); min-width: 0;
  }}
  .agpx-kpi .agpx-kpi-label {{
    font-size: .78rem; font-weight: 600; letter-spacing: .03em;
    text-transform: uppercase; opacity: .95; line-height: 1.25;
  }}
  .agpx-kpi .agpx-kpi-valor {{
    font-size: 1.4rem; font-weight: 700; line-height: 1.2; margin: .3rem 0 .1rem 0;
    font-variant-numeric: tabular-nums;   /* los montos alinean entre tarjetas */
    overflow-wrap: anywhere;              /* un numero largo no desborda */
  }}
  .agpx-kpi .agpx-kpi-nota {{ font-size: .75rem; opacity: .92; line-height: 1.3; }}
  /* Tablet: de a dos, que es lo que entra sin achicar el numero */
  @media (max-width: 860px) {{
    .agpx-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  }}
  @media (max-width: 480px) {{
    .agpx-kpis {{ grid-template-columns: 1fr; }}
    .agpx-kpi .agpx-kpi-valor {{ font-size: 1.3rem; }}
  }}
</style>
"""


def tarjetas_kpi(tarjetas: list, columnas: int | None = None) -> None:
    """KPIs destacados con fondo de color.

    tarjetas: dicts con label, valor, nota (opcional) y gradiente (clave de
    GRADIENTES_KPI o tupla (claro, oscuro)).

    columnas: cuantas por fila en desktop. Por defecto se acomodan solas
    (auto-fit), que con pocas tarjetas y la barra lateral abierta las puede
    partir en dos filas; pasando un numero se fuerza una sola fila.
    """
    if not tarjetas:
        return
    # minmax(0, 1fr) y no (210px, 1fr): con el minimo en px, si no entran todas
    # el grid las baja de fila en vez de angostarlas
    grid = (f"repeat({columnas}, minmax(0, 1fr))" if columnas
            else "repeat(auto-fit, minmax(200px, 1fr))")
    bloques = []
    for t in tarjetas:
        gradiente = t.get("gradiente", "neutro")
        claro, oscuro = GRADIENTES_KPI.get(gradiente, gradiente) if isinstance(gradiente, str) else gradiente
        nota = f'<div class="agpx-kpi-nota">{t["nota"]}</div>' if t.get("nota") else ""
        bloques.append(
            f'<div class="agpx-kpi" style="background:linear-gradient(135deg,{claro},{oscuro})">'
            f'<div class="agpx-kpi-label">{t["label"]}</div>'
            f'<div class="agpx-kpi-valor">{t["valor"]}</div>{nota}</div>'
        )
    st.html(_CSS_TARJETAS.format(columnas=grid)
            + f'<div class="agpx-kpis">{"".join(bloques)}</div>')
