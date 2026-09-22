"""Fija las reglas que salieron de validar el dashboard contra el Sheet.

Los numeros de esta validacion difieren de Excel en tres puntos, y en los tres
la diferencia es la MISMA causa: Excel no descarto las operaciones con
Estado = "Devuelto", aunque su propia especificacion decia hacerlo. Estos tests
dejan esa decision escrita, para que un cambio futuro sea deliberado y no un
descuido.
"""

import pytest

from tests.test_comisiones import ops, servicios, unidades
from utils import comisiones as cm
from utils.data import CANCELADO, COBRADO, kpis_equipos, kpis_servicios, vigentes


# ---------------------------------------------------------------------------
# Lo devuelto no se vendio
# ---------------------------------------------------------------------------
def test_una_operacion_devuelta_no_suma_volumen_ni_unidades():
    """El caso real: Diego martinez, Mavic 3M + T70, factura 37.000, devuelto."""
    e = ops([
        {"comision": 5000.0, "cobrado": True, "factura": 100_000.0, "unidades": 1,
         "pendiente_precio": False},
        {"comision": 0.0, "cobrado": False, "factura": 37_000.0, "unidades": 2,
         "estado_cobro": CANCELADO, "pendiente_precio": False},
    ])
    u = unidades([
        {"modelo": "T100", "id_operacion": 1},
        {"modelo": "Mavic 3M", "id_operacion": 2, "estado_cobro": CANCELADO},
        {"modelo": "T70", "id_operacion": 2, "estado_cobro": CANCELADO},
    ])
    k = kpis_equipos(e, u)
    assert k["unidades"] == 1, "las 2 unidades devueltas no se vendieron"
    assert k["monto"] == 100_000.0, "los 37.000 devueltos no son volumen intermediado"
    assert len(vigentes(e)) == 1


def test_la_comision_de_una_devuelta_es_cero_asi_que_el_total_no_cambia():
    """Por eso la comision total coincide con Excel aunque las unidades no."""
    e = ops([
        {"comision": 5000.0, "cobrado": True},
        {"comision": 0.0, "cobrado": False, "estado_cobro": CANCELADO},
    ])
    assert cm.kpis_comisiones(servicios([]), e)["ingresos"] == 5000.0
    assert float(e["comision"].sum()) == 5000.0, "incluso sin filtrar da lo mismo"


# ---------------------------------------------------------------------------
# Ticket de equipos: comision total / unidades
# ---------------------------------------------------------------------------
def test_el_ticket_de_equipos_usa_la_comision_total_y_no_la_cobrada():
    e = ops([{"comision": 1000.0, "cobrado": True}, {"comision": 3000.0, "cobrado": False}])
    u = unidades([{"modelo": "T100", "id_operacion": 1}, {"modelo": "T70", "id_operacion": 2}])
    t = cm.ticket_promedio_equipos(e, u)
    assert t["comision_generada"] == 4000.0
    assert t["ticket_generado"] == 2000.0, "4.000 / 2 unidades"
    assert t["ticket_cobrado"] == 500.0, "queda disponible, pero no es lo que se muestra"


# ---------------------------------------------------------------------------
# Servicios: clientes y ticket
# ---------------------------------------------------------------------------
def test_un_cliente_sin_monto_cargado_igual_cuenta_como_cliente():
    """Antes desaparecia del KPI solo porque faltaba cargarle el importe."""
    s = servicios([
        {"monto": 1000.0, "cliente": "Con monto", "estado_cobro": COBRADO},
        {"monto": 0.0, "cliente": "Sin monto todavía", "estado_cobro": COBRADO},
    ])
    assert kpis_servicios(s)["clientes"] == 2


def test_el_ticket_no_se_hunde_con_los_trabajos_sin_monto():
    """8 trabajos reales no tienen importe cargado; contarlos como $0 miente."""
    s = servicios([
        {"monto": 1000.0, "cliente": "A", "estado_cobro": COBRADO},
        {"monto": 3000.0, "cliente": "B", "estado_cobro": COBRADO},
        {"monto": 0.0, "cliente": "C", "estado_cobro": COBRADO},
    ])
    k = kpis_servicios(s)
    assert k["trabajos"] == 2, "el divisor son los que tienen monto"
    assert k["trabajos_totales"] == 3
    assert k["trabajos_sin_monto"] == 1
    assert k["ticket_promedio"] == 2000.0, "4.000 / 2, no / 3"


def test_el_divisor_del_ticket_es_el_que_se_muestra_en_la_tarjeta():
    """El bug era mostrar 318 trabajos y dividir por 310."""
    s = servicios([{"monto": float(i or 0), "cliente": f"C{i}", "estado_cobro": COBRADO}
                   for i in range(5)])
    k = kpis_servicios(s)
    assert k["ticket_promedio"] == pytest.approx(k["ventas"] / k["trabajos"])


def test_los_cancelados_siguen_fuera_de_servicios():
    s = servicios([
        {"monto": 1000.0, "cliente": "A", "estado_cobro": COBRADO},
        {"monto": 9999.0, "cliente": "Cancelado", "estado_cobro": CANCELADO},
    ])
    k = kpis_servicios(s)
    assert k["ventas"] == 1000.0
    assert k["clientes"] == 1


# ---------------------------------------------------------------------------
# Comision por forma de pago
# ---------------------------------------------------------------------------
def test_la_comision_por_forma_de_pago_suma_la_comision_total():
    """El grafico repartia el Facturado s/IVA, que es plata del proveedor."""
    e = ops([
        {"comision": 1000.0, "cobrado": True, "factura": 50_000.0, "forma_pago": "Contado"},
        {"comision": 500.0, "cobrado": False, "factura": 30_000.0, "forma_pago": "Financiado"},
    ])
    v = vigentes(e)
    por_pago = v.groupby("forma_pago", as_index=False).agg(comision=("comision", "sum"))
    assert por_pago["comision"].sum() == 1500.0
    assert por_pago["comision"].sum() != v["factura"].sum()


# ---------------------------------------------------------------------------
# Ingresos del Reporte General
# ---------------------------------------------------------------------------
def test_ingresos_es_la_suma_de_las_dos_unidades_de_negocio():
    k = cm.kpis_comisiones(
        servicios([{"monto": 336_349.90, "estado_cobro": COBRADO}]),
        ops([{"comision": 178_728.88, "cobrado": True}]),
    )
    assert k["ingresos"] == pytest.approx(515_078.78)
    assert k["generada_equipos"] == pytest.approx(178_728.88)
    assert k["generado_servicios"] == pytest.approx(336_349.90)


def test_los_clientes_del_reporte_general_juntan_crm_y_vendidos_sin_duplicar():
    k = cm.kpis_comisiones(
        servicios([{"monto": 100.0, "cliente": "Compartido", "estado_cobro": COBRADO},
                   {"monto": 100.0, "cliente": "Solo servicios", "estado_cobro": COBRADO}]),
        ops([{"comision": 100.0, "cobrado": True, "cliente": "Compartido"},
             {"comision": 100.0, "cobrado": True, "cliente": "Solo equipos"}]),
    )
    assert k["clientes"] == 3, "Compartido no se cuenta dos veces"


def test_los_clientes_se_comparan_sin_tildes_ni_mayusculas():
    k = cm.kpis_comisiones(
        servicios([{"monto": 100.0, "cliente": "Martín Pérez", "estado_cobro": COBRADO}]),
        ops([{"comision": 100.0, "cobrado": True, "cliente": "MARTIN PEREZ"}]),
    )
    assert k["clientes"] == 1, "es el mismo cliente escrito distinto"
