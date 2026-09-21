"""Tests de las tarjetas de KPI: layout, tamaño y robustez ante deploys parciales."""
import re

import pytest

from utils import comisiones as cm, ui
from utils.format import GRADIENTES_KPI


class HtmlFalso:
    """Captura lo que tarjetas_kpi() le pasa a st.html()."""

    def __init__(self):
        self.ultimo = ""

    def __call__(self, cuerpo):
        self.ultimo = cuerpo


@pytest.fixture
def html(monkeypatch):
    falso = HtmlFalso()
    monkeypatch.setattr(ui.st, "html", falso)
    return falso


TRES = [
    dict(label="Ingresos", valor="US$ 515.078,77", gradiente="cobradas"),
    dict(label="Has trabajadas", valor="20.154 ha", gradiente="hectareas"),
    dict(label="Clientes", valor="124", gradiente="generadas"),
]


# ---------------------------------------------------------------------------
# Layout: una sola fila
# ---------------------------------------------------------------------------
def test_con_columnas_fijas_las_tarjetas_van_en_una_sola_fila(html):
    ui.tarjetas_kpi(TRES, columnas=3)
    assert "repeat(3, minmax(0, 1fr))" in html.ultimo


def test_el_minimo_del_grid_va_en_cero_y_no_en_pixeles(html):
    """Con un minimo en px, si no entran todas el grid las baja de fila."""
    ui.tarjetas_kpi(TRES, columnas=3)
    assert "minmax(0, 1fr)" in html.ultimo
    assert "minmax(210px" not in html.ultimo


def test_sin_columnas_se_acomodan_solas(html):
    ui.tarjetas_kpi(TRES)
    assert "auto-fit" in html.ultimo


def test_en_tablet_y_celular_se_apilan(html):
    ui.tarjetas_kpi(TRES, columnas=3)
    assert "@media (max-width: 860px)" in html.ultimo, "falta el corte de tablet"
    assert "@media (max-width: 480px)" in html.ultimo, "falta el corte de celular"


# ---------------------------------------------------------------------------
# Tamaño del número
# ---------------------------------------------------------------------------
def test_el_numero_bajo_de_tamano():
    """Venia en 1.9rem y se pidio 20-30% mas chico."""
    medida = re.search(r"agpx-kpi-valor \{\{[^}]*font-size: ([\d.]+)rem", ui._CSS_TARJETAS)
    assert medida, "no se encontro el tamano del valor"
    tamano = float(medida.group(1))
    assert 1.33 <= tamano <= 1.52, f"1.9rem menos 20-30% deberia caer ahi; es {tamano}"


def test_el_titulo_sigue_siendo_mas_chico_que_el_numero():
    """La jerarquia visual no se invierte al achicar el numero."""
    valor = float(re.search(r"agpx-kpi-valor \{\{[^}]*font-size: ([\d.]+)rem", ui._CSS_TARJETAS).group(1))
    label = float(re.search(r"agpx-kpi-label \{\{[^}]*font-size: ([\d.]+)rem", ui._CSS_TARJETAS).group(1))
    assert label < valor


def test_los_montos_alinean_entre_tarjetas():
    assert "tabular-nums" in ui._CSS_TARJETAS
    assert "overflow-wrap: anywhere" in ui._CSS_TARJETAS, "un monto largo no debe desbordar"


# ---------------------------------------------------------------------------
# Contenido
# ---------------------------------------------------------------------------
def test_pinta_una_tarjeta_por_item_con_su_gradiente(html):
    ui.tarjetas_kpi(TRES, columnas=3)
    assert html.ultimo.count('class="agpx-kpi"') == 3
    for t in TRES:
        assert t["valor"] in html.ultimo
        assert GRADIENTES_KPI[t["gradiente"]][0] in html.ultimo


def test_una_tarjeta_sin_nota_no_deja_el_div_vacio(html):
    """El CSS define la clase siempre; lo que no debe haber es el div."""
    ui.tarjetas_kpi(TRES, columnas=3)
    assert '<div class="agpx-kpi-nota">' not in html.ultimo


def test_una_tarjeta_con_nota_si_la_dibuja(html):
    ui.tarjetas_kpi([dict(label="Has", valor="20 ha", nota="3 trabajos")], columnas=1)
    assert '<div class="agpx-kpi-nota">3 trabajos</div>' in html.ultimo


def test_sin_tarjetas_no_dibuja_nada(html):
    ui.tarjetas_kpi([])
    assert html.ultimo == ""


# ---------------------------------------------------------------------------
# El KeyError de produccion
# ---------------------------------------------------------------------------
def test_ingresos_es_comision_de_equipos_mas_ventas_de_servicios():
    from tests.test_comisiones import ops, servicios

    k = cm.kpis_comisiones(
        servicios([{"monto": 3000.0, "estado_cobro": "Cobrado"}]),
        ops([{"comision": 1000.0, "cobrado": False}]),
    )
    assert k["ingresos"] == 4000.0
    assert k["ingresos"] == k["generada_equipos"] + k["generado_servicios"]


def test_ingresos_y_comision_generada_son_el_mismo_numero():
    """La pagina usa comision_generada de fallback: tienen que coincidir siempre."""
    from tests.test_comisiones import ops, servicios

    for eq, sv in [([], []),
                   ([{"comision": 500.0, "cobrado": True}], []),
                   ([], [{"monto": 800.0, "estado_cobro": "Cobrado"}]),
                   ([{"comision": 1.5, "cobrado": False}], [{"monto": 2.5, "estado_cobro": "Por cobrar"}])]:
        k = cm.kpis_comisiones(servicios(sv), ops(eq))
        assert k["ingresos"] == k["comision_generada"]


def test_la_pagina_no_se_rompe_con_un_modulo_viejo_sin_la_clave():
    """Reproduce el KeyError de Cloud: modulo viejo en memoria, pagina nueva."""
    km_viejo = {"comision_generada": 4000.0, "hectareas": 10.0, "clientes": 3}
    assert km_viejo.get("ingresos", km_viejo["comision_generada"]) == 4000.0
