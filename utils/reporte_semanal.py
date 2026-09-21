"""Reporte semanal de Agropix: periodo, KPIs y cuerpo del mail.

Se ejecuta fuera de Streamlit, desde scripts/enviar_reporte_semanal.py, que a su
vez corre en GitHub Actions los lunes 8:00 ART. Aca va solo la logica pura
(que semana, que numeros, que texto); el envio y el armado del PDF van aparte.

Por que GitHub Actions y no `schedule` + thread dentro de la app
---------------------------------------------------------------
Streamlit Community Cloud duerme la app cuando nadie la visita y mata el
proceso. Un scheduler en un thread de la app se muere con ella y no se despierta
solo, asi que los lunes sin visitas el mail no saldria. El cron de Actions
corre en la infraestructura de GitHub, no depende de que la app este viva.

Zona horaria
------------
Argentina usa UTC-3 todo el año (no mueve los relojes desde 2009), asi que
8:00 ART son 11:00 UTC de forma estable. Igual el periodo se calcula con
zoneinfo y no con offsets a mano.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from config.settings import URL_APP
from utils.comisiones import kpis_comisiones, top_clientes

TZ_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")

# Destinatarios del reporte semanal. Se pueden sobreescribir desde los secrets
# con EMAIL_DESTINATARIOS (lista separada por comas).
# infoagropix@ salio de la lista: sigue teniendo acceso a la app, pero no
# recibe el mail.
DESTINATARIOS = (
    "francobomone14@gmail.com",     # Franco
    "matias21tossen@gmail.com",     # Matias
    "ggaletto.gg@gmail.com",        # Guido
    "ignacio.ramello879@gmail.com", # Ignacio
    "nicotobaldi55@gmail.com",      # Luciano
    "fabiocailletbois@gmail.com",   # Fabio
)


# ---------------------------------------------------------------------------
# Periodo
# ---------------------------------------------------------------------------
def ahora_argentina() -> datetime:
    return datetime.now(TZ_ARGENTINA)


def semana_cerrada(hoy: date | datetime | None = None) -> tuple[date, date]:
    """(lunes, domingo) de la ultima semana COMPLETA antes de `hoy`.

    El mail sale los lunes temprano, asi que la semana que se reporta es la que
    acaba de cerrar: el envio del lunes 21/09 trae del 14/09 al 20/09. Reportar
    lunes-a-hoy daria una semana incompleta y los numeros no serian comparables
    entre envios.
    """
    if hoy is None:
        hoy = ahora_argentina()
    if isinstance(hoy, datetime):
        hoy = hoy.date()
    lunes_de_esta_semana = hoy - timedelta(days=hoy.weekday())
    lunes = lunes_de_esta_semana - timedelta(days=7)
    return lunes, lunes + timedelta(days=6)


def etiqueta_periodo(desde: date, hasta: date) -> str:
    """'Lunes 08/09 - Domingo 14/09' para el asunto del mail."""
    return f"Lunes {desde:%d/%m} - Domingo {hasta:%d/%m}"


def asunto(desde: date, hasta: date) -> str:
    return f"Reporte Semanal Agropix - [{etiqueta_periodo(desde, hasta)}]"


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
    if k["cantidad_servicios"] == 0 and k.get("total_negocio", k["comision_generada"]) == 0:
        return (f"Entre el {desde:%d/%m} y el {hasta:%d/%m} no se registraron "
                "trabajos ni ventas de equipos en las planillas.")
    return " ".join(partes)


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
  <p style="margin:0 0 16px 0;color:#5D6D7E">{etiqueta_periodo(desde, hasta)}</p>

  <p>Hola, va el resumen de la semana.</p>

  <table width="100%" cellpadding="0" cellspacing="0" style="margin:12px 0"><tr>{tarjetas}</tr></table>

  <p style="line-height:1.55">{resumen_texto(k, desde, hasta)}</p>

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
