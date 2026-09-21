"""Valida los workflows de GitHub Actions.

Un error acá no lo agarra ningún linter de Python y recién se ve cuando la
corrida falla — que en este caso sería un lunes a la mañana, con el reporte sin
salir y nadie mirando.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml está en requirements-dev.txt")

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# La clave de `on:` la parsea PyYAML como el booleano True (YAML 1.1)
ON = True


def cargar(nombre: str) -> dict:
    return yaml.safe_load((WORKFLOWS / nombre).read_text(encoding="utf-8"))


def pasos(workflow: dict) -> list[dict]:
    return list(workflow["jobs"].values())[0]["steps"]


def secrets_usados(workflow: dict) -> set[str]:
    usados = set()
    for paso in pasos(workflow):
        for valor in (paso.get("env") or {}).values():
            if "secrets." in str(valor):
                usados.add(str(valor).split("secrets.")[1].split(" ")[0].rstrip("}"))
    return usados


@pytest.mark.parametrize("archivo", ["reporte-semanal.yml", "prueba-envio.yml"])
def test_el_yaml_es_valido_y_tiene_un_job(archivo):
    w = cargar(archivo)
    assert w["name"]
    assert len(w["jobs"]) == 1
    assert pasos(w), "el job no tiene pasos"


def test_el_reporte_sale_los_lunes_8am_argentina():
    """0 11 * * 1 = lunes 11:00 UTC = 8:00 ART (Argentina es UTC-3 todo el año)."""
    assert cargar("reporte-semanal.yml")[ON]["schedule"][0]["cron"] == "0 11 * * 1"


def test_la_prueba_corre_a_medianoche_argentina():
    """0 3 * * 1 = lunes 03:00 UTC = 00:00 ART."""
    assert cargar("prueba-envio.yml")[ON]["schedule"][0]["cron"] == "0 3 * * 1"


def test_los_dos_se_pueden_disparar_a_mano():
    """Sin workflow_dispatch habría que esperar al lunes para probar."""
    for archivo in ["reporte-semanal.yml", "prueba-envio.yml"]:
        assert "workflow_dispatch" in cargar(archivo)[ON]


@pytest.mark.parametrize("archivo", ["reporte-semanal.yml", "prueba-envio.yml"])
def test_pasa_los_secrets_que_el_script_necesita(archivo):
    usados = secrets_usados(cargar(archivo))
    for secret in ["SMTP_USER", "SMTP_PASSWORD", "GOOGLE_CREDENTIALS_JSON",
                   "CRM_SHEET_ID", "VENTAS_SHEET_ID"]:
        assert secret in usados, f"{archivo} no le pasa {secret} al script"


@pytest.mark.parametrize("archivo", ["reporte-semanal.yml", "prueba-envio.yml"])
def test_verifica_los_secrets_antes_de_la_parte_lenta(archivo):
    """Enterarse de que falta un secret recién con el PDF armado es tarde."""
    nombres = [p.get("name", "") for p in pasos(cargar(archivo))]
    verificacion = next(i for i, n in enumerate(nombres) if "Verificar secrets" in n)
    envio = next(i for i, n in enumerate(nombres) if "Enviar reporte" in n)
    credenciales = next(i for i, n in enumerate(nombres) if "Escribir credenciales" in n)
    assert verificacion < credenciales < envio


@pytest.mark.parametrize("archivo", ["reporte-semanal.yml", "prueba-envio.yml"])
def test_borra_las_credenciales_pase_lo_que_pase(archivo):
    borrado = [p for p in pasos(cargar(archivo)) if "Borrar credenciales" in p.get("name", "")]
    assert borrado, f"{archivo} deja credentials.json en el runner"
    assert borrado[0].get("if") == "always()", "tiene que borrarse aunque el envío falle"


def test_la_prueba_manda_solo_a_franco():
    """Es una prueba: no tiene que llegarle al resto del equipo."""
    envio = next(p for p in pasos(cargar("prueba-envio.yml"))
                 if "Enviar reporte" in p.get("name", ""))
    assert "--destinatarios francobomone14@gmail.com" in envio["run"]
    assert "--tipo PRUEBA" in envio["run"]


def test_la_prueba_avisa_que_hay_que_borrarla():
    """Si queda, todos los lunes a medianoche llega un mail de prueba de más."""
    texto = (WORKFLOWS / "prueba-envio.yml").read_text(encoding="utf-8")
    assert "BORRAR ESTE ARCHIVO" in texto


def test_los_dos_workflows_no_comparten_grupo_de_concurrencia():
    """Con el mismo grupo, el de las 8 podría cancelar al de medianoche."""
    a = cargar("reporte-semanal.yml")["concurrency"]["group"]
    b = cargar("prueba-envio.yml")["concurrency"]["group"]
    assert a != b
