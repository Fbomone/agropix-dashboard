"""Asistente IA: preguntas en lenguaje natural sobre los datos del dashboard.

Ver docs/ASISTENTE_IA.md. La pagina solo LEE lo que app.py deja en la sesion
("datos", "datos_completos" y los filtros): no los modifica, no vuelve a leer
Google Sheets ni toca la cache. Los numeros salen de utils/herramientas_chat.py,
que reutiliza las mismas funciones que las tarjetas.
"""
import streamlit as st

from utils import agente
from utils.auth import sesion_es_admin, usuario_actual

SUGERENCIAS = (
    "¿Cuánto ingresó Agropix en el período?",
    "¿Quiénes son los 5 mejores clientes?",
    "¿Qué está pendiente de cobro?",
    "¿Cómo vienen los ingresos mes a mes?",
)

st.title("💬 Asistente IA")
st.caption("Preguntá sobre servicios, equipos, clientes y cobranzas. Usa el período y los estados "
           "del filtro de la izquierda salvo que indiques otro.")

config = agente.configuracion()
if not config["api_key"]:
    st.info(
        "El asistente todavía no está configurado. Para activarlo hay que cargar `GROQ_API_KEY` "
        "en los secrets: en Streamlit Cloud, **Settings → Secrets**; en local, "
        "`.streamlit/secrets.toml`. La key se crea gratis en https://console.groq.com/keys "
        "(ver la sección «Asistente IA» de DEPLOY.md). El resto del dashboard funciona igual.",
        icon="🔑",
    )
    st.stop()


def _contexto() -> dict:
    """Lo que necesitan las herramientas. Referencias de solo lectura a la sesion."""
    periodo = st.session_state.get("periodo")
    desde, hasta = periodo if isinstance(periodo, tuple) and len(periodo) == 2 else (None, None)
    return {
        "datos": st.session_state["datos"],
        "datos_completos": st.session_state["datos_completos"],
        "estados_trabajo": list(st.session_state.get("estados_trabajo") or []),
        "desde": desde,
        "hasta": hasta,
    }


def _describir_argumentos(argumentos) -> str:
    if not isinstance(argumentos, dict):
        return "argumentos no válidos"
    if not argumentos:
        return "período del filtro"
    return ", ".join(f"{k}={v}" for k, v in argumentos.items())


def _mostrar_pasos(pasos: list) -> None:
    if not pasos:
        return
    with st.expander("🔎 Cómo lo calculé"):
        for p in pasos:
            st.markdown(f"- `{p['herramienta']}` ({_describir_argumentos(p['argumentos'])}) → {p['resultado']}")


def _elegir_sugerencia(texto: str) -> None:
    st.session_state["_chat_sugerencia"] = texto


def _nueva_conversacion() -> None:
    st.session_state["chat_mensajes"] = []


mensajes = st.session_state.setdefault("chat_mensajes", [])
pregunta = st.session_state.pop("_chat_sugerencia", None)

for m in mensajes:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant":
            _mostrar_pasos(m.get("pasos", []))

if not mensajes and not pregunta:
    columnas = st.columns(len(SUGERENCIAS))
    for i, (columna, texto) in enumerate(zip(columnas, SUGERENCIAS)):
        columna.button(texto, key=f"chat_sugerencia_{i}", width="stretch",
                       on_click=_elegir_sugerencia, args=(texto,))

usuario = usuario_actual() or {"email": "-"}
es_admin = sesion_es_admin()
restantes = agente.preguntas_restantes(usuario["email"], config["limite_diario"], es_admin)

escrita = st.chat_input("Escribí tu pregunta…", disabled=restantes == 0)
pregunta = pregunta or escrita

if pregunta:
    # Al modelo no le sirven las respuestas que fueron errores ("no pude conectarme…")
    historial = [m for m in mensajes if not m.get("error")]
    mensajes.append({"role": "user", "content": pregunta})
    with st.chat_message("user"):
        st.markdown(pregunta)
    with st.chat_message("assistant"):
        with st.spinner("Pensando…"):
            respuesta = agente.responder(pregunta, historial, _contexto(), config=config)
        st.markdown(respuesta.texto)
        _mostrar_pasos(respuesta.pasos)
    mensajes.append({"role": "assistant", "content": respuesta.texto, "pasos": respuesta.pasos,
                     "error": respuesta.error})
    restantes = agente.preguntas_restantes(usuario["email"], config["limite_diario"], es_admin)

st.divider()
izquierda, derecha = st.columns([3, 1])
with izquierda:
    if restantes is None:
        st.caption("Sin límite de preguntas (administrador).")
    elif restantes == 0:
        st.warning(agente.mensaje_limite(config["limite_diario"]), icon="⏳")
    else:
        st.caption(f"Te {'queda' if restantes == 1 else 'quedan'} {restantes} "
                   f"pregunta{'' if restantes == 1 else 's'} hoy.")
with derecha:
    st.button("🗑️ Nueva conversación", width="stretch", on_click=_nueva_conversacion,
              disabled=not mensajes, key="chat_nueva")
st.caption("Las respuestas se generan con IA a partir de los datos del dashboard. "
           "Verificá cifras importantes en los reportes.")
