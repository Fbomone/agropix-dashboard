import pandas as pd
import streamlit as st

from utils.data import FECHA_MAX, FECHA_MIN, SIN_MODELO, cargar_precios, guardar_precios, normalizar
from utils.ui import FECHA

datos = st.session_state["datos_completos"]

st.title("⚙️ Configuración")

if st.session_state.pop("precios_guardados", False):
    st.success("Precios guardados. Los reportes ya usan los valores nuevos.")

# ---------------------------------------------------------------------------
# Calidad de datos
# ---------------------------------------------------------------------------
st.header("🩺 Calidad de datos")
st.caption(
    f"Lo que llega realmente desde Google Sheets, sin filtro de periodo. Fechas aceptadas: "
    f"{FECHA_MIN:%d/%m/%Y} a {FECHA_MAX:%d/%m/%Y}; fuera de ese rango la celda queda sin fecha. "
    "Las alertas son informativas: la app sigue funcionando."
)
calidad = datos["calidad"]

st.subheader("Alertas")

faltantes = calidad["columnas_faltantes"]
if any(faltantes.values()):
    for origen, columnas in faltantes.items():
        if columnas:
            st.error(f"**{origen}**: columnas esperadas por el código que no están en el Sheet: "
                     + ", ".join(f"`{c}`" for c in columnas))
else:
    st.success("Todas las columnas esperadas existen en ambos Sheets.")

fi = calidad["fechas_invalidas"]
if fi.empty:
    st.success("Sin fechas inválidas ni fuera de rango.")
else:
    st.warning(f"**{len(fi)} celda(s) con fecha inválida o fuera de rango.** "
               "Esas filas quedan sin fecha y no entran en ningún periodo.")
    st.dataframe(fi.groupby(["origen", "columna"]).size().reset_index(name="celdas"), hide_index=True)
    config_fi = {"origen": "Origen", "columna": "Columna", "fila_sheet": "Fila Sheet",
                 "valor_crudo": "Valor crudo", "leido_como": "Leído sin límite de rango"}
    st.caption("Muestra (5)")
    st.dataframe(fi.head(5), hide_index=True, width="stretch", column_config=config_fi)
    if len(fi) > 5:
        with st.expander(f"Ver las {len(fi)} celdas"):
            st.dataframe(fi, hide_index=True, width="stretch", column_config=config_fi)

mc = calidad["montos_cero"]
if mc.empty:
    st.success("No hay filas con fecha y cliente pero monto 0.")
else:
    por_origen = ", ".join(f"{o}: {n}" for o, n in mc["origen"].value_counts().items())
    st.warning(f"**{len(mc)} fila(s) con monto 0 pero con fecha y cliente** ({por_origen}). "
               "Puede ser un monto sin cargar o un parseo fallido: revisá el valor crudo y el estado.")
    config_mc = {"origen": "Origen", "fila_sheet": "Fila Sheet", "fecha": FECHA, "cliente": "Cliente",
                 "estado": "Estado / última acción", "columna_monto": "Columna", "valor_crudo": "Valor crudo"}
    st.caption("Muestra (5)")
    st.dataframe(mc.head(5), hide_index=True, width="stretch", column_config=config_mc)
    if len(mc) > 5:
        with st.expander(f"Ver las {len(mc)} filas"):
            st.dataframe(mc, hide_index=True, width="stretch", column_config=config_mc)

msp = calidad["modelos_sin_precio"]
if msp.empty:
    st.success("Todos los modelos vendidos tienen precio de lista.")
else:
    st.warning(f"**{len(msp)} modelo(s) vendidos sin precio de lista.** Cuentan como unidades y su factura "
               "suma a la venta total, pero no se reparten por modelo. Cargalos en Precios de lista.")
    st.dataframe(msp, hide_index=True,
                 column_config={"modelo": "Modelo", "unidades": "Unidades", "operaciones": "Operaciones"})

st.subheader("Perfil de columnas")
st.caption("Una fila por columna del Sheet. *Tipos de valor* muestra la mezcla real (p. ej. int y str en la "
           "misma columna); *Usada como* indica qué campo del dashboard la consume.")
config_perfil = {
    "columna": "Columna (repr)", "dtype": "dtype pandas", "tipos_python": "Tipos de valor",
    "pct_nulos": st.column_config.NumberColumn("% nulos", format="percent"), "unicos": "Únicos",
    "ejemplos": "Ejemplos", "usada_como": "Usada como",
}
for tab, origen in zip(st.tabs(["CRM – Trabajos", "Ventas"]), ["CRM", "Ventas"]):
    perfil = datos["perfil"][origen]
    tab.caption(f"{perfil['filas']} filas · {len(perfil['tabla'])} columnas")
    tab.dataframe(perfil["tabla"], hide_index=True, width="stretch", column_config=config_perfil)

# ---------------------------------------------------------------------------
# Precios de lista
# ---------------------------------------------------------------------------
st.divider()
st.header("Precios de lista")
st.caption(
    "Se usan solo para repartir la factura entre los equipos de una misma operación; la venta total "
    "sale siempre de Factura s/IVA. Dejá el precio vacío si todavía no está confirmado."
)

precios = cargar_precios()
unidades = datos["unidades"]
en_base = {normalizar(m) for m in unidades["modelo"] if m != SIN_MODELO}

# Modelos que aparecen en la base y todavia no estan en el archivo
conocidos = {normalizar(m) for m in precios}
for modelo in sorted({m for m in unidades["modelo"] if m != SIN_MODELO}):
    if normalizar(modelo) not in conocidos:
        precios[modelo] = None
        conocidos.add(normalizar(modelo))

tabla = pd.DataFrame({
    "modelo": list(precios),
    "precio_lista": pd.array(list(precios.values()), dtype="Float64"),
    "en_base": [normalizar(m) in en_base for m in precios],
})

editado = st.data_editor(
    tabla,
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
    column_config={
        "modelo": st.column_config.TextColumn("Modelo", required=True),
        "precio_lista": st.column_config.NumberColumn("Precio de lista (US$)", min_value=0, step=100,
                                                      format="%.0f"),
        "en_base": st.column_config.CheckboxColumn("Aparece en ventas", disabled=True),
    },
    key="editor_precios",
)

if st.button("💾 Guardar precios", type="primary"):
    nuevos = {}
    for modelo, precio in zip(editado["modelo"], editado["precio_lista"]):
        if pd.isna(modelo) or not str(modelo).strip():
            continue
        nuevos[str(modelo).strip()] = float(precio) if pd.notna(precio) and precio > 0 else None
    guardar_precios(nuevos)
    st.session_state["precios_guardados"] = True
    st.rerun()
