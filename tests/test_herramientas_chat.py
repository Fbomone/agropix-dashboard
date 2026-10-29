"""Herramientas del Asistente IA: mismos numeros que el dashboard, sin red."""
import json
from datetime import date

import pandas as pd
import pytest

from utils import comisiones as cm
from utils import herramientas_chat as hc
from utils.data import ESTADOS_TRABAJO_EJECUTADO, aplicar_filtros, construir_datos

PRECIOS = {"T100": 30000, "Mavic 3M": 5000}  # T50 y RTK sin precio a proposito


def crm_crudo() -> pd.DataFrame:
    filas = [
        # fecha, cliente, servicio, cultivo, ultima accion, has, monto, operadores
        ("10/03/2025", "Estancia La Peña", "Pulverización", "Soja", "Cobro recibido", 100, 1000, ("Guido", 100), None),
        ("20/03/2025", "Juan Pérez", "Fumigación", "Maíz", "Facturado esperando cobro", 50, 600,
         ("Guido", 50), ("Nico", 50)),
        ("05/06/2025", "estancia la pena", "Pulverización", "Trigo", "Trabajo realizado", 30, 300, ("Nico", 30), None),
        ("15/11/2024", "Agro Sur", "Pulverización", "Soja", "Cobro recibido", 80, 900, ("Guido", 80), None),
        ("01/07/2025", "Agro Sur", "Fumigación", "Maíz", "Trabajo Cancelado", 20, 200, None, None),
        ("01/08/2025", "Juana Pereyra", "Fumigación", "Soja", "Envio de presupuesto", 10, 100, None, None),
    ]
    registros = []
    for i, (fecha, cliente, servicio, cultivo, accion, has, monto, op1, op2) in enumerate(filas):
        registros.append({
            "Fecha trabajo": fecha, "Fecha de contacto": "", "ID Orden de trabajo": f"OT-{i + 1}",
            "Nombre del cliente": cliente, "Id Cliente": i + 1, "Producto/servicio de interés": servicio,
            "Trabajo": servicio, "Cultivo": cultivo, "Última acción": accion, "Has trabajadas": has,
            "Valor por ha USD": 10, "Valor total de ventas": monto,
            "Operador 1": op1[0] if op1 else "", "Has1": op1[1] if op1 else "",
            "Operador 2": op2[0] if op2 else "", "Has2": op2[1] if op2 else "",
        })
    return pd.DataFrame(registros, index=range(2, 2 + len(registros)))


def ventas_crudo() -> pd.DataFrame:
    filas = [
        # fecha, cliente, modelos, canal, estado, vendedor, factura, comision, cobrado
        ("15/04/2025", "Juan Pérez", "T50, Mavic 3M", "Instagram", "Entregado", "Matías", 20000, 1500, "Sí"),
        ("10/09/2025", "Agro Sur", "T100", "Referido", "Entregado", "Fabio", 30000, 2000, "No"),
        ("01/12/2024", "Campo Norte", "RTK", "", "Entregado", "Matías", 3000, 200, "Sí"),
        ("05/10/2025", "Juan Pérez", "Mavic 3M", "Instagram", "Devuelto", "Fabio", 5000, 400, "No"),
    ]
    registros = [{
        "Fecha venta": f, "Fecha de entrega": "", "Nombre": c, "ID": i + 1, "Modelo": m, "Condición": "",
        "Origen del leas": canal, "Forma de pago": "", "Estado": estado, "Proveedor": "DJI", "Vendedor": vend,
        "Factura s/IVA": fac, "Comisión $": com, "Cobrado": cob,
    } for i, (f, c, m, canal, estado, vend, fac, com, cob) in enumerate(filas)]
    return pd.DataFrame(registros, index=range(2, 2 + len(registros)))


@pytest.fixture
def completos():
    return construir_datos(crm_crudo(), ventas_crudo(), tuple(sorted(PRECIOS.items())))


@pytest.fixture
def datos(completos):
    """Lo que ve el usuario con los filtros por defecto (todo el rango)."""
    return aplicar_filtros(completos, None, None, ESTADOS_TRABAJO_EJECUTADO)


@pytest.fixture
def contexto(completos, datos):
    return {"datos": datos, "datos_completos": completos, "estados_trabajo": ESTADOS_TRABAJO_EJECUTADO,
            "desde": date(2024, 11, 15), "hasta": date(2025, 10, 5)}


@pytest.fixture
def contexto_vacio():
    vacio = construir_datos(pd.DataFrame(), pd.DataFrame(), ())
    filtrado = aplicar_filtros(vacio, None, None, ESTADOS_TRABAJO_EJECUTADO)
    return {"datos": filtrado, "datos_completos": vacio, "estados_trabajo": ESTADOS_TRABAJO_EJECUTADO}


ARGS_VALIDOS = {
    "kpis_generales": {},
    "ingresos_por_periodo": {"granularidad": "Mensual"},
    "top_clientes": {"n": 5},
    "ranking_vendedores": {},
    "comisiones_por_canal": {},
    "equipos_por_modelo": {"solo_principales": False},
    "resumen_servicios": {"agrupar_por": "cultivo"},
    "pendientes_de_cobro": {},
    "buscar_cliente": {"nombre": "agro sur"},
    "resumen_operadores": {},
    "calidad_de_datos": {},
}


# ---------------------------------------------------------------------------
# Esquemas
# ---------------------------------------------------------------------------

def test_cada_esquema_tiene_su_funcion_y_viceversa():
    nombres = [h["function"]["name"] for h in hc.HERRAMIENTAS]
    assert len(nombres) == len(set(nombres))
    assert set(nombres) == set(hc.FUNCIONES)
    assert set(ARGS_VALIDOS) == set(hc.FUNCIONES)


def test_los_esquemas_tienen_formato_openai_y_descripcion_de_uso():
    for h in hc.HERRAMIENTAS:
        assert h["type"] == "function"
        f = h["function"]
        assert "Usar para" in f["description"]
        assert f["parameters"]["type"] == "object"
        assert set(f["parameters"]["required"]) <= set(f["parameters"]["properties"])
    json.dumps(hc.HERRAMIENTAS)


# ---------------------------------------------------------------------------
# Consistencia con el dashboard
# ---------------------------------------------------------------------------

def test_kpis_generales_son_los_de_kpis_comisiones(datos, contexto):
    esperado = cm.kpis_comisiones(datos["servicios"], datos["equipos"])
    directo = hc.kpis_generales(datos)
    for clave in hc.CLAVES_KPIS:
        assert directo[clave] == esperado[clave]

    via_chat = hc.ejecutar("kpis_generales", {}, contexto)
    assert via_chat["ingresos"] == round(esperado["ingresos"], 2)
    assert via_chat["pct_cobranza"] == round(esperado["pct_cobranza"], 4)
    # servicios 1000+600+300+900 (sin cancelado ni presupuesto) + comision 1500+2000+200 (sin devuelto)
    assert via_chat["ingresos"] == 2800 + 3700


def test_top_clientes_es_comisiones_top_clientes(datos, contexto):
    esperado = cm.top_clientes(datos["servicios"], datos["equipos"], top=3)
    r = hc.ejecutar("top_clientes", {"n": 3}, contexto)
    assert [f["cliente"] for f in r["filas"]] == esperado["cliente"].tolist()
    assert [f["ingreso"] for f in r["filas"]] == [round(v, 2) for v in esperado["ingreso"]]


def test_ranking_vendedores_es_el_de_comisiones(datos, contexto):
    esperado = cm.ranking_vendedores(datos["equipos"])
    r = hc.ejecutar("ranking_vendedores", {}, contexto)
    assert [f["vendedor"] for f in r["filas"]] == esperado["vendedor"].tolist()
    assert [f["comision_cobrada"] for f in r["filas"]] == [round(v, 2) for v in esperado["comision_cobrada"]]


def test_equipos_por_modelo_incluye_la_cobertura(datos, contexto):
    esperado = cm.equipos_por_modelo(datos["unidades"], True)
    r = hc.ejecutar("equipos_por_modelo", {}, contexto)
    assert [f["modelo"] for f in r["filas"]] == esperado["modelo"].tolist()
    assert [f["unidades"] for f in r["filas"]] == esperado["unidades"].tolist()
    assert r["cobertura"] == hc._limpio(cm.cobertura_atribucion(datos["unidades"]))
    assert r["cobertura_completa"] is False
    assert "T50" in r["cobertura"]["modelos_sin_precio"]


def test_pendientes_de_cobro_por_cliente(contexto):
    r = hc.ejecutar("pendientes_de_cobro", {}, contexto)
    # Agro Sur: comision 2000 no cobrada; Juan Perez: servicio facturado 600; Estancia: realizado 300
    assert r["total_pendiente"] == 2900
    assert r["filas"][0] == {"cliente": "Agro Sur", "servicios_pendiente": 0.0,
                             "comision_pendiente": 2000.0, "total_pendiente": 2000.0}
    # el equipo devuelto de Juan Perez no suma
    juan = next(f for f in r["filas"] if f["cliente"] == "Juan Pérez")
    assert juan["total_pendiente"] == 600


def test_resumen_servicios_agrupa_por_cultivo(datos, contexto):
    r = hc.ejecutar("resumen_servicios", {"agrupar_por": "cultivo"}, contexto)
    assert r["kpis"]["ventas"] == 2800
    soja = next(f for f in r["filas"] if f["cultivo"] == "Soja")
    assert soja == {"cultivo": "Soja", "cantidad": 2, "hectareas": 180.0, "monto": 1900.0}


def test_resumen_operadores(contexto):
    r = hc.ejecutar("resumen_operadores", {}, contexto)
    guido = next(f for f in r["filas"] if f["operador"] == "Guido")
    assert guido["has"] == 230 and guido["trabajos"] == 3 and guido["trabajos_acompanado"] == 1


def test_calidad_de_datos_no_manda_filas(contexto):
    r = hc.ejecutar("calidad_de_datos", {}, contexto)
    assert {"modelo": "T50", "unidades": 1} in r["modelos_sin_precio"]
    texto = json.dumps(r, ensure_ascii=False)
    for cliente in ("Juan Pérez", "Agro Sur", "Campo Norte", "Estancia"):
        assert cliente not in texto


# ---------------------------------------------------------------------------
# Periodo
# ---------------------------------------------------------------------------

def test_sin_fechas_usa_lo_que_ve_el_usuario(contexto):
    r = hc.ejecutar("kpis_generales", {}, contexto)
    assert r["periodo"]["desde"] == "2024-11-15" and r["periodo"]["hasta"] == "2025-10-05"


def test_con_fechas_filtra_los_datos_completos(completos, contexto):
    r = hc.ejecutar("kpis_generales", {"desde": "2025-01-01", "hasta": "2025-12-31"}, contexto)
    esperado = aplicar_filtros(completos, date(2025, 1, 1), date(2025, 12, 31), ESTADOS_TRABAJO_EJECUTADO)
    k = cm.kpis_comisiones(esperado["servicios"], esperado["equipos"])
    assert r["ingresos"] == round(k["ingresos"], 2)
    # sin el servicio de Agro Sur de 2024 (900) ni el RTK de 2024 (200)
    assert r["ingresos"] == 6500 - 900 - 200
    assert r["periodo"]["desde"] == "2025-01-01" and r["periodo"]["hasta"] == "2025-12-31"


def test_el_filtro_por_fecha_respeta_los_estados_seleccionados(contexto):
    contexto["estados_trabajo"] = ["Cobro recibido"]
    r = hc.ejecutar("kpis_generales", {"desde": "2025-01-01", "hasta": "2025-12-31"}, contexto)
    assert r["generado_servicios"] == 1000


def test_solo_desde_completa_hasta_con_el_ultimo_dato(contexto):
    r = hc.ejecutar("kpis_generales", {"desde": "2025-09-01"}, contexto)
    assert r["periodo"]["hasta"] == "2025-10-05"
    assert r["ingresos"] == 2000


def test_top_clientes_de_un_anio(contexto):
    r = hc.ejecutar("top_clientes", {"n": 1, "desde": "2024-01-01", "hasta": "2024-12-31"}, contexto)
    assert r["filas"] == [{"cliente": "Agro Sur", "servicios": 900.0, "equipos": 0.0, "ingreso": 900.0}]


def test_periodo_sin_movimientos_da_sin_datos(contexto):
    for nombre in hc.FUNCIONES:
        if nombre == "calidad_de_datos":
            continue
        args = {**ARGS_VALIDOS[nombre]}
        if nombre != "buscar_cliente":
            args.update(desde="2016-01-01", hasta="2016-01-31")
            r = hc.ejecutar(nombre, args, contexto)
            assert r.get("sin_datos") is True, nombre
            assert "periodo" in r


# ---------------------------------------------------------------------------
# Datos vacios y argumentos invalidos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", sorted(hc.FUNCIONES))
def test_datos_vacios_no_explotan(nombre, contexto_vacio):
    r = hc.ejecutar(nombre, ARGS_VALIDOS[nombre], contexto_vacio)
    assert "error" not in r
    assert "periodo" in r
    if nombre != "calidad_de_datos":
        assert r["sin_datos"] is True
    json.dumps(r)


@pytest.mark.parametrize("nombre, args", [
    ("kpis_generales", {"desde": "31/12/2025"}),
    ("kpis_generales", {"desde": "2025-13-01"}),
    ("kpis_generales", {"desde": "2025-12-01", "hasta": "2025-01-01"}),
    ("top_clientes", {"n": 100}),
    ("top_clientes", {"n": 0}),
    ("top_clientes", {"n": "cinco"}),
    ("top_clientes", {"n": True}),
    ("ingresos_por_periodo", {"granularidad": "Diaria"}),
    ("resumen_servicios", {"agrupar_por": "vendedor"}),
    ("equipos_por_modelo", {"solo_principales": "si"}),
    ("buscar_cliente", {}),
    ("buscar_cliente", {"nombre": "   "}),
    ("no_existe", {}),
])
def test_argumentos_invalidos_devuelven_error(nombre, args, contexto):
    r = hc.ejecutar(nombre, args, contexto)
    assert set(r) == {"error"}
    assert r["error"]


def test_acepta_argumentos_como_string_json(contexto):
    assert hc.ejecutar("top_clientes", '{"n": 2}', contexto)["filas"]
    assert hc.ejecutar("kpis_generales", "", contexto)["ingresos"]
    assert "error" in hc.ejecutar("top_clientes", "{n: 2", contexto)


def test_granularidad_ignora_mayusculas(contexto):
    r = hc.ejecutar("ingresos_por_periodo", {"granularidad": "anual"}, contexto)
    assert r["granularidad"] == "Anual"
    assert [f["periodo_label"] for f in r["filas"]] == ["2024", "2025"]


def test_un_error_de_calculo_se_devuelve_como_error(contexto, monkeypatch):
    def rompe(_datos):
        raise KeyError("columna")
    monkeypatch.setitem(hc.FUNCIONES, "kpis_generales", rompe)
    assert set(hc.ejecutar("kpis_generales", {}, contexto)) == {"error"}


# ---------------------------------------------------------------------------
# Forma de los resultados
# ---------------------------------------------------------------------------

def test_todo_resultado_es_json_y_las_listas_son_cortas(contexto):
    for nombre, args in ARGS_VALIDOS.items():
        r = hc.ejecutar(nombre, args, contexto)
        assert "error" not in r, nombre
        json.dumps(r)
        _listas_cortas(r)


def _listas_cortas(valor):
    if isinstance(valor, dict):
        for v in valor.values():
            _listas_cortas(v)
    elif isinstance(valor, list):
        assert len(valor) <= hc.MAX_FILAS
        for v in valor:
            _listas_cortas(v)


def test_las_listas_se_recortan_a_15(contexto, monkeypatch):
    muchos = pd.DataFrame({"cliente": [f"C{i}" for i in range(40)], "servicios": 1.0,
                           "equipos": 0.0, "ingreso": 1.0})
    monkeypatch.setattr(cm, "top_clientes", lambda *_a, **_k: muchos)
    assert len(hc.ejecutar("top_clientes", {"n": 15}, contexto)["filas"]) == 15


def test_ingresos_por_periodo_muestra_los_ultimos_15(completos):
    servicios = pd.concat([completos["servicios"].iloc[[0]]] * 30, ignore_index=True)
    servicios["fecha"] = pd.date_range("2023-01-01", periods=30, freq="MS")
    datos = {**completos, "servicios": servicios, "equipos": completos["equipos"].iloc[0:0]}
    r = hc.ingresos_por_periodo(datos, "Mensual")
    assert r["periodos_totales"] == 30
    assert len(r["filas"]) == 15
    assert r["filas"][-1]["periodo_label"] == "06/2025"


def test_montos_redondeados(contexto, monkeypatch):
    monkeypatch.setitem(hc.FUNCIONES, "kpis_generales",
                        lambda _d: {"ingresos": 1234.5678, "pct_cobranza": 0.123456})
    r = hc.ejecutar("kpis_generales", {}, contexto)
    assert r["ingresos"] == 1234.57 and r["pct_cobranza"] == 0.1235


def copia_profunda(datos: dict) -> dict:
    import copy
    return {k: v.copy(deep=True) if isinstance(v, pd.DataFrame) else copy.deepcopy(v) for k, v in datos.items()}


def assert_datos_iguales(antes: dict, despues: dict):
    assert antes.keys() == despues.keys()
    for clave, valor in antes.items():
        if isinstance(valor, pd.DataFrame):
            pd.testing.assert_frame_equal(despues[clave], valor, obj=clave)
        elif clave == "calidad":
            for tipo, v in valor.items():
                if isinstance(v, pd.DataFrame):
                    pd.testing.assert_frame_equal(despues[clave][tipo], v, obj=tipo)
                else:
                    assert despues[clave][tipo] == v


def test_las_herramientas_no_modifican_los_datos(contexto, completos, datos):
    """El chat solo lee: lo que muestran los reportes queda intacto."""
    antes_datos, antes_completos = copia_profunda(datos), copia_profunda(completos)
    for nombre, args in ARGS_VALIDOS.items():
        hc.ejecutar(nombre, args, contexto)
        hc.ejecutar(nombre, {**args, "desde": "2025-01-01", "hasta": "2025-06-30"}, contexto)
    assert_datos_iguales(antes_datos, datos)
    assert_datos_iguales(antes_completos, completos)
    assert contexto["datos"] is datos and contexto["datos_completos"] is completos


# ---------------------------------------------------------------------------
# buscar_cliente
# ---------------------------------------------------------------------------

def test_buscar_cliente_ignora_tildes_y_mayusculas(contexto):
    r = hc.ejecutar("buscar_cliente", {"nombre": "JUAN PEREZ"}, contexto)
    assert r["cliente"] == "Juan Pérez"
    assert r["trabajos"] == 1 and r["monto_servicios"] == 600
    assert r["equipos_comprados"] == 2  # T50 + Mavic; la devolucion no cuenta
    assert r["comision_equipos"] == 1500
    assert r["pendiente_total"] == 600


def test_buscar_cliente_junta_grafias_distintas(contexto):
    r = hc.ejecutar("buscar_cliente", {"nombre": "estancia la peña"}, contexto)
    assert r["trabajos"] == 2 and r["hectareas"] == 130


def test_buscar_cliente_ambiguo_devuelve_candidatos(contexto, completos):
    contexto["datos"] = aplicar_filtros(completos, None, None, None)  # incluye a Juana Pereyra
    r = hc.ejecutar("buscar_cliente", {"nombre": "jua"}, contexto)
    assert r["ambiguo"] is True
    assert r["coincidencias"] == ["Juan Pérez", "Juana Pereyra"]


def test_buscar_cliente_inexistente(contexto):
    r = hc.ejecutar("buscar_cliente", {"nombre": "Nadie"}, contexto)
    assert r["sin_datos"] is True
