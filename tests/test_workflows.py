"""Valida los workflows de GitHub Actions.

Un error acá no lo agarra ningún linter de Python y recién se ve cuando la
corrida falla — que en este caso sería un viernes a la tarde, con el reporte sin
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


@pytest.mark.parametrize("archivo", ["reporte_semanal.yml", "envio_prueba.yml"])
def test_el_yaml_es_valido_y_tiene_un_job(archivo):
    w = cargar(archivo)
    assert w["name"]
    assert len(w["jobs"]) == 1
    assert pasos(w), "el job no tiene pasos"


def test_el_reporte_sale_los_viernes_18_argentina():
    """0 21 * * 5 = viernes 21:00 UTC = 18:00 ART (Argentina es UTC-3 todo el año)."""
    assert cargar("reporte_semanal.yml")[ON]["schedule"][0]["cron"] == "0 21 * * 5"


def test_la_prueba_no_tiene_cron():
    """Es solo manual: si tuviera schedule mandaria mails solo."""
    assert "schedule" not in cargar("envio_prueba.yml")[ON]


def test_los_dos_se_pueden_disparar_a_mano():
    """Sin workflow_dispatch habría que esperar al viernes para probar."""
    for archivo in ["reporte_semanal.yml", "envio_prueba.yml"]:
        assert "workflow_dispatch" in cargar(archivo)[ON]


@pytest.mark.parametrize("archivo", ["reporte_semanal.yml", "envio_prueba.yml"])
def test_pasa_los_secrets_que_el_script_necesita(archivo):
    usados = secrets_usados(cargar(archivo))
    for secret in ["SMTP_USER", "SMTP_PASSWORD", "GOOGLE_CREDENTIALS_JSON",
                   "CRM_SHEET_ID", "VENTAS_SHEET_ID"]:
        assert secret in usados, f"{archivo} no le pasa {secret} al script"


@pytest.mark.parametrize("archivo", ["reporte_semanal.yml", "envio_prueba.yml"])
def test_verifica_los_secrets_antes_de_la_parte_lenta(archivo):
    """Enterarse de que falta un secret recién con el PDF armado es tarde."""
    nombres = [p.get("name", "") for p in pasos(cargar(archivo))]
    verificacion = next(i for i, n in enumerate(nombres) if "Verificar secrets" in n)
    envio = next(i for i, n in enumerate(nombres) if "Enviar reporte" in n)
    credenciales = next(i for i, n in enumerate(nombres) if "Escribir credenciales" in n)
    assert verificacion < credenciales < envio


@pytest.mark.parametrize("archivo", ["reporte_semanal.yml", "envio_prueba.yml"])
def test_borra_las_credenciales_pase_lo_que_pase(archivo):
    borrado = [p for p in pasos(cargar(archivo)) if "Borrar credenciales" in p.get("name", "")]
    assert borrado, f"{archivo} deja credentials.json en el runner"
    assert borrado[0].get("if") == "always()", "tiene que borrarse aunque el envío falle"


def test_la_prueba_usa_el_modo_que_fija_los_destinatarios():
    """--modo prueba los fija en el codigo: no dependen de un secret."""
    envio = next(p for p in pasos(cargar("envio_prueba.yml"))
                 if "Enviar reporte" in p.get("name", ""))
    assert "--modo prueba" in envio["run"]
    assert "--tipo PRUEBA" in envio["run"]


def test_el_semanal_usa_el_modo_semanal():
    envio = next(p for p in pasos(cargar("reporte_semanal.yml"))
                 if "Enviar reporte" in p.get("name", ""))
    assert "--modo semanal" in envio["run"]


def test_los_dos_aceptan_una_fecha_de_corte():
    for archivo in ["reporte_semanal.yml", "envio_prueba.yml"]:
        assert "fecha_corte" in cargar(archivo)[ON]["workflow_dispatch"]["inputs"]


def test_solo_el_semanal_avisa_a_franco_si_falla():
    """El de prueba lo dispara alguien que esta mirando la pantalla."""
    aviso = [p for p in pasos(cargar("reporte_semanal.yml"))
             if "Avisar a Franco" in p.get("name", "")]
    assert aviso, "el semanal tiene que avisar si falla"
    assert aviso[0].get("if") == "failure()"
    assert "--notificar-error" in aviso[0]["run"]
    assert not [p for p in pasos(cargar("envio_prueba.yml"))
                if "Avisar" in p.get("name", "")]


def test_los_dos_workflows_no_comparten_grupo_de_concurrencia():
    """Con el mismo grupo, uno podria cancelar al otro."""
    a = cargar("reporte_semanal.yml")["concurrency"]["group"]
    b = cargar("envio_prueba.yml")["concurrency"]["group"]
    assert a != b


def test_el_semanal_documenta_las_dos_trampas_del_cron():
    texto = (WORKFLOWS / "reporte_semanal.yml").read_text(encoding="utf-8")
    assert "demorarse" in texto, "el cron de GitHub se atrasa"
    assert "60" in texto, "los repos publicos pierden el schedule a los 60 dias"


def test_no_quedaron_los_workflows_viejos():
    """Si sobreviven, se mandarian dos reportes: el del lunes y el del viernes."""
    for viejo in ["reporte-semanal.yml", "prueba-envio.yml"]:
        assert not (WORKFLOWS / viejo).exists(), f"{viejo} sigue existiendo"
