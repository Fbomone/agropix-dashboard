"""Tests del selector de unidad de medida de Venta de Servicios.

El riesgo de esta pantalla no es que el grafico no se dibuje: es que se dibuje
con la escala de una magnitud y el rotulo de la otra. Un "$193k" donde en
realidad hay 193 mil hectareas es peor que un error, porque nadie lo duda.
"""
import pandas as pd
import pytest

from utils import ui
from utils.format import MEDIDA_PLATA, MEDIDA_SUPERFICIE, MEDIDAS


class GraficoFalso:
    """Captura las figuras que barras_por() manda a st.plotly_chart()."""

    def __init__(self):
        self.figuras = []
        self.captions = []

    def plotly_chart(self, fig, **kwargs):
        self.figuras.append(fig)

    def caption(self, texto, **kwargs):
        self.captions.append(texto)

    @property
    def ultima(self):
        assert self.figuras, "no se dibujo ningun grafico"
        return self.figuras[-1]


@pytest.fixture
def capturado(monkeypatch):
    falso = GraficoFalso()
    monkeypatch.setattr(ui.st, "plotly_chart", falso.plotly_chart)
    monkeypatch.setattr(ui.st, "caption", falso.caption)
    return falso


# Un cliente que factura mucho en pocas hectareas y otro al reves: el orden
# tiene que darse vuelta al cambiar de unidad
TRABAJOS = pd.DataFrame({
    "cliente": ["Ensayos SA", "Pulveriza SRL", "Ensayos SA"],
    "monto": [90_000.0, 30_000.0, 10_000.0],
    "hectareas": [50.0, 4_000.0, 25.0],
})


def texto_de(fig) -> str:
    return fig.data[0].texttemplate


def hover_de(fig) -> str:
    return fig.data[0].hovertemplate


# ---------------------------------------------------------------------------
# Que mide cada unidad
# ---------------------------------------------------------------------------
def test_en_plata_suma_los_montos(capturado):
    ui.barras_por(TRABAJOS, "cliente", MEDIDA_PLATA, horizontal=True)
    assert sorted(capturado.ultima.data[0].x) == [30_000.0, 100_000.0]


def test_en_superficie_suma_las_hectareas(capturado):
    ui.barras_por(TRABAJOS, "cliente", MEDIDA_SUPERFICIE, horizontal=True)
    assert sorted(capturado.ultima.data[0].x) == [75.0, 4_000.0]


def test_cambiar_la_unidad_puede_dar_vuelta_el_ranking(capturado):
    """El que mas factura no es el que mas superficie deja. Es el punto del boton."""
    ui.barras_por(TRABAJOS, "cliente", MEDIDA_PLATA, horizontal=True)
    por_plata = list(capturado.ultima.data[0].y)
    ui.barras_por(TRABAJOS, "cliente", MEDIDA_SUPERFICIE, horizontal=True)
    por_has = list(capturado.ultima.data[0].y)
    # barras_por ordena de mayor a menor, asi que el primero es el que gana
    assert por_plata[0] == "Ensayos SA", "en plata gana el ensayo caro"
    assert por_has[0] == "Pulveriza SRL", "en hectareas gana la pulverizacion grande"


# ---------------------------------------------------------------------------
# Que el rotulo acompañe a la escala
# ---------------------------------------------------------------------------
def test_en_plata_los_numeros_llevan_signo_peso(capturado):
    ui.barras_por(TRABAJOS, "cliente", MEDIDA_PLATA, horizontal=True)
    assert "$" in texto_de(capturado.ultima)
    assert " ha" not in texto_de(capturado.ultima)


def test_en_superficie_los_numeros_llevan_ha_y_ningun_signo_peso(capturado):
    """El error caro: mostrar hectareas con un '$' adelante."""
    ui.barras_por(TRABAJOS, "cliente", MEDIDA_SUPERFICIE, horizontal=True)
    assert " ha" in texto_de(capturado.ultima)
    assert "$" not in texto_de(capturado.ultima)
    assert "$" not in hover_de(capturado.ultima)


@pytest.mark.parametrize("medida", list(MEDIDAS.values()))
def test_el_eje_usa_el_formato_de_su_medida(capturado, medida):
    ui.barras_por(TRABAJOS, "cliente", medida, horizontal=True)
    assert capturado.ultima.layout.xaxis.tickformat == medida.tick


@pytest.mark.parametrize("medida", list(MEDIDAS.values()))
def test_el_eje_se_rotula_con_la_unidad(capturado, medida):
    ui.barras_por(TRABAJOS, "cliente", medida)
    assert capturado.ultima.layout.yaxis.title.text == medida.etiqueta


@pytest.mark.parametrize("medida", list(MEDIDAS.values()))
def test_el_vertical_tambien_respeta_la_medida(capturado, medida):
    """El grafico de producto/servicio es el unico vertical de los cuatro."""
    ui.barras_por(TRABAJOS, "cliente", medida)
    assert capturado.ultima.layout.yaxis.tickformat == medida.tick
    assert medida.sufijo.strip() in texto_de(capturado.ultima) or not medida.sufijo


# ---------------------------------------------------------------------------
# Que la etiqueta entre
# ---------------------------------------------------------------------------
def rango_del_eje(fig, horizontal=True):
    eje = fig.layout.xaxis if horizontal else fig.layout.yaxis
    return eje.range


def test_en_hectareas_queda_mas_aire_que_en_plata(capturado):
    """El rotulo "6,46k ha" ocupa mas que "$6,46k" y necesita mas lugar al lado."""
    ui.barras_por(TRABAJOS, "cliente", MEDIDA_PLATA, horizontal=True)
    aire_plata = rango_del_eje(capturado.ultima)[1] / 100_000.0
    ui.barras_por(TRABAJOS, "cliente", MEDIDA_SUPERFICIE, horizontal=True)
    aire_has = rango_del_eje(capturado.ultima)[1] / 4_000.0
    assert aire_has > aire_plata, "el sufijo ' ha' necesita mas aire y no lo esta pidiendo"


@pytest.mark.parametrize("medida", list(MEDIDAS.values()))
@pytest.mark.parametrize("horizontal", [True, False])
def test_la_barra_mas_larga_nunca_llega_al_borde(capturado, medida, horizontal):
    """Si la barra toca el borde, Plotly dibuja la etiqueta afuera y se recorta.

    Es el bug que se vio en Por trabajo: "6,46k ha" aparecia como "6,46k".
    """
    ui.barras_por(TRABAJOS, "cliente", medida, horizontal=horizontal)
    maximo = TRABAJOS[medida.columna].groupby(TRABAJOS["cliente"]).sum().max()
    tope = rango_del_eje(capturado.ultima, horizontal)[1]
    ocupado = maximo / tope
    assert ocupado < 0.85, (
        f"{medida.etiqueta}: la barra ocupa el {ocupado:.0%} del eje y el rótulo no entra"
    )


# ---------------------------------------------------------------------------
# Bordes
# ---------------------------------------------------------------------------
def test_sin_la_columna_de_la_medida_no_revienta(capturado):
    """Si el Sheet deja de traer hectareas, la pagina no se cae."""
    ui.barras_por(TRABAJOS.drop(columns=["hectareas"]), "cliente", MEDIDA_SUPERFICIE)
    assert not capturado.figuras


def test_si_nadie_cargo_la_medida_lo_dice_en_vez_de_dibujar_vacio(capturado):
    sin_has = TRABAJOS.assign(hectareas=0.0)
    ui.barras_por(sin_has, "cliente", MEDIDA_SUPERFICIE)
    assert not capturado.figuras
    assert any("cargado" in c for c in capturado.captions)


def test_la_plata_sigue_siendo_el_default(capturado):
    """Nadie tiene que leer hectareas creyendo que lee plata."""
    assert list(MEDIDAS)[0] == "US$"
    ui.barras_por(TRABAJOS, "cliente", horizontal=True)
    assert sorted(capturado.ultima.data[0].x) == [30_000.0, 100_000.0]


def test_los_dos_graficos_no_comparten_la_key_de_streamlit():
    """Con la misma key, Streamlit reusaria el grafico viejo al cambiar de unidad."""
    assert MEDIDA_PLATA.columna != MEDIDA_SUPERFICIE.columna
