"""Valida los workflows de GitHub Actions.

Un error acá no lo agarra ningún linter de Python y recién se ve cuando la
corrida falla — que en el caso del productivo sería un viernes a la tarde, con
el reporte sin salir y nadie mirando.
"""
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
@pytest.mark.parametrize("archivo", LLAMADORES)
def test_los_inputs_sobreviven_a_una_corrida_programada(archivo):
    """El bug que rompio el ensayo del 22/09 y habria roto el envio del viernes.

    En un evento `schedule` el contexto `inputs` viene vacio: no hubo formulario
    que completar. Un `dry_run: ${{ inputs.dry_run }}` pelado le pasa una cadena
    vacia a un input declarado `type: boolean`, el job no arranca y GitHub lo
    reporta como "No jobs were run" -- sin un solo paso ejecutado, asi que
    tampoco sale el aviso de error, que vive dentro del job.
    """
    valores = list(cargar(archivo)["jobs"].values())[0]["with"]
    assert "||" in str(valores["dry_run"]), (
        f"{archivo}: dry_run tiene que traer un valor por defecto (p. ej. "
        "`${{ inputs.dry_run || false }}`) o el cron no arranca"
    )
    assert "||" in str(valores["fecha_corte"]), f"{archivo}: idem fecha_corte"


def test_test_y_desarrollo_no_tienen_cron():
    """Los dos circulos chicos se corren a mano; un cron ahi no tiene sentido."""
    for archivo in ["envio_desarrollo.yml", "envio_test.yml"]:
        assert "schedule" not in cargar(archivo)[ON], f"{archivo} no deberia tener cron"


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
