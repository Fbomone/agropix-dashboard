"""Tests del historial de envios y del envio por destinatario."""
import json

import pytest

from utils import email_sender, envio_log


def resultado(exitosos: int, fallidos: int = 0) -> dict:
    detalle = [{"email": f"ok{i}@agropix.com", "exitoso": True, "momento": "2026-09-20T09:30:00"}
               for i in range(exitosos)]
    detalle += [{"email": f"mal{i}@agropix.com", "exitoso": False, "error": "403",
                 "momento": "2026-09-20T09:30:00"} for i in range(fallidos)]
    return {"exitosos": exitosos, "fallidos": fallidos, "total": exitosos + fallidos,
            "detalle": detalle}


@pytest.fixture
def log(tmp_path):
    return tmp_path / "envios.jsonl"


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("exitosos,fallidos,esperado", [
    (7, 0, "OK"),
    (3, 4, "PARCIAL"),
    (0, 7, "ERROR"),
    (0, 0, "ERROR"),   # no se envio nada: no es un exito
])
def test_estado_segun_cuantos_llegaron(exitosos, fallidos, esperado):
    assert envio_log.estado(resultado(exitosos, fallidos)) == esperado


# ---------------------------------------------------------------------------
# Registro y lectura
# ---------------------------------------------------------------------------
def test_registrar_guarda_una_linea_json_por_envio(log):
    envio_log.registrar(resultado(7), tipo=envio_log.PRUEBA, periodo="Lunes 07/09 - Domingo 13/09",
                        usuario="infoagropix@gmail.com", archivo=log)
    envio_log.registrar(resultado(2, 1), tipo=envio_log.MANUAL, archivo=log)

    lineas = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 2
    primera = json.loads(lineas[0])
    assert primera["tipo"] == envio_log.PRUEBA
    assert primera["estado"] == "OK"
    assert primera["usuario"] == "infoagropix@gmail.com"
    assert primera["periodo"] == "Lunes 07/09 - Domingo 13/09"
    assert len(primera["detalle"]) == 7


def test_el_momento_se_guarda_en_hora_argentina(log):
    entrada = envio_log.registrar(resultado(1), archivo=log)
    assert entrada["momento"].endswith("-03:00")


def test_historial_devuelve_del_mas_nuevo_al_mas_viejo(log):
    for i in range(3):
        envio_log.registrar(resultado(i + 1), periodo=f"semana {i}", archivo=log)
    entradas = envio_log.historial(archivo=log)
    assert [e["periodo"] for e in entradas] == ["semana 2", "semana 1", "semana 0"]


def test_historial_respeta_el_limite(log):
    for i in range(10):
        envio_log.registrar(resultado(1), periodo=str(i), archivo=log)
    assert len(envio_log.historial(limite=4, archivo=log)) == 4


def test_historial_sin_archivo_es_vacio(tmp_path):
    assert envio_log.historial(archivo=tmp_path / "no_existe.jsonl") == []


def test_una_linea_corrupta_no_rompe_la_lectura(log):
    envio_log.registrar(resultado(1), periodo="buena", archivo=log)
    with log.open("a", encoding="utf-8") as f:
        f.write("{esto no es json}\n")
    envio_log.registrar(resultado(1), periodo="otra buena", archivo=log)

    entradas = envio_log.historial(archivo=log)
    assert [e["periodo"] for e in entradas] == ["otra buena", "buena"]


def test_registrar_no_explota_si_no_puede_escribir(tmp_path):
    """En un disco de solo lectura el envio ya ocurrio: no se pierde por el log."""
    inexistente = tmp_path / "sin_permiso" / "x" / "envios.jsonl"
    inexistente.parent.parent.mkdir()
    inexistente.parent.write_text("soy un archivo, no un directorio", encoding="utf-8")
    entrada = envio_log.registrar(resultado(1), archivo=inexistente)
    assert entrada["estado"] == "OK"


def test_resumen_cuenta_por_estado(log):
    envio_log.registrar(resultado(7), archivo=log)
    envio_log.registrar(resultado(3, 4), archivo=log)
    envio_log.registrar(resultado(0, 7), archivo=log)
    r = envio_log.resumen(envio_log.historial(archivo=log))
    assert (r["envios"], r["ok"], r["parciales"], r["errores"]) == (3, 1, 1, 1)
    assert r["ultimo"]


def test_resumen_vacio():
    r = envio_log.resumen([])
    assert r["envios"] == 0 and r["ultimo"] is None


# ---------------------------------------------------------------------------
# Envio por destinatario
# ---------------------------------------------------------------------------
def test_enviar_individual_manda_uno_por_uno_y_reporta_cada_resultado(monkeypatch):
    """Un solo envio con varios 'to' falla para todos: no se sabria a quien llego."""
    enviados = []

    def falso(pdf, nombre, periodo="", destinatarios=None, asunto="", html=None):
        if destinatarios[0] == "mal@agropix.com":
            raise email_sender.ErrorEnvioEmail("SendGrid respondió 403.")
        enviados.append(destinatarios[0])
        return destinatarios

    monkeypatch.setattr(email_sender, "enviar_reporte", falso)
    r = email_sender.enviar_individual(b"%PDF-1.4", "r.pdf",
                                       ["uno@agropix.com", "mal@agropix.com", "dos@agropix.com"])

    assert enviados == ["uno@agropix.com", "dos@agropix.com"]
    assert (r["exitosos"], r["fallidos"], r["total"]) == (2, 1, 3)
    fallido = [d for d in r["detalle"] if not d["exitoso"]][0]
    assert fallido["email"] == "mal@agropix.com"
    assert "403" in fallido["error"]
    assert envio_log.estado(r) == "PARCIAL"


def test_enviar_individual_sin_destinatarios(monkeypatch):
    monkeypatch.setattr(email_sender, "enviar_reporte",
                        lambda *a, **k: pytest.fail("no debería enviar nada"))
    r = email_sender.enviar_individual(b"%PDF-1.4", "r.pdf", [])
    assert (r["exitosos"], r["fallidos"], r["total"]) == (0, 0, 0)


def test_validar_conexion_sin_configuracion_no_llama_a_la_api(monkeypatch):
    monkeypatch.setattr(email_sender, "SENDGRID_API_KEY", "")
    r = email_sender.validar_conexion()
    assert r["exitoso"] is False
    assert "SENDGRID_API_KEY" in r["mensaje"]


def test_validar_conexion_avisa_si_el_remitente_no_esta_verificado(monkeypatch):
    monkeypatch.setattr(email_sender, "SENDGRID_API_KEY", "SG.clave-de-prueba-1234")
    monkeypatch.setattr(email_sender, "EMAIL_REMITENTE", "sin-verificar@agropix.com")
    monkeypatch.setattr(email_sender, "EMAIL_DESTINATARIOS", ["alguien@agropix.com"])
    sendgrid = pytest.importorskip("sendgrid")

    class Respuesta:
        body = json.dumps({"results": [{"from_email": "otro@agropix.com"}]}).encode()

    class Cliente:
        def __init__(self, _key):
            self.client = type("C", (), {"verified_senders": type(
                "V", (), {"get": staticmethod(lambda: Respuesta())})()})()

    monkeypatch.setattr(sendgrid, "SendGridAPIClient", Cliente)
    r = email_sender.validar_conexion()
    assert r["exitoso"] is False
    assert "no está entre los remitentes verificados" in r["mensaje"]
    assert r["detalles"]["remitentes_verificados"] == "otro@agropix.com"


def test_validar_conexion_ok_cuando_el_remitente_esta_verificado(monkeypatch):
    monkeypatch.setattr(email_sender, "SENDGRID_API_KEY", "SG.clave-de-prueba-1234")
    monkeypatch.setattr(email_sender, "EMAIL_REMITENTE", "reportes@agropix.com")
    monkeypatch.setattr(email_sender, "EMAIL_DESTINATARIOS", ["alguien@agropix.com"])
    sendgrid = pytest.importorskip("sendgrid")

    class Respuesta:
        body = json.dumps({"results": [{"from_email": "reportes@agropix.com"}]}).encode()

    class Cliente:
        def __init__(self, _key):
            self.client = type("C", (), {"verified_senders": type(
                "V", (), {"get": staticmethod(lambda: Respuesta())})()})()

    monkeypatch.setattr(sendgrid, "SendGridAPIClient", Cliente)
    r = email_sender.validar_conexion()
    assert r["exitoso"] is True
    assert r["detalles"]["remitente"] == "reportes@agropix.com"
    assert "SG.cla" in r["detalles"]["api_key"], "la key va enmascarada, no completa"
    assert "clave-de-prueba" not in r["detalles"]["api_key"]
