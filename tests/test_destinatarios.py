"""Tests de a quien le llega el reporte y en que modo."""
from datetime import date

import pytest

from utils import reporte_semanal as rs


# ---------------------------------------------------------------------------
# Una sola fuente
# ---------------------------------------------------------------------------
def test_el_modo_semanal_manda_a_toda_la_lista():
    assert rs.destinatarios(rs.MODO_SEMANAL) == list(rs.DESTINATARIOS)


def test_el_modo_prueba_manda_solo_a_franco_y_matias():
    assert rs.destinatarios(rs.MODO_PRUEBA) == [
        "francobomone14@gmail.com", "matias21tossen@gmail.com"]


def test_el_modo_desarrollo_manda_solo_a_franco():
    assert rs.destinatarios(rs.MODO_DESARROLLO) == ["francobomone14@gmail.com"]


def test_los_tres_circulos_son_concentricos():
    """Cada modo incluye al anterior: probar en el chico sirve para el grande."""
    dev = set(rs.destinatarios(rs.MODO_DESARROLLO))
    test = set(rs.destinatarios(rs.MODO_PRUEBA))
    prod = set(rs.destinatarios(rs.MODO_SEMANAL))
    assert dev < test < prod
    assert len(dev) == 1 and len(test) == 2 and len(prod) == 6


def test_cada_modo_tiene_su_prefijo_de_asunto():
    assert rs.prefijo_asunto(rs.MODO_DESARROLLO) == "[DEV] "
    assert rs.prefijo_asunto(rs.MODO_PRUEBA) == "[PRUEBA] "
    assert rs.prefijo_asunto(rs.MODO_SEMANAL) == "", "el real no lleva prefijo"


def test_el_asunto_de_desarrollo_avisa_que_es_dev():
    a = rs.asunto(date(2026, 9, 18), date(2026, 9, 25), rs.MODO_DESARROLLO)
    assert a.startswith("[DEV] ")


def test_ningun_modo_deja_entrar_a_infoagropix():
    for modo in rs.MODOS:
        assert not any(rs.excluido(e) for e in rs.destinatarios(modo))


def test_los_de_prueba_estan_dentro_de_la_lista_general():
    """Si alguno no estuviera, probariamos con una direccion que no recibe."""
    for email in rs.DESTINATARIOS_PRUEBA:
        assert email in rs.DESTINATARIOS


def test_la_app_usa_la_misma_lista_que_el_envio():
    from pathlib import Path

    admin = (Path(rs.__file__).resolve().parent.parent / "paginas" / "0_Admin.py")
    assert "DESTINATARIOS" in admin.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# El filtro de infoagropix, explicito
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("email", [
    "infoagropix@gmail.com",
    "INFOAGROPIX@Gmail.com",
    "  infoagropix@gmail.com  ",
    "infoagropix.ventas@agropix.com",
    "contacto+infoagropix@gmail.com",
])
def test_cualquier_direccion_con_infoagropix_queda_afuera(email):
    assert rs.excluido(email)
    assert rs.destinatarios(lista=["ok@agropix.com", email]) == ["ok@agropix.com"]


def test_el_filtro_no_se_puede_saltear_pasando_la_lista_a_mano():
    """Ni --destinatarios ni EMAIL_DESTINATARIOS pueden meterla de vuelta."""
    assert "infoagropix@gmail.com" not in rs.destinatarios(
        rs.MODO_SEMANAL, lista=["infoagropix@gmail.com"])
    assert "infoagropix@gmail.com" not in rs.destinatarios(
        rs.MODO_PRUEBA, lista=["infoagropix@gmail.com"])


def test_infoagropix_no_esta_en_la_lista_pero_igual_hay_filtro():
    """Cinturon y tiradores: salio de la lista Y hay un filtro que la veta."""
    assert not any(rs.excluido(e) for e in rs.DESTINATARIOS)
    assert "infoagropix" in rs.EXCLUIDOS


def test_infoagropix_conserva_el_acceso_a_la_app():
    from utils.auth import EMAILS_AUTORIZADOS, es_admin

    assert "infoagropix@gmail.com" in EMAILS_AUTORIZADOS
    assert es_admin("infoagropix@gmail.com")


def test_una_direccion_normal_no_se_filtra():
    assert not rs.excluido("francobomone14@gmail.com")


# ---------------------------------------------------------------------------
# Higiene de la lista
# ---------------------------------------------------------------------------
def test_no_se_manda_dos_veces_al_mismo():
    assert rs.destinatarios(lista=["a@x.com", "A@X.com", " a@x.com "]) == ["a@x.com"]


def test_las_direcciones_salen_normalizadas():
    assert rs.destinatarios(lista=["  Franco@Gmail.COM "]) == ["franco@gmail.com"]


def test_una_lista_vacia_no_rompe():
    assert rs.destinatarios(lista=[]) == list(rs.DESTINATARIOS)
    assert rs.destinatarios(lista=["", "   "]) == []


# ---------------------------------------------------------------------------
# Asunto
# ---------------------------------------------------------------------------
def test_el_asunto_de_prueba_lleva_el_prefijo():
    a = rs.asunto(date(2026, 9, 18), date(2026, 9, 25), rs.MODO_PRUEBA)
    assert a.startswith("[PRUEBA] ")
    assert "Viernes 18/09 a Viernes 25/09/2026" in a


def test_el_asunto_semanal_no_lleva_prefijo():
    a = rs.asunto(date(2026, 9, 18), date(2026, 9, 25), rs.MODO_SEMANAL)
    assert not a.startswith("[PRUEBA]")
    assert a == "Reporte Semanal Agropix - [Viernes 18/09 a Viernes 25/09/2026]"


# ---------------------------------------------------------------------------
# Contenido del mail
# ---------------------------------------------------------------------------
def _kpis(con_datos: bool):
    from tests.test_comisiones import ops, servicios
    from utils.data import COBRADO

    if not con_datos:
        return rs.kpis_semana({"servicios": servicios([]), "equipos": ops([])})
    return rs.kpis_semana({
        "servicios": servicios([{"monto": 3000.0, "hectareas": 120.0, "estado_cobro": COBRADO}]),
        "equipos": ops([{"comision": 1000.0, "cobrado": False}]),
    })


def test_el_mail_trae_el_desglose_que_pidio_franco():
    html = rs.cuerpo_html(_kpis(True), date(2026, 9, 18), date(2026, 9, 25))
    for concepto in ["Ingresos del período", "Comisiones cobradas", "Comisiones por cobrar",
                     "Venta de servicios", "Venta de equipos", "Hectáreas trabajadas", "Clientes"]:
        assert concepto in html, f"falta {concepto}"


def test_sin_actividad_lo_dice_con_esas_palabras():
    k = _kpis(False)
    assert rs.sin_actividad(k)
    html = rs.cuerpo_html(k, date(2026, 9, 18), date(2026, 9, 25))
    assert "Sin actividad registrada en el período" in html


def test_sin_actividad_no_dibuja_una_tabla_de_ceros():
    html = rs.cuerpo_html(_kpis(False), date(2026, 9, 18), date(2026, 9, 25))
    assert "Resumen del período" not in html


def test_el_mail_sigue_llevando_el_link_a_la_app():
    html = rs.cuerpo_html(_kpis(False), date(2026, 9, 18), date(2026, 9, 25))
    assert rs.URL_APP in html
