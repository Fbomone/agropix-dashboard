"""Asistente IA: bucle de tool calling contra Groq (ver docs/ASISTENTE_IA.md).

El modelo nunca ve las planillas: elige herramientas de utils/herramientas_chat.py,
recibe solo sus resultados agregados y redacta la respuesta.

Groq expone una API compatible con OpenAI, por eso el cliente es el SDK de
openai con otra base_url. responder() recibe el cliente inyectable para poder
testear el bucle sin red.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import openai
import streamlit as st

from utils.auth import audit_log, sesion_es_admin, usuario_actual
from utils.herramientas_chat import HERRAMIENTAS, ejecutar

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODELO_DEFAULT = "openai/gpt-oss-120b"
MODELO_RESPALDO_DEFAULT = "llama-3.3-70b-versatile"
LIMITE_DIARIO_DEFAULT = 30

MAX_VUELTAS = 5
MAX_HISTORIAL = 6  # mensajes usuario/asistente previos que se reenvian

# Argentina no tiene horario de verano: un offset fijo evita depender de tzdata
HORA_ARGENTINA = timezone(timedelta(hours=-3))

MSJ_LIMITE_GROQ = "El asistente alcanzó el límite gratuito por ahora. Probá de nuevo en un minuto."
MSJ_CONEXION = "No pude conectarme con el servicio de IA. Probá de nuevo."
MSJ_CLAVE = "La clave del servicio de IA no es válida. Avisale a un administrador."
MSJ_GENERICO = "No pude generar la respuesta. Probá de nuevo en un rato."
MSJ_VACIA = "No pude armar una respuesta. Probá reformular la pregunta."
AVISO_VUELTAS = (f"⚠️ Corté la búsqueda después de {MAX_VUELTAS} consultas a los datos: la respuesta "
                 "puede estar incompleta. Probá con una pregunta más concreta.")

PROMPT_SISTEMA = """\
Sos el asistente de datos de Agropix, empresa argentina de aplicaciones y
fumigaciones con drones y venta de drones. Respondés en español rioplatense,
claro y breve, a usuarios internos del dashboard.

REGLAS
- Todos los números salen de las herramientas. Nunca inventes, estimes ni
  calcules cifras por tu cuenta (salvo restas o porcentajes simples sobre
  valores que te devolvió una herramienta). Si no hay herramienta para algo,
  decilo y sugerí qué pantalla del dashboard mirar.
- Si la pregunta no indica período, usá el período de los filtros actuales
  ({periodo_actual}) y mencionalo en la respuesta.
- Montos en dólares con formato US$ 12.345 (punto de miles). Hectáreas: "1.234 ha".
- Respuesta corta: 1 a 4 oraciones o una lista breve / tabla markdown chica.
- Si una herramienta devuelve sin_datos o error, explicalo en simple.
- Solo temas de los datos de Agropix. Para otra cosa, decí amablemente que
  solo podés ayudar con el reporte.

DEFINICIONES DE NEGOCIO
- Ingresos Agropix = Valor total de ventas de servicios + Comisión $ de equipos.
- La factura de equipos NO es ingreso: es "volumen intermediado" (informativo).
- Estados de trabajo que cuentan como venta por defecto: Cobro recibido,
  Facturado esperando cobro, Trabajo realizado. Los trabajos cancelados y los
  equipos devueltos nunca suman ingreso.
- Servicio cobrado = "Cobro recibido"; el resto de lo vendido está por cobrar.
- Equipos: cobrado según la columna Cobrado de la planilla de Ventas.
- Las hectáreas por operador pueden superar las del trabajo (trabajan en
  simultáneo sobre el mismo lote).
- El reparto de comisión por modelo depende del precio de lista; si la
  herramienta informa cobertura incompleta, avisalo.
- Marcas principales de equipos: Agras T y Mavic; accesorios: MIXER JR, RTK, PIX4D.
"""


@dataclass
class Respuesta:
    texto: str
    pasos: list[dict] = field(default_factory=list)  # herramienta, argumentos, resultado resumido
    error: bool = False  # no llego a responder: no descuenta del limite diario


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

def configuracion() -> dict:
    """Secrets del asistente. api_key vacia = asistente no configurado.

    Se relee en cada pregunta: cambiar el modelo en los secrets de Cloud tiene
    efecto sin redeploy.
    """
    try:
        secrets = st.secrets
        api_key = str(secrets.get("GROQ_API_KEY", "") or "").strip()
        modelo = str(secrets.get("GROQ_MODEL", "") or "").strip() or MODELO_DEFAULT
        respaldo = str(secrets.get("GROQ_MODEL_RESPALDO", "") or "").strip() or MODELO_RESPALDO_DEFAULT
        limite = int(secrets.get("CHAT_LIMITE_DIARIO", LIMITE_DIARIO_DEFAULT))
    except Exception:
        api_key, modelo, respaldo, limite = "", MODELO_DEFAULT, MODELO_RESPALDO_DEFAULT, LIMITE_DIARIO_DEFAULT
    if api_key.startswith("gsk_reemplazar"):  # el placeholder de secrets.toml.example
        api_key = ""
    return {"api_key": api_key, "modelo": modelo, "modelo_respaldo": respaldo, "limite_diario": limite}


def crear_cliente(api_key: str) -> openai.OpenAI:
    return openai.OpenAI(api_key=api_key, base_url=GROQ_BASE_URL, timeout=30, max_retries=1)


# ---------------------------------------------------------------------------
# Limite diario por usuario
# ---------------------------------------------------------------------------

@st.cache_resource
def _contador() -> dict:
    """Compartido entre sesiones: el limite es por usuario, no por pestaña.

    Vive en memoria del proceso: un reinicio de la app lo pone en cero.
    """
    return {"lock": threading.Lock(), "conteos": {}}


def hoy_argentina() -> date:
    return datetime.now(HORA_ARGENTINA).date()


def preguntas_hechas(email: str, hoy: date | None = None) -> int:
    c = _contador()
    with c["lock"]:
        return c["conteos"].get((email, (hoy or hoy_argentina()).isoformat()), 0)


def preguntas_restantes(email: str, limite: int, es_admin: bool, hoy: date | None = None) -> int | None:
    """Cuantas le quedan hoy; None = sin limite (admins)."""
    if es_admin:
        return None
    return max(0, limite - preguntas_hechas(email, hoy))


def registrar_pregunta(email: str, hoy: date | None = None) -> None:
    clave_hoy = (hoy or hoy_argentina()).isoformat()
    c = _contador()
    with c["lock"]:
        # los dias anteriores ya no sirven: se descartan para que no crezca
        for clave in [k for k in c["conteos"] if k[1] != clave_hoy]:
            del c["conteos"][clave]
        c["conteos"][(email, clave_hoy)] = c["conteos"].get((email, clave_hoy), 0) + 1


def mensaje_limite(limite: int) -> str:
    return f"Llegaste al límite de {limite} preguntas por hoy. Mañana se renueva."


# ---------------------------------------------------------------------------
# Mensajes
# ---------------------------------------------------------------------------

def describir_periodo(contexto: dict) -> str:
    desde, hasta = contexto.get("desde"), contexto.get("hasta")
    rango = f"{desde:%d/%m/%Y} – {hasta:%d/%m/%Y}" if desde and hasta else "todo el rango disponible"
    estados = contexto.get("estados_trabajo")
    return f"{rango}; estados de trabajo: {', '.join(estados) if estados else 'ninguno seleccionado'}"


def prompt_sistema(contexto: dict) -> str:
    return PROMPT_SISTEMA.replace("{periodo_actual}", describir_periodo(contexto))


def armar_mensajes(pregunta: str, historial: list, contexto: dict) -> list:
    """Sistema + ultimos MAX_HISTORIAL mensajes de texto + la pregunta.

    Del historial solo viaja el texto: ni los pasos ni resultados de
    herramientas de turnos anteriores.
    """
    previos = [
        {"role": m["role"], "content": m["content"]}
        for m in historial or []
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"]
    ]
    return ([{"role": "system", "content": prompt_sistema(contexto)}]
            + previos[-MAX_HISTORIAL:]
            + [{"role": "user", "content": pregunta}])


def _resumen_resultado(resultado: dict) -> str:
    if "error" in resultado:
        return f"error: {resultado['error']}"
    if resultado.get("sin_datos"):
        return "sin datos"
    if resultado.get("ambiguo"):
        return f"{resultado.get('total_coincidencias', 0)} clientes posibles"
    if "filas" in resultado:
        return f"{len(resultado['filas'])} fila(s)"
    return "ok"


def _argumentos(crudo) -> dict | str:
    try:
        valor = json.loads(crudo) if isinstance(crudo, str) and crudo.strip() else (crudo or {})
    except json.JSONDecodeError:
        return crudo
    return valor


# ---------------------------------------------------------------------------
# Llamada al modelo
# ---------------------------------------------------------------------------

def _amerita_respaldo(error: Exception) -> bool:
    """429, modelo inexistente (404) o 400 por el modelo (dado de baja, sin tools)."""
    if isinstance(error, (openai.RateLimitError, openai.NotFoundError)):
        return True
    if isinstance(error, openai.BadRequestError):
        codigo = str(getattr(error, "code", "") or "")
        return "model" in codigo or "model" in str(error).lower()
    return False


def _completar(cliente, mensajes: list, estado: dict):
    """Una llamada al modelo; si corresponde, un unico reintento con el de respaldo."""
    def llamar():
        return cliente.chat.completions.create(
            model=estado["modelo"], messages=mensajes, tools=HERRAMIENTAS,
            tool_choice="auto", temperature=0.1,
        )
    try:
        return llamar()
    except Exception as e:
        if estado["respaldo_usado"] or not estado["respaldo"] or not _amerita_respaldo(e):
            raise
        estado.update(modelo=estado["respaldo"], respaldo_usado=True)
        return llamar()


def _mensaje_de_error(error: Exception) -> str:
    if isinstance(error, openai.RateLimitError):
        return MSJ_LIMITE_GROQ
    if isinstance(error, openai.APIConnectionError):  # incluye APITimeoutError
        return MSJ_CONEXION
    if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return MSJ_CLAVE
    return MSJ_GENERICO


def _bucle(cliente, mensajes: list, contexto: dict, estado: dict, pasos: list) -> str:
    ultimo_texto = ""
    for _ in range(MAX_VUELTAS):
        mensaje = _completar(cliente, mensajes, estado).choices[0].message
        ultimo_texto = (mensaje.content or "").strip()
        llamadas = mensaje.tool_calls or []
        if not llamadas:
            return ultimo_texto or MSJ_VACIA

        mensajes.append({
            "role": "assistant",
            "content": mensaje.content or "",
            "tool_calls": [{"id": t.id, "type": "function",
                            "function": {"name": t.function.name, "arguments": t.function.arguments or "{}"}}
                           for t in llamadas],
        })
        for t in llamadas:
            resultado = ejecutar(t.function.name, t.function.arguments, contexto)
            pasos.append({"herramienta": t.function.name, "argumentos": _argumentos(t.function.arguments),
                          "resultado": _resumen_resultado(resultado)})
            mensajes.append({"role": "tool", "tool_call_id": t.id,
                             "content": json.dumps(resultado, ensure_ascii=False)})

    return f"{ultimo_texto}\n\n{AVISO_VUELTAS}" if ultimo_texto else AVISO_VUELTAS


def responder(pregunta: str, historial: list, contexto: dict, *, cliente=None,
              config: dict | None = None) -> Respuesta:
    """Responde `pregunta` usando las herramientas. Nunca lanza.

    `contexto`: el de herramientas_chat.ejecutar() (datos, datos_completos,
    estados_trabajo, desde, hasta). El usuario sale de la sesion de auth.
    """
    config = config or configuracion()
    usuario = usuario_actual() or {"email": "-"}
    email = usuario["email"]

    if not config["api_key"] and cliente is None:
        return Respuesta("El asistente no está configurado: falta GROQ_API_KEY en los secrets.", error=True)

    restantes = preguntas_restantes(email, config["limite_diario"], sesion_es_admin())
    if restantes == 0:
        return Respuesta(mensaje_limite(config["limite_diario"]), error=True)

    cliente = cliente or crear_cliente(config["api_key"])
    estado = {"modelo": config["modelo"], "respaldo": config["modelo_respaldo"], "respaldo_usado": False}
    pasos: list[dict] = []
    try:
        texto = _bucle(cliente, armar_mensajes(pregunta, historial, contexto), contexto, estado, pasos)
        respuesta = Respuesta(texto, pasos)
    except Exception as e:  # nunca un traceback en el chat
        respuesta = Respuesta(_mensaje_de_error(e), pasos, error=True)

    if not respuesta.error:
        registrar_pregunta(email)
    # Sin el texto de la pregunta ni de la respuesta: solo que herramientas se usaron
    herramientas = ",".join(p["herramienta"] for p in pasos) or "-"
    audit_log("chat_pregunta", email,
              f"herramientas={herramientas} modelo={estado['modelo']} ok={not respuesta.error}")
    return respuesta
