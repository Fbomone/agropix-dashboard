"""Corre app.py de verdad (AppTest) para verificar la porteria.

Lo que se prueba: sin sesion valida la app muestra el login y NO llega a leer
Google Sheets. cargar_crudos se mockea con un fallo ruidoso: si la porteria se
saltea, el test rompe.
"""
import os
from pathlib import Path

import pytest

from utils import auth

APP = Path(__file__).resolve().parent.parent / "app.py"
TIMEOUT = 60  # el import de app.py arrastra plotly y reportlab


@pytest.fixture
def app(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def no_deberia_llamarse(*_args, **_kwargs):
        raise AssertionError("se leyo Google Sheets sin sesion autenticada")

    monkeypatch.setattr("utils.data.cargar_crudos", no_deberia_llamarse)
    return AppTest.from_file(str(APP), default_timeout=TIMEOUT)


def test_sin_login_muestra_el_formulario_y_no_lee_sheets(app):
    app.run()
    assert not app.exception
    etiquetas = [e.label for e in app.text_input]
    assert "Email" in etiquetas and "Contraseña" in etiquetas
    assert app.button  # boton Ingresar
    # La navegacion multipagina y los filtros no se declararon todavia
    assert not app.multiselect


def test_password_incorrecta_muestra_error(app):
    app.run()
    app.text_input[0].set_value("dueno@agropix.com")
    app.text_input[1].set_value("password-que-no-es")
    app.button[0].click().run()
    assert not app.exception
    assert app.error, "deberia mostrar st.error con credenciales invalidas"


def test_usuario_inexistente_no_crea_sesion(app):
    app.run()
    app.text_input[0].set_value("intruso@example.com")
    app.text_input[1].set_value("lo-que-sea")
    app.button[0].click().run()
    # session_state de AppTest expone las claves por __getitem__, no tiene .get()
    assert "auth_ok" not in app.session_state
    assert app.session_state["auth_intentos"] == 1


def test_el_aviso_confidencial_esta_en_la_pantalla(app):
    app.run()
    html = " ".join(b.body for b in app.get("html"))
    assert "CONFIDENCIAL" in html
    assert auth.CONTACTO_SOPORTE in html


@pytest.mark.skipif(
    not os.getenv("AGROPIX_TEST_PASS_DUENO"),
    reason="falta AGROPIX_TEST_PASS_DUENO",
)
def test_login_valido_abre_la_sesion(monkeypatch):
    """Con credenciales correctas la app pasa la porteria y recien ahi lee Sheets."""
    from streamlit.testing.v1 import AppTest

    llamadas = []

    def falla_controlada(*_args, **_kwargs):
        llamadas.append(1)
        raise RuntimeError("sheets no disponible en el test")

    monkeypatch.setattr("utils.data.cargar_crudos", falla_controlada)
    app = AppTest.from_file(str(APP), default_timeout=TIMEOUT).run()
    app.text_input[0].set_value("dueno@agropix.com")
    app.text_input[1].set_value(os.environ["AGROPIX_TEST_PASS_DUENO"])
    app.button[0].click().run()

    assert app.session_state["auth_ok"] is True
    assert app.session_state["auth_rol"] == "admin"
    assert llamadas, "despues del login la app deberia intentar leer Sheets"
    # app.py atrapa el fallo de Sheets y muestra su propio mensaje
    assert any("No se pudo leer Google Sheets" in e.value for e in app.error)
    # El encabezado se dibuja antes de leer Sheets, asi que esta igual
    html = " ".join(b.body for b in app.get("html"))
    assert "Bienvenido" in html and "Dueño" in html
    assert "DATOS CONFIDENCIALES" in html
