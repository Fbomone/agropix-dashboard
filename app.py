import streamlit as st

from utils.auth import check_authentication, logout_button
from utils.data import (
    ESTADOS_TRABAJO_EJECUTADO, aplicar_filtros, cantidad_alertas, cargar_crudos, cargar_precios,
    construir_datos, opciones_estado_trabajo, rango_fechas,
)
from utils.ui import aplicar_tema

st.set_page_config(page_title="Agropix Dashboard", page_icon="🌱", layout="wide")
aplicar_tema()

# Porteria: sin sesion valida no se declara la navegacion ni se toca Google Sheets.
# Tiene que ir antes de cargar_crudos() para que los datos del cliente no se lean
# (ni queden cacheados) en una sesion anonima.
usuario = check_authentication()

# Evita que st.metric corte los valores con "…" en columnas angostas
st.html("""
<style>
[data-testid="stMetricValue"] { font-size: 1.6rem; white-space: normal; }
[data-testid="stMetricValue"] > div { white-space: normal; overflow: visible; text-overflow: clip; }
[data-testid="stMetricLabel"] { white-space: normal; }
[data-testid="stMetricLabel"] p { white-space: normal; }
</style>
""")

# Encabezado comun a todas las paginas. Va como franja compacta y no como
# st.title() porque cada pagina ya trae su propio titulo: dos titulos apilados
# en cada pantalla se leen peor que una linea de contexto.
st.html(f"""
<div style="display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:baseline;
            border-left:4px solid #2E7D32;background:#F4F8F4;border-radius:4px;
            padding:.55rem .8rem;margin-bottom:.75rem;font-size:.9rem">
  <strong style="color:#2E7D32">📊 Dashboard Agropix</strong>
  <span style="color:#B3261E;font-weight:600;letter-spacing:.03em">DATOS CONFIDENCIALES</span>
  <span style="color:#5F6B7A;margin-left:auto">
    Bienvenido: <strong>{usuario["email"]}</strong>
  </span>
</div>
""")

# La carpeta NO se llama "pages/": con ese nombre Streamlit activa la navegacion
# vieja y una URL directa a una pagina la ejecuta sin pasar por este archivo.
pagina_config = st.Page("paginas/4_Configuracion.py", title="Configuración", icon="⚙️")
paginas = st.navigation([
    st.Page("paginas/1_Reporte_General.py", title="Reporte General", icon="📊", default=True),
    st.Page("paginas/2_Venta_Servicios.py", title="Venta de Servicios", icon="🚜"),
    st.Page("paginas/3_Venta_Equipos.py", title="Venta de Equipos", icon="🛸"),
    pagina_config,
])

try:
    crm_df, ventas_df = cargar_crudos()
except Exception as e:
    st.error(f"No se pudo leer Google Sheets: {e}")
    st.info(
        "Revisá credentials.json (cuenta de servicio), CRM_SHEET_ID / VENTAS_SHEET_ID en .env "
        "y que ambos Sheets estén compartidos con el email de la cuenta de servicio."
    )
    st.stop()

datos = construir_datos(crm_df, ventas_df, tuple(sorted(cargar_precios().items())))

if datos["problemas_esquema"]:
    st.warning(
        "**ventas_unificadas no cumple el esquema esperado.** Tomá los KPIs con cuidado:\n"
        + "\n".join(f"- {p}" for p in datos["problemas_esquema"]),
        icon="⚠️",
    )

with st.sidebar:
    st.header("Filtros")
    fmin, fmax = rango_fechas(datos)
    desde = hasta = None
    if fmin is None:
        st.warning("No hay registros con fecha válida.")
    else:
        rango = st.date_input("Periodo", (fmin, fmax), min_value=fmin, max_value=fmax,
                              format="DD/MM/YYYY", key="periodo")
        desde, hasta = rango if isinstance(rango, tuple) and len(rango) == 2 else (fmin, fmax)

    opciones_estado = opciones_estado_trabajo(datos["servicios"])
    estados_trabajo = st.multiselect(
        "Estado del trabajo", opciones_estado, default=ESTADOS_TRABAJO_EJECUTADO, key="estados_trabajo",
        help="Filtra los servicios por 'Última acción'. Afecta Venta de Servicios y el Reporte General.",
    )

    sin_fecha = int(datos["servicios"]["fecha"].isna().sum() + datos["equipos"]["fecha"].isna().sum())
    if sin_fecha:
        st.caption(f"{sin_fecha} registro(s) sin fecha válida quedan fuera del periodo.")

    n_alertas = cantidad_alertas(datos["calidad"])
    if n_alertas:
        st.page_link(pagina_config, label=f"{n_alertas} tipo(s) de alerta de calidad", icon="⚠️")

    st.divider()
    if st.button("🔄 Actualizar datos", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Fuente: Google Sheets (en vivo)")

st.session_state["datos_completos"] = datos
st.session_state["estados_trabajo_opciones"] = opciones_estado
st.session_state["datos"] = aplicar_filtros(datos, desde, hasta, estados_trabajo)

# Exportacion PDF: toma los filtros activos, incluso los de otras paginas (operador, granularidad)
filtros_pdf = {
    "desde": desde,
    "hasta": hasta,
    "estados_trabajo": estados_trabajo,
    "estados_opciones": opciones_estado,
    "operadores": st.session_state.get("operadores", st.session_state.get("_filtro_operadores", [])),
    "granularidad": st.session_state.get("granularidad") or st.session_state.get("_filtro_granularidad", "Mensual"),
}
firma_pdf = repr(sorted(filtros_pdf.items()))

with st.sidebar:
    st.divider()
    if st.button("📄 Exportar reporte PDF", width="stretch", key="exportar_pdf"):
        with st.spinner("Generando PDF… puede tardar alrededor de 30 segundos."):
            try:
                from utils.pdf import generar_pdf, nombre_archivo
                st.session_state["_pdf"] = {
                    "firma": firma_pdf,
                    "bytes": generar_pdf(st.session_state["datos"], filtros_pdf),
                    "nombre": nombre_archivo(filtros_pdf),
                }
            except ImportError as e:
                st.session_state.pop("_pdf", None)
                st.error(f"Falta la dependencia '{e.name}' para exportar a PDF. "
                         "Instalala con: pip install -r requirements.txt")
            except Exception as e:
                st.session_state.pop("_pdf", None)
                # ErrorExportacionPDF ya trae un mensaje pensado para el usuario
                st.error(str(e) if type(e).__name__ == "ErrorExportacionPDF" else f"No se pudo generar el PDF: {e}")

    pdf = st.session_state.get("_pdf")
    if pdf and pdf["firma"] == firma_pdf:
        st.download_button("⬇️ Descargar PDF", data=pdf["bytes"], file_name=pdf["nombre"], mime="application/pdf",
                           on_click="ignore", type="primary", width="stretch")
        # El boton de mail solo aparece si SendGrid esta configurado en los secrets
        from utils.email_sender import ErrorEnvioEmail, configurado, enviar_reporte
        mail_listo, mail_motivo = configurado()
        if mail_listo and st.button("✉️ Enviar por mail", width="stretch", key="enviar_mail"):
            periodo = f"{desde:%d/%m/%Y} a {hasta:%d/%m/%Y}" if desde and hasta else ""
            with st.spinner("Enviando…"):
                try:
                    destinos = enviar_reporte(pdf["bytes"], pdf["nombre"], periodo=periodo)
                    st.success(f"Enviado a {', '.join(destinos)}")
                except ErrorEnvioEmail as e:
                    st.error(str(e))
        elif not mail_listo:
            st.caption(f"✉️ Envío por mail no disponible: {mail_motivo}")
    elif pdf:
        st.caption("Cambiaron los filtros: volvé a exportar para actualizar el PDF.")

    logout_button()

paginas.run()

# Advertencia al pie, despues del contenido de la pagina activa
st.divider()
st.html("""
<div style="background-color:#FFF3CD;border:1px solid #FFE08A;padding:12px;
            border-radius:4px;font-size:.88rem;color:#5C4600">
  <strong>⚠️ DATOS CONFIDENCIALES</strong><br>
  Este dashboard contiene información de facturación de Agropix.
  No compartir ni hacer screenshots sin autorización.
</div>
""")
