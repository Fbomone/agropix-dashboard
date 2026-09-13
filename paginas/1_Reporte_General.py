import pandas as pd
import plotly.express as px
import streamlit as st

from utils.data import (
    COBRADO, EQUIPOS, GRANULARIDADES, POR_COBRAR, SERVICIO, ingresos_por_periodo, kpis_consolidado,
    kpis_general, ticket_por_mes, vigentes,
)
from utils.format import (
    ALTO_GRAFICO, COLORES_COBRO, COLORES_UNIDAD, ETIQUETA_MONEDA, HOVER_MONEDA, MES_PLOTLY,
    formatear_moneda, formatear_moneda_completa, formatear_numero, formatear_porcentaje,
)
from utils.ui import columna_moneda, grafico, hay_datos, leyenda_estados, metricas

datos = st.session_state["datos"]
u, servicios, ops = datos["ventas_unificadas"], datos["servicios"], datos["equipos"]
ORDEN_UNIDADES = {"unidad_negocio": [SERVICIO, EQUIPOS]}


def eje_x_periodo(periodos: pd.DataFrame, granularidad: str) -> str:
    """Mensual usa eje de fechas; trimestral y anual, etiquetas como categorias."""
    return "periodo" if granularidad == "Mensual" else "periodo_label"


def formatear_eje_periodo(fig, periodos: pd.DataFrame, granularidad: str):
    if granularidad == "Mensual":
        n = periodos["periodo"].nunique()
        fig.update_xaxes(tickformat=MES_PLOTLY, dtick="M1" if n <= 12 else "M3" if n <= 24 else "M6")
    else:
        fig.update_xaxes(type="category", categoryorder="array", categoryarray=periodos["periodo_label"].tolist())


st.title("📊 Reporte General")
st.caption(f"🔎 {leyenda_estados(st.session_state.get('estados_trabajo'), st.session_state.get('estados_trabajo_opciones'))} "
           "Los trabajos cancelados y los equipos devueltos nunca suman ingreso.")

# ---------------------------------------------------------------------------
# E) Foto consolidada: ingreso real de Agropix
# ---------------------------------------------------------------------------
kc = kpis_consolidado(servicios, ops)
metricas([
    dict(label="Ingreso Agropix", value=formatear_moneda(kc["ingreso_total"]),
         help=f"{formatear_moneda_completa(kc['ingreso_total'])} = ventas de servicios + comisión de equipos"),
    dict(label="Ventas de servicios", value=formatear_moneda(kc["ventas_servicios"]),
         delta=f"{formatear_porcentaje(kc['pct_servicios'])} del ingreso", delta_color="off", delta_arrow="off",
         help=formatear_moneda_completa(kc["ventas_servicios"])),
    dict(label="Has trabajadas", value=f"{formatear_numero(kc['hectareas'])} ha"),
    dict(label="Comisión Agropix cobrada", value=formatear_moneda(kc["comision_cobrada"]),
         delta=f"{formatear_porcentaje(kc['pct_equipos'])} del ingreso (total comisión)", delta_color="off",
         delta_arrow="off", help=formatear_moneda_completa(kc["comision_cobrada"])),
    dict(label="Comisión Agropix por cobrar", value=formatear_moneda(kc["comision_por_cobrar"]),
         help=formatear_moneda_completa(kc["comision_por_cobrar"])),
    dict(label="Volumen intermediado", value=formatear_moneda(kc["facturado_equipos"]),
         help=f"{formatear_moneda_completa(kc['facturado_equipos'])}: Facturado s/IVA al cliente por equipos. "
              "No es ingreso de Agropix."),
])
st.caption(
    "**Ingreso Agropix** = Valor total de ventas de servicios + Comisión $ de equipos. En servicios Agropix se "
    "queda con todo lo facturado; en equipos solo con la comisión. Por eso el Facturado s/IVA de equipos se "
    "muestra aparte como **volumen intermediado** y no entra en la participación."
)

st.divider()
# Streamlit borra el estado de un widget al cambiar de pagina: se restaura desde _filtro_granularidad
# (tambien lo usa la exportacion PDF cuando se exporta desde otra pagina)
if "granularidad" not in st.session_state:
    st.session_state["granularidad"] = st.session_state.get("_filtro_granularidad", "Mensual")
granularidad = st.segmented_control("Granularidad", list(GRANULARIDADES), key="granularidad") or "Mensual"
st.session_state["_filtro_granularidad"] = granularidad
periodos = ingresos_por_periodo(servicios, ops, granularidad)
x = eje_x_periodo(periodos, granularidad)

g1, g2 = st.columns([1, 2])
with g1:
    st.subheader("Participación en el ingreso")
    mix = pd.DataFrame({"unidad_negocio": [SERVICIO, EQUIPOS],
                        "ingreso": [kc["ventas_servicios"], kc["comision_total"]]})
    if hay_datos(mix[mix["ingreso"] > 0]):
        fig = px.pie(mix, values="ingreso", names="unidad_negocio", hole=0.5,
                     color="unidad_negocio", color_discrete_map=COLORES_UNIDAD, category_orders=ORDEN_UNIDADES)
        fig.update_traces(sort=False, texttemplate=f"%{{percent:.1%}}<br>%{{value:{ETIQUETA_MONEDA}}}",
                          hovertemplate=f"%{{label}}<br>%{{value:{HOVER_MONEDA}}} (%{{percent:.1%}})<extra></extra>")
        grafico(fig, key="participacion_ingreso", eje_moneda=None)

with g2:
    st.subheader(f"Evolución del ingreso ({granularidad.lower()})")
    if hay_datos(periodos):
        largo = periodos.melt(id_vars=["periodo", "periodo_label"], value_vars=["ingreso_servicios", "ingreso_equipos"],
                              var_name="unidad_negocio", value_name="ingreso")
        largo["unidad_negocio"] = largo["unidad_negocio"].map({"ingreso_servicios": SERVICIO,
                                                               "ingreso_equipos": EQUIPOS})
        fig = px.bar(largo, x=x, y="ingreso", color="unidad_negocio", color_discrete_map=COLORES_UNIDAD,
                     category_orders=ORDEN_UNIDADES, custom_data=["periodo_label"],
                     labels={x: "", "ingreso": "US$", "unidad_negocio": ""})
        fig.update_traces(hovertemplate=f"%{{fullData.name}} · %{{customdata[0]}}<br>%{{y:{HOVER_MONEDA}}}<extra></extra>")
        formatear_eje_periodo(fig, periodos, granularidad)
        grafico(fig, key="evolucion_ingreso")

g3, g4 = st.columns(2)
with g3:
    st.subheader(f"Has trabajadas ({granularidad.lower()})")
    has = periodos[periodos["has_trabajadas"] > 0] if not periodos.empty else periodos
    if hay_datos(has):
        fig = px.bar(has, x=x, y="has_trabajadas", custom_data=["periodo_label"], labels={x: "", "has_trabajadas": "Has"})
        fig.update_traces(marker_color=COLORES_UNIDAD[SERVICIO],
                          hovertemplate="%{customdata[0]}<br>%{y:,.0f} ha<extra></extra>")
        fig.update_yaxes(tickformat=",.0f")
        formatear_eje_periodo(fig, has, granularidad)
        grafico(fig, key="has_por_periodo", eje_moneda=None)

with g4:
    st.subheader("Resumen por período")
    if hay_datos(periodos):
        tabla = periodos.sort_values("periodo", ascending=False).assign(
            pct_servicios=lambda d: d["pct_servicios"] * 100,
            pct_equipos=lambda d: d["pct_equipos"] * 100,
        )
        st.dataframe(
            tabla, hide_index=True, width="stretch", height=ALTO_GRAFICO,
            column_order=["periodo_label", "ingreso_servicios", "ingreso_equipos", "total",
                          "pct_servicios", "pct_equipos", "has_trabajadas"],
            column_config={
                "periodo_label": "Período",
                "ingreso_servicios": columna_moneda("Ingreso servicios"),
                "ingreso_equipos": columna_moneda("Ingreso equipos (comisión)"),
                "total": columna_moneda("Total"),
                "pct_servicios": st.column_config.NumberColumn("% servicios", format="%.1f %%"),
                "pct_equipos": st.column_config.NumberColumn("% equipos", format="%.1f %%"),
                "has_trabajadas": st.column_config.NumberColumn("Has trabajadas", format="%,.0f"),
            },
        )

# ---------------------------------------------------------------------------
# Facturación y cobranza (sobre lo facturado, no sobre el ingreso)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Facturación y cobranza")
st.caption("Esta sección usa lo **facturado**: Valor total de ventas en servicios y Facturado s/IVA (cliente) en "
           "equipos. Sirve para seguir la cobranza, no para medir el ingreso de Agropix.")

k = kpis_general(u)
metricas([
    dict(label="Facturación total", value=formatear_moneda(k["venta_total"]),
         help=f"{formatear_moneda_completa(k['venta_total'])} (servicios + Facturado s/IVA de equipos)"),
    dict(label="% Cobrado", value=formatear_porcentaje(k["pct_cobrado"]),
         delta=formatear_moneda(k["cobrado"]), delta_color="off", delta_arrow="off",
         help=f"{formatear_moneda_completa(k['cobrado'])} cobrados"),
    dict(label="% Por cobrar", value=formatear_porcentaje(k["pct_por_cobrar"]),
         delta=formatear_moneda(k["por_cobrar"]), delta_color="off", delta_arrow="off",
         help=f"{formatear_moneda_completa(k['por_cobrar'])} por cobrar"),
    dict(label="Ticket promedio", value=formatear_moneda(k["ticket_promedio"]),
         help=formatear_moneda_completa(k["ticket_promedio"])),
    dict(label="Clientes con venta", value=formatear_numero(k["clientes"]),
         help="Clientes distintos con al menos una venta no cancelada en el período"),
])

if k["en_proceso"] > 0:
    st.caption(f"Otros {formatear_moneda(k['en_proceso'])} ({formatear_porcentaje(k['en_proceso'] / k['venta_total'])}) "
               "corresponden a servicios en proceso (ni cobrados ni facturados).")

v = vigentes(u)
v = v[v["monto"] > 0].assign(
    unidad_negocio=lambda d: d["unidad_negocio"].astype(str),
    estado_cobro=lambda d: d["estado_cobro"].astype(str),
)

g5, g6 = st.columns(2)
with g5:
    st.subheader("Cobrado vs Por cobrar")
    cobro = v[v["estado_cobro"].isin([COBRADO, POR_COBRAR])]
    if hay_datos(cobro):
        cobro = cobro.groupby(["unidad_negocio", "estado_cobro"], as_index=False)["monto"].sum()
        fig = px.bar(cobro, x="unidad_negocio", y="monto", color="estado_cobro", barmode="group",
                     color_discrete_map=COLORES_COBRO,
                     category_orders={"estado_cobro": [COBRADO, POR_COBRAR], **ORDEN_UNIDADES},
                     labels={"unidad_negocio": "", "monto": "US$", "estado_cobro": ""})
        fig.update_traces(texttemplate=f"%{{y:{ETIQUETA_MONEDA}}}", textposition="outside", cliponaxis=False,
                          hovertemplate=f"%{{x}} · %{{fullData.name}}<br>%{{y:{HOVER_MONEDA}}}<extra></extra>")
        grafico(fig, key="cobrado_vs_por_cobrar")

with g6:
    st.subheader("Ticket promedio por mes")
    tabla = ticket_por_mes(u)
    if hay_datos(tabla):
        tabla = (tabla.assign(mes=pd.to_datetime(tabla["mes"], format="%Y-%m"))
                 .sort_values("mes", ascending=False))
        st.dataframe(
            tabla, hide_index=True, width="stretch", height=ALTO_GRAFICO, placeholder="—",
            column_config={"mes": st.column_config.DateColumn("Mes", format="MM/YYYY"),
                           **{c: columna_moneda(c) for c in tabla.columns if c != "mes"}},
        )
