"""Reporte PDF del dashboard (A4 vertical): Reporte General, Venta de Servicios y Venta de Equipos.

generar_pdf(datos, filtros) no usa Streamlit, asi se puede llamar tambien desde un envio
automatico por mail. Los graficos se exportan con kaleido (usa el Chrome instalado) y el
documento se arma con reportlab, todo en memoria.
"""
import threading
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

import pandas as pd
import plotly.express as px
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import HRFlowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from utils.comisiones import (
    comisiones_por_canal, comisiones_por_mes, kpis_comisiones, ranking_vendedores,
)
from utils.data import (
    COBRADO, EQUIPOS, POR_COBRAR, SERVICIO, columna_mes, ingresos_por_periodo, kpis_consolidado,
    kpis_equipos, kpis_servicios, resumen_operadores, resumen_por_modelo, vigentes,
)
from utils.format import (
    AMBAR, AZUL, COLORES_COBRO, COLORES_UNIDAD, FECHA_CORTA_PLOTLY, GRIS, MES_PLOTLY, PLOTLY_TEMPLATE, SEPARADORES_PLOTLY,
    TICK_MONEDA, VERDE, es_nulo, formatear_moneda_completa, formatear_numero, formatear_porcentaje,
)

# Granularidades cuyo eje x va como fecha; el resto va como categoria
EJE_FECHA = ("Semanal", "Mensual")

MAX_FILAS_TABLA = 15
MARGEN = 1.5 * cm
ANCHO_UTIL = A4[0] - 2 * MARGEN  # 18 cm
MEDIO = 8.8                      # cm: dos graficos por fila con 0,4 cm de separacion
ALTO_GENERAL = 5.2               # cm: torta y evolucion del Reporte General
ALTO_HAS = 3.6                   # cm: has por periodo (va a lo ancho)
PX_POR_CM = 50                   # 18 cm -> 900 px; con scale=2 queda nitido al imprimir
SIN_DATOS = "No hay datos para el período seleccionado"

# kaleido maneja un unico Chrome global: dos exportaciones simultaneas no pueden compartirlo
_LOCK_KALEIDO = threading.Lock()

TEXTO = colors.HexColor("#1B2631")
TEXTO_SUAVE = colors.HexColor("#5D6D7E")
FONDO_TARJETA = colors.HexColor("#F4F6F8")
FONDO_ZEBRA = colors.HexColor("#FAFBFC")
BORDE = colors.HexColor("#D5DBDB")


class ErrorExportacionPDF(RuntimeError):
    """Falla esperable al exportar (kaleido o Chrome); el mensaje se puede mostrar al usuario."""


# ---------------------------------------------------------------------------
# Estilos y textos
# ---------------------------------------------------------------------------

def _estilo(nombre, **kw):
    base = dict(fontName="Helvetica", fontSize=8, leading=10, textColor=TEXTO)
    base.update(kw)
    return ParagraphStyle(nombre, **base)


ESTILOS = {
    "titulo": _estilo("titulo", fontName="Helvetica-Bold", fontSize=17, leading=21),
    "meta": _estilo("meta", fontSize=8.5, leading=12, textColor=TEXTO_SUAVE),
    "seccion": _estilo("seccion", fontName="Helvetica-Bold", fontSize=10.5, leading=13, spaceBefore=2, spaceAfter=4),
    "grafico": _estilo("grafico", fontName="Helvetica-Bold", fontSize=8.5, leading=11),
    "kpi_label": _estilo("kpi_label", fontSize=7.5, leading=9.5, textColor=TEXTO_SUAVE),
    "kpi_valor": _estilo("kpi_valor", fontName="Helvetica-Bold", fontSize=12, leading=15),
    "kpi_sub": _estilo("kpi_sub", fontSize=7, leading=9, textColor=TEXTO_SUAVE),
    "nota": _estilo("nota", fontName="Helvetica-Oblique", fontSize=7.5, leading=10, textColor=TEXTO_SUAVE),
    "aviso": _estilo("aviso", fontSize=8, leading=10.5, textColor=colors.HexColor("#7D5A00"),
                     backColor=colors.HexColor("#FFF8E1"), borderPadding=5),
    "celda": _estilo("celda", fontSize=7.5, leading=9.5),
    "celda_der": _estilo("celda_der", fontSize=7.5, leading=9.5, alignment=2),
    "cabecera": _estilo("cabecera", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5),
    "cabecera_der": _estilo("cabecera_der", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, alignment=2),
    "vacio": _estilo("vacio", fontSize=8, textColor=TEXTO_SUAVE, alignment=1),
}


def _ahora() -> datetime:
    """Hora de Argentina aunque el servidor (o el envio por mail) corra en UTC."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
    except Exception:
        return datetime.now()


def _fecha(valor) -> str:
    return pd.Timestamp(valor).strftime("%d/%m/%Y")


def describir_periodo(filtros: dict) -> str:
    desde, hasta = filtros.get("desde"), filtros.get("hasta")
    if desde is None or hasta is None:
        return "todo el historial"
    return f"{_fecha(desde)} a {_fecha(hasta)}"


def describir_estados(filtros: dict) -> str:
    estados, opciones = filtros.get("estados_trabajo"), filtros.get("estados_opciones") or []
    if estados is None:
        return "todos"
    if not estados:
        return "ninguno (no se incluyen servicios)"
    if opciones and set(estados) >= set(opciones):
        return "todos"
    return ", ".join(estados)


def nombre_archivo(filtros: dict) -> str:
    desde, hasta = filtros.get("desde"), filtros.get("hasta")
    rango = ""
    if desde is not None and hasta is not None:
        rango = f"_{pd.Timestamp(desde):%Y-%m-%d}_a_{pd.Timestamp(hasta):%Y-%m-%d}"
    return f"Agropix_reporte{rango}.pdf"


def _corto(texto, largo: int = 30) -> str:
    s = str(texto)
    return s if len(s) <= largo else s[: largo - 1] + "…"


# Formateadores de celda: devuelven texto ya escapado para Paragraph
def _f_texto(v):
    return "—" if es_nulo(v) or not str(v).strip() else escape(str(v).strip())


def _f_moneda(v):
    return "—" if es_nulo(v) else escape(formatear_moneda_completa(v))


def _f_numero(v):
    return "—" if es_nulo(v) else formatear_numero(v)


def _f_ha(v):
    return "—" if es_nulo(v) else f"{formatear_numero(v)} ha"


def _f_pct(v):
    return "—" if es_nulo(v) else formatear_porcentaje(v)


# ---------------------------------------------------------------------------
# Bloques del documento
# ---------------------------------------------------------------------------

def _encabezado(pagina: str, filtros: dict, generado: datetime, extras=()) -> list:
    # Dos lineas para que cada seccion entre en una carilla: los estados pueden ser largos y van solos
    separador = "&nbsp;&nbsp;·&nbsp;&nbsp;"
    primera = separador.join([
        f"<b>Período:</b> {escape(describir_periodo(filtros))}",
        *extras,
        f"<b>Generado:</b> {generado:%d/%m/%Y %H:%M}",
    ])
    lineas = [primera, f"<b>Estados incluidos:</b> {escape(describir_estados(filtros))}"]
    return [
        Paragraph(f"Agropix — {escape(pagina)}", ESTILOS["titulo"]),
        Spacer(0, 2),
        Paragraph("<br/>".join(lineas), ESTILOS["meta"]),
        Spacer(0, 4),
        HRFlowable(width="100%", thickness=2, color=colors.HexColor(VERDE), spaceAfter=6),
    ]


def _tarjetas(items: list, columnas: int = 3) -> list:
    """KPIs como tarjetas. items: dicts con label, valor, sub (opcional) y color del borde."""
    celdas = []
    for item in items:
        contenido = [Paragraph(escape(item["label"]), ESTILOS["kpi_label"]),
                     Paragraph(escape(item["valor"]), ESTILOS["kpi_valor"])]
        if item.get("sub"):
            contenido.append(Paragraph(escape(item["sub"]), ESTILOS["kpi_sub"]))
        celdas.append(contenido)
    filas = [celdas[i:i + columnas] for i in range(0, len(celdas), columnas)]
    filas[-1] = filas[-1] + [""] * (columnas - len(filas[-1]))

    estilo = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    posiciones = [divmod(i, columnas) for i in range(len(items))]
    estilo += [("BACKGROUND", (c, f), (c, f), FONDO_TARJETA) for f, c in posiciones]
    estilo.append(("GRID", (0, 0), (-1, -1), 4, colors.white))  # separacion entre tarjetas
    estilo += [("LINEBEFORE", (c, f), (c, f), 3, colors.HexColor(item.get("color", GRIS)))
               for (f, c), item in zip(posiciones, items)]

    tabla = Table(filas, colWidths=[ANCHO_UTIL / columnas] * columnas)
    tabla.setStyle(TableStyle(estilo))
    return [tabla, Spacer(0, 6)]


def _imagen(pngs: dict, nombre: str, ancho: float, alto: float):
    png = pngs.get(nombre)
    if png is not None:
        return Image(BytesIO(png), width=ancho * cm, height=alto * cm)
    vacio = Table([[Paragraph(SIN_DATOS, ESTILOS["vacio"])]], colWidths=[ancho * cm], rowHeights=[alto * cm])
    vacio.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, BORDE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("BACKGROUND", (0, 0), (-1, -1), FONDO_ZEBRA)]))
    return vacio


def _fila_graficos(pngs: dict, graficos: list) -> list:
    """graficos: [(nombre, titulo, ancho_cm, alto_cm)], con anchos que sumen 18 cm (0,4 cm entre cada uno)."""
    titulos, imagenes, anchos = [], [], []
    for i, (nombre, titulo, ancho, alto) in enumerate(graficos):
        if i:
            titulos.append("")
            imagenes.append("")
            anchos.append(0.4 * cm)
        titulos.append(Paragraph(escape(titulo), ESTILOS["grafico"]))
        imagenes.append(_imagen(pngs, nombre, ancho, alto))
        anchos.append(ancho * cm)
    tabla = Table([titulos, imagenes], colWidths=anchos)
    tabla.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [tabla, Spacer(0, 6)]


def _tabla(df: pd.DataFrame, columnas: list, color_cabecera: str) -> list:
    """columnas: [(campo, titulo, formateador, a_la_derecha, peso_ancho)]. Hasta MAX_FILAS_TABLA filas."""
    if df is None or df.empty:
        return [Paragraph(SIN_DATOS + ".", ESTILOS["nota"]), Spacer(0, 6)]
    total = len(df)
    filas = [[Paragraph(escape(titulo), ESTILOS["cabecera_der" if der else "cabecera"])
              for _, titulo, _, der, _ in columnas]]
    for _, registro in df.head(MAX_FILAS_TABLA).iterrows():
        filas.append([Paragraph(fmt(registro[campo]), ESTILOS["celda_der" if der else "celda"])
                      for campo, _, fmt, der, _ in columnas])

    pesos = sum(c[4] for c in columnas)
    tabla = Table(filas, colWidths=[ANCHO_UTIL * c[4] / pesos for c in columnas], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(color_cabecera)),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, BORDE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, FONDO_ZEBRA]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, BORDE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    salida = [tabla]
    if total > MAX_FILAS_TABLA:
        salida.append(Paragraph(f"Se muestran {MAX_FILAS_TABLA} de {formatear_numero(total)} filas.", ESTILOS["nota"]))
    return salida + [Spacer(0, 6)]


# ---------------------------------------------------------------------------
# Graficos
# ---------------------------------------------------------------------------

def _preparar(fig, eje_moneda: str | None = "y", leyenda: str = "derecha"):
    """Estilo de impresion: fondo blanco, separadores es-AR, sin titulo dentro de la imagen."""
    fig.update_layout(
        template=PLOTLY_TEMPLATE, separators=SEPARADORES_PLOTLY, paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family="Arial, Helvetica, sans-serif", size=12, color="#1B2631"),
        margin=dict(l=8, r=14, t=34 if leyenda == "arriba" else 8, b=8), legend_title_text="",
    )
    if eje_moneda == "x":
        fig.update_xaxes(tickformat=TICK_MONEDA)
    elif eje_moneda == "y":
        fig.update_yaxes(tickformat=TICK_MONEDA)
    if leyenda == "arriba":
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    return fig


def _eje_periodo(fig, periodos: pd.DataFrame, granularidad: str):
    # separa las fechas del eje para que la primera no se pise con el "$0" del eje vertical
    fig.update_xaxes(ticklabelstandoff=6)
    n = periodos["periodo"].nunique()
    if granularidad == "Semanal":
        fig.update_xaxes(tickformat=FECHA_CORTA_PLOTLY,
                         dtick=7 * 86_400_000 * (1 if n <= 10 else 4 if n <= 40 else 8))
    elif granularidad == "Mensual":
        fig.update_xaxes(tickformat=MES_PLOTLY, dtick="M1" if n <= 12 else "M3" if n <= 24 else "M6")
    else:
        fig.update_xaxes(type="category", categoryorder="array", categoryarray=periodos["periodo_label"].tolist())


def _barras_horizontales(df: pd.DataFrame, categoria: str, valor: str, color: str, texto: str, top: int = 10):
    """Mayor arriba; etiquetas largas recortadas para que entren en media carilla."""
    g = df[df[valor] > 0].sort_values(valor, ascending=False).head(top)
    if g.empty:
        return None
    g = g.assign(_etiqueta=g[categoria].astype(str).map(_corto)).iloc[::-1]
    fig = px.bar(g, x=valor, y="_etiqueta", orientation="h", labels={valor: "", "_etiqueta": ""})
    fig.update_traces(marker_color=color, texttemplate=texto, textposition="outside", cliponaxis=False)
    fig.update_xaxes(range=[0, float(g[valor].max()) * 1.3])
    return fig


def _exportar_png(figuras: dict) -> dict:
    """{nombre: (fig, ancho_cm, alto_cm)} -> {nombre: png}. Un solo Chrome para todos los graficos."""
    try:
        import kaleido
    except ImportError as e:
        raise ErrorExportacionPDF(
            "No está instalado kaleido, que se usa para convertir los gráficos en imágenes. "
            "Instalalo con: pip install -r requirements.txt"
        ) from e

    pngs = {}
    try:
        with _LOCK_KALEIDO:
            kaleido.start_sync_server(silence_warnings=True)
            try:
                for nombre, (fig, ancho, alto) in figuras.items():
                    pngs[nombre] = kaleido.calc_fig_sync(fig, opts={
                        "format": "png", "width": int(ancho * PX_POR_CM), "height": int(alto * PX_POR_CM), "scale": 2,
                    })
            finally:
                kaleido.stop_sync_server(silence_warnings=True)
    except Exception as e:
        raise ErrorExportacionPDF(
            "No se pudieron convertir los gráficos en imágenes. kaleido necesita Google Chrome o Chromium "
            "instalado en la máquina donde corre el dashboard. Si no está, se puede instalar con: "
            f'python -c "import kaleido; kaleido.get_chrome_sync()". Detalle técnico: {e}'
        ) from e
    return pngs


# ---------------------------------------------------------------------------
# Secciones: cada una devuelve (figuras a exportar, funcion que arma la carilla)
# ---------------------------------------------------------------------------

def _seccion_general(datos: dict, filtros: dict):
    servicios, ops = datos["servicios"], datos["equipos"]
    granularidad = filtros.get("granularidad") or "Mensual"
    kc = kpis_consolidado(servicios, ops)
    periodos = ingresos_por_periodo(servicios, ops, granularidad)
    x = "periodo" if granularidad in EJE_FECHA else "periodo_label"

    figuras = {}
    if kc["ingreso_total"] > 0:
        mix = pd.DataFrame({"unidad": [SERVICIO, EQUIPOS], "ingreso": [kc["ventas_servicios"], kc["comision_total"]]})
        fig = px.pie(mix, values="ingreso", names="unidad", hole=0.45, color="unidad", color_discrete_map=COLORES_UNIDAD)
        fig.update_traces(sort=False, texttemplate="%{label}<br>%{percent:.1%}", textposition="inside",
                          textfont=dict(color="white", size=12))
        fig.update_layout(showlegend=False)
        figuras["general_participacion"] = (_preparar(fig, eje_moneda=None), 5.6, ALTO_GENERAL)
    if not periodos.empty:
        largo = periodos.melt(id_vars=["periodo", "periodo_label"], value_vars=["ingreso_servicios", "ingreso_equipos"],
                              var_name="unidad_negocio", value_name="ingreso")
        largo["unidad_negocio"] = largo["unidad_negocio"].map({"ingreso_servicios": SERVICIO, "ingreso_equipos": EQUIPOS})
        fig = px.bar(largo, x=x, y="ingreso", color="unidad_negocio", color_discrete_map=COLORES_UNIDAD,
                     category_orders={"unidad_negocio": [SERVICIO, EQUIPOS]},
                     labels={x: "", "ingreso": "", "unidad_negocio": ""})
        _eje_periodo(fig, periodos, granularidad)
        figuras["general_evolucion"] = (_preparar(fig, "y", leyenda="arriba"), 12.0, ALTO_GENERAL)

        has = periodos[periodos["has_trabajadas"] > 0]
        if not has.empty:
            fig = px.bar(has, x=x, y="has_trabajadas", labels={x: "", "has_trabajadas": ""})
            fig.update_traces(marker_color=VERDE)
            fig.update_yaxes(tickformat=",.0f")
            _eje_periodo(fig, has, granularidad)
            figuras["general_has"] = (_preparar(fig, eje_moneda=None), 18.0, ALTO_HAS)

    def armar(pngs, generado):
        g = granularidad.lower()
        historia = _encabezado("Reporte General", filtros, generado, extras=[f"<b>Granularidad:</b> {escape(granularidad)}"])
        historia += _tarjetas([
            dict(label="Ingreso Agropix", valor=formatear_moneda_completa(kc["ingreso_total"]),
                 sub="Ventas de servicios + comisión de equipos", color=GRIS),
            dict(label="Ventas de servicios", valor=formatear_moneda_completa(kc["ventas_servicios"]),
                 sub=f"{formatear_porcentaje(kc['pct_servicios'])} del ingreso", color=VERDE),
            dict(label="Has trabajadas", valor=f"{formatear_numero(kc['hectareas'])} ha", color=VERDE),
            dict(label="Comisión Agropix cobrada", valor=formatear_moneda_completa(kc["comision_cobrada"]),
                 sub=f"Comisión total: {formatear_porcentaje(kc['pct_equipos'])} del ingreso", color=AZUL),
            dict(label="Comisión Agropix por cobrar", valor=formatear_moneda_completa(kc["comision_por_cobrar"]), color=AZUL),
            dict(label="Volumen intermediado", valor=formatear_moneda_completa(kc["facturado_equipos"]),
                 sub="Facturado s/IVA de equipos (no es ingreso)", color=AZUL),
        ], columnas=3)
        historia += [
            Paragraph("Ingreso Agropix = Valor total de ventas de servicios + Comisión $ de equipos. El Facturado s/IVA "
                      "de equipos es volumen intermediado y no entra en la participación.", ESTILOS["nota"]),
            Spacer(0, 8),
        ]
        historia += _fila_graficos(pngs, [("general_participacion", "Participación en el ingreso", 5.6, ALTO_GENERAL),
                                          ("general_evolucion", f"Evolución del ingreso ({g})", 12.0, ALTO_GENERAL)])
        historia += _fila_graficos(pngs, [("general_has", f"Has trabajadas ({g})", 18.0, ALTO_HAS)])
        historia.append(Paragraph("Resumen por período", ESTILOS["seccion"]))
        tabla = periodos.sort_values("periodo", ascending=False) if not periodos.empty else periodos
        historia += _tabla(tabla, [
            ("periodo_label", "Período", _f_texto, False, 1.0),
            ("ingreso_servicios", "Ingreso servicios", _f_moneda, True, 1.5),
            ("ingreso_equipos", "Ingreso equipos (comisión)", _f_moneda, True, 1.7),
            ("total", "Total", _f_moneda, True, 1.4),
            ("pct_servicios", "% servicios", _f_pct, True, 1.0),
            ("pct_equipos", "% equipos", _f_pct, True, 1.0),
            ("has_trabajadas", "Has trabajadas", _f_ha, True, 1.3),
        ], color_cabecera="#EAF2EA")
        return historia

    return figuras, armar


def _seccion_servicios(datos: dict, filtros: dict):
    s = datos["servicios"]
    seleccion = list(filtros.get("operadores") or [])
    operadores = datos["operadores"]
    largo = operadores[operadores["operador"].isin(seleccion)] if seleccion else operadores
    k = kpis_servicios(s, solo_vigentes=False)
    resumen = resumen_operadores(largo)
    trabajos = int(largo["fila_sheet"].nunique()) if not largo.empty else 0
    solos = int(largo.loc[largo["cantidad_operadores_en_trabajo"] == 1, "fila_sheet"].nunique()) if not largo.empty else 0

    figuras = {}
    if not s.empty:
        por_trabajo = (s.assign(trabajo=s["trabajo"].astype("string").fillna("Sin dato"))
                       .groupby("trabajo", as_index=False)["monto"].sum())
        fig = _barras_horizontales(por_trabajo, "trabajo", "monto", VERDE, "%{x:$,.3~s}")
        if fig is not None:
            figuras["servicios_trabajo"] = (_preparar(fig, "x"), MEDIO, 6.0)
    if not resumen.empty:
        fig = _barras_horizontales(resumen, "operador", "has", VERDE, "%{x:,.0f} ha", top=15)
        if fig is not None:
            fig.update_xaxes(tickformat=",.0f")
            figuras["servicios_has_operador"] = (_preparar(fig, eje_moneda=None), MEDIO, 6.0)
        con_fecha = largo[largo["fecha"].notna()]
        if not con_fecha.empty:
            tabla_mes = (con_fecha.assign(mes=columna_mes(con_fecha["fecha"]), operador=con_fecha["operador"].astype(str))
                         .pivot_table(index="mes", columns="operador", values="has_operador", aggfunc="sum"))
            meses = pd.date_range(tabla_mes.index.min(), tabla_mes.index.max(), freq="MS")
            mensual = (tabla_mes.reindex(meses).fillna(0).rename_axis("mes").reset_index()
                       .melt(id_vars="mes", var_name="operador", value_name="has_operador"))
            fig = px.line(mensual, x="mes", y="has_operador", color="operador", markers=True,
                          category_orders={"operador": resumen["operador"].tolist()},
                          color_discrete_sequence=px.colors.qualitative.Safe,
                          labels={"mes": "", "has_operador": "", "operador": ""})
            n = len(meses)
            fig.update_xaxes(tickformat=MES_PLOTLY, dtick="M1" if n <= 12 else "M3" if n <= 24 else "M6")
            fig.update_yaxes(tickformat=",.0f")
            fig.update_traces(marker=dict(size=4), line=dict(width=1.6))
            figuras["servicios_has_mensual"] = (_preparar(fig, eje_moneda=None), 18.0, 5.2)

    def armar(pngs, generado):
        operadores_txt = escape(", ".join(seleccion)) if seleccion else "todos"
        historia = _encabezado("Venta de Servicios", filtros, generado, extras=[f"<b>Operadores:</b> {operadores_txt}"])
        historia += _tarjetas([
            dict(label="Ventas totales", valor=formatear_moneda_completa(k["ventas"]), color=VERDE),
            dict(label="Has trabajadas", valor=f"{formatear_numero(k['hectareas'])} ha", color=VERDE),
            dict(label="Clientes", valor=formatear_numero(k["clientes"]), color=VERDE),
            dict(label="Ticket promedio", valor=formatear_moneda_completa(k["ticket_promedio"]), color=VERDE),
            dict(label="Has trabajadas por operador", valor=f"{formatear_numero(largo['has_operador'].sum())} ha",
                 sub="Suma de las has que registra cada operador", color=GRIS),
            dict(label="Trabajos con operador", valor=formatear_numero(trabajos), color=GRIS),
            dict(label="Trabajos hechos solo", valor=formatear_porcentaje(solos / trabajos if trabajos else 0),
                 sub=f"{formatear_numero(solos)} de {formatear_numero(trabajos)} trabajos", color=GRIS),
        ], columnas=4)
        historia += _fila_graficos(pngs, [("servicios_trabajo", "Ventas por trabajo (top 10)", MEDIO, 6.0),
                                          ("servicios_has_operador", "Has por operador", MEDIO, 6.0)])
        historia += _fila_graficos(pngs, [("servicios_has_mensual", "Evolución mensual de has por operador", 18.0, 5.2)])
        historia.append(Paragraph("Carga de trabajo por operador", ESTILOS["seccion"]))
        historia += _tabla(resumen, [
            ("operador", "Operador", _f_texto, False, 2.0),
            ("has", "Has totales", _f_ha, True, 1.3),
            ("trabajos", "Trabajos", _f_numero, True, 0.9),
            ("trabajos_solo", "Solo", _f_numero, True, 0.8),
            ("pct_solo", "% solo", _f_pct, True, 0.9),
            ("trabajos_acompanado", "Acompañado", _f_numero, True, 1.1),
            ("pct_acompanado", "% acompañado", _f_pct, True, 1.1),
        ], color_cabecera="#EAF2EA")
        sin_has = int(largo["has_operador"].isna().sum()) if not largo.empty else 0
        nota = ("Cada operador registra las has que ejecutó él: en un trabajo compartido la suma entre operadores "
                "puede superar las has del trabajo.")
        if sin_has:
            nota += f" {formatear_numero(sin_has)} registro(s) de operador sin has cargadas suman 0 ha."
        historia.append(Paragraph(nota, ESTILOS["nota"]))
        return historia

    return figuras, armar


def _seccion_equipos(datos: dict, filtros: dict):
    ops, unidades = datos["equipos"], datos["unidades"]
    k = kpis_equipos(ops, unidades)
    v = vigentes(ops)
    rm = resumen_por_modelo(unidades)
    comision_total = k["comision_cobrada"] + k["comision_por_cobrar"]

    figuras = {}
    if not rm.empty:
        unid = rm.melt(id_vars="modelo", value_vars=["unidades_prorrateadas", "unidades_pendientes"],
                       var_name="tipo", value_name="cantidad")
        unid["tipo"] = unid["tipo"].map({"unidades_prorrateadas": "Con monto asignado",
                                         "unidades_pendientes": "Pendiente de precio"})
        unid = unid[unid["cantidad"] > 0]
        fig = px.bar(unid, x="cantidad", y="modelo", color="tipo", orientation="h",
                     color_discrete_map={"Con monto asignado": AZUL, "Pendiente de precio": AMBAR},
                     category_orders={"tipo": ["Con monto asignado", "Pendiente de precio"]},
                     labels={"modelo": "", "cantidad": "", "tipo": ""})
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_xaxes(tickformat=",d")
        figuras["equipos_unidades"] = (_preparar(fig, eje_moneda=None, leyenda="arriba"), MEDIO, 6.0)
    if not v.empty:
        canal = (v.assign(canal=v["canal"].astype("string").fillna("Sin dato"))
                 .groupby("canal", as_index=False)["factura"].sum())
        fig = _barras_horizontales(canal, "canal", "factura", AZUL, "%{x:$,.3~s}")
        if fig is not None:
            figuras["equipos_canal"] = (_preparar(fig, "x"), MEDIO, 6.0)

        pagos = (v.assign(forma_pago=v["forma_pago"].astype("string").fillna("Sin dato"))
                 .groupby("forma_pago", as_index=False).agg(operaciones=("id_operacion", "size")))
        fig = px.pie(pagos, values="operaciones", names="forma_pago", hole=0.45,
                     color_discrete_sequence=px.colors.sequential.Blues_r[:-2])
        fig.update_traces(texttemplate="%{percent:.1%}", textposition="inside")
        figuras["equipos_pago"] = (_preparar(fig, eje_moneda=None), MEDIO, 5.0)
    if comision_total > 0:
        com = pd.DataFrame({"estado": ["Cobrada", "Por cobrar"], "monto": [k["comision_cobrada"], k["comision_por_cobrar"]]})
        fig = px.bar(com, x="estado", y="monto", color="estado", labels={"estado": "", "monto": ""},
                     color_discrete_map={"Cobrada": COLORES_COBRO[COBRADO], "Por cobrar": COLORES_COBRO[POR_COBRAR]})
        fig.update_traces(texttemplate="%{y:$,.3~s}", textposition="outside", cliponaxis=False)
        fig.update_yaxes(range=[0, float(com["monto"].max()) * 1.25])
        fig.update_layout(showlegend=False)
        figuras["equipos_comision"] = (_preparar(fig, "y"), MEDIO, 5.0)

    def armar(pngs, generado):
        historia = _encabezado("Venta de Equipos", filtros, generado)
        historia += _tarjetas([
            dict(label="Unidades vendidas", valor=formatear_numero(k["unidades"]),
                 sub=f"{formatear_numero(k['operaciones'])} operaciones", color=AZUL),
            dict(label="Facturado s/IVA (cliente)", valor=formatear_moneda_completa(k["monto"]),
                 sub="Precio al cliente sin IVA, por operación", color=AZUL),
            dict(label="Ticket promedio (facturado)", valor=formatear_moneda_completa(k["ticket_promedio"]), color=AZUL),
            dict(label="Comisión Agropix cobrada", valor=formatear_moneda_completa(k["comision_cobrada"]), color=AZUL),
            dict(label="Comisión Agropix por cobrar", valor=formatear_moneda_completa(k["comision_por_cobrar"]), color=AZUL),
        ], columnas=3)
        historia += [
            Paragraph(
                "Facturado s/IVA (cliente): precio al cliente sin IVA por toda la operación; depende de la forma de pago, "
                "por eso no coincide con el precio de lista. Comisión Agropix: lo que gana Agropix "
                f"({formatear_porcentaje(comision_total / k['monto'] if k['monto'] else 0)} del facturado en el período). "
                "El precio de lista solo reparte el facturado entre los modelos de una misma operación.",
                ESTILOS["nota"]),
            Spacer(0, 8),
        ]
        if k["ops_pendientes"]:
            historia += [
                Paragraph(f"<b>Facturado pendiente de precio de lista: {escape(formatear_moneda_completa(k['monto_pendiente']))}</b> "
                          f"en {formatear_numero(k['ops_pendientes'])} operación(es): sus equipos cuentan como unidades y la "
                          "factura suma al total, pero no se reparte por modelo.", ESTILOS["aviso"]),
                Spacer(0, 10),
            ]
        historia += _fila_graficos(pngs, [("equipos_unidades", "Unidades vendidas por modelo", MEDIO, 6.0),
                                          ("equipos_canal", "Facturado s/IVA por canal (top 10)", MEDIO, 6.0)])
        historia += _fila_graficos(pngs, [("equipos_pago", "Formas de pago (operaciones)", MEDIO, 5.0),
                                          ("equipos_comision", "Comisión Agropix", MEDIO, 5.0)])
        historia.append(Paragraph("Ventas por modelo", ESTILOS["seccion"]))
        historia += _tabla(rm, [
            ("modelo", "Modelo", _f_texto, False, 1.3),
            ("estado_precio", "Precio de lista", _f_texto, False, 1.3),
            ("precio_lista", "Precio lista (ref.)", _f_moneda, True, 1.3),
            ("unidades", "Unidades", _f_numero, True, 0.9),
            ("unidades_pendientes", "Unid. pendientes de precio", _f_numero, True, 1.5),
            ("monto_asignado", "Facturado s/IVA prorrateado", _f_moneda, True, 1.7),
        ], color_cabecera="#E3EDF8")
        return historia

    return figuras, armar


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------

def _canvas_numerado(generado: datetime):
    """Canvas que escribe 'Página X de Y' (necesita conocer el total al final)."""

    class CanvasNumerado(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._paginas = []

        def showPage(self):
            self._paginas.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._paginas)
            for estado in self._paginas:
                self.__dict__.update(estado)
                self._pie(total)
                super().showPage()
            super().save()

        def _pie(self, total):
            self.setFont("Helvetica", 7.5)
            self.setFillColor(TEXTO_SUAVE)
            self.setStrokeColor(BORDE)
            self.line(MARGEN, 1.25 * cm, A4[0] - MARGEN, 1.25 * cm)
            self.drawString(MARGEN, 0.85 * cm, f"Agropix · Reporte generado el {generado:%d/%m/%Y %H:%M}")
            self.drawRightString(A4[0] - MARGEN, 0.85 * cm, f"Página {self._pageNumber} de {total}")

    return CanvasNumerado


def _seccion_cobros(datos: dict, filtros: dict):
    """Cuarta carilla: estado de las comisiones, evolucion del cobro y cortes."""
    servicios, ops = datos["servicios"], datos["equipos"]
    k = kpis_comisiones(servicios, ops)
    mensual = comisiones_por_mes(servicios, ops)
    canal = comisiones_por_canal(ops)
    vendedores = ranking_vendedores(ops)

    figuras = {}
    if k["comision_generada"] > 0:
        estado = pd.DataFrame({
            "estado": ["Cobradas", "Por cobrar"],
            "monto": [k["comision_cobrada"], k["por_cobrar"]],
        })
        fig = px.pie(estado[estado["monto"] > 0], values="monto", names="estado", hole=0.45,
                     color="estado", color_discrete_map={"Cobradas": VERDE, "Por cobrar": AMBAR})
        fig.update_traces(sort=False, texttemplate="%{label}<br>%{percent:.1%}", textposition="inside",
                          textfont=dict(color="white", size=12))
        fig.update_layout(showlegend=False)
        figuras["cobros_estado"] = (_preparar(fig, eje_moneda=None), 5.6, ALTO_GENERAL)

    if not mensual.empty:
        largo = mensual.melt(id_vars="mes", value_vars=["cobrada", "por_cobrar"],
                             var_name="estado", value_name="monto")
        largo["estado"] = largo["estado"].map({"cobrada": "Cobradas", "por_cobrar": "Por cobrar"})
        fig = px.bar(largo, x="mes", y="monto", color="estado",
                     color_discrete_map={"Cobradas": VERDE, "Por cobrar": AMBAR},
                     category_orders={"estado": ["Cobradas", "Por cobrar"]},
                     labels={"mes": "", "monto": "", "estado": ""})
        fig.update_xaxes(tickformat=MES_PLOTLY)
        figuras["cobros_evolucion"] = (_preparar(fig, "y", leyenda="arriba"), 12.0, ALTO_GENERAL)

    def armar(pngs: dict, generado: datetime) -> list:
        historia = _encabezado("Resumen de cobros", filtros, generado)
        historia += _tarjetas([
            dict(label="Comisiones cobradas", valor=_f_moneda(k["comision_cobrada"]),
                 sub=f"{_f_pct(k['pct_cobranza'])} de lo generado", color=VERDE),
            dict(label="Comisiones generadas", valor=_f_moneda(k["comision_generada"]),
                 sub=f"equipos {_f_moneda(k['generada_equipos'])} · servicios {_f_moneda(k['generado_servicios'])}",
                 color=AZUL),
            dict(label="Por cobrar", valor=_f_moneda(k["por_cobrar"]),
                 sub=f"equipos {_f_moneda(k['por_cobrar_equipos'])} · servicios {_f_moneda(k['por_cobrar_servicios'])}",
                 color=AMBAR),
        ], columnas=3)
        historia += _fila_graficos(pngs, [
            ("cobros_estado", "Estado de las comisiones", 5.6, ALTO_GENERAL),
            ("cobros_evolucion", "Cobrado y por cobrar por mes", 12.0, ALTO_GENERAL),
        ])
        historia.append(Paragraph("Comisiones por canal (origen del lead)", ESTILOS["seccion"]))
        historia += _tabla(canal, [
            ("canal", "Canal", _f_texto, False, 3),
            ("comision_cobrada", "Cobrada", _f_moneda, True, 2),
            ("comision_generada", "Generada", _f_moneda, True, 2),
            ("por_cobrar", "Por cobrar", _f_moneda, True, 2),
            ("pct_cobranza", "% cobro", _f_pct, True, 1.4),
            ("operaciones", "Ops.", _f_numero, True, 1),
        ], AZUL)
        historia.append(Paragraph("Vendedores por comisión cobrada (solo equipos)", ESTILOS["seccion"]))
        historia += _tabla(vendedores, [
            ("vendedor", "Vendedor", _f_texto, False, 3),
            ("comision_cobrada", "Cobrada", _f_moneda, True, 2),
            ("comision_generada", "Generada", _f_moneda, True, 2),
            ("por_cobrar", "Por cobrar", _f_moneda, True, 2),
            ("pct_cobranza", "% cobro", _f_pct, True, 1.4),
            ("unidades", "Equipos", _f_numero, True, 1),
        ], VERDE)
        historia.append(Paragraph(
            "El CRM de servicios no registra vendedor (trae Operador 1..4, que es quien ejecuta el "
            "trabajo), así que el ranking de vendedores es solo de venta de equipos.", ESTILOS["nota"]))
        return historia

    return figuras, armar


def generar_pdf(datos: dict, filtros: dict | None = None) -> bytes:
    """PDF A4 vertical de 4 carillas: General, Equipos, Servicios y Resumen de cobros.

    datos: lo que ve el dashboard, ya filtrado (salida de utils.data.aplicar_filtros).
    filtros: desde, hasta, estados_trabajo, estados_opciones, operadores, granularidad y,
        opcional, generado (datetime). Los dos primeros y los estados solo se usan para el
        encabezado: el filtrado de periodo y estado ya viene aplicado en `datos`.
    Lanza ErrorExportacionPDF si no se pueden exportar los graficos.
    """
    filtros = dict(filtros or {})
    generado = filtros.get("generado") or _ahora()

    secciones = [_seccion_general(datos, filtros), _seccion_equipos(datos, filtros),
                 _seccion_servicios(datos, filtros), _seccion_cobros(datos, filtros)]
    figuras = {nombre: spec for figs, _ in secciones for nombre, spec in figs.items()}
    pngs = _exportar_png(figuras) if figuras else {}

    historia = []
    for i, (_, armar) in enumerate(secciones):
        if i:
            historia.append(PageBreak())
        historia += armar(pngs, generado)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGEN, rightMargin=MARGEN, topMargin=1.0 * cm, bottomMargin=1.5 * cm,
        title=f"Agropix — Reporte {describir_periodo(filtros)}", author="Agropix", subject="Reporte del dashboard",
    )
    doc.build(historia, canvasmaker=_canvas_numerado(generado))
    return buffer.getvalue()
