"""Tests del periodo del reporte: viernes a viernes, en hora de Argentina."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from utils import reporte_semanal as rs

UTC = ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# Los casos que pidio Franco
# ---------------------------------------------------------------------------
def test_el_envio_del_viernes_25_cubre_del_18_al_25():
    assert rs.semana_reporte(date(2026, 9, 25)) == (date(2026, 9, 18), date(2026, 9, 25))


def test_el_envio_del_viernes_2_de_octubre_cubre_del_25_al_2():
    assert rs.semana_reporte(date(2026, 10, 2)) == (date(2026, 9, 25), date(2026, 10, 2))


@pytest.mark.parametrize("dia,nombre", [
    (date(2026, 9, 26), "sábado"),
    (date(2026, 9, 27), "domingo"),
    (date(2026, 9, 28), "lunes"),
    (date(2026, 10, 1), "jueves"),
])
def test_si_el_runner_se_atrasa_el_cierre_sigue_siendo_el_viernes(dia, nombre):
    """El reporte no debe cambiar de periodo porque GitHub demoro la corrida."""
    assert rs.semana_reporte(dia) == (date(2026, 9, 18), date(2026, 9, 25)), nombre


def test_el_cierre_siempre_cae_viernes():
    for salto in range(0, 400, 7):
        referencia = date(2026, 1, 1) + __import__("datetime").timedelta(days=salto)
        _, hasta = rs.semana_reporte(referencia)
        assert hasta.weekday() == rs.VIERNES
        assert hasta <= referencia


# ---------------------------------------------------------------------------
# Ambos extremos inclusive
# ---------------------------------------------------------------------------
def test_con_ambos_viernes_el_periodo_dura_ocho_dias():
    desde, hasta = rs.semana_reporte(date(2026, 9, 25), ambos_inclusive=True)
    assert desde.weekday() == rs.VIERNES and hasta.weekday() == rs.VIERNES
    assert (hasta - desde).days + 1 == 8


def test_sin_el_viernes_de_apertura_arranca_el_sabado_y_dura_siete():
    desde, hasta = rs.semana_reporte(date(2026, 9, 25), ambos_inclusive=False)
    assert (desde, hasta) == (date(2026, 9, 19), date(2026, 9, 25))
    assert (hasta - desde).days + 1 == 7


def test_con_ambos_inclusive_el_viernes_se_repite_en_dos_reportes():
    """Es el efecto conocido de la decision: queda escrito para que no sorprenda."""
    _, cierre1 = rs.semana_reporte(date(2026, 9, 25), ambos_inclusive=True)
    apertura2, _ = rs.semana_reporte(date(2026, 10, 2), ambos_inclusive=True)
    assert cierre1 == apertura2 == date(2026, 9, 25)


def test_sin_ambos_inclusive_no_hay_superposicion():
    _, cierre1 = rs.semana_reporte(date(2026, 9, 25), ambos_inclusive=False)
    apertura2, _ = rs.semana_reporte(date(2026, 10, 2), ambos_inclusive=False)
    assert apertura2 > cierre1


def test_el_default_sale_de_la_configuracion(monkeypatch):
    monkeypatch.setattr(rs, "REPORTE_AMBOS_VIERNES", False)
    assert rs.semana_reporte(date(2026, 9, 25)) == (date(2026, 9, 19), date(2026, 9, 25))
    monkeypatch.setattr(rs, "REPORTE_AMBOS_VIERNES", True)
    assert rs.semana_reporte(date(2026, 9, 25)) == (date(2026, 9, 18), date(2026, 9, 25))


# ---------------------------------------------------------------------------
# Zona horaria
# ---------------------------------------------------------------------------
def test_se_usa_la_fecha_de_argentina_y_no_la_del_runner(monkeypatch):
    """21:00 UTC del viernes ya es sabado en UTC+2, pero en Buenos Aires son las 18:00."""
    viernes_21_utc = datetime(2026, 9, 25, 21, 0, tzinfo=UTC)
    monkeypatch.setattr(rs, "ahora_argentina",
                        lambda: viernes_21_utc.astimezone(rs.TZ_ARGENTINA))
    desde, hasta = rs.semana_reporte()
    assert hasta == date(2026, 9, 25), "en Argentina sigue siendo viernes"
    assert desde == date(2026, 9, 18)


def test_tarde_en_la_noche_del_viernes_sigue_siendo_el_mismo_periodo(monkeypatch):
    """23:30 ART del viernes = 02:30 UTC del sabado. Con UTC daria otra semana."""
    monkeypatch.setattr(rs, "ahora_argentina",
                        lambda: datetime(2026, 9, 25, 23, 30, tzinfo=rs.TZ_ARGENTINA))
    assert rs.semana_reporte() == (date(2026, 9, 18), date(2026, 9, 25))


def test_acepta_datetime_ademas_de_date():
    assert rs.semana_reporte(datetime(2026, 9, 25, 18, 0)) == (date(2026, 9, 18), date(2026, 9, 25))


def test_viernes_de_cierre_sobre_un_viernes_devuelve_ese_mismo_dia():
    assert rs.viernes_de_cierre(date(2026, 9, 25)) == date(2026, 9, 25)


# ---------------------------------------------------------------------------
# Titulo y etiqueta
# ---------------------------------------------------------------------------
def test_el_titulo_es_el_que_pidio_franco():
    desde, hasta = rs.semana_reporte(date(2026, 9, 25))
    assert rs.titulo_reporte(desde, hasta) == "REPORTE SEMANAL — Viernes 18/09 a Viernes 25/09/2026"


def test_la_etiqueta_nombra_los_dos_dias_y_el_ano_una_sola_vez():
    etiqueta = rs.etiqueta_periodo(date(2026, 9, 18), date(2026, 9, 25))
    assert etiqueta == "Viernes 18/09 a Viernes 25/09/2026"
    assert etiqueta.count("2026") == 1


def test_el_asunto_usa_la_misma_etiqueta():
    desde, hasta = rs.semana_reporte(date(2026, 9, 25))
    assert rs.asunto(desde, hasta) == (
        "Reporte Semanal Agropix - [Viernes 18/09 a Viernes 25/09/2026]")


def test_el_titulo_aparece_en_el_cuerpo_del_mail():
    from tests.test_comisiones import ops, servicios

    desde, hasta = rs.semana_reporte(date(2026, 9, 25))
    k = rs.kpis_semana({"servicios": servicios([]), "equipos": ops([])})
    assert rs.titulo_reporte(desde, hasta) in rs.cuerpo_html(k, desde, hasta)


def test_el_pdf_lleva_el_mismo_titulo_que_el_mail():
    from utils.pdf import titulo_pdf

    desde, hasta = rs.semana_reporte(date(2026, 9, 25))
    assert titulo_pdf({"desde": desde, "hasta": hasta}) == (
        "Agropix — REPORTE SEMANAL — Viernes 18/09 a Viernes 25/09/2026")


def test_el_pdf_sin_periodo_no_inventa_fechas():
    from utils.pdf import titulo_pdf

    assert "historial" in titulo_pdf({"desde": None, "hasta": None})


# ---------------------------------------------------------------------------
# Una sola fuente
# ---------------------------------------------------------------------------
def test_semana_cerrada_sigue_andando_como_alias():
    assert rs.semana_cerrada(date(2026, 9, 25)) == rs.semana_reporte(date(2026, 9, 25))


def test_la_app_el_pdf_y_el_mail_usan_la_misma_funcion():
    """Si alguno calculara el periodo por su cuenta, podrian discrepar."""
    from pathlib import Path

    raiz = Path(rs.__file__).resolve().parent.parent
    for archivo in ["paginas/0_Admin.py", "scripts/enviar_reporte_semanal.py"]:
        texto = (raiz / archivo).read_text(encoding="utf-8")
        assert "semana_reporte" in texto, f"{archivo} no usa la funcion central"
