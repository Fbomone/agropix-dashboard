"""Componentes de Streamlit comunes a todas las paginas."""
import math

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.format import (
    ALTO_GRAFICO, AMBAR, AZUL, ETIQUETA_MONEDA, FORMATO_MONEDA_TABLA, GRIS, HOVER_MONEDA,
    PLOTLY_TEMPLATE, SEPARADORES_PLOTLY, TICK_MONEDA, VERDE,
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


def espacio_para_etiquetas(fig, maximo: float, eje: str = "x"):
    """Deja aire despues de la barra mas larga para que la etiqueta 'outside' no se corte."""
    if maximo and maximo > 0:
        rango = [0, float(maximo) * 1.18]
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


def barras_por(df: pd.DataFrame, columna: str, valor: str = "monto", horizontal: bool = False,
               top: int | None = None, color: str = VERDE):
    """Suma `valor` por `columna`, de mayor a menor. Horizontal: el mayor queda arriba."""
    if not hay_datos(df):
        return
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
        return

    labels = {valor: "US$", columna: ""}
    if horizontal:
        fig = px.bar(g, x=valor, y=columna, orientation="h", labels=labels)
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_traces(texttemplate=f"%{{x:{ETIQUETA_MONEDA}}}",
                          hovertemplate=f"%{{y}}<br>%{{x:{HOVER_MONEDA}}}<extra></extra>")
    else:
        fig = px.bar(g, x=columna, y=valor, labels=labels)
        fig.update_xaxes(categoryorder="total descending")
        fig.update_traces(texttemplate=f"%{{y:{ETIQUETA_MONEDA}}}",
                          hovertemplate=f"%{{x}}<br>%{{y:{HOVER_MONEDA}}}<extra></extra>")
    fig.update_traces(marker_color=color, textposition="outside", cliponaxis=False)
    espacio_para_etiquetas(fig, g[valor].max(), eje="x" if horizontal else "y")
    # key explicita: dos graficos con los mismos datos chocarian en el ID automatico
    grafico(fig, key=f"barras_{columna}_{valor}", eje_moneda="x" if horizontal else "y")
    if top and total_categorias > top:
        st.caption(f"Top {top} de {total_categorias}")
