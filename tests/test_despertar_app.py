"""Clasificacion de las pantallas de Streamlit Cloud en scripts/despertar_app.py."""
import pytest

from scripts.despertar_app import estado


@pytest.mark.parametrize("texto,esperado", [
    ("Zzzz\nThis app has gone to sleep due to inactivity. Would you like to wake it "
     "back up?\nYes, get this app back up!", "dormida"),
    ("Your app is in the oven", "despertando"),
    ("This will take just a sec! Your app is waking up!", "despertando"),
    ("Agropix Dashboard\nAcceso privado", "lista"),
    ("", "otro"),
])
def test_estado(texto, esperado):
    assert estado(texto) == esperado


def test_lista_gana_aunque_siga_el_cartel_de_waking_up():
    """Lo que se vio en el Safari de Matias: login cargado y el cartel trabado arriba."""
    assert estado("Your app is waking up!\nAgropix Dashboard") == "lista"
