#!/usr/bin/env python
"""Abre el dashboard en un navegador de verdad para que Streamlit Cloud no lo duerma.

Por que existe
--------------
Streamlit Community Cloud duerme las apps que pasan ~12 horas sin visitas. El
que entra despues ve la pantalla "Zzzz", aprieta el boton y espera unos 5
minutos mientras el contenedor se reconstruye ("Your app is in the oven"). En
Safari, encima, la pantalla de "waking up" a veces queda trabada y hay que
recargar muchas veces (reclamo de Matias del 02/11/2026).

La solucion es que nunca llegue a dormirse: este script lo corre cada pocas
horas .github/workflows/mantener_despierta.yml.

Por que un navegador y no un curl
---------------------------------
Streamlit cuenta como visita una sesion real (el websocket que abre la pagina),
no un GET suelto. Y si la app ya se durmio, hay que apretar el boton "Yes, get
this app back up!", cosa que solo se puede hacer con un navegador.

Uso:
    pip install playwright && playwright install --with-deps chromium
    python scripts/despertar_app.py                 # URL por defecto
    python scripts/despertar_app.py --url https://otra.streamlit.app/

Codigo de salida distinto de 0 si la app no quedo lista a tiempo, para que
Actions lo marque en rojo.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

URL_POR_DEFECTO = "https://agropix.streamlit.app/"

# Texto que solo aparece cuando la app ya cargo: el titulo de la pantalla de
# login. No hace falta iniciar sesion; con que Streamlit sirva la pagina alcanza.
SEÑAL_LISTA = "Agropix Dashboard"

# Frases de las pantallas de Streamlit Cloud (en minusculas)
SEÑALES_DORMIDA = ("gone to sleep", "get this app back up")
SEÑALES_DESPERTANDO = ("waking up", "in the oven", "your app is")


def estado(texto: str) -> str:
    """Clasifica lo que se ve en la pagina: 'lista', 'dormida', 'despertando' u 'otro'.

    'lista' gana sobre las demas: en Safari se vio el login cargado debajo del
    cartel de "waking up" que no se iba.
    """
    if SEÑAL_LISTA in texto:
        return "lista"
    bajo = texto.lower()
    if any(s in bajo for s in SEÑALES_DORMIDA):
        return "dormida"
    if any(s in bajo for s in SEÑALES_DESPERTANDO):
        return "despertando"
    return "otro"


def _texto_de_todo(page) -> str:
    """Texto de la pagina y de sus iframes: la app vive dentro de uno."""
    partes = []
    for frame in page.frames:
        try:
            partes.append(frame.inner_text("body", timeout=2_000))
        except Exception:
            pass  # frame que se esta recargando o todavia sin body
    return "\n".join(partes)


def despertar(url: str, espera_max: int) -> bool:
    from playwright.sync_api import sync_playwright

    limite = time.monotonic() + espera_max
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        page = navegador.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        ultimo = None
        while time.monotonic() < limite:
            actual = estado(_texto_de_todo(page))
            if actual != ultimo:
                print(f"[{time.strftime('%H:%M:%S')}] {actual}", flush=True)
                ultimo = actual

            if actual == "lista":
                # Unos segundos mas con la sesion abierta para que cuente la visita
                page.wait_for_timeout(15_000)
                navegador.close()
                return True

            if actual == "dormida":
                boton = page.get_by_role("button", name="get this app back up")
                try:
                    boton.click(timeout=5_000)
                    print("Click en 'Yes, get this app back up!'", flush=True)
                except Exception as e:
                    print(f"No se pudo apretar el boton: {e}", flush=True)

            page.wait_for_timeout(5_000)

        navegador.close()
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.getenv("URL_APP") or URL_POR_DEFECTO)
    parser.add_argument("--espera-max", type=int, default=600,
                        help="Segundos maximos esperando que la app cargue (default 600)")
    args = parser.parse_args()

    print(f"Abriendo {args.url}", flush=True)
    if despertar(args.url, args.espera_max):
        print("La app esta despierta.")
        return 0
    print(f"::error::La app no cargo en {args.espera_max} s.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
