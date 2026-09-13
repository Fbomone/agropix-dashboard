import pandas as pd
import plotly.express as px
import streamlit as st

from utils.data import COBRADO, EQUIPOS, POR_COBRAR, kpis_equipos, ranking_vendedores, resumen_por_modelo, vigentes
from utils.format import (
    AMBAR, COLORES_COBRO, COLORES_UNIDAD, ETIQUETA_MONEDA, HOVER_MONEDA,
    formatear_moneda, formatear_moneda_completa, formatear_numero, formatear_porcentaje,
)
from utils.ui import barras_por, columna_moneda, espacio_para_etiquetas, grafico, hay_datos, metricas

COLOR = COLORES_UNIDAD[EQUIPOS]

datos = st.session_state["datos"]
ops, unidades = datos["equipos"], datos["unidades"]

st.title("🛸 Venta de Equipos")
st.caption("Fuente: Ventas. Una operación puede incluir varios equipos; las devueltas no suman.")

k = kpis_equipos(ops, unidades)
comision_total = k["comision_cobrada"] + k["comision_por_cobrar"]
metricas([
    dict(label="Unidades vendidas", value=formatear_numero(k["unidades"]),
         delta=f"{formatear_numero(k['operaciones'])} operaciones", delta_color="off", delta_arrow="off",
         help="Cada modelo de la celda 'Modelo' es una unidad; repetido = varias unidades"),
    dict(label="Facturado s/IVA (cliente)", value=formatear_moneda(k["monto"]),
         help=f"{formatear_moneda_completa(k['monto'])}: precio de venta al cliente sin IVA, por operación completa"),
    dict(label="Comisión Agropix cobrada", value=formatear_moneda(k["comision_cobrada"]),
         help=formatear_moneda_completa(k["comision_cobrada"])),
    dict(label="Comisión Agropix por cobrar", value=formatear_moneda(k["comision_por_cobrar"]),
         help=formatear_moneda_completa(k["comision_por_cobrar"])),
    dict(label="Ticket promedio (facturado)", value=formatear_moneda(k["ticket_promedio"]),
         help=f"{formatear_moneda_completa(k['ticket_promedio'])} de Facturado s/IVA por operación"),
])
st.caption(
    "**Facturado s/IVA (cliente)**: precio al cliente sin IVA por toda la operación; depende de la forma de pago, "
    "por eso no coincide con el precio de lista. **Comisión Agropix**: lo que gana Agropix (Comisión % aplicado; "
    f"en el período, {formatear_porcentaje(comision_total / k['monto'] if k['monto'] else 0)} del facturado). "
    "El precio de lista solo reparte el facturado entre los modelos de una misma operación."
)

v = vigentes(ops)

if k["ops_pendientes"]:
    st.warning(
        f"**Facturado pendiente de precio de lista: {formatear_moneda_completa(k['monto_pendiente'])}** en "
        f"{formatear_numero(k['ops_pendientes'])} operación(es). Incluyen modelos sin precio de lista: sus equipos "
        "cuentan como unidades vendidas y la factura suma al facturado total, pero no se reparte por modelo. "
        "Cargá los precios en ⚙️ Configuración."
    )

st.divider()
st.subheader("Ventas por modelo")
rm = resumen_por_modelo(unidades)

if hay_datos(rm):
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Unidades vendidas**")
        unid = rm.melt(id_vars="modelo", value_vars=["unidades_prorrateadas", "unidades_pendientes"],
                       var_name="tipo", value_name="cantidad")
        unid["tipo"] = unid["tipo"].map({"unidades_prorrateadas": "Con monto asignado",
                                         "unidades_pendientes": "Pendiente de precio"})
        unid = unid[unid["cantidad"] > 0]
        fig = px.bar(unid, x="cantidad", y="modelo", color="tipo", orientation="h",
                     color_discrete_map={"Con monto asignado": COLOR, "Pendiente de precio": AMBAR},
                     category_orders={"tipo": ["Con monto asignado", "Pendiente de precio"]},
                     labels={"modelo": "", "cantidad": "Unidades", "tipo": ""})
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_xaxes(tickformat=",d")
        fig.update_traces(hovertemplate="%{y} · %{fullData.name}<br>%{x} unidades<extra></extra>")
        grafico(fig, key="unidades_por_modelo", eje_moneda=None)
    with g2:
        st.markdown("**Facturado s/IVA prorrateado por modelo**")
        con_monto = rm[rm["monto_asignado"].fillna(0) > 0]
        if hay_datos(con_monto):
            fig = px.bar(con_monto, x="monto_asignado", y="modelo", orientation="h",
                         labels={"modelo": "", "monto_asignado": "US$"})
            fig.update_yaxes(categoryorder="total ascending")
            fig.update_traces(marker_color=COLOR, texttemplate=f"%{{x:{ETIQUETA_MONEDA}}}", textposition="outside",
                              cliponaxis=False, hovertemplate=f"%{{y}}<br>%{{x:{HOVER_MONEDA}}}<extra></extra>")
            espacio_para_etiquetas(fig, con_monto["monto_asignado"].max())
            grafico(fig, key="monto_por_modelo", eje_moneda="x")

    st.dataframe(
        rm[["modelo", "estado_precio", "precio_lista", "unidades", "unidades_pendientes", "monto_asignado"]],
        hide_index=True,
        width="stretch",
        placeholder="—",
        column_config={
            "modelo": "Modelo", "estado_precio": "Precio de lista",
            "precio_lista": columna_moneda("Precio lista (solo para prorratear)"),
            "unidades": "Unidades", "unidades_pendientes": "Unid. pendientes de precio",
            "monto_asignado": columna_moneda("Facturado s/IVA prorrateado"),
        },
    )

st.divider()
g3, g4 = st.columns(2)
with g3:
    st.subheader("Formas de pago")
    if hay_datos(v):
        pagos = (v.assign(forma_pago=v["forma_pago"].astype("string").fillna("Sin dato"))
                 .groupby("forma_pago", as_index=False)
                 .agg(operaciones=("id_operacion", "size"), monto=("factura", "sum")))
        fig = px.pie(pagos, values="operaciones", names="forma_pago", hole=0.5, custom_data=["monto"],
                     color_discrete_sequence=px.colors.sequential.Blues_r[:-2])
        fig.update_traces(texttemplate="%{percent:.1%}",
                          hovertemplate=f"%{{label}}<br>%{{value}} operaciones (%{{percent:.1%}})"
                                        f"<br>Facturado s/IVA: %{{customdata[0]:{HOVER_MONEDA}}}<extra></extra>")
        grafico(fig, key="formas_de_pago", eje_moneda=None)
with g4:
    st.subheader("Facturado s/IVA por canal (origen del lead)")
    barras_por(v, "canal", valor="factura", horizontal=True, top=15, color=COLOR)

g5, g6 = st.columns(2)
with g5:
    st.subheader("Comisión Agropix")
    com = pd.DataFrame({"estado": ["Cobrada", "Por cobrar"],
                        "monto": [k["comision_cobrada"], k["comision_por_cobrar"]]})
    if hay_datos(com[com["monto"] > 0]):
        fig = px.bar(com, x="estado", y="monto", color="estado",
                     color_discrete_map={"Cobrada": COLORES_COBRO[COBRADO], "Por cobrar": COLORES_COBRO[POR_COBRAR]},
                     labels={"estado": "", "monto": "US$"})
        fig.update_traces(texttemplate=f"%{{y:{ETIQUETA_MONEDA}}}", textposition="outside", cliponaxis=False,
                          hovertemplate=f"%{{x}}<br>%{{y:{HOVER_MONEDA}}}<extra></extra>")
        fig.update_layout(showlegend=False)
        grafico(fig, key="comisiones")
with g6:
    st.subheader("Top vendedores")
    ranking = ranking_vendedores(ops)
    if hay_datos(ranking):
        st.dataframe(
            ranking,
            hide_index=True,
            width="stretch",
            column_config={"vendedor": "Vendedor", "unidades": "Unidades", "operaciones": "Operaciones",
                           "monto": columna_moneda("Facturado s/IVA")},
        )
