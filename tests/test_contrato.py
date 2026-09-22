"""Tests del chequeo de arranque y del estado vacio de las paginas."""
import pytest

from utils import contrato, ui


class StFalso:
    """Imita lo que contrato.verificar() usa de streamlit."""

    def __init__(self):
        self.errores, self.detenido = [], False

    def error(self, mensaje, icon=None):
        self.errores.append(mensaje)

    def stop(self):
        self.detenido = True
        raise RuntimeError("st.stop()")


# ---------------------------------------------------------------------------
# Contrato entre paginas y modulos
# ---------------------------------------------------------------------------
def test_el_codigo_actual_cumple_el_contrato():
    """Si esto falla, una pagina va a pedir una clave que su modulo ya no devuelve."""
    assert contrato.faltantes() == {}


def test_el_contrato_cubre_las_funciones_que_usan_las_paginas():
    assert set(contrato.CONTRATO) == {
        "utils.comisiones:kpis_comisiones",
        "utils.comisiones:ticket_promedio_equipos",
        "utils.comisiones:ticket_promedio_servicios",
        "utils.data:kpis_servicios",
        "utils.data:kpis_equipos",
    }


def test_el_contrato_incluye_las_claves_que_rompieron_en_produccion():
    """comision_generada, ingresos y trabajos: las tres tiraron la app abajo."""
    assert "ingresos" in contrato.CONTRATO["utils.comisiones:kpis_comisiones"]
    assert "comision_generada" in contrato.CONTRATO["utils.comisiones:kpis_comisiones"]
    assert "trabajos" in contrato.CONTRATO["utils.data:kpis_servicios"]


def test_detecta_una_clave_que_el_modulo_dejo_de_devolver(monkeypatch):
    from utils import comisiones

    original = comisiones.kpis_comisiones
    monkeypatch.setattr(comisiones, "kpis_comisiones",
                        lambda sv, eq: {k: v for k, v in original(sv, eq).items()
                                        if k != "ingresos"})
    problemas = contrato.faltantes()
    assert problemas == {"utils.comisiones:kpis_comisiones": ["ingresos"]}


def test_una_funcion_que_explota_tambien_se_reporta(monkeypatch):
    from utils import data

    def rota(*a, **k):
        raise AttributeError("modulo viejo")

    monkeypatch.setattr(data, "kpis_servicios", rota)
    problemas = contrato.faltantes()
    assert "utils.data:kpis_servicios" in problemas
    assert "AttributeError" in problemas["utils.data:kpis_servicios"][0]


def test_verificar_corta_la_app_con_un_mensaje_accionable(monkeypatch):
    monkeypatch.setattr(contrato, "faltantes",
                        lambda: {"utils.data:kpis_servicios": ["trabajos"]})
    st = StFalso()
    with pytest.raises(RuntimeError):
        contrato.verificar(st)
    assert st.detenido
    mensaje = st.errores[0]
    assert "Reboot app" in mensaje, "tiene que decir que hacer, no solo que fallo"
    assert "módulos viejos" in mensaje
    assert "trabajos" in mensaje, "y que clave falta, para poder diagnosticar"


def test_verificar_no_molesta_cuando_esta_todo_bien(monkeypatch):
    monkeypatch.setattr(contrato, "faltantes", lambda: {})
    st = StFalso()
    contrato.verificar(st)
    assert not st.errores and not st.detenido


def test_el_chequeo_no_toca_google_sheets(monkeypatch):
    """Corre en cada carga de la app: no puede depender de la red."""
    from utils import data

    monkeypatch.setattr(data, "cargar_crudos",
                        lambda: pytest.fail("el contrato no debe leer Sheets"))
    assert contrato.faltantes() == {}


# ---------------------------------------------------------------------------
# Aviso unico de periodo vacio
# ---------------------------------------------------------------------------
@pytest.fixture
def info(monkeypatch):
    mensajes = []
    monkeypatch.setattr(ui.st, "info", lambda m, icon=None: mensajes.append(m))
    return mensajes


def df(filas: int):
    import pandas as pd

    return pd.DataFrame({"x": range(filas)})


def test_sin_datos_avisa_una_sola_vez(info):
    assert ui.aviso_sin_datos(df(0), df(0)) is True
    assert len(info) == 1, "antes cada grafico avisaba por su cuenta"
    assert "ampliar el rango" in info[0]
    assert "Estado del trabajo" in info[0], "tiene que decir dónde tocar"


def test_con_datos_en_uno_solo_no_avisa(info):
    assert ui.aviso_sin_datos(df(0), df(3)) is False
    assert info == []


def test_el_texto_se_adapta_a_la_pagina(info):
    ui.aviso_sin_datos(df(0), que="ventas de equipos")
    assert "No hay ventas de equipos" in info[0]


def test_periodo_vacio_tolera_none():
    assert ui.periodo_vacio(None, df(0)) is True
    assert ui.periodo_vacio(None, df(1)) is False
