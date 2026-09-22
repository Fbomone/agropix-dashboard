import pandas as pd
import plotly.express as px
import streamlit as st

from utils.comisiones import (
    MARCAS_PRINCIPALES, cobertura_atribucion, comisiones_por_canal, equipos_por_modelo, kpis_comisiones, ranking_vendedores, ticket_promedio_equipos,
    ticket_promedio_servicios, top_clientes,
)
from utils.data import (
    COBRADO, EQUIPOS, GRANULARIDADES, POR_COBRAR, SERVICIO, ingresos_por_periodo, kpis_general,
    ticket_por_mes, vigentes,
)
from utils.format import (
    ALTO_GRAFICO, COLORES_COBRO, COLORES_MARCA, COLORES_UNIDAD, ETIQUETA_MONEDA,
    FECHA_CORTA_PLOTLY, HOVER_MONEDA, MES_PLOTLY, formatear_moneda, formatear_moneda_card,
    formatear_moneda_completa, formatear_numero, formatear_porcentaje,
)
from utils.ui import (
    columna_moneda, espacio_para_etiquetas, grafico, hay_datos, leyenda_estados, metricas,
    tarjetas_kpi,
)

datos = st.session_state["datos"]
u, servicios, ops = datos["ventas_unificadas"], datos["servicios"], datos["equipos"]
unidades = datos["unidades"]
ORDEN_UNIDADES = {"unidad_negocio": [SERVICIO, EQUIPOS]}


EJE_FECHA = ("Semanal", "Mensual")


def eje_x_periodo(periodos: pd.DataFrame, granularidad: str) -> str:
    """Semanal y mensual usan eje de fechas; trimestral y anual, etiquetas como categorias."""
    return "periodo" if granularidad in EJE_FECHA else "periodo_label"


def formatear_eje_periodo(fig, periodos: pd.DataFrame, granularidad: str):
    if granularidad == "Semanal":
        # Con dos años son ~90 semanas: como categorias el eje queda ilegible
        n = periodos["periodo"].nunique()
        fig.update_xaxes(tickformat=FECHA_CORTA_PLOTLY,
                         dtick=7 * 86_400_000 * (1 if n <= 12 else 4 if n <= 52 else 8))
    elif granularidad == "Mensual":
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
km = kpis_comisiones(servicios, ops)

# .get() con comision_generada de fallback: es exactamente el mismo valor (uno
# es alias del otro) y evita que la pagina reviente si Streamlit Cloud quedo con
# una version vieja de utils/comisiones.py importada en memoria, que es lo que
# paso en el deploy del 21/09.
ingresos = km.get("ingresos", km["comision_generada"])

st.markdown("#### 💰 Ingresos")
tarjetas_kpi([
    dict(label="💰 Ingresos", valor=formatear_moneda_card(ingresos), gradiente="cobradas"),
    dict(label="🌾 Has trabajadas", valor=f"{formatear_numero(km['hectareas'])} ha",
         gradiente="hectareas"),
    dict(label="👥 Clientes", valor=formatear_numero(km["clientes"]), gradiente="generadas"),
], columnas=3)

# Desglose por tipo de ingreso. Van las 6 en una sola grilla de 3 columnas:
# dos bloques de st.columns(3) lado a lado no alinean entre si.
st.markdown("##### 🎯 Desglose por tipo de ingreso")
te, ts = ticket_promedio_equipos(ops, unidades), ticket_promedio_servicios(servicios)
metricas([
    dict(label="🚁 Equipos — comisión cobrada", value=formatear_moneda_completa(km["cobrada_equipos"])),
    dict(label="🚁 Equipos — comisión total", value=formatear_moneda_completa(km["generada_equipos"])),
    dict(label="🚁 Ticket por equipo", value=formatear_moneda_completa(te["ticket_generado"])),
    dict(label="🚁 Volumen intermediado", value=formatear_moneda_completa(km["volumen_equipos"])),
    dict(label="🚜 Servicios — cobrado", value=formatear_moneda_completa(km["cobrado_servicios"])),
    dict(label="🚜 Ticket por trabajo", value=formatear_moneda_completa(ts["ticket"])),
    dict(label="🚜 Valor por hectárea", value=formatear_moneda_completa(ts["valor_por_ha"], 2)),
], por_fila=3)

st.divider()
# ---------------------------------------------------------------------------
# Analisis detallado, en pestanias para que la pagina no sea un scroll infinito
# ---------------------------------------------------------------------------
st.markdown("#### 📉 Análisis detallado")

# La granularidad se LEE aca (los periodos hacen falta en varias pestanias) pero
# el selector se dibuja abajo, pegado a los graficos que la usan: arriba parecia
# afectar al donut y a la serie mensual, que tienen su propio corte.
# Streamlit borra el estado de un widget al cambiar de pagina: se restaura desde
# _filtro_granularidad, que ademas usa la exportacion PDF desde otra pagina.
if "granularidad" not in st.session_state:
    st.session_state["granularidad"] = st.session_state.get("_filtro_granularidad", "Mensual")
granularidad = st.session_state["granularidad"] or "Mensual"
st.session_state["_filtro_granularidad"] = granularidad
periodos = ingresos_por_periodo(servicios, ops, granularidad)
x = eje_x_periodo(periodos, granularidad)

tab_com, tab_eq, tab_serv = st.tabs(["💰 Ingresos", "🚁 Equipos", "🚜 Servicios"])

# ---------------------------------------------------------------------------
with tab_com:
    # De aca para abajo si manda la granularidad: el donut y la serie mensual de
    # arriba tienen su propio corte y no la usan.
    st.segmented_control("Granularidad", list(GRANULARIDADES), key="granularidad")

    c3, c4 = st.columns([1, 2])
    with c3:
        st.subheader("Participación en el ingreso")
        mix = pd.DataFrame({"unidad_negocio": [SERVICIO, EQUIPOS],
                            "ingreso": [km["cobrado_servicios"], km["cobrada_equipos"]]})
        if hay_datos(mix[mix["ingreso"] > 0]):
            fig = px.pie(mix, values="ingreso", names="unidad_negocio", hole=0.5, color="unidad_negocio",
                         color_discrete_map=COLORES_UNIDAD, category_orders=ORDEN_UNIDADES)
            fig.update_traces(sort=False, texttemplate=f"%{{percent:.1%}}<br>%{{value:{ETIQUETA_MONEDA}}}",
                              hovertemplate=f"%{{label}}<br>%{{value:{HOVER_MONEDA}}} (%{{percent:.1%}})<extra></extra>")
            grafico(fig, key="participacion_ingreso", eje_moneda=None)

    with c4:
        st.subheader(f"Evolución del ingreso ({granularidad.lower()})")
        if hay_datos(periodos):
            largo = periodos.melt(id_vars=["periodo", "periodo_label"],
                                  value_vars=["ingreso_servicios", "ingreso_equipos"],
                                  var_name="unidad_negocio", value_name="ingreso")
            largo["unidad_negocio"] = largo["unidad_negocio"].map({"ingreso_servicios": SERVICIO,
                                                                   "ingreso_equipos": EQUIPOS})
            fig = px.bar(largo, x=x, y="ingreso", color="unidad_negocio", color_discrete_map=COLORES_UNIDAD,
                         category_orders=ORDEN_UNIDADES, custom_data=["periodo_label"],
                         labels={x: "", "ingreso": "US$", "unidad_negocio": ""})
            fig.update_traces(
                hovertemplate=f"%{{fullData.name}} · %{{customdata[0]}}<br>%{{y:{HOVER_MONEDA}}}<extra></extra>")
            formatear_eje_periodo(fig, periodos, granularidad)
            grafico(fig, key="evolucion_ingreso")

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
with tab_eq:
    metricas([
        dict(label="Equipos vendidos", value=formatear_numero(te["cantidad"]),
             delta="Agras T + Mavic", delta_color="off", delta_arrow="off",
             help="Unidades, no operaciones: una venta puede incluir varios drones."),
        dict(label="Ticket por equipo", value=formatear_moneda_card(te["ticket_cobrado"]),
             delta="comisión cobrada / unidad", delta_color="off", delta_arrow="off"),
        dict(label="Comisión generada", value=formatear_moneda_card(km["generada_equipos"]),
             delta=f"{formatear_moneda(km['cobrada_equipos'])} cobrada", delta_color="off",
             delta_arrow="off", help=formatear_moneda_completa(km["generada_equipos"])),
    ], por_fila=3)

    por_modelo = equipos_por_modelo(unidades)
    cobertura = cobertura_atribucion(unidades)

    e1, e2 = st.columns([2, 1])
    with e1:
        st.subheader("Equipos vendidos — Agras T y Mavic")
        if hay_datos(por_modelo):
            fig = px.bar(por_modelo.sort_values("unidades"), x="unidades", y="modelo", orientation="h",
                         color="marca", color_discrete_map=COLORES_MARCA, custom_data=["comision_atribuida"],
                         labels={"unidades": "Unidades", "modelo": "", "marca": ""})
            fig.update_traces(texttemplate="%{x:.0f}", textposition="outside", cliponaxis=False,
                              hovertemplate="%{y}<br>%{x:.0f} unidades<br>comisión atribuida: "
                                            f"%{{customdata[0]:{HOVER_MONEDA}}}<extra></extra>")
            fig.update_xaxes(tickformat=",.0f")
            espacio_para_etiquetas(fig, por_modelo["unidades"].max(), eje="x")
            grafico(fig, key="equipos_principales", eje_moneda=None)

    with e2:
        st.subheader("Otros modelos")
        otros = equipos_por_modelo(unidades, solo_principales=False)
        otros = otros[~otros["marca"].isin(MARCAS_PRINCIPALES)] if not otros.empty else otros
        if hay_datos(otros):
            fig = px.pie(otros, values="unidades", names="modelo", hole=0.45)
            fig.update_traces(texttemplate="%{label}<br>%{value:.0f}",
                              hovertemplate="%{label}<br>%{value:.0f} unidades<extra></extra>")
            grafico(fig, key="equipos_otros", eje_moneda=None, alto=260)
            st.caption("Accesorios y software que se venden junto al equipo: no cuentan como drones.")

    if cobertura["modelos_sin_precio"]:
        st.info(
            f"La comisión se puede atribuir a un modelo en **{cobertura['atribuibles']} de "
            f"{cobertura['unidades']} unidades** ({formatear_porcentaje(cobertura['pct'])}). La comisión viene "
            "cargada por operación y repartirla exige el precio de lista de todos los modelos de esa venta. "
            f"Faltan: **{', '.join(cobertura['modelos_sin_precio'])}**. Se cargan en Configuración → Precios de "
            "lista y con eso el reparto queda completo. Las unidades se cuentan igual, sin importar el precio.",
            icon="ℹ️",
        )

# ---------------------------------------------------------------------------
with tab_serv:
    metricas([
        dict(label="Has trabajadas", value=f"{formatear_numero(ts['hectareas'])} ha"),
        dict(label="Trabajos", value=formatear_numero(ts["cantidad"])),
        dict(label="Ticket por trabajo", value=formatear_moneda_card(ts["ticket"]),
             delta=f"{formatear_moneda(ts['valor_por_ha'])} por ha", delta_color="off", delta_arrow="off"),
    ], por_fila=3)

    s1, s2 = st.columns(2)
    with s1:
        st.subheader(f"Has trabajadas ({granularidad.lower()})")
        has = periodos[periodos["has_trabajadas"] > 0] if not periodos.empty else periodos
        if hay_datos(has):
            fig = px.bar(has, x=x, y="has_trabajadas", custom_data=["periodo_label"],
                         labels={x: "", "has_trabajadas": "Has"})
            fig.update_traces(marker_color=COLORES_UNIDAD[SERVICIO],
                              hovertemplate="%{customdata[0]}<br>%{y:,.0f} ha<extra></extra>")
            fig.update_yaxes(tickformat=",.0f")
            formatear_eje_periodo(fig, has, granularidad)
            grafico(fig, key="has_por_periodo", eje_moneda=None)

    with s2:
        st.subheader(f"Ingreso de servicios ({granularidad.lower()})")
        if hay_datos(periodos):
            fig = px.bar(periodos, x=x, y="ingreso_servicios", custom_data=["periodo_label"],
                         labels={x: "", "ingreso_servicios": "US$"})
            fig.update_traces(marker_color=COLORES_UNIDAD[SERVICIO],
                              hovertemplate=f"%{{customdata[0]}}<br>%{{y:{HOVER_MONEDA}}}<extra></extra>")
            formatear_eje_periodo(fig, periodos, granularidad)
            grafico(fig, key="ingreso_servicios_periodo")

# ---------------------------------------------------------------------------
# Top performers
# ---------------------------------------------------------------------------
st.divider()
st.markdown("#### 🏆 Top performers")
st.caption("Ordenados por **ingreso real de Agropix**: comisión en equipos, facturado en servicios.")

t1, t2 = st.columns(2)
with t1:
    st.subheader("Top 10 clientes")
    clientes = top_clientes(servicios, ops, top=10)
    if hay_datos(clientes):
        st.dataframe(
            clientes, hide_index=True, width="stretch", height=ALTO_GRAFICO,
            column_config={"cliente": "Cliente",
                           "servicios": columna_moneda("Servicios"),
                           "equipos": columna_moneda("Equipos (comisión)"),
                           "ingreso": columna_moneda("Ingreso total")},
        )

with t2:
    st.subheader("Vendedores por comisión cobrada")
    vendedores = ranking_vendedores(ops)
    if hay_datos(vendedores):
        st.dataframe(
            vendedores, hide_index=True, width="stretch", height=ALTO_GRAFICO,
            column_order=["vendedor", "comision_cobrada", "comision_generada", "por_cobrar",
                          "pct_cobranza", "unidades"],
            column_config={"vendedor": "Vendedor",
                           "comision_cobrada": columna_moneda("Cobrada"),
                           "comision_generada": columna_moneda("Generada"),
                           "por_cobrar": columna_moneda("Por cobrar"),
                           "pct_cobranza": st.column_config.ProgressColumn(
                               "% cobro", format="percent", min_value=0, max_value=1),
                           "unidades": st.column_config.NumberColumn("Equipos", format="%,.0f")},
        )
        st.caption("Solo venta de equipos: el CRM de servicios registra **Operador 1..4** (quien ejecuta el "
                   "trabajo), no vendedor.")

# ---------------------------------------------------------------------------
# Canal
# ---------------------------------------------------------------------------
st.divider()
st.markdown("#### 📡 Comisiones por canal")
st.caption("Origen del lead en la venta de equipos. El volumen intermediado va como referencia, no como ingreso.")

canal = comisiones_por_canal(ops)
n1, n2 = st.columns([2, 1])
with n1:
    if hay_datos(canal):
        largo = canal.melt(id_vars="canal", value_vars=["comision_cobrada", "por_cobrar"],
                           var_name="estado", value_name="monto")
        largo["estado"] = largo["estado"].map({"comision_cobrada": COBRADO, "por_cobrar": POR_COBRAR})
        fig = px.bar(largo, x="monto", y="canal", orientation="h", color="estado",
                     color_discrete_map=COLORES_COBRO, category_orders={"estado": [COBRADO, POR_COBRAR]},
                     labels={"monto": "US$", "canal": "", "estado": ""})
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_traces(hovertemplate=f"%{{y}} · %{{fullData.name}}<br>%{{x:{HOVER_MONEDA}}}<extra></extra>")
        grafico(fig, key="comisiones_canal", eje_moneda="x")

with n2:
    if hay_datos(canal):
        st.dataframe(
            canal, hide_index=True, width="stretch", height=ALTO_GRAFICO,
            column_order=["canal", "comision_cobrada", "pct_cobranza", "volumen"],
            column_config={"canal": "Canal",
                           "comision_cobrada": columna_moneda("Cobrada"),
                           "pct_cobranza": st.column_config.ProgressColumn(
                               "% cobro", format="percent", min_value=0, max_value=1),
                           "volumen": columna_moneda("Volumen")},
        )

# ---------------------------------------------------------------------------
# Cobranza sobre lo facturado: queda plegada para no competir con las comisiones
# ---------------------------------------------------------------------------
st.divider()
with st.expander("📄 Cobranza sobre lo facturado (no es el ingreso de Agropix)"):
    st.caption("Esta sección mide lo **facturado**: Valor total de ventas en servicios y Facturado s/IVA al "
               "cliente en equipos. Sirve para seguir la cobranza de las facturas, no para medir el ingreso de "
               "Agropix: de la factura de un dron, a Agropix le entra sólo la comisión.")

    k = kpis_general(u)
    metricas([
        dict(label="Facturación total", value=formatear_moneda_card(k["venta_total"]),
             help=f"{formatear_moneda_completa(k['venta_total'])} (servicios + Facturado s/IVA de equipos)"),
        dict(label="% Cobrado", value=formatear_porcentaje(k["pct_cobrado"]),
             delta=formatear_moneda(k["cobrado"]), delta_color="off", delta_arrow="off",
             help=f"{formatear_moneda_completa(k['cobrado'])} cobrados"),
        dict(label="% Por cobrar", value=formatear_porcentaje(k["pct_por_cobrar"]),
             delta=formatear_moneda(k["por_cobrar"]), delta_color="off", delta_arrow="off",
             help=f"{formatear_moneda_completa(k['por_cobrar'])} por cobrar"),
        dict(label="Clientes con venta", value=formatear_numero(k["clientes"]),
             help="Clientes distintos con al menos una venta no cancelada en el período"),
    ], por_fila=4)

    if k["en_proceso"] > 0:
        st.caption(f"Otros {formatear_moneda(k['en_proceso'])} "
                   f"({formatear_porcentaje(k['en_proceso'] / k['venta_total'])}) corresponden a servicios en "
                   "proceso (ni cobrados ni facturados).")

    v = vigentes(u)
    v = v[v["monto"] > 0].assign(
        unidad_negocio=lambda d: d["unidad_negocio"].astype(str),
        estado_cobro=lambda d: d["estado_cobro"].astype(str),
    )

    f1, f2 = st.columns(2)
    with f1:
        st.subheader("Facturado: cobrado vs por cobrar")
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

    with f2:
        st.subheader("Ticket promedio facturado por mes")
        tabla = ticket_por_mes(u)
        if hay_datos(tabla):
            tabla = (tabla.assign(mes=pd.to_datetime(tabla["mes"], format="%Y-%m"))
                     .sort_values("mes", ascending=False))
            st.dataframe(
                tabla, hide_index=True, width="stretch", height=ALTO_GRAFICO, placeholder="—",
                column_config={"mes": st.column_config.DateColumn("Mes", format="MM/YYYY"),
                               **{c: columna_moneda(c) for c in tabla.columns if c != "mes"}},
            )
