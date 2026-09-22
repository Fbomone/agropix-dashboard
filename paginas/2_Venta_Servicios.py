import pandas as pd
import plotly.express as px
import streamlit as st

from utils.data import ESTADOS_COBRO, SERVICIO, columna_mes, kpis_servicios, resumen_operadores
from utils.format import (
    COLORES_UNIDAD, MES_PLOTLY, formatear_moneda_card, formatear_numero,
    formatear_porcentaje,
)
from utils.ui import (
    aviso_sin_datos, barras_por, columna_moneda, espacio_para_etiquetas, grafico, hay_datos,
    leyenda_estados, metricas, tarjetas_kpi,
)

COLOR = COLORES_UNIDAD[SERVICIO]

datos = st.session_state["datos"]
s = datos["servicios"]

st.title("🚜 Venta de Servicios")
st.caption("Fuente: CRM – Trabajos.")
st.caption(f"🔎 {leyenda_estados(st.session_state.get('estados_trabajo'), st.session_state.get('estados_trabajo_opciones'))} "
           "Se cambia en *Estado del trabajo*, en la barra lateral.")

# El filtro de estado manda: si se eligen trabajos cancelados, se muestran
k = kpis_servicios(s, solo_vigentes=False)
tarjetas_kpi([
    dict(label="💰 Ventas totales", valor=formatear_moneda_card(k["ventas"]),
         nota="En servicios el ingreso es todo lo facturado", gradiente="cobradas"),
    dict(label="🌾 Has trabajadas", valor=f"{formatear_numero(k['hectareas'])} ha",
         nota=f"{formatear_moneda_card(k['ventas'] / k['hectareas']) if k['hectareas'] else '—'} por ha",
         gradiente="hectareas"),
    dict(label="🎫 Ticket promedio", valor=formatear_moneda_card(k["ticket_promedio"]),
         nota=f"Sobre {formatear_numero(k['trabajos'])} trabajos con monto cargado",
         gradiente="generadas"),
    dict(label="👥 Clientes", valor=formatear_numero(k["clientes"]),
         nota="Con al menos un trabajo en el período", gradiente="neutro"),
], columnas=4)

if aviso_sin_datos(s, que="trabajos"):
    st.stop()

st.divider()
g1, g2 = st.columns(2)
with g1:
    st.subheader("Por producto / servicio")
    barras_por(s, "servicio", color=COLOR)
with g2:
    st.subheader("Por trabajo")
    barras_por(s, "trabajo", horizontal=True, top=15, color=COLOR)

g3, g4 = st.columns(2)
with g3:
    st.subheader("Por cultivo")
    barras_por(s, "cultivo", horizontal=True, top=15, color=COLOR)
with g4:
    st.subheader("Top clientes")
    barras_por(s, "cliente", horizontal=True, top=15, color=COLOR)

# ---------------------------------------------------------------------------
# B) Analisis por operador
# ---------------------------------------------------------------------------
st.divider()
st.subheader("👷 Análisis por operador")

operadores = datos["operadores"]
opciones_operador = sorted(
    st.session_state["datos_completos"]["operadores"]["operador"].dropna().astype(str).unique(), key=str.casefold
)
with st.sidebar:
    st.divider()
    st.subheader("Venta de Servicios")
    # Streamlit borra el estado de un widget al cambiar de pagina: se restaura desde _filtro_operadores
    # (tambien lo usa la exportacion PDF cuando se exporta desde otra pagina)
    if "operadores" not in st.session_state:
        st.session_state["operadores"] = [o for o in st.session_state.get("_filtro_operadores", [])
                                          if o in opciones_operador]
    seleccion = st.multiselect("Operador", opciones_operador, key="operadores", placeholder="Todos los operadores")
    st.session_state["_filtro_operadores"] = seleccion

largo = operadores[operadores["operador"].isin(seleccion)] if seleccion else operadores
st.caption(
    f"{'Operadores: ' + ', '.join(seleccion) if seleccion else 'Todos los operadores'}. Cada operador registra las "
    "has que ejecutó él: en un trabajo compartido la suma entre operadores puede superar las has del trabajo."
)

if hay_datos(largo):
    resumen = resumen_operadores(largo)
    trabajos = largo["fila_sheet"].nunique()
    solos = largo.loc[largo["cantidad_operadores_en_trabajo"] == 1, "fila_sheet"].nunique()
    metricas([
        dict(label="Has trabajadas por operador", value=f"{formatear_numero(largo['has_operador'].sum())} ha",
             help="Suma de las has registradas por los operadores seleccionados"),
        dict(label="Trabajos", value=formatear_numero(trabajos)),
        dict(label="Trabajos hechos solo", value=formatear_porcentaje(solos / trabajos if trabajos else 0),
             help=f"{solos} de {trabajos} trabajos con un único operador"),
    ])

    o1, o2 = st.columns(2)
    with o1:
        st.markdown("**Has por operador**")
        fig = px.bar(resumen, x="has", y="operador", orientation="h", labels={"has": "Has", "operador": ""})
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_xaxes(tickformat=",.0f")
        fig.update_traces(marker_color=COLOR, texttemplate="%{x:,.0f} ha", textposition="outside", cliponaxis=False,
                          hovertemplate="%{y}<br>%{x:,.0f} ha<extra></extra>")
        espacio_para_etiquetas(fig, resumen["has"].max())
        grafico(fig, key="has_por_operador", eje_moneda=None)

    with o2:
        st.markdown("**Evolución mensual de has por operador**")
        con_fecha = largo[largo["fecha"].notna()]
        if hay_datos(con_fecha):
            tabla_mes = (con_fecha.assign(mes=columna_mes(con_fecha["fecha"]), operador=con_fecha["operador"].astype(str))
                         .pivot_table(index="mes", columns="operador", values="has_operador", aggfunc="sum"))
            # meses sin trabajo = 0 has, para que la linea no una puntos salteando meses
            meses = pd.date_range(tabla_mes.index.min(), tabla_mes.index.max(), freq="MS")
            mensual = (tabla_mes.reindex(meses).fillna(0).rename_axis("mes").reset_index()
                       .melt(id_vars="mes", var_name="operador", value_name="has_operador"))
            fig = px.line(mensual, x="mes", y="has_operador", color="operador", markers=True,
                          category_orders={"operador": resumen["operador"].tolist()},
                          labels={"mes": "", "has_operador": "Has", "operador": ""})
            fig.update_traces(hovertemplate=f"%{{fullData.name}} · %{{x|{MES_PLOTLY}}}<br>%{{y:,.0f}} ha<extra></extra>")
            n = len(meses)
            fig.update_xaxes(tickformat=MES_PLOTLY, dtick="M1" if n <= 12 else "M3" if n <= 24 else "M6")
            fig.update_yaxes(tickformat=",.0f")
            grafico(fig, key="has_mensual_operador", eje_moneda=None)

    st.dataframe(
        resumen.assign(pct_solo=resumen["pct_solo"] * 100, pct_acompanado=resumen["pct_acompanado"] * 100),
        hide_index=True,
        width="stretch",
        column_order=["operador", "has", "trabajos", "trabajos_solo", "pct_solo", "trabajos_acompanado",
                      "pct_acompanado"],
        column_config={
            "operador": "Operador",
            "has": st.column_config.NumberColumn("Has totales", format="%,.0f"),
            "trabajos": "Trabajos",
            "trabajos_solo": "Solo",
            "pct_solo": st.column_config.NumberColumn("% solo", format="%.1f %%"),
            "trabajos_acompanado": "Acompañado",
            "pct_acompanado": st.column_config.NumberColumn("% acompañado", format="%.1f %%"),
        },
    )
    sin_has = int(largo["has_operador"].isna().sum())
    if sin_has:
        st.caption(f"{sin_has} registro(s) de operador sin has cargadas: cuentan como trabajo pero suman 0 ha.")

# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Detalle de trabajos")

f1, f2 = st.columns([2, 1])
busqueda = f1.text_input("Buscar", placeholder="Cliente, orden, trabajo, cultivo...")
estados = f2.multiselect("Estado de cobro", ESTADOS_COBRO)

detalle = s
if estados:
    detalle = detalle[detalle["estado_cobro"].isin(estados)]
if busqueda:
    cols_texto = ["id_orden", "cliente", "servicio", "trabajo", "cultivo", "ultima_accion"]
    coincide = detalle[cols_texto].apply(
        lambda c: c.astype("string").str.contains(busqueda, case=False, regex=False, na=False)
    ).any(axis=1)
    detalle = detalle[coincide]

if hay_datos(detalle):
    st.dataframe(
        detalle.drop(columns=["unidad_negocio"]),
        hide_index=True,
        width="stretch",
        placeholder="—",
        column_config={
            "fila_sheet": "Fila Sheet", "fecha": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY"),
            "id_orden": "Orden", "cliente": "Cliente",
            "id_cliente": "ID cliente", "servicio": "Servicio", "trabajo": "Trabajo", "cultivo": "Cultivo",
            "ultima_accion": "Última acción", "hectareas": st.column_config.NumberColumn("Has", format="%.1f"),
            "valor_ha": columna_moneda("Valor/ha"), "monto": columna_moneda("Monto"),
            "estado_cobro": "Estado de cobro",
        },
    )
st.caption(f"{formatear_numero(len(detalle))} de {formatear_numero(len(s))} trabajos")
