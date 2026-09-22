"""Panel de administración. Va en paginas/ y no en pages/ a propósito.

Con la carpeta `pages/`, Streamlit arma su navegación vieja y una URL directa a
la página la ejecuta SIN pasar por app.py: el panel quedaría accesible sin
login. Acá la página sólo existe si app.py la declara, y app.py la declara
únicamente cuando la sesión es de un admin. Igual se revalida abajo, para que la
página sea segura por sí misma si alguien la agrega a la navegación por error.
"""
import platform
import sys
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from utils import envio_log
from utils.auth import ADMINS, EMAILS_AUTORIZADOS, audit_log, cargar_usuarios, sesion_es_admin
from utils.data import aplicar_filtros
from utils.email_sender import configurado, enviar_individual, transporte, validar_conexion
from utils.format import formatear_moneda, formatear_numero
from utils.reporte_semanal import (
    DESTINATARIOS, asunto, cuerpo_html, etiqueta_periodo, kpis_semana, nombre_pdf,
    semana_reporte, top_clientes_semana,
)
from utils.version import VERSION, resumen_entorno

# Doble portería: app.py ya no declara esta página para no-admins, pero si algún
# día se declara de más, acá se corta igual.
if not sesion_es_admin():
    audit_log("acceso_denegado_admin", st.session_state.get("auth_email", "-"))
    st.error("Acceso denegado: el panel de administración es sólo para administradores.", icon="🚫")
    st.stop()

st.title("⚙️ Panel de administración")
st.caption(f"Agropix Dashboard {VERSION} · administradores: {', '.join(ADMINS)}")

datos_completos = st.session_state["datos_completos"]

tab_envio, tab_validacion, tab_historial, tab_sistema = st.tabs(
    ["📧 Envío de prueba", "🔧 Validación", "📋 Historial", "ℹ️ Sistema"]
)

# ---------------------------------------------------------------------------
# Envío manual
# ---------------------------------------------------------------------------
with tab_envio:
    st.subheader("Envío manual de reporte")
    listo, motivo = configurado()
    if not listo:
        st.warning(f"El envío no está configurado: {motivo} "
                   "Mientras tanto se puede generar el PDF y descargarlo desde acá.", icon="⚙️")

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**Destinatarios**")
        st.caption("Arranca con sólo el admin tildado: conviene probar a uno antes de los 7.")
        elegidos = []
        for email in DESTINATARIOS:
            # Por defecto, únicamente el admin: una prueba no debería llegarle a
            # todo el equipo hasta que sepas que el PDF y el mail salen bien.
            if st.checkbox(email, value=email in ADMINS, key=f"dest_{email}"):
                elegidos.append(email)

    with c2:
        st.markdown("**Período del reporte**")
        opciones = {
            "Semana del reporte (viernes a viernes)": "semana_anterior",
            "Esta semana (en curso)": "esta_semana",
            "Últimos 7 días": "ultimos_7",
            "Personalizado": "personalizado",
        }
        elegida = st.radio("Período", list(opciones), label_visibility="collapsed", key="periodo_admin")
        modo = opciones[elegida]
        hoy = date.today()

        if modo == "semana_anterior":
            desde, hasta = semana_reporte(hoy)
        elif modo == "esta_semana":
            desde, hasta = hoy - timedelta(days=hoy.weekday()), hoy
        elif modo == "ultimos_7":
            desde, hasta = hoy - timedelta(days=6), hoy
        else:
            desde = st.date_input("Desde", hoy - timedelta(days=7), format="DD/MM/YYYY", key="admin_desde")
            hasta = st.date_input("Hasta", hoy, format="DD/MM/YYYY", key="admin_hasta")

        if desde > hasta:
            st.error("El período está invertido: «desde» es posterior a «hasta».", icon="📅")
            st.stop()
        st.info(f"**{etiqueta_periodo(desde, hasta)}** — {desde:%d/%m/%Y} a {hasta:%d/%m/%Y}", icon="📅")

    datos = aplicar_filtros(datos_completos, desde, hasta, None)
    k = kpis_semana(datos)
    st.markdown("**Lo que va a decir el reporte**")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Comisiones cobradas", formatear_moneda(k["comision_cobrada"]))
    m2.metric("Comisiones generadas", formatear_moneda(k["comision_generada"]))
    m3.metric("Por cobrar", formatear_moneda(k["por_cobrar"]))
    m4.metric("Has trabajadas", f"{formatear_numero(k['hectareas'])} ha")
    if k["comision_generada"] == 0 and k["cantidad_servicios"] == 0:
        st.warning("El período elegido no tiene movimiento en las planillas: el reporte va a salir "
                   "en cero. Sirve igual como prueba de envío.", icon="📭")

    st.divider()
    if st.button("🚀 Generar y enviar", type="primary", width="stretch",
                 disabled=not (listo and elegidos)):
        with st.spinner("Generando el PDF…"):
            try:
                from utils.pdf import generar_pdf

                pdf = generar_pdf(datos, {"desde": desde, "hasta": hasta, "estados_trabajo": None,
                                          "estados_opciones": [], "granularidad": "Semanal"})
            except Exception as e:
                st.error(f"No se pudo generar el PDF: {e}")
                st.stop()

        with st.spinner(f"Enviando a {len(elegidos)} destinatario(s)…"):
            resultado = enviar_individual(
                pdf, nombre_pdf(hasta), elegidos, asunto=asunto(desde, hasta),
                html=cuerpo_html(k, desde, hasta, top_clientes_semana(datos)),
                periodo=etiqueta_periodo(desde, hasta),
            )
        entrada = envio_log.registrar(
            resultado, tipo=envio_log.PRUEBA, periodo=etiqueta_periodo(desde, hasta),
            usuario=st.session_state.get("auth_email", "-"),
        )
        st.session_state["_admin_ultimo_envio"] = entrada
        st.session_state["_admin_pdf"] = {"bytes": pdf, "nombre": nombre_pdf(hasta)}
        st.rerun()

    if not elegidos:
        st.caption("Tildá al menos un destinatario.")

    ultimo = st.session_state.get("_admin_ultimo_envio")
    if ultimo:
        st.divider()
        if ultimo["estado"] == "OK":
            st.success(f"Enviado a {ultimo['exitosos']} destinatario(s) · {ultimo['momento']}")
        elif ultimo["estado"] == "PARCIAL":
            st.warning(f"Enviado a {ultimo['exitosos']} de {ultimo['total']} · {ultimo['momento']}")
        else:
            st.error(f"No se pudo enviar a ninguno de los {ultimo['total']} · {ultimo['momento']}")
        for d in ultimo["detalle"]:
            if d["exitoso"]:
                st.write(f"✅ {d['email']}")
            else:
                st.write(f"❌ {d['email']} — {d.get('error', 'error desconocido')}")

    pdf_guardado = st.session_state.get("_admin_pdf")
    if pdf_guardado:
        st.download_button("⬇️ Descargar el PDF que se envió", data=pdf_guardado["bytes"],
                           file_name=pdf_guardado["nombre"], mime="application/pdf",
                           on_click="ignore", width="stretch")

# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
with tab_validacion:
    st.subheader("Validación del envío")
    via = transporte()
    if via == "smtp":
        st.caption("Vía activa: **SMTP (Gmail)**. Conecta y autentica sin mandar ningún mail.")
    elif via == "sendgrid":
        st.caption("Vía activa: **SendGrid**. Consulta la API sin mandar nada: comprueba que la "
                   "key sirva y que el remitente esté verificado, que es la causa más común de "
                   "un 403 al enviar.")
    else:
        st.caption("No hay vía de envío configurada. Cargá `[smtp]` con un App Password de Gmail, "
                   "o `[sendgrid]` con una API key.")

    if st.button("🔌 Probar la conexión", width="stretch"):
        with st.spinner("Consultando SendGrid…"):
            st.session_state["_admin_validacion"] = validar_conexion()

    validacion = st.session_state.get("_admin_validacion")
    if validacion:
        (st.success if validacion["exitoso"] else st.error)(validacion["mensaje"])
        st.markdown("**Detalles técnicos**")
        st.dataframe(
            pd.DataFrame({"Dato": list(validacion["detalles"]),
                          "Valor": [str(v) for v in validacion["detalles"].values()]}),
            hide_index=True, width="stretch",
        )

    st.divider()
    st.markdown("**Usuarios habilitados**")
    con_clave = cargar_usuarios()
    st.caption(f"{len(con_clave)} de {len(EMAILS_AUTORIZADOS)} tienen contraseña cargada en los "
               "secrets. Los que no, figuran en la lista pero no pueden entrar.")
    st.dataframe(
        pd.DataFrame([
            {"Email": email,
             "Contraseña cargada": "sí" if email in con_clave else "no",
             "Rol": "administrador" if email in ADMINS else "usuario",
             "Clave en [auth_users]": clave}
            for email, clave in EMAILS_AUTORIZADOS.items()
        ]),
        hide_index=True, width="stretch",
    )

# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------
with tab_historial:
    st.subheader("Historial de envíos")
    entradas = envio_log.historial()
    resumen = envio_log.resumen(entradas)

    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Envíos registrados", resumen["envios"])
    h2.metric("Completos", resumen["ok"])
    h3.metric("Parciales", resumen["parciales"])
    h4.metric("Fallidos", resumen["errores"])

    st.info("En Streamlit Cloud el disco es **efímero**: este historial se borra en cada reinicio "
            "del contenedor. Lo que queda de verdad son los logs de *Manage app → Logs* y el "
            "Activity Feed de SendGrid.", icon="ℹ️")

    if not entradas:
        st.caption("Todavía no hay envíos registrados.")
    else:
        tipos = ["Todos"] + sorted({e.get("tipo", "?") for e in entradas})
        tipo = st.selectbox("Filtrar por tipo", tipos, key="filtro_tipo_envio")
        visibles = entradas if tipo == "Todos" else [e for e in entradas if e.get("tipo") == tipo]

        st.dataframe(
            pd.DataFrame([{
                "Fecha/hora": e["momento"].replace("T", " ")[:16],
                "Tipo": e.get("tipo", "?"),
                "Período": e.get("periodo", ""),
                "Destinatarios": e["total"],
                "Estado": {"OK": "✅ OK", "PARCIAL": "⚠️ Parcial"}.get(e["estado"], "❌ Error"),
                "Lo pidió": e.get("usuario", "-"),
            } for e in visibles]),
            hide_index=True, width="stretch",
        )
        for e in visibles[:10]:
            with st.expander(f"{e['momento'].replace('T', ' ')[:16]} · {e.get('tipo', '?')} · "
                             f"{e['exitosos']}/{e['total']}"):
                for d in e.get("detalle", []):
                    if d.get("exitoso"):
                        st.write(f"✅ {d['email']}")
                    else:
                        st.write(f"❌ {d['email']} — {d.get('error', '')}")

# ---------------------------------------------------------------------------
# Sistema
# ---------------------------------------------------------------------------
with tab_sistema:
    st.subheader("Información del sistema")
    entorno = resumen_entorno()

    s1, s2 = st.columns(2)
    with s1:
        st.markdown("**Aplicación**")
        st.dataframe(
            pd.DataFrame({"Dato": list(entorno), "Valor": [str(v) for v in entorno.values()]}),
            hide_index=True, width="stretch",
        )
    with s2:
        st.markdown("**Datos cargados**")
        perfil = datos_completos["perfil"]
        servicios, equipos = datos_completos["servicios"], datos_completos["equipos"]
        fechas = pd.concat([servicios["fecha"], equipos["fecha"]]).dropna()
        st.dataframe(
            pd.DataFrame([
                {"Dato": "Filas en Ventas (Sheet)", "Valor": formatear_numero(perfil["Ventas"]["filas"])},
                {"Dato": "Filas en Trabajos (Sheet)", "Valor": formatear_numero(perfil["CRM"]["filas"])},
                {"Dato": "Operaciones de equipos", "Valor": formatear_numero(len(equipos))},
                {"Dato": "Unidades (equipos + accesorios)", "Valor": formatear_numero(len(datos_completos["unidades"]))},
                {"Dato": "Trabajos de servicios", "Valor": formatear_numero(len(servicios))},
                {"Dato": "Período cubierto",
                 "Valor": f"{fechas.min():%d/%m/%Y} a {fechas.max():%d/%m/%Y}" if not fechas.empty else "sin fechas"},
            ]),
            hide_index=True, width="stretch",
        )

    st.caption("Los datos se leen de Google Sheets en vivo y quedan en caché hasta que alguien "
               "toca «🔄 Actualizar datos» en la barra lateral o se reinicia la app.")

    st.divider()
    st.markdown("**Accesos registrados**")
    st.caption("Últimas líneas de la auditoría de accesos (login, logout, intentos fallidos y "
               "bloqueos). También van al log de consola, que es lo que persiste en Cloud.")
    try:
        from utils.auth import ARCHIVO_AUDITORIA

        lineas = ARCHIVO_AUDITORIA.read_text(encoding="utf-8").splitlines()[-40:]
    except OSError:
        lineas = []
    if lineas:
        filas = []
        for linea in reversed(lineas):
            partes = linea.split("\t")
            if len(partes) >= 3:
                filas.append({"Momento": partes[0].replace("T", " "), "Evento": partes[1],
                              "Usuario": partes[2], "Detalle": partes[3] if len(partes) > 3 else ""})
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
    else:
        st.caption("Sin auditoría en disco (es lo esperado en Streamlit Cloud: sólo va al log de consola).")

    st.divider()
    reporte = "\n".join([
        f"Agropix Dashboard — reporte técnico ({VERSION})",
        *(f"{clave}: {valor}" for clave, valor in entorno.items()),
        "",
        f"Python ejecutable: {sys.executable}",
        f"Plataforma: {platform.platform()}",
        "",
        "Usuarios autorizados:",
        *(f"  {email} — {'admin' if email in ADMINS else 'usuario'}, "
          f"contraseña {'cargada' if email in cargar_usuarios() else 'FALTA'}"
          for email in EMAILS_AUTORIZADOS),
    ])
    st.download_button("⬇️ Descargar reporte técnico", data=reporte.encode("utf-8"),
                       file_name=f"agropix_reporte_tecnico_{date.today():%Y%m%d}.txt",
                       mime="text/plain", on_click="ignore", width="stretch")
