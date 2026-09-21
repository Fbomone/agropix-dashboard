from datetime import date, datetime

import pandas as pd
import pytest

from utils.data import (
    CANCELADO, COBRADO, COLUMNAS_CRM, COLUMNAS_OPERADORES, DOMINIOS_UNIFICADO, EN_PROCESO, EQUIPOS,
    ESQUEMA_UNIFICADO, ESTADOS_TRABAJO, ESTADOS_TRABAJO_EJECUTADO, POR_COBRAR, SERVICIO, SIN_ESTADO,
    SIN_MODELO, alertas_calidad, aplicar_filtros, cargar_precios, clientes_unicos, col, construir_datos,
    despivotar_operadores, estado_cobro_equipo, estado_cobro_servicio, filtrar_por_estado_trabajo,
    filtrar_por_fecha, guardar_precios, ingresos_por_periodo, kpis_consolidado, kpis_equipos,
    kpis_general, kpis_servicios, normalizar_columnas, opciones_estado_trabajo, pares_operador,
    parse_fecha, parse_monto, perfil_columnas, resumen_operadores, resumen_por_modelo,
    transformar_equipos, transformar_servicios, unificar, validar_esquema,
)

PRECIOS = {"T100": 42000.0, "Mavic 3M": 7500.0, "T55": None}


def dtypes(df):
    return {c: str(t) for c, t in df.dtypes.items()}


@pytest.mark.parametrize("accion, esperado", [
    ("Cobro recibido", COBRADO),
    ("Facturado esperando cobro", POR_COBRAR),
    ("Trabajo realizado", POR_COBRAR),
    ("Trabajo cancelado", CANCELADO),
    ("  trabajo CANCELADO ", CANCELADO),
    ("Consulta", EN_PROCESO),
    ("Envío de presupuesto", EN_PROCESO),
    (None, EN_PROCESO),
])
def test_estado_cobro_servicio(accion, esperado):
    assert estado_cobro_servicio(accion) == esperado


@pytest.mark.parametrize("estado, cobrado, esperado", [
    ("Devuelto", "si", CANCELADO),
    ("Entregado", "si", COBRADO),
    ("Entregado", "Sí", COBRADO),
    ("Entregado", "no", POR_COBRAR),
    (None, None, POR_COBRAR),
])
def test_estado_cobro_equipo(estado, cobrado, esperado):
    assert estado_cobro_equipo(estado, cobrado) == esperado


def vendidos(filas):
    base = {"Nombre": "Cliente", "Estado": "Entregado", "Cobrado": "no", "Fecha venta": datetime(2025, 3, 10),
            "Factura s/IVA": 0, "Comisión $": 0, "Vendedor": "Ana", "forma de pago": "Contado"}
    return pd.DataFrame([{**base, **f} for f in filas])


# --- Fechas -----------------------------------------------------------------

def test_parse_fecha_mezcla_formatos():
    f = parse_fecha(pd.Series([datetime(2025, 3, 1), 45717, "05/03/2025", None, "basura", "2025-03-05"]))
    assert str(f.dtype) == "datetime64[ns]"
    assert f.tolist()[:3] == [pd.Timestamp("2025-03-01"), pd.Timestamp("2025-03-01"), pd.Timestamp("2025-03-05")]
    assert f.iloc[3:5].isna().all()
    assert f.iloc[5] == pd.Timestamp("2025-03-05")


def test_parse_fecha_fuera_de_rango_queda_nat_sin_lanzar():
    # -611738 es el serial real que rompia la app: 11/02/0225
    basura = [-611738, 99999999, "11/02/225", "01/01/2040", datetime(1900, 1, 1), date(225, 2, 11)]
    f = parse_fecha(pd.Series(basura + [45717], dtype=object))
    assert str(f.dtype) == "datetime64[ns]"
    assert f.iloc[:-1].isna().all()
    assert f.iloc[-1] == pd.Timestamp("2025-03-01")


def test_filtro_de_fecha_incluye_extremos_y_excluye_sin_fecha():
    df = pd.DataFrame({"fecha": [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-31 18:00"),
                                 pd.NaT, pd.Timestamp("2025-02-01")]})
    out = filtrar_por_fecha(df, datetime(2025, 1, 1).date(), datetime(2025, 1, 31).date())
    assert len(out) == 2


# --- Montos, ids, columnas ---------------------------------------------------

def test_parse_monto_numeros_y_texto_local():
    m = parse_monto(pd.Series([1500, 12.5, "$ 1.234,50", "1.500", None, "abc"]))
    assert m.tolist() == [1500.0, 12.5, 1234.5, 1500.0, 0.0, 0.0]


def test_clientes_vacios_no_cuentan():
    assert clientes_unicos(pd.Series(["Juan", " juan", pd.NA, None, ""])) == 1


def test_col_matchea_sin_tildes_mayusculas_ni_espacios():
    df = pd.DataFrame({"  Última   acción ": ["Cobro recibido"], "Valor total de ventas": [10]})
    for alias in ["Última acción", "Ultima accion", "ultima  acción", "ÚLTIMA ACCIÓN"]:
        assert col(df, alias).tolist() == ["Cobro recibido"]
    assert col(df, "No existe").isna().all()


def test_normalizar_columnas_conserva_original():
    df = normalizar_columnas(pd.DataFrame(columns=["  Última   acción ", "Cobrado"]))
    assert list(df.columns) == ["Última acción", "Cobrado"]
    assert df.attrs["columnas_originales"]["Última acción"] == "  Última   acción "


def test_id_cliente_mixto_queda_string():
    s = transformar_servicios(pd.DataFrame({
        "Id Cliente": [123, "A-7", 45.0], "Fecha trabajo": [45717] * 3, "Nombre del cliente": ["x"] * 3,
    }))
    assert str(s["id_cliente"].dtype) == "string"
    assert s["id_cliente"].tolist() == ["123", "A-7", "45"]


# --- Prorrateo y KPIs --------------------------------------------------------

def test_prorrateo_por_precio_de_lista():
    ops, unidades = transformar_equipos(vendidos([{"Modelo": "T100, Mavic 3M", "Factura s/IVA": 51049}]), PRECIOS)

    assert ops.loc[0, "unidades"] == 2
    assert not ops.loc[0, "pendiente_precio"]
    montos = unidades.set_index("modelo")["monto_asignado"]
    assert montos["T100"] == pytest.approx(51049 * 42000 / 49500)
    assert montos["Mavic 3M"] == pytest.approx(51049 * 7500 / 49500)
    assert montos.sum() == pytest.approx(51049)


def test_operacion_con_modelo_sin_precio_queda_pendiente_completa():
    _, unidades = transformar_equipos(vendidos([{"Modelo": "T100, T55", "Factura s/IVA": 60000}]), PRECIOS)

    assert len(unidades) == 2
    assert unidades["pendiente_precio"].all()
    assert unidades["monto_asignado"].isna().all()


def test_modelo_desconocido_y_celda_vacia():
    ops, unidades = transformar_equipos(vendidos([
        {"Modelo": "RTK", "Factura s/IVA": 1000},
        {"Modelo": None, "Factura s/IVA": 500},
    ]), PRECIOS)

    assert unidades["modelo"].tolist() == ["RTK", SIN_MODELO]
    assert ops["pendiente_precio"].all()


def test_modelo_se_matchea_sin_importar_mayusculas():
    _, unidades = transformar_equipos(vendidos([{"Modelo": " mavic 3m ,", "Factura s/IVA": 7000}]), PRECIOS)

    assert unidades["modelo"].tolist() == ["Mavic 3M"]
    assert unidades.loc[0, "monto_asignado"] == pytest.approx(7000)


def test_venta_total_incluye_operaciones_sin_precio_de_lista():
    ops, unidades = transformar_equipos(vendidos([
        {"Modelo": "T100", "Factura s/IVA": 40000},
        {"Modelo": "T50, RTK", "Factura s/IVA": 25000},
    ]), PRECIOS)
    u = unificar(transformar_servicios(pd.DataFrame()), ops)

    assert kpis_general(u)["venta_total"] == 65000
    assert kpis_equipos(ops, unidades)["monto"] == 65000
    rm = resumen_por_modelo(unidades).set_index("modelo")
    assert rm["monto_asignado"].sum() == pytest.approx(40000)
    assert rm.loc["T50", "unidades_pendientes"] == 1


def test_kpis_equipos_excluye_devueltos_y_separa_comisiones():
    ops, unidades = transformar_equipos(vendidos([
        {"Modelo": "T100, Mavic 3M", "Factura s/IVA": 50000, "Comisión $": 1000, "Cobrado": "si"},
        {"Modelo": "T55", "Factura s/IVA": 30000, "Comisión $": 600, "Cobrado": "no"},
        {"Modelo": "T100", "Factura s/IVA": 40000, "Comisión $": 800, "Estado": "Devuelto"},
    ]), PRECIOS)
    k = kpis_equipos(ops, unidades)

    assert k["unidades"] == 3
    assert k["monto"] == 80000
    assert k["comision_cobrada"] == 1000
    assert k["comision_por_cobrar"] == 600
    assert k["ops_pendientes"] == 1
    assert k["monto_pendiente"] == 30000
    assert k["ticket_promedio"] == 40000

    rm = resumen_por_modelo(unidades).set_index("modelo")
    assert rm.loc["T100", "unidades"] == 1
    assert rm.loc["T55", "estado_precio"] == "Precio pendiente"
    assert pd.isna(rm.loc["T55", "monto_asignado"])


def test_reporte_unificado():
    crm = pd.DataFrame([
        {"Fecha trabajo": "15/01/2025", "Nombre del cliente": "Juan", "Última acción": "Cobro recibido",
         "Valor total de ventas": "1.500"},
        {"Fecha trabajo": 45700, "Nombre del cliente": "juan ", "Última acción": "Trabajo realizado",
         "Valor total de ventas": 500},
        {"Fecha trabajo": datetime(2025, 2, 1), "Nombre del cliente": "Pedro",
         "Última acción": "Trabajo cancelado", "Valor total de ventas": 9999},
    ])
    servicios = transformar_servicios(crm)
    ops, _ = transformar_equipos(vendidos([{"Modelo": "T100", "Factura s/IVA": 2000, "Cobrado": "si",
                                            "Nombre": "Maria"}]), PRECIOS)
    u = unificar(servicios, ops)

    assert set(u["unidad_negocio"]) == {SERVICIO, EQUIPOS}
    k = kpis_general(u)
    assert k["venta_total"] == 4000
    assert k["pct_cobrado"] == pytest.approx(3500 / 4000)
    assert k["pct_por_cobrar"] == pytest.approx(500 / 4000)
    assert k["clientes"] == 2
    assert k["ticket_promedio"] == pytest.approx(4000 / 3)


# --- Esquema del modelo unificado --------------------------------------------

def test_ventas_unificadas_tiene_esquema_exacto():
    servicios = transformar_servicios(pd.DataFrame([{"Fecha trabajo": 45717, "Nombre del cliente": "Juan",
                                                     "Última acción": "Consulta", "Valor total de ventas": 100}]))
    ops, _ = transformar_equipos(vendidos([{"Modelo": "T100", "Factura s/IVA": 2000}]), PRECIOS)
    u = unificar(servicios, ops)

    assert dtypes(u) == ESQUEMA_UNIFICADO
    assert validar_esquema(u, ESQUEMA_UNIFICADO, DOMINIOS_UNIFICADO) == []


def test_validar_esquema_detecta_dtype_y_valores_raros():
    df = pd.DataFrame({
        "fecha": pd.to_datetime(["2025-01-01"]).as_unit("ns"),
        "cliente": pd.array(["a"], dtype="string"),
        "unidad_negocio": pd.array(["Otra"], dtype="string"),
        "monto": ["10"],
        "estado_cobro": pd.array([COBRADO], dtype="string"),
    })
    problemas = validar_esquema(df, ESQUEMA_UNIFICADO, DOMINIOS_UNIFICADO)

    assert any("monto" in p for p in problemas)
    assert any("Otra" in p for p in problemas)


def test_datos_vacios_no_rompen():
    servicios = transformar_servicios(pd.DataFrame())
    ops, unidades = transformar_equipos(pd.DataFrame(), PRECIOS)
    u = unificar(servicios, ops)

    assert servicios.empty and ops.empty and unidades.empty and u.empty
    assert dtypes(u) == ESQUEMA_UNIFICADO
    assert kpis_general(u)["venta_total"] == 0
    assert kpis_equipos(ops, unidades)["unidades"] == 0
    a = alertas_calidad(pd.DataFrame(), pd.DataFrame(), unidades)
    assert a["fechas_invalidas"].empty and a["montos_cero"].empty


# --- Calidad de datos --------------------------------------------------------

def test_alertas_de_calidad():
    crm = pd.DataFrame({
        "Fecha trabajo": [45717, -611738, 45720, None],
        "Nombre del cliente": ["Juan", "Pedro", "Ana", "Luis"],
        "Última acción": ["Cobro recibido", "Consulta", "Trabajo realizado", "Consulta"],
        "Valor total de ventas": [100, 50, None, 0],
    }, index=range(2, 6))
    ventas = vendidos([{"Modelo": "T100, T50", "Factura s/IVA": 1000}])
    _, unidades = transformar_equipos(ventas, PRECIOS)

    a = alertas_calidad(crm, ventas, unidades)

    assert "Id Cliente" in a["columnas_faltantes"]["CRM"]
    assert not any("Factura" in c for c in a["columnas_faltantes"]["Ventas"])
    fi = a["fechas_invalidas"]
    assert fi[["columna", "fila_sheet", "leido_como"]].values.tolist() == [["Fecha trabajo", 3, "0225-02-11"]]
    assert a["montos_cero"]["fila_sheet"].tolist() == [4]
    assert a["montos_cero"].loc[0, "valor_crudo"] == "(vacío)"
    assert a["modelos_sin_precio"]["modelo"].tolist() == ["T50"]


def test_perfil_columnas():
    df = pd.DataFrame({" Id Cliente": [123, "A-7", None, 123], "Notas": ["", None, "x", "y"]})
    p = perfil_columnas(df, COLUMNAS_CRM).set_index("columna")

    fila = p.loc["' Id Cliente'"]
    assert fila["pct_nulos"] == 0.25
    assert fila["unicos"] == 2
    assert fila["tipos_python"] == "int (2), str (1)"
    assert fila["ejemplos"] == "123 | 'A-7'"
    assert fila["usada_como"] == "id_cliente"
    assert p.loc["'Notas'", "pct_nulos"] == 0.5
    assert p.loc["'Notas'", "usada_como"] == ""


# --- B) Operadores -----------------------------------------------------------

def crm_con_operadores():
    # Fila 2: el ejemplo real (trabajo de 80 has: Guido 40, Nicolas 80, Matias 80, Franco 13).
    # Fila 3: par 5 con header "Has 5" y otra grafia de Guido, sin has cargadas.
    # Fila 4: Guido solo; el operador 5 esta en blanco y se descarta.
    return pd.DataFrame({
        "Fecha trabajo": [45717, 45748, 45778],
        "Nombre del cliente": ["Juan", "Pedro", "Ana"],
        "Trabajo": ["Herbicida", "Siembra", "Mapeo"],
        "Última acción": ["Cobro recibido", "Trabajo realizado", "Consulta"],
        "Has trabajadas": [80, 50, 10],
        "Operador 1": ["Guido galetto", "Nicolas", "Guido galetto"],
        "Has1": [40, 50, 10],
        "Operador 2": ["Nicolas", None, None],
        "Has2": [80, None, None],
        "Operador 3": ["Matias", None, None],
        "Has3": [80, None, None],
        "Operador 4": ["Franco", None, None],
        "Has4": [13, None, None],
        "Operador 5": [None, "Guido Galetto", "  "],
        "Has 5": [None, None, None],
    }, index=range(2, 5))


def test_pares_de_operador_se_detectan_dinamicamente():
    pares = pares_operador(crm_con_operadores())
    assert [(n, op, has) for n, op, has in pares] == [
        (1, "Operador 1", "Has1"), (2, "Operador 2", "Has2"), (3, "Operador 3", "Has3"),
        (4, "Operador 4", "Has4"), (5, "Operador 5", "Has 5"),
    ]


def test_despivotar_operadores():
    largo = despivotar_operadores(crm_con_operadores())

    assert list(largo.columns) == COLUMNAS_OPERADORES
    assert len(largo) == 7
    assert set(largo["operador"]) == {"Guido galetto", "Nicolas", "Matias", "Franco"}

    trabajo = largo[largo["fila_sheet"] == 2].set_index("operador")
    assert trabajo["has_operador"].to_dict() == {"Guido galetto": 40, "Nicolas": 80, "Matias": 80, "Franco": 13}
    assert (trabajo["has_totales_trabajo"] == 80).all()
    assert (trabajo["cantidad_operadores_en_trabajo"] == 4).all()

    guido_sin_has = largo[(largo["fila_sheet"] == 3) & (largo["operador"] == "Guido galetto")].iloc[0]
    assert pd.isna(guido_sin_has["has_operador"])
    assert guido_sin_has["cantidad_operadores_en_trabajo"] == 2


def test_resumen_operadores_solo_vs_acompanado():
    r = resumen_operadores(despivotar_operadores(crm_con_operadores())).set_index("operador")

    assert list(r.index) == ["Nicolas", "Matias", "Guido galetto", "Franco"]
    guido = r.loc["Guido galetto"]
    assert guido["has"] == 50
    assert (guido["trabajos"], guido["trabajos_solo"], guido["trabajos_acompanado"]) == (3, 1, 2)
    assert guido["pct_solo"] == pytest.approx(1 / 3)
    assert guido["pct_acompanado"] == pytest.approx(2 / 3)
    assert (r.loc["Nicolas", "has"], r.loc["Nicolas", "trabajos_solo"]) == (130, 0)


def test_despivotar_sin_columnas_de_operador_no_rompe():
    largo = despivotar_operadores(pd.DataFrame({"Nombre del cliente": ["x"]}))
    assert largo.empty and list(largo.columns) == COLUMNAS_OPERADORES
    assert resumen_operadores(largo).empty


# --- A) Estado del trabajo ---------------------------------------------------

def test_filtro_estado_trabajo_ignora_tildes_y_mayusculas():
    s = transformar_servicios(pd.DataFrame({
        "Fecha trabajo": [45717] * 5,
        "Nombre del cliente": list("abcde"),
        "Última acción": ["Cobro recibido", "Trabajo Cancelado", "Envio de presupuesto", None, "Algo nuevo"],
        "Valor total de ventas": [100, 200, 300, 400, 500],
    }))

    assert filtrar_por_estado_trabajo(s, ESTADOS_TRABAJO_EJECUTADO)["monto"].tolist() == [100]
    assert filtrar_por_estado_trabajo(s, ["Trabajo cancelado", "Envío de presupuesto"])["monto"].tolist() == [200, 300]
    assert filtrar_por_estado_trabajo(s, [SIN_ESTADO])["monto"].tolist() == [400]
    assert len(filtrar_por_estado_trabajo(s, None)) == 5
    assert filtrar_por_estado_trabajo(s, []).empty

    opciones = opciones_estado_trabajo(s)
    assert opciones[:len(ESTADOS_TRABAJO)] == ESTADOS_TRABAJO
    assert opciones[len(ESTADOS_TRABAJO):] == ["Algo nuevo", SIN_ESTADO]

    solo_cancelados = filtrar_por_estado_trabajo(s, ["Trabajo Cancelado"])
    assert kpis_servicios(solo_cancelados, solo_vigentes=False)["ventas"] == 200
    assert kpis_servicios(solo_cancelados)["ventas"] == 0


def test_aplicar_filtros_afecta_servicios_operadores_y_unificado():
    crm = crm_con_operadores().assign(**{"Valor total de ventas": [1000, 500, 50]})
    ventas = vendidos([{"Modelo": "T100", "Factura s/IVA": 40000, "Comisión $": 6000}])
    datos = construir_datos(crm, ventas, tuple(sorted(PRECIOS.items())))

    out = aplicar_filtros(datos, None, None, ["Cobro recibido"])

    assert out["servicios"]["monto"].tolist() == [1000]
    assert set(out["operadores"]["fila_sheet"]) == {2}
    unif = out["ventas_unificadas"]
    assert unif.loc[unif["unidad_negocio"] == SERVICIO, "monto"].tolist() == [1000]
    assert unif.loc[unif["unidad_negocio"] == EQUIPOS, "monto"].tolist() == [40000]
    assert len(datos["servicios"]) == 3  # el original no se modifica


# --- E/F/G) Ingreso real consolidado -----------------------------------------

def test_ingreso_real_usa_comision_y_no_facturado():
    servicios = transformar_servicios(pd.DataFrame({
        "Fecha trabajo": [45717, 45748],  # 01/03/2025 y 01/04/2025
        "Nombre del cliente": ["a", "b"],
        "Última acción": ["Cobro recibido", "Cobro recibido"],
        "Valor total de ventas": [1000, 500],
        "Has trabajadas": [100, 20],
    }))
    ops, _ = transformar_equipos(vendidos([
        {"Modelo": "T100", "Factura s/IVA": 40000, "Comisión $": 6000, "Cobrado": "si",
         "Fecha venta": datetime(2025, 3, 15)},
        {"Modelo": "T70", "Factura s/IVA": 30000, "Comisión $": 4500, "Fecha venta": datetime(2025, 5, 2)},
        {"Modelo": "T100", "Factura s/IVA": 40000, "Comisión $": 6000, "Estado": "Devuelto",
         "Fecha venta": datetime(2025, 5, 3)},
    ]), PRECIOS)

    k = kpis_consolidado(servicios, ops)
    assert (k["ventas_servicios"], k["comision_cobrada"], k["comision_por_cobrar"]) == (1500, 6000, 4500)
    assert (k["comision_total"], k["ingreso_total"], k["facturado_equipos"], k["hectareas"]) == (10500, 12000, 70000, 120)
    assert k["pct_servicios"] == pytest.approx(1500 / 12000)

    m = ingresos_por_periodo(servicios, ops, "Mensual")
    assert m["periodo_label"].tolist() == ["03/2025", "04/2025", "05/2025"]
    assert m["ingreso_servicios"].tolist() == [1000, 500, 0]
    assert m["ingreso_equipos"].tolist() == [6000, 0, 4500]
    assert m["has_trabajadas"].tolist() == [100, 20, 0]
    assert m["pct_equipos"].tolist() == pytest.approx([6 / 7, 0, 1])

    q = ingresos_por_periodo(servicios, ops, "Trimestral")
    assert q["periodo_label"].tolist() == ["T1 2025", "T2 2025"]
    assert q["total"].tolist() == [7000, 5000]

    a = ingresos_por_periodo(servicios, ops, "Anual")
    assert (a["periodo_label"].tolist(), a["total"].tolist()) == (["2025"], [12000])

    vacio = ingresos_por_periodo(transformar_servicios(pd.DataFrame()), transformar_equipos(pd.DataFrame(), PRECIOS)[0])
    assert vacio.empty


# --- D) Unidades -------------------------------------------------------------

def test_modelo_repetido_en_la_celda_cuenta_dos_unidades():
    ops, unidades = transformar_equipos(vendidos([{"Modelo": "T100, T100, Mavic 3M", "Factura s/IVA": 91500}]), PRECIOS)

    assert ops.loc[0, "unidades"] == 3
    assert unidades["modelo"].tolist() == ["T100", "T100", "Mavic 3M"]
    assert unidades["monto_asignado"].tolist() == pytest.approx([42000, 42000, 7500])
    assert resumen_por_modelo(unidades).set_index("modelo").loc["T100", "unidades"] == 2


# --- Exportacion PDF ---------------------------------------------------------

def _png_chico():
    import io
    from PIL import Image as ImagenPIL
    buffer = io.BytesIO()
    ImagenPIL.new("RGB", (4, 2), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _datos_para_pdf():
    crm = crm_con_operadores().assign(**{"Valor total de ventas": [1000, 500, 50]})
    ventas = vendidos([{"Modelo": "T100, T50", "Factura s/IVA": 40000, "Comisión $": 6000, "Cobrado": "si",
                        "Fecha venta": datetime(2025, 3, 10)}])
    datos = construir_datos(crm, ventas, tuple(sorted(PRECIOS.items())))
    return aplicar_filtros(datos, None, None, ESTADOS_TRABAJO_EJECUTADO)


def _paginas_pdf(pdf: bytes) -> int:
    import re
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def test_generar_pdf_arma_las_cuatro_paginas(monkeypatch):
    import utils.pdf as pdf_mod

    exportadas = {}

    def exportar_falso(figuras):
        exportadas.update(figuras)
        return {nombre: _png_chico() for nombre in figuras}

    monkeypatch.setattr(pdf_mod, "_exportar_png", exportar_falso)
    filtros = {"desde": date(2025, 1, 1), "hasta": date(2025, 12, 31), "estados_trabajo": ESTADOS_TRABAJO_EJECUTADO,
               "estados_opciones": ESTADOS_TRABAJO, "operadores": ["Nicolas"], "granularidad": "Trimestral",
               "generado": datetime(2026, 9, 13, 18, 30)}

    pdf = pdf_mod.generar_pdf(_datos_para_pdf(), filtros)

    assert pdf.startswith(b"%PDF")
    # General, Equipos, Servicios y Resumen de cobros
    assert _paginas_pdf(pdf) == 4
    assert {"general_evolucion", "servicios_has_operador", "equipos_unidades",
            "cobros_estado", "cobros_evolucion"} <= set(exportadas)


def test_generar_pdf_sin_datos_no_rompe(monkeypatch):
    import utils.pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "_exportar_png", lambda figuras: {n: _png_chico() for n in figuras})
    datos = aplicar_filtros(construir_datos(pd.DataFrame(), pd.DataFrame(), ()), None, None, [])

    pdf = pdf_mod.generar_pdf(datos, {"estados_trabajo": []})

    assert pdf.startswith(b"%PDF") and _paginas_pdf(pdf) == 4


def test_pdf_error_claro_si_no_esta_kaleido(monkeypatch):
    import sys
    import utils.pdf as pdf_mod

    monkeypatch.setitem(sys.modules, "kaleido", None)
    with pytest.raises(pdf_mod.ErrorExportacionPDF, match="pip install"):
        pdf_mod._exportar_png({"x": (None, 1, 1)})


def test_pdf_error_claro_si_kaleido_no_encuentra_chrome(monkeypatch):
    import sys
    import types
    import utils.pdf as pdf_mod

    def sin_chrome(**_):
        raise RuntimeError("ChromeNotFoundError")

    monkeypatch.setitem(sys.modules, "kaleido", types.SimpleNamespace(
        start_sync_server=sin_chrome, stop_sync_server=lambda **_: None, calc_fig_sync=None))
    with pytest.raises(pdf_mod.ErrorExportacionPDF, match="Chrome"):
        pdf_mod._exportar_png({"x": (None, 1, 1)})


def test_textos_del_encabezado_pdf():
    from utils.pdf import describir_estados, describir_periodo, nombre_archivo

    filtros = {"desde": date(2025, 1, 5), "hasta": date(2025, 2, 1),
               "estados_trabajo": ESTADOS_TRABAJO, "estados_opciones": ESTADOS_TRABAJO}
    assert describir_periodo(filtros) == "05/01/2025 a 01/02/2025"
    assert describir_estados(filtros) == "todos"
    assert describir_estados({**filtros, "estados_trabajo": ["Consulta"]}) == "Consulta"
    assert describir_periodo({}) == "todo el historial"
    assert nombre_archivo(filtros) == "Agropix_reporte_2025-01-05_a_2025-02-01.pdf"


def test_precios_ida_y_vuelta(tmp_path):
    path = tmp_path / "precios.json"
    guardar_precios({"T100": 42000.0, "T50": None}, path)
    assert cargar_precios(path) == {"T100": 42000.0, "T50": None}


# ---------------------------------------------------------------------------
# Precios de lista: persistencia en Cloud
# ---------------------------------------------------------------------------
def test_los_precios_de_secrets_pisan_al_archivo(tmp_path, monkeypatch):
    """En Cloud el archivo se borra al reiniciar: los secrets son lo unico que queda."""
    archivo = tmp_path / "precios.json"
    archivo.write_text('{"T100": 42000, "T50": null, "T70": 35000}', encoding="utf-8")
    monkeypatch.setattr("utils.data.precios_de_secrets",
                        lambda: {"T50": 26000, "T100": 43500})

    precios = cargar_precios(archivo)
    assert precios["T50"] == 26000.0, "el precio que faltaba entra desde los secrets"
    assert precios["T100"] == 43500.0, "los secrets le ganan al archivo"
    assert precios["T70"] == 35000.0, "lo que no esta en secrets sigue saliendo del archivo"


def test_sin_secrets_los_precios_salen_del_archivo(tmp_path, monkeypatch):
    archivo = tmp_path / "precios.json"
    archivo.write_text('{"T100": 42000}', encoding="utf-8")
    monkeypatch.setattr("utils.data.precios_de_secrets", lambda: {})
    assert cargar_precios(archivo) == {"T100": 42000.0}


def test_sin_archivo_pero_con_secrets_igual_hay_precios(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.data.precios_de_secrets", lambda: {"T55": 32000})
    assert cargar_precios(tmp_path / "no_existe.json") == {"T55": 32000.0}


def test_un_precio_invalido_en_secrets_queda_como_pendiente(tmp_path, monkeypatch):
    archivo = tmp_path / "precios.json"
    archivo.write_text('{"T100": 42000}', encoding="utf-8")
    monkeypatch.setattr("utils.data.precios_de_secrets",
                        lambda: {"T100": 0, "T70": -5, "T50": "cuarenta mil"})
    precios = cargar_precios(archivo)
    assert precios["T100"] is None and precios["T70"] is None and precios["T50"] is None
