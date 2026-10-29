"""Corre paginas/5_Asistente.py de verdad (AppTest) con un agente falso: sin red."""
from datetime import date
from pathlib import Path

import pytest

from test_herramientas_chat import PRECIOS, assert_datos_iguales, copia_profunda, crm_crudo, ventas_crudo
from utils import agente
from utils.data import ESTADOS_TRABAJO_EJECUTADO, aplicar_filtros, construir_datos

PAGINA = Path(__file__).resolve().parent.parent / "paginas" / "5_Asistente.py"
EMAIL = "matias21tossen@gmail.com"
CONFIG = {"api_key": "gsk_test", "modelo": "m", "modelo_respaldo": "r", "limite_diario": 30}


@pytest.fixture(autouse=True)
def limpiar_contador():
    agente._contador.clear()
    yield
    agente._contador.clear()


@pytest.fixture
def datos():
    completos = construir_datos(crm_crudo(), ventas_crudo(), tuple(sorted(PRECIOS.items())))
    return completos, aplicar_filtros(completos, None, None, ESTADOS_TRABAJO_EJECUTADO)


@pytest.fixture
def llamadas(monkeypatch):
    """Reemplaza al agente: registra con que se lo llamo y contesta fijo."""
    registro = []

    def responder_falso(pregunta, historial, contexto, config=None):
        registro.append({"pregunta": pregunta, "historial": historial, "contexto": contexto})
        return agente.Respuesta(f"Respuesta a: {pregunta}",
                                [{"herramienta": "kpis_generales", "argumentos": {}, "resultado": "ok"}])

    monkeypatch.setattr(agente, "responder", responder_falso)
    monkeypatch.setattr(agente, "configuracion", lambda: dict(CONFIG))
    return registro


def pagina(datos, rol="usuario"):
    from streamlit.testing.v1 import AppTest

    completos, filtrados = datos
    at = AppTest.from_file(str(PAGINA), default_timeout=30)
    at.session_state["auth_ok"] = True
    at.session_state["auth_email"] = EMAIL
    at.session_state["auth_rol"] = rol
    at.session_state["datos_completos"] = completos
    at.session_state["datos"] = filtrados
    at.session_state["estados_trabajo"] = ESTADOS_TRABAJO_EJECUTADO
    at.session_state["periodo"] = (date(2024, 11, 15), date(2025, 10, 5))
    return at


def test_sin_key_avisa_y_no_muestra_el_chat(monkeypatch, datos):
    monkeypatch.setattr(agente, "configuracion", lambda: {**CONFIG, "api_key": ""})
    at = pagina(datos).run()
    assert not at.exception
    assert any("GROQ_API_KEY" in i.value for i in at.info)
    assert not at.chat_input


def test_sugerencias_con_historial_vacio(llamadas, datos):
    at = pagina(datos).run()
    assert not at.exception
    assert at.title[0].value == "💬 Asistente IA"
    etiquetas = [b.label for b in at.button]
    assert "¿Cuánto ingresó Agropix en el período?" in etiquetas
    assert len([k for k in etiquetas if k.startswith("¿")]) == 4
    assert any("Te quedan 30 preguntas hoy" in c.value for c in at.caption)


def test_una_sugerencia_pregunta_y_muestra_como_lo_calculo(llamadas, datos):
    at = pagina(datos).run()
    at.button(key="chat_sugerencia_0").click().run()
    assert not at.exception
    assert llamadas[0]["pregunta"] == "¿Cuánto ingresó Agropix en el período?"
    assert [m.name for m in at.chat_message] == ["user", "assistant"]
    assert at.expander[0].label == "🔎 Cómo lo calculé"
    # las sugerencias desaparecen una vez que hay conversacion
    assert not any(b.label.startswith("¿") for b in at.button)


def test_el_chat_le_pasa_los_filtros_actuales(llamadas, datos):
    at = pagina(datos).run()
    at.chat_input[0].set_value("¿Cuántas hectáreas?").run()
    contexto = llamadas[0]["contexto"]
    assert contexto["desde"] == date(2024, 11, 15) and contexto["hasta"] == date(2025, 10, 5)
    assert contexto["estados_trabajo"] == ESTADOS_TRABAJO_EJECUTADO
    assert contexto["datos"] is at.session_state["datos"]


def test_el_chat_no_modifica_los_datos_del_dashboard(monkeypatch, datos):
    """Con el agente real (y un cliente falso que pide todas las herramientas)."""
    from test_agente import ClienteFalso, herramienta, respuesta
    from utils.herramientas_chat import FUNCIONES

    llamadas = [herramienta(n, {"nombre": "agro"} if n == "buscar_cliente" else {}, id_=n) for n in FUNCIONES]
    llamadas_con_fecha = [herramienta(n, {"desde": "2025-01-01", "hasta": "2025-06-30"}, id_=f"{n}_f")
                          for n in FUNCIONES if n not in ("buscar_cliente", "calidad_de_datos")]
    cliente = ClienteFalso(respuesta(llamadas=llamadas + llamadas_con_fecha), respuesta("ok"))
    responder_real = agente.responder
    monkeypatch.setattr(agente, "configuracion", lambda: dict(CONFIG))
    monkeypatch.setattr(agente, "audit_log", lambda *a: None)
    monkeypatch.setattr(agente, "responder",
                        lambda p, h, c, config=None: responder_real(p, h, c, cliente=cliente, config=config))

    completos, filtrados = datos
    antes_completos, antes_filtrados = copia_profunda(completos), copia_profunda(filtrados)
    at = pagina(datos).run()
    at.chat_input[0].set_value("Dame todo").run()

    assert not at.exception
    assert len(cliente.pedidos) == 2
    assert_datos_iguales(antes_completos, at.session_state["datos_completos"])
    assert_datos_iguales(antes_filtrados, at.session_state["datos"])


def test_nueva_conversacion_limpia_el_historial(llamadas, datos):
    at = pagina(datos).run()
    at.chat_input[0].set_value("Hola").run()
    assert len(at.session_state["chat_mensajes"]) == 2
    at.button(key="chat_nueva").click().run()
    assert at.session_state["chat_mensajes"] == []
    assert not at.chat_message


def test_el_historial_no_reenvia_respuestas_con_error(monkeypatch, llamadas, datos):
    at = pagina(datos).run()
    at.session_state["chat_mensajes"] = [
        {"role": "user", "content": "uno"},
        {"role": "assistant", "content": agente.MSJ_CONEXION, "pasos": [], "error": True},
    ]
    at.chat_input[0].set_value("dos").run()
    assert llamadas[0]["historial"] == [{"role": "user", "content": "uno"}]


def test_limite_alcanzado_desactiva_el_input(monkeypatch, llamadas, datos):
    monkeypatch.setattr(agente, "preguntas_restantes", lambda *_a: 0)
    at = pagina(datos).run()
    assert at.chat_input[0].disabled
    assert any("límite" in w.value for w in at.warning)


def test_admin_sin_limite(llamadas, datos):
    at = pagina(datos, rol="admin").run()
    assert any("Sin límite" in c.value for c in at.caption)
