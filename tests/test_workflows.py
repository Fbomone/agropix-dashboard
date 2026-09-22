"""Valida los workflows de GitHub Actions.

Un error acá no lo agarra ningún linter de Python y recién se ve cuando la
corrida falla — que en el caso del productivo sería un viernes a la tarde, con
el reporte sin salir y nadie mirando.
"""
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml está en requirements-dev.txt")

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# La clave de `on:` la parsea PyYAML como el booleano True (YAML 1.1)
ON = True

REUTILIZABLE = "_enviar_reporte.yml"
LLAMADORES = {
    "envio_desarrollo.yml": "desarrollo",
    "envio_test.yml": "prueba",
    "reporte_semanal.yml": "semanal",
}


def cargar(nombre: str) -> dict:
    return yaml.safe_load((WORKFLOWS / nombre).read_text(encoding="utf-8"))


def pasos(workflow: dict) -> list[dict]:
    return list(workflow["jobs"].values())[0]["steps"]


# ---------------------------------------------------------------------------
# Los tres llamadores
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("archivo,modo", LLAMADORES.items())
def test_cada_llamador_usa_el_reutilizable_con_su_modo(archivo, modo):
    job = list(cargar(archivo)["jobs"].values())[0]
    assert job["uses"] == f"./.github/workflows/{REUTILIZABLE}"
    assert job["with"]["modo"] == modo
    assert job["secrets"] == "inherit", "sin esto el job no ve ningún secret"


@pytest.mark.parametrize("archivo", LLAMADORES)
def test_los_tres_se_pueden_disparar_a_mano(archivo):
    assert "workflow_dispatch" in cargar(archivo)[ON]


@pytest.mark.parametrize("archivo", LLAMADORES)
def test_los_tres_aceptan_fecha_de_corte(archivo):
    assert "fecha_corte" in cargar(archivo)[ON]["workflow_dispatch"]["inputs"]


@pytest.mark.parametrize("archivo", LLAMADORES)
def test_cada_uno_tiene_su_grupo_de_concurrencia(archivo):
    assert cargar(archivo)["concurrency"]["group"]


def test_los_grupos_de_concurrencia_no_se_repiten():
    """Con el mismo grupo, un envío podría cancelar a otro."""
    grupos = [cargar(a)["concurrency"]["group"] for a in LLAMADORES]
    assert len(set(grupos)) == len(grupos)


# ---------------------------------------------------------------------------
# Quien corre solo y quien no
# ---------------------------------------------------------------------------
def test_desarrollo_nunca_se_dispara_solo():
    """El circulo chico es para probar a mano: un cron ahi no tiene sentido."""
    assert "schedule" not in cargar("envio_desarrollo.yml")[ON]


def test_si_test_tiene_cron_es_de_una_sola_vez():
    """El ensayo automatico esta bien; un cron semanal en test no.

    Un `0 1 * * 2` le mandaria a Matias un reporte duplicado todos los martes
    para siempre. Fijando dia y mes, si alguien se olvida de sacarlo lo peor
    que pasa es que se repita dentro de un año.
    """
    schedule = cargar("envio_test.yml")[ON].get("schedule")
    if not schedule:
        return  # ya lo quitaron: es el estado final esperado
    for entrada in schedule:
        minuto, hora, dia, mes, semana = entrada["cron"].split()
        assert dia != "*" and mes != "*", (
            f"cron {entrada['cron']!r} se repite: fijá día y mes para que sea de una sola vez"
        )


def test_el_cron_temporal_de_test_dice_cuando_sacarlo():
    """Sin fecha escrita al lado, un cron 'temporal' se queda para siempre."""
    texto = (WORKFLOWS / "envio_test.yml").read_text(encoding="utf-8")
    if "schedule:" not in texto:
        return
    assert "TEMPORAL" in texto, "marcá el cron como temporal"
    assert re.search(r"QUITAR DESPUES DEL \d{4}-\d{2}-\d{2}", texto), (
        "poné la fecha en que hay que sacarlo"
    )


def test_el_productivo_sale_los_viernes_18_argentina():
    """0 21 * * 5 = viernes 21:00 UTC = 18:00 ART (Argentina es UTC-3 todo el año)."""
    assert cargar("reporte_semanal.yml")[ON]["schedule"][0]["cron"] == "0 21 * * 5"


def test_el_reutilizable_no_se_dispara_solo():
    on = cargar(REUTILIZABLE)[ON]
    assert "workflow_call" in on
    assert "schedule" not in on and "workflow_dispatch" not in on


def test_el_cron_manual_queda_marcado_distinto_en_el_historial():
    """Para poder distinguir un reenvío a mano de la corrida automática."""
    job = list(cargar("reporte_semanal.yml")["jobs"].values())[0]
    assert "schedule" in job["with"]["tipo_historial"]
    assert "AUTOMATICO" in job["with"]["tipo_historial"]


# ---------------------------------------------------------------------------
# El reutilizable: donde viven los pasos
# ---------------------------------------------------------------------------
def test_el_reutilizable_recibe_el_modo_como_input():
    assert cargar(REUTILIZABLE)[ON]["workflow_call"]["inputs"]["modo"]["required"] is True


def test_pasa_los_secrets_que_el_script_necesita():
    usados = set()
    for paso in pasos(cargar(REUTILIZABLE)):
        for valor in (paso.get("env") or {}).values():
            if "secrets." in str(valor):
                usados.add(str(valor).split("secrets.")[1].split(" ")[0].rstrip("}"))
    for secret in ["SMTP_USER", "SMTP_PASSWORD", "GOOGLE_CREDENTIALS_JSON",
                   "CRM_SHEET_ID", "VENTAS_SHEET_ID"]:
        assert secret in usados, f"no se le pasa {secret} al script"


def test_verifica_los_secrets_antes_de_la_parte_lenta():
    """Enterarse de que falta un secret recién con el PDF armado es tarde."""
    nombres = [p.get("name", "") for p in pasos(cargar(REUTILIZABLE))]
    verificacion = next(i for i, n in enumerate(nombres) if "Verificar secrets" in n)
    credenciales = next(i for i, n in enumerate(nombres) if "Escribir credenciales" in n)
    envio = next(i for i, n in enumerate(nombres) if "Enviar reporte" in n)
    assert verificacion < credenciales < envio


def test_los_tres_avisan_a_franco_si_falla():
    """El aviso vive en el reutilizable, asi que lo heredan los tres."""
    aviso = [p for p in pasos(cargar(REUTILIZABLE)) if "Avisar a Franco" in p.get("name", "")]
    assert aviso, "falta el aviso de error"
    assert aviso[0]["if"] == "failure()"
    assert "--notificar-error" in aviso[0]["run"]


def test_las_credenciales_se_borran_pase_lo_que_pase():
    borrado = [p for p in pasos(cargar(REUTILIZABLE)) if "Borrar credenciales" in p.get("name", "")]
    assert borrado, "deja credentials.json en el runner"
    assert borrado[0]["if"] == "always()", "tiene que borrarse aunque el envío falle"


def test_el_modo_va_por_linea_de_comandos_y_no_por_secret():
    """Un secret mal cargado no puede convertir una prueba en un envío a todos."""
    envio = next(p for p in pasos(cargar(REUTILIZABLE)) if "Enviar reporte" in p.get("name", ""))
    assert "--modo ${{ inputs.modo }}" in envio["run"]


def test_el_productivo_documenta_las_dos_trampas_del_cron():
    texto = (WORKFLOWS / "reporte_semanal.yml").read_text(encoding="utf-8")
    assert "demorarse" in texto, "el cron de GitHub se atrasa"
    assert "60" in texto, "los repos públicos pierden el schedule a los 60 días"


# ---------------------------------------------------------------------------
# Higiene
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("archivo", [REUTILIZABLE, *LLAMADORES])
def test_el_yaml_es_valido(archivo):
    assert cargar(archivo)["name"]


def test_no_quedaron_los_workflows_viejos():
    """Si sobreviven, saldrían dos reportes: el del lunes y el del viernes."""
    for viejo in ["reporte-semanal.yml", "prueba-envio.yml", "envio_prueba.yml"]:
        assert not (WORKFLOWS / viejo).exists(), f"{viejo} sigue existiendo"


def test_no_hay_workflows_de_mas():
    presentes = {f.name for f in WORKFLOWS.glob("*.yml")}
    assert presentes == {REUTILIZABLE, *LLAMADORES}


def test_los_nombres_se_leen_en_orden_en_la_pantalla_de_actions():
    """1, 2 y 3: el orden en que conviene usarlos."""
    for archivo, numero in [("envio_desarrollo.yml", "1"), ("envio_test.yml", "2"),
                            ("reporte_semanal.yml", "3")]:
        assert cargar(archivo)["name"].startswith(numero)
