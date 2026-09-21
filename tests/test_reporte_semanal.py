"""Tests del reporte semanal: periodo, KPIs, cuerpo del mail y el script de envio."""
from datetime import date, datetime

import pandas as pd
import pytest

from tests.test_comisiones import ops, servicios
from utils import reporte_semanal as rs
from utils.data import COBRADO


def datos(sv=None, eq=None) -> dict:
    return {"servicios": sv if sv is not None else servicios([]),
            "equipos": eq if eq is not None else ops([])}


# ---------------------------------------------------------------------------
# Periodo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("hoy,lunes,domingo", [
    # Viernes 18/09/2026 -> se reporta lunes 7 a domingo 13
    (date(2026, 9, 18), date(2026, 9, 7), date(2026, 9, 13)),
    (date(2026, 9, 14), date(2026, 9, 7), date(2026, 9, 13)),   # lunes
    (date(2026, 9, 20), date(2026, 9, 7), date(2026, 9, 13)),   # domingo
    (date(2026, 1, 2), date(2025, 12, 22), date(2025, 12, 28)),  # cruza el año
])
def test_semana_cerrada_es_siempre_la_anterior_completa(hoy, lunes, domingo):
    assert rs.semana_cerrada(hoy) == (lunes, domingo)


def test_la_semana_reportada_no_incluye_el_dia_del_envio():
    """Reportar lunes-a-hoy daria semanas incompletas y no comparables."""
    viernes = date(2026, 9, 18)
    _, hasta = rs.semana_cerrada(viernes)
    assert hasta < viernes


def test_semana_cerrada_dura_siete_dias():
    desde, hasta = rs.semana_cerrada(date(2026, 9, 18))
    assert (hasta - desde).days == 6
    assert desde.weekday() == 0 and hasta.weekday() == 6


def test_semana_cerrada_acepta_datetime():
    assert rs.semana_cerrada(datetime(2026, 9, 18, 9, 30)) == (date(2026, 9, 7), date(2026, 9, 13))


def test_asunto_y_nombre_de_archivo():
    desde, hasta = date(2026, 9, 7), date(2026, 9, 13)
    assert rs.asunto(desde, hasta) == "Reporte Semanal Agropix - [Lunes 07/09 - Domingo 13/09]"
    assert rs.nombre_pdf(hasta) == "reporte_semanal_20260913.pdf"


def test_la_hora_se_calcula_en_zona_argentina():
    assert rs.ahora_argentina().utcoffset().total_seconds() == -3 * 3600


# ---------------------------------------------------------------------------
# Destinatarios
# ---------------------------------------------------------------------------
def test_son_los_siete_destinatarios_y_estan_normalizados():
    assert len(rs.DESTINATARIOS) == 7
    assert len(set(rs.DESTINATARIOS)) == 7, "hay destinatarios repetidos"
    for email in rs.DESTINATARIOS:
        assert email == email.lower().strip()
        assert "@" in email and " " not in email


# ---------------------------------------------------------------------------
# KPIs y variacion
# ---------------------------------------------------------------------------
def test_kpis_semana_sin_semana_previa_no_trae_variacion():
    k = rs.kpis_semana(datos(eq=ops([{"comision": 1000.0, "cobrado": True}])))
    assert k["comision_cobrada"] == 1000.0
    assert "variacion_cobradas" not in k


def test_variacion_contra_la_semana_previa():
    actual = datos(eq=ops([{"comision": 1500.0, "cobrado": True}]))
    previa = datos(eq=ops([{"comision": 1000.0, "cobrado": True}]))
    k = rs.kpis_semana(actual, previa)
    assert k["variacion_cobradas"] == pytest.approx(0.5)
    assert k["cobradas_previa"] == 1000.0


def test_variacion_negativa():
    actual = datos(eq=ops([{"comision": 500.0, "cobrado": True}]))
    previa = datos(eq=ops([{"comision": 1000.0, "cobrado": True}]))
    assert rs.kpis_semana(actual, previa)["variacion_cobradas"] == pytest.approx(-0.5)


def test_semana_previa_en_cero_no_produce_un_porcentaje_enganoso():
    """Dividir por cero daria +infinito%: se informa None y el mail lo omite."""
    actual = datos(eq=ops([{"comision": 1000.0, "cobrado": True}]))
    k = rs.kpis_semana(actual, datos())
    assert k["variacion_cobradas"] is None
    assert rs._delta(None) == ""


# ---------------------------------------------------------------------------
# Formato es-AR
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valor,esperado", [
    (0, "US$ 0"), (1234, "US$ 1.234"), (1234567, "US$ 1.234.567"),
])
def test_moneda_usa_punto_de_miles(valor, esperado):
    assert rs._moneda(valor) == esperado


def test_porcentaje_usa_coma_decimal():
    assert rs._pct(0.755) == "75,5 %"


def test_delta_muestra_el_signo():
    assert rs._delta(0.123).startswith("+12,3 %")
    assert rs._delta(-0.5).startswith("−50,0 %")


# ---------------------------------------------------------------------------
# Resumen y cuerpo del mail
# ---------------------------------------------------------------------------
def test_resumen_menciona_cobrado_generado_y_hectareas():
    k = rs.kpis_semana(datos(
        sv=servicios([{"monto": 3000.0, "hectareas": 120.0, "estado_cobro": COBRADO}]),
        eq=ops([{"comision": 1000.0, "cobrado": False}]),
    ))
    texto = rs.resumen_texto(k, date(2026, 9, 7), date(2026, 9, 13))
    assert "07/09" in texto and "13/09" in texto
    assert "US$ 3.000" in texto      # cobrado
    assert "US$ 4.000" in texto      # generado
    assert "120" in texto and "ha" in texto


def test_resumen_de_una_semana_sin_movimiento_lo_dice():
    texto = rs.resumen_texto(rs.kpis_semana(datos()), date(2026, 9, 7), date(2026, 9, 13))
    assert "no se registraron" in texto


def test_cuerpo_html_trae_los_tres_kpis_el_boton_y_el_aviso():
    k = rs.kpis_semana(datos(
        sv=servicios([{"monto": 3000.0, "hectareas": 120.0, "estado_cobro": COBRADO}]),
        eq=ops([{"comision": 1000.0, "cobrado": True}]),
    ))
    html = rs.cuerpo_html(k, date(2026, 9, 7), date(2026, 9, 13))
    assert "Comisiones cobradas" in html
    assert "Has trabajadas" in html
    assert "Clientes" in html
    assert "Ver reporte completo en Streamlit" in html
    assert rs.URL_APP in html
    assert "CONFIDENCIAL" in html
    assert "Lunes 07/09 - Domingo 13/09" in html


def test_el_cuerpo_no_usa_flex_ni_grid_ni_style_externo():
    """Gmail descarta <style> y no soporta flex/grid: el mail va con tablas e inline."""
    html = rs.cuerpo_html(rs.kpis_semana(datos()), date(2026, 9, 7), date(2026, 9, 13))
    assert "<style" not in html
    assert "display:flex" not in html.replace(" ", "")
    assert "display:grid" not in html.replace(" ", "")
    assert "<table" in html


def test_tabla_de_clientes_aparece_cuando_hay_datos():
    k = rs.kpis_semana(datos())
    clientes = pd.DataFrame({"cliente": ["Don Mario", "Paredes"],
                             "servicios": [1000.0, 500.0], "equipos": [0.0, 200.0],
                             "ingreso": [1000.0, 700.0]})
    html = rs.cuerpo_html(k, date(2026, 9, 7), date(2026, 9, 13), clientes)
    assert "Top 5 clientes" in html
    assert "Don Mario" in html and "US$ 1.000" in html


def test_sin_clientes_no_se_dibuja_la_tabla():
    html = rs.cuerpo_html(rs.kpis_semana(datos()), date(2026, 9, 7), date(2026, 9, 13),
                          pd.DataFrame())
    assert "Top 5 clientes" not in html


def test_la_tabla_corta_en_cinco_clientes():
    clientes = pd.DataFrame({"cliente": [f"C{i}" for i in range(10)],
                             "servicios": [0.0] * 10, "equipos": [0.0] * 10,
                             "ingreso": [float(10 - i) for i in range(10)]})
    html = rs.cuerpo_html(rs.kpis_semana(datos()), date(2026, 9, 7), date(2026, 9, 13), clientes)
    assert "C4" in html and "C5" not in html


# ---------------------------------------------------------------------------
# Script de envio: validacion de argumentos, sin tocar red ni Sheets
# ---------------------------------------------------------------------------
def test_el_script_rechaza_desde_sin_hasta():
    from scripts import enviar_reporte_semanal as script

    assert script.main(["--desde", "2026-09-07"]) == 2
    assert script.main(["--hasta", "2026-09-13"]) == 2


def test_el_script_rechaza_un_periodo_invertido():
    from scripts import enviar_reporte_semanal as script

    assert script.main(["--desde", "2026-09-13", "--hasta", "2026-09-07"]) == 2


def test_el_script_corta_si_el_envio_no_esta_configurado(monkeypatch):
    """Avisa antes de leer Sheets y armar el PDF, que es la parte lenta."""
    from scripts import enviar_reporte_semanal as script

    monkeypatch.setattr(script, "configurado", lambda: (False, "falta SENDGRID_API_KEY"))

    def no_deberia_leer(*_a, **_k):
        raise AssertionError("no debería leer los Sheets sin configuración de envío")

    monkeypatch.setattr(script, "cargar", no_deberia_leer)
    assert script.main([]) == 3


# ---------------------------------------------------------------------------
# Resultado del envio: un fallo parcial NO es exito
# ---------------------------------------------------------------------------
def _script_con_envio(monkeypatch, resultado, tmp_path):
    """Prepara el script con todo mockeado salvo el resultado del envio."""
    from scripts import enviar_reporte_semanal as script
    from utils import envio_log

    monkeypatch.setattr(script, "configurado", lambda: (True, ""))
    monkeypatch.setattr(script, "cargar", lambda d, h: datos())
    monkeypatch.setattr(script, "enviar_individual", lambda *a, **k: resultado)
    monkeypatch.setattr(envio_log, "ARCHIVO", tmp_path / "envios.jsonl")
    monkeypatch.setitem(__import__("sys").modules, "utils.pdf",
                        type("M", (), {"generar_pdf": staticmethod(lambda *a, **k: b"%PDF-1.4")}))
    return script


def test_el_script_devuelve_error_si_alguno_no_llego(monkeypatch, tmp_path):
    """Si Actions lo marcara verde con envíos caídos, nadie se entera."""
    parcial = {"exitosos": 1, "fallidos": 1, "total": 2, "detalle": [
        {"email": "ok@agropix.com", "exitoso": True, "momento": "2026-09-20T09:30:00"},
        {"email": "mal@agropix.com", "exitoso": False, "error": "535 auth",
         "momento": "2026-09-20T09:30:00"},
    ]}
    script = _script_con_envio(monkeypatch, parcial, tmp_path)
    assert script.main(["--desde", "2026-09-07", "--hasta", "2026-09-13"]) == 6


def test_el_script_devuelve_cero_si_llegaron_todos(monkeypatch, tmp_path):
    completo = {"exitosos": 2, "fallidos": 0, "total": 2, "detalle": [
        {"email": "a@agropix.com", "exitoso": True, "momento": "2026-09-20T09:30:00"},
        {"email": "b@agropix.com", "exitoso": True, "momento": "2026-09-20T09:30:00"},
    ]}
    script = _script_con_envio(monkeypatch, completo, tmp_path)
    assert script.main(["--desde", "2026-09-07", "--hasta", "2026-09-13"]) == 0


def test_el_envio_queda_registrado_en_el_historial(monkeypatch, tmp_path):
    from utils import envio_log

    completo = {"exitosos": 1, "fallidos": 0, "total": 1, "detalle": [
        {"email": "a@agropix.com", "exitoso": True, "momento": "2026-09-20T09:30:00"}]}
    archivo = tmp_path / "envios.jsonl"
    script = _script_con_envio(monkeypatch, completo, tmp_path)
    monkeypatch.setattr(envio_log, "ARCHIVO", archivo)

    script.main(["--desde", "2026-09-07", "--hasta", "2026-09-13", "--tipo", "AUTOMATICO"])
    entradas = envio_log.historial(archivo=archivo)
    assert len(entradas) == 1
    assert entradas[0]["tipo"] == "AUTOMATICO"
    assert entradas[0]["periodo"] == "Lunes 07/09 - Domingo 13/09"


def test_en_github_actions_el_envio_se_marca_automatico(monkeypatch, tmp_path):
    from utils import envio_log

    completo = {"exitosos": 1, "fallidos": 0, "total": 1, "detalle": [
        {"email": "a@agropix.com", "exitoso": True, "momento": "2026-09-20T09:30:00"}]}
    archivo = tmp_path / "envios.jsonl"
    script = _script_con_envio(monkeypatch, completo, tmp_path)
    monkeypatch.setattr(envio_log, "ARCHIVO", archivo)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    script.main(["--desde", "2026-09-07", "--hasta", "2026-09-13"])
    assert envio_log.historial(archivo=archivo)[0]["tipo"] == "AUTOMATICO"


def test_corrido_a_mano_el_envio_se_marca_manual(monkeypatch, tmp_path):
    from utils import envio_log

    completo = {"exitosos": 1, "fallidos": 0, "total": 1, "detalle": [
        {"email": "a@agropix.com", "exitoso": True, "momento": "2026-09-20T09:30:00"}]}
    archivo = tmp_path / "envios.jsonl"
    script = _script_con_envio(monkeypatch, completo, tmp_path)
    monkeypatch.setattr(envio_log, "ARCHIVO", archivo)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    script.main(["--desde", "2026-09-07", "--hasta", "2026-09-13"])
    assert envio_log.historial(archivo=archivo)[0]["tipo"] == "MANUAL"


# ---------------------------------------------------------------------------
# Link a la app
# ---------------------------------------------------------------------------
def test_el_link_apunta_a_la_app_de_produccion():
    assert rs.URL_APP == "https://agropix-dashboard-rlugsmacrmmzqtonnbqw9.streamlit.app"


def test_el_link_va_en_el_boton_y_tambien_en_texto_copiable():
    """Hay clientes de correo que no pintan el botón; el link tiene que estar visible."""
    html = rs.cuerpo_html(rs.kpis_semana(datos()), date(2026, 9, 14), date(2026, 9, 20))
    assert html.count(rs.URL_APP) >= 3, "debería estar en el href del botón, en el href del texto y visible"
    assert "copiá y pegá" in html
    assert f">{rs.URL_APP}</a>" in html, "el link tiene que verse escrito, no sólo como destino"


def test_el_horario_del_cron_es_lunes_8am_argentina():
    """0 11 * * 1 = lunes 11:00 UTC = 8:00 ART (Argentina es UTC-3 todo el año)."""
    from pathlib import Path

    workflow = (Path(rs.__file__).resolve().parent.parent
                / ".github" / "workflows" / "reporte-semanal.yml").read_text(encoding="utf-8")
    assert 'cron: "0 11 * * 1"' in workflow


def test_el_mail_del_lunes_21_reporta_del_14_al_20():
    """El caso exacto que pidió Franco."""
    desde, hasta = rs.semana_cerrada(date(2026, 9, 21))
    assert (desde, hasta) == (date(2026, 9, 14), date(2026, 9, 20))
    assert rs.asunto(desde, hasta) == "Reporte Semanal Agropix - [Lunes 14/09 - Domingo 20/09]"
