"""Tests del modulo de comisiones. Datos sinteticos, sin red ni Streamlit."""
import pandas as pd
import pytest

from utils import comisiones as cm
from utils.data import CANCELADO, COBRADO, EN_PROCESO, EQUIPOS, POR_COBRAR, SERVICIO


def ops(filas) -> pd.DataFrame:
    """Operaciones de equipos con las columnas que consume el modulo."""
    df = pd.DataFrame(filas)
    df["unidad_negocio"] = SERVICIO if False else EQUIPOS
    for col, default in [("estado_cobro", COBRADO), ("canal", "Instagram"),
                         ("vendedor", "Matias"), ("unidades", 1), ("factura", 0.0)]:
        if col not in df.columns:
            df[col] = default
    if "id_operacion" not in df.columns:
        df["id_operacion"] = range(1, len(df) + 1)
    if "fecha" not in df.columns:
        df["fecha"] = pd.Timestamp("2026-03-15")
    return df


def servicios(filas) -> pd.DataFrame:
    df = pd.DataFrame(filas)
    df["unidad_negocio"] = SERVICIO
    for col, default in [("estado_cobro", COBRADO), ("hectareas", 0.0), ("cliente", "Cliente A")]:
        if col not in df.columns:
            df[col] = default
    if "fecha" not in df.columns:
        df["fecha"] = pd.Timestamp("2026-03-15")
    return df


def unidades(filas) -> pd.DataFrame:
    df = pd.DataFrame(filas)
    df["unidad_negocio"] = EQUIPOS
    for col, default in [("estado_cobro", COBRADO), ("id_operacion", 1), ("comision", 0.0),
                         ("precio_lista", 1000.0), ("peso", 1.0), ("cobrado", True)]:
        if col not in df.columns:
            df[col] = default
    return df


# ---------------------------------------------------------------------------
# Clasificacion de modelos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modelo,esperado", [
    ("T50", cm.AGRAS_T), ("T70", cm.AGRAS_T), ("T100", cm.AGRAS_T), ("T55", cm.AGRAS_T),
    ("t100", cm.AGRAS_T),                      # el matcheo ignora mayusculas
    ("Mavic 3M", cm.MAVIC), ("MAVIC AIR 2", cm.MAVIC),
    ("MIXER JR", cm.ACCESORIO), ("RTK", cm.ACCESORIO), ("Pix4D", cm.ACCESORIO),
    ("Sin modelo", cm.OTRO), ("", cm.OTRO), (None, cm.OTRO),
])
def test_clasificar_modelo(modelo, esperado):
    assert cm.clasificar_modelo(modelo) == esperado


def test_un_modelo_con_T_pero_sin_numero_no_es_agras():
    """startswith('T') pelado atraparia cualquier cosa; se exige T + digito."""
    assert cm.clasificar_modelo("Tractor") == cm.OTRO
    assert cm.clasificar_modelo("Termometro") == cm.OTRO


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
def test_comisiones_generadas_cobradas_y_por_cobrar():
    e = ops([
        {"comision": 1000.0, "cobrado": True},
        {"comision": 500.0, "cobrado": False},
        {"comision": 300.0, "cobrado": False},
    ])
    k = cm.kpis_comisiones(servicios([]), e)
    assert k["generada_equipos"] == 1800.0
    assert k["cobrada_equipos"] == 1000.0
    assert k["por_cobrar_equipos"] == 800.0
    assert k["pct_cobranza"] == pytest.approx(1000 / 1800)


def test_por_cobrar_es_generada_menos_cobrada():
    e = ops([{"comision": 1000.0, "cobrado": True}, {"comision": 250.0, "cobrado": False}])
    k = cm.kpis_comisiones(servicios([]), e)
    assert k["por_cobrar"] == k["comision_generada"] - k["comision_cobrada"]


def test_los_cancelados_no_suman():
    e = ops([
        {"comision": 1000.0, "cobrado": True},
        {"comision": 9999.0, "cobrado": True, "estado_cobro": CANCELADO},  # devuelto
    ])
    assert cm.kpis_comisiones(servicios([]), e)["cobrada_equipos"] == 1000.0


def test_servicios_suman_lo_facturado_y_respetan_el_estado_de_cobro():
    s = servicios([
        {"monto": 2000.0, "hectareas": 100.0, "estado_cobro": COBRADO},
        {"monto": 500.0, "hectareas": 20.0, "estado_cobro": POR_COBRAR},
        {"monto": 300.0, "hectareas": 10.0, "estado_cobro": EN_PROCESO},
        {"monto": 9999.0, "hectareas": 999.0, "estado_cobro": CANCELADO},  # no suma
    ])
    k = cm.kpis_comisiones(s, ops([]))
    assert k["generado_servicios"] == 2800.0
    assert k["cobrado_servicios"] == 2000.0
    assert k["por_cobrar_servicios"] == 800.0
    assert k["hectareas"] == 130.0
    assert k["cantidad_servicios"] == 3


def test_el_volumen_de_equipos_no_entra_en_la_comision():
    """Factura s/IVA es volumen intermediado: se informa aparte, nunca como ingreso."""
    e = ops([{"comision": 1500.0, "cobrado": True, "factura": 45000.0}])
    k = cm.kpis_comisiones(servicios([]), e)
    assert k["volumen_equipos"] == 45000.0
    assert k["comision_generada"] == 1500.0
    assert k["comision_cobrada"] == 1500.0


def test_participacion_equipos_mas_servicios_da_uno():
    e = ops([{"comision": 1000.0, "cobrado": True}])
    s = servicios([{"monto": 3000.0, "estado_cobro": COBRADO}])
    k = cm.kpis_comisiones(s, e)
    assert k["comision_cobrada"] == 4000.0
    assert k["pct_equipos"] + k["pct_servicios"] == pytest.approx(1.0)
    assert k["pct_equipos"] == pytest.approx(0.25)


def test_sin_datos_no_divide_por_cero():
    k = cm.kpis_comisiones(servicios([]), ops([]))
    assert k["comision_generada"] == 0.0
    assert k["pct_cobranza"] == 0.0
    assert k["clientes"] == 0


# ---------------------------------------------------------------------------
# Ticket promedio
# ---------------------------------------------------------------------------
def test_ticket_de_equipos_divide_por_unidades_no_por_operaciones():
    """Una venta con 3 drones son 3 equipos: dividir por operacion infla el ticket."""
    e = ops([{"comision": 3000.0, "cobrado": True, "unidades": 3}])
    u = unidades([
        {"modelo": "T100", "comision": 3000.0},
        {"modelo": "T70", "comision": 3000.0},
        {"modelo": "Mavic 3M", "comision": 3000.0},
    ])
    t = cm.ticket_promedio_equipos(e, u)
    assert t["cantidad"] == 3
    assert t["ticket_cobrado"] == 1000.0


def test_ticket_de_equipos_ignora_accesorios():
    e = ops([{"comision": 2000.0, "cobrado": True}])
    u = unidades([
        {"modelo": "T100", "comision": 2000.0},
        {"modelo": "MIXER JR", "comision": 2000.0},   # accesorio: no es un equipo
        {"modelo": "RTK", "comision": 2000.0},        # accesorio
    ])
    assert cm.ticket_promedio_equipos(e, u)["cantidad"] == 1
    assert cm.ticket_promedio_equipos(e, u, solo_principales=False)["cantidad"] == 3


def test_ticket_de_servicios_y_valor_por_hectarea():
    s = servicios([
        {"monto": 1000.0, "hectareas": 50.0},
        {"monto": 3000.0, "hectareas": 150.0},
    ])
    t = cm.ticket_promedio_servicios(s)
    assert t["cantidad"] == 2
    assert t["ticket"] == 2000.0
    assert t["valor_por_ha"] == 20.0


def test_ticket_sin_equipos_es_cero_y_no_explota():
    assert cm.ticket_promedio_equipos(ops([]), unidades([]))["ticket_cobrado"] == 0.0
    assert cm.ticket_promedio_servicios(servicios([]))["ticket"] == 0.0


# ---------------------------------------------------------------------------
# Equipos por marca y por modelo
# ---------------------------------------------------------------------------
def test_equipos_por_marca_separa_principales_de_accesorios():
    u = unidades([
        {"modelo": "T100"}, {"modelo": "T100"}, {"modelo": "Mavic 3M"},
        {"modelo": "MIXER JR"}, {"modelo": "Pix4D"},
    ])
    r = cm.equipos_por_marca(u).set_index("marca")
    assert r.loc[cm.AGRAS_T, "unidades"] == 2
    assert r.loc[cm.MAVIC, "unidades"] == 1
    assert r.loc[cm.ACCESORIO, "unidades"] == 2
    assert bool(r.loc[cm.AGRAS_T, "principal"]) is True
    assert bool(r.loc[cm.ACCESORIO, "principal"]) is False


def test_comision_se_prorratea_por_peso_de_precio_de_lista():
    """Operacion de 1000 de comision repartida 75/25 segun precio de lista."""
    u = unidades([
        {"modelo": "T100", "comision": 1000.0, "peso": 0.75, "precio_lista": 42000.0},
        {"modelo": "Mavic 3M", "comision": 1000.0, "peso": 0.25, "precio_lista": 7500.0},
    ])
    r = cm.equipos_por_modelo(u).set_index("modelo")
    assert r.loc["T100", "comision_atribuida"] == 750.0
    assert r.loc["Mavic 3M", "comision_atribuida"] == 250.0
    assert r["comision_atribuida"].sum() == 1000.0


def test_unidades_sin_precio_de_lista_quedan_sin_comision_atribuida():
    """No se reparte con datos parciales: se cuenta la unidad y se avisa."""
    u = unidades([
        {"modelo": "T50", "comision": 800.0, "peso": None, "precio_lista": None},
        {"modelo": "T55", "comision": 800.0, "peso": None, "precio_lista": None},
    ])
    r = cm.equipos_por_modelo(u)
    assert r["unidades"].sum() == 2, "las unidades se cuentan igual"
    assert r["comision_atribuida"].isna().all(), "sin precio no se atribuye comision"
    assert r["unidades_sin_atribuir"].sum() == 2


def test_cobertura_de_atribucion_informa_los_modelos_sin_precio():
    u = unidades([
        {"modelo": "T100", "peso": 1.0, "precio_lista": 42000.0},
        {"modelo": "T50", "peso": None, "precio_lista": None},
        {"modelo": "MIXER JR", "peso": None, "precio_lista": None},
    ])
    c = cm.cobertura_atribucion(u)
    assert c["unidades"] == 3
    assert c["atribuibles"] == 1
    assert c["pct"] == pytest.approx(1 / 3)
    assert c["modelos_sin_precio"] == ["MIXER JR", "T50"]


# ---------------------------------------------------------------------------
# Canal y vendedor
# ---------------------------------------------------------------------------
def test_comisiones_por_canal_ordena_por_cobrada():
    e = ops([
        {"comision": 100.0, "cobrado": True, "canal": "Instagram", "factura": 1000.0},
        {"comision": 900.0, "cobrado": True, "canal": "Referido", "factura": 9000.0},
        {"comision": 500.0, "cobrado": False, "canal": "Referido", "factura": 5000.0},
    ])
    r = cm.comisiones_por_canal(e)
    assert r.iloc[0]["canal"] == "Referido"
    assert r.iloc[0]["comision_cobrada"] == 900.0
    assert r.iloc[0]["comision_generada"] == 1400.0
    assert r.iloc[0]["por_cobrar"] == 500.0
    assert r.iloc[0]["pct_cobranza"] == pytest.approx(900 / 1400)
    assert r.iloc[0]["volumen"] == 14000.0


def test_ranking_de_vendedores_va_por_dinero_no_por_cantidad():
    e = ops([
        {"comision": 100.0, "cobrado": True, "vendedor": "Agustin", "unidades": 5},
        {"comision": 5000.0, "cobrado": True, "vendedor": "Matias", "unidades": 1},
    ])
    r = cm.ranking_vendedores(e)
    assert r.iloc[0]["vendedor"] == "Matias", "gana quien trae mas plata, no mas unidades"
    assert r.iloc[0]["comision_cobrada"] == 5000.0


def test_canal_y_vendedor_vacios_reciben_etiqueta():
    e = ops([{"comision": 100.0, "cobrado": True, "canal": None, "vendedor": None}])
    assert cm.comisiones_por_canal(e).iloc[0]["canal"] == "Sin canal"
    assert cm.ranking_vendedores(e).iloc[0]["vendedor"] == "Sin vendedor"


def test_cortes_sin_datos_devuelven_tabla_vacia_con_columnas():
    r = cm.comisiones_por_canal(ops([]))
    assert r.empty and "comision_cobrada" in r.columns


# ---------------------------------------------------------------------------
# Top clientes
# ---------------------------------------------------------------------------
def test_top_clientes_suma_comision_de_equipos_y_facturado_de_servicios():
    s = servicios([{"monto": 1000.0, "cliente": "Estancia Sur"}])
    e = ops([{"comision": 400.0, "cobrado": True, "cliente": "Estancia Sur", "factura": 50000.0}])
    r = cm.top_clientes(s, e)
    fila = r[r["cliente"] == "Estancia Sur"].iloc[0]
    assert fila["servicios"] == 1000.0
    assert fila["equipos"] == 400.0
    assert fila["ingreso"] == 1400.0, "la factura de equipos no entra"


def test_top_clientes_respeta_el_limite():
    s = servicios([{"monto": float(i), "cliente": f"C{i}"} for i in range(1, 21)])
    assert len(cm.top_clientes(s, ops([]), top=5)) == 5


# ---------------------------------------------------------------------------
# Evolucion
# ---------------------------------------------------------------------------
def test_comisiones_por_mes_agrupa_las_dos_unidades_de_negocio():
    e = ops([
        {"comision": 1000.0, "cobrado": True, "fecha": pd.Timestamp("2026-03-10")},
        {"comision": 500.0, "cobrado": False, "fecha": pd.Timestamp("2026-04-02")},
    ])
    s = servicios([{"monto": 200.0, "fecha": pd.Timestamp("2026-03-20"), "estado_cobro": COBRADO}])
    r = cm.comisiones_por_mes(s, e).set_index("mes")
    marzo, abril = pd.Timestamp("2026-03-01"), pd.Timestamp("2026-04-01")
    assert r.loc[marzo, "cobrada"] == 1200.0
    assert r.loc[abril, "cobrada"] == 0.0
    assert r.loc[abril, "por_cobrar"] == 500.0


def test_filas_sin_fecha_no_rompen_la_serie():
    e = ops([{"comision": 1000.0, "cobrado": True, "fecha": pd.NaT}])
    assert cm.comisiones_por_mes(servicios([]), e).empty
