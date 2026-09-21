import pandas as pd
import plotly.express as px
import streamlit as st

from utils.comisiones import comisiones_por_canal, ranking_vendedores, ticket_promedio_equipos
from utils.data import (
    COBRADO, EQUIPOS, POR_COBRAR, kpis_equipos, resumen_por_modelo, vigentes,
)
from utils.format import (
    AMBAR, COLORES_COBRO, COLORES_UNIDAD, ETIQUETA_MONEDA, HOVER_MONEDA,
    formatear_moneda_card, formatear_moneda_completa, formatear_numero,
)
from utils.ui import (
    columna_moneda, espacio_para_etiquetas, grafico, hay_datos, tarjetas_kpi,
)

COLOR = COLORES_UNIDAD[EQUIPOS]

datos = st.session_state["datos"]
ops, unidades = datos["equipos"], datos["unidades"]

st.title("🛸 Venta de Equipos")
st.caption("Fuente: Ventas. Una operación puede incluir varios equipos; las devueltas no suman.")

k = kpis_equipos(ops, unidades)
te = ticket_promedio_equipos(ops, unidades)

# La comision va primero: es el ingreso real de Agropix. El facturado al cliente
# queda al final, como volumen intermediado.
tarjetas_kpi([
    dict(label="💰 Comisión cobrada", valor=formatear_moneda_card(k["comision_cobrada"]),
         gradiente="cobradas"),
    dict(label="⏳ Comisión por cobrar", valor=formatear_moneda_card(k["comision_por_cobrar"]),
         gradiente="por_cobrar"),
    dict(label="🎫 Ticket por equipo", valor=formatear_moneda_card(te["ticket_cobrado"]),
         gradiente="generadas"),
    dict(label="🛸 Unidades vendidas", valor=formatear_numero(k["unidades"]), gradiente="neutro"),
    dict(label="📦 Volumen intermediado", valor=formatear_moneda_card(k["monto"]),
         gradiente="neutro"),
])

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
    st.subheader("Comisión por canal (origen del lead)")
    canal = comisiones_por_canal(ops)
    if hay_datos(canal):
        largo = canal.melt(id_vars="canal", value_vars=["comision_cobrada", "por_cobrar"],
                           var_name="estado", value_name="monto")
        largo["estado"] = largo["estado"].map({"comision_cobrada": "Cobrada", "por_cobrar": "Por cobrar"})
        fig = px.bar(largo[largo["monto"] > 0], x="monto", y="canal", orientation="h", color="estado",
                     color_discrete_map={"Cobrada": COLORES_COBRO[COBRADO],
                                         "Por cobrar": COLORES_COBRO[POR_COBRAR]},
                     category_orders={"estado": ["Cobrada", "Por cobrar"]},
                     labels={"canal": "", "monto": "US$", "estado": ""})
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_traces(hovertemplate=f"%{{y}} · %{{fullData.name}}<br>%{{x:{HOVER_MONEDA}}}<extra></extra>")
        grafico(fig, key="comision_por_canal", eje_moneda="x")
        st.caption("El volumen intermediado por canal está en la tabla del Reporte General.")

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
            column_order=["vendedor", "comision_generada", "comision_cobrada", "unidades"],
            column_config={
                "vendedor": "Vendedor",
                "comision_generada": columna_moneda("Comisión generada"),
                "comision_cobrada": columna_moneda("Comisión cobrada"),
                "unidades": st.column_config.NumberColumn("Unidades", format="%,.0f"),
            },
        )
