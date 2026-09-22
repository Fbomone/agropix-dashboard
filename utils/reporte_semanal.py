"""Reporte semanal de Agropix: periodo, KPIs y cuerpo del mail.

Se ejecuta fuera de Streamlit, desde scripts/enviar_reporte_semanal.py, que a su
vez corre en GitHub Actions los viernes 18:00 ART. Aca va solo la logica pura
(que semana, que numeros, que texto); el envio y el armado del PDF van aparte.

Por que GitHub Actions y no `schedule` + thread dentro de la app
---------------------------------------------------------------
Streamlit Community Cloud duerme la app cuando nadie la visita y mata el
proceso. Un scheduler en un thread de la app se muere con ella y no se despierta
solo, asi que los viernes sin visitas el mail no saldria. El cron de Actions
corre en la infraestructura de GitHub, no depende de que la app este viva.

Zona horaria
------------
Argentina usa UTC-3 todo el año (no mueve los relojes desde 2009), asi que
18:00 ART son 21:00 UTC de forma estable. Igual el periodo se calcula con
zoneinfo y no con offsets a mano.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from config.settings import REPORTE_AMBOS_VIERNES, URL_APP
from utils.comisiones import kpis_comisiones, top_clientes

TZ_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")

# ---------------------------------------------------------------------------
# Destinatarios: UNA sola fuente, compartida por el mail, el CLI y la pestania
# Administracion de la app. Cambiar la lista aca la cambia en los tres lados.
# ---------------------------------------------------------------------------
DESTINATARIOS = (
    "francobomone14@gmail.com",     # Franco
    "matias21tossen@gmail.com",     # Matias
    "ggaletto.gg@gmail.com",        # Guido
    "ignacio.ramello879@gmail.com", # Ignacio
    "nicotobaldi55@gmail.com",      # Luciano
    "fabiocailletbois@gmail.com",   # Fabio
)

# Tres circulos concentricos, de menor a mayor alcance. La idea es probar
# siempre en el mas chico antes de pasar al siguiente.
DESTINATARIOS_DESARROLLO = (
    "francobomone14@gmail.com",     # Franco y nadie mas: para probar cualquier cosa
)

DESTINATARIOS_PRUEBA = (
    "francobomone14@gmail.com",     # Franco
    "matias21tossen@gmail.com",     # Matias
)

# A quien avisarle si el envio automatico falla. Solo Franco: es quien puede
# arreglarlo, y un mail de error al equipo entero no le sirve a nadie.
AVISO_DE_ERROR = "francobomone14@gmail.com"

# Filtro explicito, no por omision. La direccion salio de la lista, pero si
# alguien la vuelve a agregar —o llega por EMAIL_DESTINATARIOS en los secrets—
# igual queda afuera del reporte. Conserva el acceso a la app.
EXCLUIDOS = ("infoagropix",)

MODO_DESARROLLO, MODO_PRUEBA, MODO_SEMANAL = "desarrollo", "prueba", "semanal"
MODOS = (MODO_DESARROLLO, MODO_PRUEBA, MODO_SEMANAL)

# Quien recibe en cada modo. El semanal es el unico que puede tomar la lista de
# los secrets; los otros dos la tienen fija en el codigo a proposito, asi un
# secret mal cargado no convierte una prueba en un envio a todo el equipo.
POR_MODO = {
    MODO_DESARROLLO: DESTINATARIOS_DESARROLLO,
    MODO_PRUEBA: DESTINATARIOS_PRUEBA,
    MODO_SEMANAL: DESTINATARIOS,
}


def excluido(email: str) -> bool:
    """True si la direccion contiene alguno de los fragmentos vetados."""
    limpio = (email or "").strip().lower()
    return any(fragmento in limpio for fragmento in EXCLUIDOS)


def destinatarios(modo: str = MODO_SEMANAL, lista: list[str] | None = None) -> list[str]:
    """A quien le llega el reporte, ya filtrado, normalizado y sin repetidos.

    desarrollo -> solo Franco. prueba -> Franco y Matias. semanal -> la lista
    completa. `lista` permite pasar destinatarios a mano (desde los secrets o
    desde --destinatarios); el filtro de EXCLUIDOS se aplica igual.
    """
    base = list(lista) if lista else list(POR_MODO.get(modo, DESTINATARIOS))

    vistos, salida = set(), []
    for email in base:
        limpio = (email or "").strip().lower()
        if not limpio or limpio in vistos or excluido(limpio):
            continue
        vistos.add(limpio)
        salida.append(limpio)
    return salida


def prefijo_asunto(modo: str) -> str:
    """El asunto dice de entrada si es un envio real o una prueba."""
    return {MODO_DESARROLLO: "[DEV] ", MODO_PRUEBA: "[PRUEBA] "}.get(modo, "")


# ---------------------------------------------------------------------------
# Periodo
# ---------------------------------------------------------------------------
def ahora_argentina() -> datetime:
    return datetime.now(TZ_ARGENTINA)


VIERNES = 4  # date.weekday(): lunes=0 … viernes=4


def viernes_de_cierre(referencia: date | datetime | None = None) -> date:
    """El viernes mas reciente hasta `referencia` inclusive.

    Si el cron se atrasa y el job corre un sabado, el cierre sigue siendo el
    viernes: el reporte no cambia de periodo porque GitHub demoro la corrida.
    """
    if referencia is None:
        referencia = ahora_argentina()
    if isinstance(referencia, datetime):
        referencia = referencia.date()
    return referencia - timedelta(days=(referencia.weekday() - VIERNES) % 7)


def semana_reporte(referencia: date | datetime | None = None,
                   ambos_inclusive: bool | None = None) -> tuple[date, date]:
    """(desde, hasta) del reporte semanal: de viernes a viernes.

    Es la UNICA fuente del periodo: la usan la app, el PDF y el mail, asi que los
    tres dicen siempre lo mismo.

    El envio del viernes 25/09/2026 cubre del 18/09 al 25/09, ambos inclusive.
    Con `ambos_inclusive=False` arranca el sabado 19/09 y no se superpone con el
    reporte siguiente. El default sale de REPORTE_AMBOS_VIERNES en los secrets.

    Sin `referencia` se toma la fecha de Argentina, nunca la UTC del runner: a
    las 21:00 UTC del viernes en Buenos Aires siguen siendo las 18:00 del mismo
    viernes, pero un cron que corra mas tarde ya estaria en sabado UTC.
    """
    if ambos_inclusive is None:
        ambos_inclusive = REPORTE_AMBOS_VIERNES
    hasta = viernes_de_cierre(referencia)
    return hasta - timedelta(days=7 if ambos_inclusive else 6), hasta


def semana_cerrada(referencia: date | datetime | None = None) -> tuple[date, date]:
    """Alias historico de semana_reporte(). Se mantiene por compatibilidad."""
    return semana_reporte(referencia)


DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def etiqueta_periodo(desde: date, hasta: date) -> str:
    """'Viernes 18/09 a Viernes 25/09/2026'. El año va una sola vez, al final."""
    return (f"{DIAS[desde.weekday()]} {desde:%d/%m} a "
            f"{DIAS[hasta.weekday()]} {hasta:%d/%m/%Y}")


def titulo_reporte(desde: date, hasta: date) -> str:
    """Encabezado del mail y del PDF."""
    return f"REPORTE SEMANAL — {etiqueta_periodo(desde, hasta)}"


def asunto(desde: date, hasta: date, modo: str = MODO_SEMANAL) -> str:
    return (f"{prefijo_asunto(modo)}Reporte Semanal Agropix - "
            f"[{etiqueta_periodo(desde, hasta)}]")


def nombre_pdf(hasta: date) -> str:
    return f"reporte_semanal_{hasta:%Y%m%d}.pdf"


# ---------------------------------------------------------------------------
# KPIs de la semana
# ---------------------------------------------------------------------------
def kpis_semana(datos: dict, datos_semana_anterior: dict | None = None) -> dict:
    """KPIs del periodo + variacion contra la semana previa, si se pasa.

    `datos` ya viene filtrado al periodo (salida de utils.data.aplicar_filtros).
    """
    k = kpis_comisiones(datos["servicios"], datos["equipos"])
    # "Total del negocio": todo lo que factura Agropix en la semana, cobrado o no.
    # Es Comision $ de equipos + Valor total de ventas de servicios, que es
    # exactamente lo que kpis_comisiones() suma como comision_generada.
    k["total_negocio"] = k["comision_generada"]
    if datos_semana_anterior:
        previa = kpis_comisiones(datos_semana_anterior["servicios"], datos_semana_anterior["equipos"])
        k["variacion_cobradas"] = _variacion(k["comision_cobrada"], previa["comision_cobrada"])
        k["variacion_hectareas"] = _variacion(k["hectareas"], previa["hectareas"])
        k["cobradas_previa"] = previa["comision_cobrada"]
    return k


def _variacion(actual: float, previo: float) -> float | None:
    """Variacion relativa, o None si no hay base contra la que comparar.

    Con previo=0 cualquier porcentaje seria enganoso (division por cero o un
    +infinito%), asi que se devuelve None y el mail lo omite.
    """
    if not previo:
        return None
    return (actual - previo) / previo


def resumen_texto(k: dict, desde: date, hasta: date) -> str:
    """Dos o tres frases sobre la semana, para el cuerpo del mail."""
    partes = [
        f"Entre el {desde:%d/%m} y el {hasta:%d/%m} Agropix cobró "
        f"{_moneda(k['comision_cobrada'])}."
    ]
    if k["por_cobrar"] > 0:
        partes.append(f"Quedan {_moneda(k['por_cobrar'])} por cobrar.")
    if k["hectareas"] > 0:
        partes.append(
            f"Se trabajaron {_numero(k['hectareas'])} ha en {k['cantidad_servicios']} trabajos."
        )
    if sin_actividad(k):
        return "Sin actividad registrada en el período."
    return " ".join(partes)


def sin_actividad(k: dict) -> bool:
    """Ni trabajos ni ventas de equipos en el periodo."""
    return (k["cantidad_servicios"] == 0
            and k.get("total_negocio", k["comision_generada"]) == 0)


# ---------------------------------------------------------------------------
# Formato (independiente de utils.format, que asume contexto de la app)
# ---------------------------------------------------------------------------
def _es_ar(valor: float, decimales: int = 0) -> str:
    """Miles con punto y decimales con coma."""
    txt = f"{valor:,.{decimales}f}"
    return txt.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _moneda(valor: float) -> str:
    return f"US$ {_es_ar(valor)}"


def _numero(valor: float) -> str:
    return _es_ar(valor)


def _pct(valor: float) -> str:
    return f"{_es_ar(valor * 100, 1)} %"


def _delta(variacion: float | None) -> str:
    if variacion is None:
        return ""
    signo = "+" if variacion >= 0 else "−"
    return f"{signo}{_es_ar(abs(variacion) * 100, 1)} % vs. semana anterior"


# ---------------------------------------------------------------------------
# Cuerpo del mail
# ---------------------------------------------------------------------------
_TARJETA = """
        <td style="padding:0 6px" width="33%">
          <div style="background:{color};border-radius:10px;padding:14px 16px;color:#FFFFFF">
            <div style="font-size:11px;letter-spacing:.04em;text-transform:uppercase;opacity:.95">{label}</div>
            <div style="font-size:22px;font-weight:700;padding:4px 0 2px 0">{valor}</div>
            <div style="font-size:11px;opacity:.92">{nota}</div>
          </div>
        </td>"""


def cuerpo_html(k: dict, desde: date, hasta: date, clientes: pd.DataFrame | None = None,
                url_app: str = URL_APP) -> str:
    """HTML del mail: 3 KPIs, resumen, top 5 clientes y boton a la app.

    Va con tablas y estilos inline a proposito: los clientes de correo
    (Gmail sobre todo) descartan <style> y no soportan flex ni grid.
    """
    tarjetas = "".join([
        _TARJETA.format(color="#00A651", label="Total del negocio",
                        valor=_moneda(k.get("total_negocio", k["comision_generada"])),
                        nota=f"{_pct(k['pct_cobranza'])} de cobranza"),
        _TARJETA.format(color="#3F7D3F", label="Has trabajadas",
                        valor=f"{_numero(k['hectareas'])} ha",
                        nota=_delta(k.get("variacion_hectareas")) or f"{k['cantidad_servicios']} trabajos"),
        _TARJETA.format(color="#1F77B4", label="Clientes",
                        valor=_numero(k["clientes"]),
                        nota=f"{_moneda(k['por_cobrar'])} por cobrar"),
    ])
    return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1B2631;max-width:640px">
  <h2 style="color:#2E7D32;margin:0 0 4px 0">🌱 Reporte Semanal Agropix</h2>
  <p style="margin:0 0 16px 0;color:#5D6D7E;font-weight:600">{titulo_reporte(desde, hasta)}</p>

  <p>Hola, va el resumen de la semana.</p>

  <table width="100%" cellpadding="0" cellspacing="0" style="margin:12px 0"><tr>{tarjetas}</tr></table>

  <p style="line-height:1.55">{resumen_texto(k, desde, hasta)}</p>

  {_desglose(k)}

  {_tabla_clientes(clientes)}

  <p style="margin:24px 0 8px 0">
    <a href="{url_app}" style="background:#2E7D32;color:#FFFFFF;text-decoration:none;
       padding:12px 22px;border-radius:8px;font-weight:700;display:inline-block">
      Ver reporte completo en Streamlit</a>
  </p>
  <p style="margin:0 0 4px 0;font-size:12px;color:#5D6D7E">
    (Versión para computadora — no optimizado para dispositivos móviles)
  </p>
  <!-- El link tambien en texto: hay clientes que no pintan el boton, y en el
       celular a veces es mas comodo copiarlo que tocarlo -->
  <p style="margin:0 0 20px 0;font-size:12px;color:#5D6D7E;line-height:1.5">
    Si el botón no funciona, copiá y pegá este link:<br>
    <a href="{url_app}" style="color:#1565C0;word-break:break-all">{url_app}</a>
  </p>

  <p style="color:#5D6D7E;font-size:12px;margin-top:20px">
    Agropix · reporte generado automáticamente · soporte@agropix.com
  </p>
</div>
"""


_FILA_DESGLOSE = """
    <tr style="background:{fondo}">
      <td style="padding:7px 10px;border-bottom:1px solid #E5E9EC">{concepto}</td>
      <td style="padding:7px 10px;border-bottom:1px solid #E5E9EC;text-align:right">{valor}</td>
    </tr>"""


def _desglose(k: dict) -> str:
    """Las cifras que el equipo mira al abrir el mail, sin tener que ir al PDF."""
    if sin_actividad(k):
        return ""
    filas = [
        ("Ingresos del período", _moneda(k.get("total_negocio", k["comision_generada"]))),
        ("Comisiones cobradas", _moneda(k["comision_cobrada"])),
        ("Comisiones por cobrar", _moneda(k["por_cobrar"])),
        ("Venta de servicios", _moneda(k["generado_servicios"])),
        ("Venta de equipos (comisión)", _moneda(k["generada_equipos"])),
        ("Hectáreas trabajadas", f"{_numero(k['hectareas'])} ha"),
        ("Clientes", _numero(k["clientes"])),
    ]
    cuerpo = "".join(
        _FILA_DESGLOSE.format(fondo="#FFFFFF" if i % 2 else "#FAFBFC",
                              concepto=concepto, valor=valor)
        for i, (concepto, valor) in enumerate(filas)
    )
    return f"""
  <h3 style="font-size:15px;margin:22px 0 8px 0">Resumen del período</h3>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border-collapse:collapse;font-size:13px">
    <tr style="background:#2E7D32;color:#FFFFFF">
      <th style="padding:8px 10px;text-align:left">Concepto</th>
      <th style="padding:8px 10px;text-align:right">Valor</th>
    </tr>
    {cuerpo}
  </table>"""


def _tabla_clientes(clientes: pd.DataFrame | None) -> str:
    if clientes is None or clientes.empty:
        return ""
    filas = []
    for i, (_, fila) in enumerate(clientes.head(5).iterrows()):
        fondo = "#FFFFFF" if i % 2 else "#FAFBFC"
        filas.append(
            f'<tr style="background:{fondo}">'
            f'<td style="padding:7px 10px;border-bottom:1px solid #E5E9EC">{fila["cliente"]}</td>'
            f'<td style="padding:7px 10px;border-bottom:1px solid #E5E9EC;text-align:right">'
            f'{_moneda(fila["ingreso"])}</td></tr>'
        )
    return f"""
  <h3 style="font-size:15px;margin:22px 0 8px 0">Top 5 clientes de la semana</h3>
  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px">
    <tr style="background:#2E7D32;color:#FFFFFF">
      <th style="padding:8px 10px;text-align:left">Cliente</th>
      <th style="padding:8px 10px;text-align:right">Ingreso Agropix</th>
    </tr>
    {"".join(filas)}
  </table>"""


def top_clientes_semana(datos: dict, top: int = 5) -> pd.DataFrame:
    return top_clientes(datos["servicios"], datos["equipos"], top=top)
