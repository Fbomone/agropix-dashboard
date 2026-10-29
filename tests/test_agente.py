"""Bucle del Asistente IA con un cliente falso: sin red ni Groq."""
import json
from datetime import date
from types import SimpleNamespace

import openai
import pytest
import streamlit as st

from test_herramientas_chat import PRECIOS, crm_crudo, ventas_crudo
from utils import agente
from utils.data import ESTADOS_TRABAJO_EJECUTADO, aplicar_filtros, construir_datos
from utils.herramientas_chat import HERRAMIENTAS

try:  # openai >= 3 trae su propio httpx2
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

PEDIDO = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
EMAIL = "matias21tossen@gmail.com"
CONFIG = {"api_key": "gsk_test", "modelo": "principal", "modelo_respaldo": "respaldo", "limite_diario": 30}


# ---------------------------------------------------------------------------
# Cliente falso
# ---------------------------------------------------------------------------

def herramienta(nombre, argumentos=None, id_="call_1"):
    return SimpleNamespace(id=id_, type="function",
                           function=SimpleNamespace(name=nombre, arguments=json.dumps(argumentos or {})))


def respuesta(texto=None, llamadas=None):
    mensaje = SimpleNamespace(content=texto, tool_calls=llamadas)
    return SimpleNamespace(choices=[SimpleNamespace(message=mensaje)])


def error_429():
    return openai.RateLimitError("Rate limit reached", response=httpx.Response(429, request=PEDIDO), body=None)


def error_modelo_404():
    return openai.NotFoundError("The model `principal` does not exist",
                                response=httpx.Response(404, request=PEDIDO), body=None)


class ClienteFalso:
    """Devuelve (o lanza) los elementos de `guion` en orden y guarda cada pedido."""

    def __init__(self, *guion, repetir_ultimo=False):
        self.guion = list(guion)
        self.repetir_ultimo = repetir_ultimo
        self.pedidos = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # copia: el agente sigue agregando mensajes a la misma lista
        self.pedidos.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        paso = self.guion[0] if self.repetir_ultimo and len(self.guion) == 1 else self.guion.pop(0)
        if isinstance(paso, Exception):
            raise paso
        return paso


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def sesion_de_usuario(monkeypatch):
    agente._contador.clear()
    monkeypatch.setattr(agente, "usuario_actual", lambda: {"email": EMAIL, "rol": "usuario"})
    monkeypatch.setattr(agente, "sesion_es_admin", lambda: False)
    yield
    agente._contador.clear()


@pytest.fixture(autouse=True)
def auditoria(monkeypatch):
    """Ademas de inspeccionarla, evita que los tests escriban en data/auditoria.log."""
    eventos = []
    monkeypatch.setattr(agente, "audit_log", lambda *a: eventos.append(a))
    return eventos


@pytest.fixture
def contexto():
    completos = construir_datos(crm_crudo(), ventas_crudo(), tuple(sorted(PRECIOS.items())))
    return {"datos": aplicar_filtros(completos, None, None, ESTADOS_TRABAJO_EJECUTADO),
            "datos_completos": completos, "estados_trabajo": ESTADOS_TRABAJO_EJECUTADO,
            "desde": date(2024, 11, 15), "hasta": date(2025, 10, 5)}


def preguntar(cliente, contexto, pregunta="¿Cuánto ingresó Agropix?", historial=(), config=CONFIG):
    return agente.responder(pregunta, list(historial), contexto, cliente=cliente, config=config)


def mensajes_tool(pedido):
    return [json.loads(m["content"]) for m in pedido["messages"] if m["role"] == "tool"]


# ---------------------------------------------------------------------------
# Bucle
# ---------------------------------------------------------------------------

def test_llama_la_herramienta_y_arma_la_respuesta(contexto):
    cliente = ClienteFalso(respuesta(llamadas=[herramienta("kpis_generales")]),
                           respuesta("Ingresaron US$ 6.500 en el período."))
    r = preguntar(cliente, contexto)

    assert r.texto == "Ingresaron US$ 6.500 en el período."
    assert r.error is False
    assert r.pasos == [{"herramienta": "kpis_generales", "argumentos": {}, "resultado": "ok"}]

    primero, segundo = cliente.pedidos
    assert primero["tools"] is HERRAMIENTAS
    assert primero["tool_choice"] == "auto" and primero["temperature"] == 0.1
    assert primero["model"] == "principal"
    # el numero que vuelve al modelo es el de la herramienta, igual al de la tarjeta
    assert mensajes_tool(segundo)[0]["ingresos"] == 6500
    assistant = [m for m in segundo["messages"] if m["role"] == "assistant"][-1]
    assert assistant["tool_calls"][0]["function"]["name"] == "kpis_generales"


def test_pasa_las_fechas_que_pide_el_modelo(contexto):
    args = {"n": 1, "desde": "2024-01-01", "hasta": "2024-12-31"}
    cliente = ClienteFalso(respuesta(llamadas=[herramienta("top_clientes", args)]),
                           respuesta("Agro Sur."))
    r = preguntar(cliente, contexto, "¿Quién es el mejor cliente en 2024?")
    assert r.pasos[0]["argumentos"] == args
    resultado = mensajes_tool(cliente.pedidos[1])[0]
    assert resultado["periodo"]["desde"] == "2024-01-01"
    assert resultado["filas"][0]["cliente"] == "Agro Sur"


def test_varias_herramientas_en_una_vuelta(contexto):
    cliente = ClienteFalso(
        respuesta(llamadas=[herramienta("kpis_generales", id_="a"), herramienta("top_clientes", {"n": 100}, id_="b")]),
        respuesta("Listo."))
    r = preguntar(cliente, contexto)
    assert [p["herramienta"] for p in r.pasos] == ["kpis_generales", "top_clientes"]
    assert r.pasos[1]["resultado"].startswith("error:")
    tool_ids = [m["tool_call_id"] for m in cliente.pedidos[1]["messages"] if m["role"] == "tool"]
    assert tool_ids == ["a", "b"]


def test_corta_a_las_cinco_vueltas(contexto):
    cliente = ClienteFalso(respuesta("Sigo buscando…", [herramienta("kpis_generales")]), repetir_ultimo=True)
    r = preguntar(cliente, contexto)
    assert len(cliente.pedidos) == agente.MAX_VUELTAS == 5
    assert len(r.pasos) == 5
    assert r.texto.startswith("Sigo buscando…")
    assert agente.AVISO_VUELTAS in r.texto


def test_respuesta_vacia_no_queda_en_blanco(contexto):
    r = preguntar(ClienteFalso(respuesta("")), contexto)
    assert r.texto == agente.MSJ_VACIA


# ---------------------------------------------------------------------------
# Errores y modelo de respaldo
# ---------------------------------------------------------------------------

def test_429_usa_el_modelo_de_respaldo_una_vez(contexto):
    cliente = ClienteFalso(error_429(), respuesta("Respuesta del respaldo."))
    r = preguntar(cliente, contexto)
    assert r.texto == "Respuesta del respaldo." and r.error is False
    assert [p["model"] for p in cliente.pedidos] == ["principal", "respaldo"]


def test_429_tambien_en_el_respaldo_da_mensaje_amable(contexto):
    cliente = ClienteFalso(error_429(), error_429(), respuesta("no deberia llegar"))
    r = preguntar(cliente, contexto)
    assert r.texto == agente.MSJ_LIMITE_GROQ
    assert r.error is True
    assert len(cliente.pedidos) == 2


def test_el_respaldo_se_usa_una_sola_vez_por_pregunta(contexto):
    cliente = ClienteFalso(error_429(), respuesta(llamadas=[herramienta("kpis_generales")]), error_429())
    r = preguntar(cliente, contexto)
    assert r.texto == agente.MSJ_LIMITE_GROQ
    assert [p["model"] for p in cliente.pedidos] == ["principal", "respaldo", "respaldo"]
    assert len(r.pasos) == 1  # lo que llego a hacer queda para la trazabilidad


def test_modelo_inexistente_usa_el_respaldo(contexto):
    cliente = ClienteFalso(error_modelo_404(), respuesta("ok"))
    assert preguntar(cliente, contexto).texto == "ok"
    assert cliente.pedidos[1]["model"] == "respaldo"


def test_400_de_modelo_usa_el_respaldo_y_otro_400_no(contexto):
    de_modelo = openai.BadRequestError("The model `principal` has been decommissioned",
                                       response=httpx.Response(400, request=PEDIDO), body=None)
    cliente = ClienteFalso(de_modelo, respuesta("ok"))
    assert preguntar(cliente, contexto).texto == "ok"

    otro = openai.BadRequestError("messages: invalid", response=httpx.Response(400, request=PEDIDO), body=None)
    cliente = ClienteFalso(otro, respuesta("no deberia llegar"))
    assert preguntar(cliente, contexto).texto == agente.MSJ_GENERICO
    assert len(cliente.pedidos) == 1


def test_timeout_da_mensaje_de_conexion_sin_respaldo(contexto):
    cliente = ClienteFalso(openai.APITimeoutError(request=PEDIDO))
    r = preguntar(cliente, contexto)
    assert r.texto == agente.MSJ_CONEXION
    assert len(cliente.pedidos) == 1


def test_error_de_conexion(contexto):
    r = preguntar(ClienteFalso(openai.APIConnectionError(request=PEDIDO)), contexto)
    assert r.texto == agente.MSJ_CONEXION


def test_cualquier_otro_error_no_muestra_traceback(contexto):
    r = preguntar(ClienteFalso(RuntimeError("boom en /ruta/secreta.py")), contexto)
    assert r.texto == agente.MSJ_GENERICO
    assert "boom" not in r.texto


def test_sin_clave_no_llama_a_la_api(contexto, monkeypatch):
    monkeypatch.setattr(agente, "crear_cliente", lambda _k: pytest.fail("no deberia crear el cliente"))
    r = agente.responder("hola", [], contexto, config={**CONFIG, "api_key": ""})
    assert r.error is True and "GROQ_API_KEY" in r.texto


# ---------------------------------------------------------------------------
# Limite diario
# ---------------------------------------------------------------------------

def test_limite_diario_por_usuario(contexto):
    config = {**CONFIG, "limite_diario": 2}
    for _ in range(2):
        assert preguntar(ClienteFalso(respuesta("ok")), contexto, config=config).texto == "ok"
    assert agente.preguntas_restantes(EMAIL, 2, False) == 0

    cliente = ClienteFalso(respuesta("no deberia llegar"))
    r = preguntar(cliente, contexto, config=config)
    assert r.texto == agente.mensaje_limite(2) and r.error is True
    assert cliente.pedidos == []


def test_el_limite_es_por_usuario(contexto, monkeypatch):
    config = {**CONFIG, "limite_diario": 1}
    preguntar(ClienteFalso(respuesta("ok")), contexto, config=config)
    monkeypatch.setattr(agente, "usuario_actual", lambda: {"email": "otro@gmail.com", "rol": "usuario"})
    assert preguntar(ClienteFalso(respuesta("ok")), contexto, config=config).texto == "ok"


def test_admin_sin_limite(contexto, monkeypatch):
    monkeypatch.setattr(agente, "sesion_es_admin", lambda: True)
    config = {**CONFIG, "limite_diario": 1}
    for _ in range(3):
        assert preguntar(ClienteFalso(respuesta("ok")), contexto, config=config).texto == "ok"
    assert agente.preguntas_restantes(EMAIL, 1, True) is None


def test_los_errores_no_descuentan_preguntas(contexto):
    preguntar(ClienteFalso(openai.APITimeoutError(request=PEDIDO)), contexto)
    assert agente.preguntas_hechas(EMAIL) == 0


def test_el_contador_cambia_de_dia():
    agente.registrar_pregunta(EMAIL, date(2026, 10, 28))
    assert agente.preguntas_hechas(EMAIL, date(2026, 10, 28)) == 1
    agente.registrar_pregunta(EMAIL, date(2026, 10, 29))
    assert agente.preguntas_hechas(EMAIL, date(2026, 10, 29)) == 1
    assert agente.preguntas_hechas(EMAIL, date(2026, 10, 28)) == 0  # el dia viejo se descarta


# ---------------------------------------------------------------------------
# Mensajes que viajan
# ---------------------------------------------------------------------------

def test_historial_solo_los_ultimos_seis_y_sin_pasos(contexto):
    historial = []
    for i in range(5):
        historial += [{"role": "user", "content": f"pregunta {i}"},
                      {"role": "assistant", "content": f"respuesta {i}", "pasos": [{"herramienta": "x"}]}]
    cliente = ClienteFalso(respuesta("ok"))
    preguntar(cliente, contexto, "pregunta nueva", historial)

    enviados = cliente.pedidos[0]["messages"]
    assert enviados[0]["role"] == "system"
    assert [m["content"] for m in enviados[1:]] == [
        "pregunta 2", "respuesta 2", "pregunta 3", "respuesta 3", "pregunta 4", "respuesta 4", "pregunta nueva"]
    assert all(set(m) == {"role", "content"} for m in enviados)


def test_prompt_de_sistema_con_el_periodo_actual(contexto):
    cliente = ClienteFalso(respuesta("ok"))
    preguntar(cliente, contexto)
    sistema = cliente.pedidos[0]["messages"][0]["content"]
    assert "{periodo_actual}" not in sistema
    assert "15/11/2024 – 05/10/2025" in sistema
    assert "Cobro recibido, Facturado esperando cobro, Trabajo realizado" in sistema
    assert sistema.startswith("Sos el asistente de datos de Agropix")


def test_nunca_viajan_filas_crudas(contexto):
    """Criterio 4: a Groq solo llegan agregados, aunque se usen todas las herramientas."""
    from utils.herramientas_chat import FUNCIONES
    args = {"buscar_cliente": {"nombre": "agro"}}
    llamadas = [herramienta(n, args.get(n), id_=n) for n in FUNCIONES]
    cliente = ClienteFalso(respuesta(llamadas=llamadas), respuesta("ok"))
    preguntar(cliente, contexto)

    resultados = mensajes_tool(cliente.pedidos[-1])
    assert len(resultados) == len(FUNCIONES)
    assert not any("error" in r for r in resultados)
    # lo que vuelve de las herramientas (el prompt de sistema si nombra columnas)
    enviado = json.dumps(resultados, ensure_ascii=False)
    for crudo in ("OT-1", "DJI", "Entregado", "Valor total de ventas", "Factura s/IVA", "fila_sheet",
                  "id_cliente", "Nombre del cliente"):
        assert crudo not in enviado


def test_auditoria_sin_texto_de_pregunta_ni_respuesta(contexto, auditoria):
    cliente = ClienteFalso(respuesta(llamadas=[herramienta("kpis_generales")]), respuesta("Respuesta secreta"))
    preguntar(cliente, contexto, "¿Pregunta confidencial?")
    assert len(auditoria) == 1
    evento, email, detalle = auditoria[0]
    assert evento == "chat_pregunta" and email == EMAIL
    assert "herramientas=kpis_generales" in detalle
    assert "confidencial" not in detalle and "secreta" not in detalle


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

def test_configuracion_desde_secrets(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"GROQ_API_KEY": " gsk_real ", "GROQ_MODEL": "otro-modelo",
                                        "CHAT_LIMITE_DIARIO": 10})
    c = agente.configuracion()
    assert c == {"api_key": "gsk_real", "modelo": "otro-modelo",
                 "modelo_respaldo": agente.MODELO_RESPALDO_DEFAULT, "limite_diario": 10}


def test_el_placeholder_cuenta_como_sin_clave(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"GROQ_API_KEY": "gsk_reemplazar"})
    assert agente.configuracion()["api_key"] == ""


def test_sin_secrets_no_rompe(monkeypatch):
    class SinArchivo:
        def get(self, *_a):
            raise FileNotFoundError("no secrets.toml")
    monkeypatch.setattr(st, "secrets", SinArchivo())
    c = agente.configuracion()
    assert c["api_key"] == "" and c["modelo"] == agente.MODELO_DEFAULT
