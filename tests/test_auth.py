"""Tests de la capa de autenticacion (sin runtime de Streamlit).

Los tests que necesitan las contrasenas reales las leen del entorno: este
archivo se versiona, asi que no puede contenerlas. Para correrlos:

    AGROPIX_TEST_PASS_DUENO=... AGROPIX_TEST_PASS_GERENTE=... \\
    AGROPIX_TEST_PASS_VENDEDOR=... pytest

Sin esas variables esos tests se saltean; el resto corre siempre.
"""
import base64
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from utils import auth

PASSWORDS = {
    email: os.getenv(var, "")
    for email, var in [
        ("dueno@agropix.com", "AGROPIX_TEST_PASS_DUENO"),
        ("gerente@agropix.com", "AGROPIX_TEST_PASS_GERENTE"),
        ("vendedor@agropix.com", "AGROPIX_TEST_PASS_VENDEDOR"),
    ]
}

sin_passwords = pytest.mark.skipif(
    not all(PASSWORDS.values()),
    reason="faltan las variables AGROPIX_TEST_PASS_* con las contrasenas reales",
)


@sin_passwords
@pytest.mark.parametrize("email", list(PASSWORDS))
def test_credenciales_validas(email):
    usuario = auth.verificar_credenciales(email, PASSWORDS[email])
    assert usuario is not None
    assert usuario["rol"]


@sin_passwords
@pytest.mark.parametrize("mutar", [
    lambda p: p.lower(),        # otra capitalizacion
    lambda p: "",               # password vacia
    lambda p: p + " ",          # espacio de mas
    lambda p: p[:-1],           # un caracter menos
])
def test_password_incorrecta_no_entra(mutar):
    correcta = PASSWORDS["dueno@agropix.com"]
    mutada = mutar(correcta)
    assert mutada != correcta, "la mutacion no cambio la password"
    assert auth.verificar_credenciales("dueno@agropix.com", mutada) is None


@pytest.mark.parametrize("email,password", [
    ("nadie@agropix.com", "CualquieraQueSea1!"),  # usuario inexistente
    ("dueno@agropix.com", ""),                    # password vacia
    ("", ""),
])
def test_credenciales_invalidas(email, password):
    assert auth.verificar_credenciales(email, password) is None


def test_email_se_normaliza_y_alias_con_enie_apunta_al_usuario_canonico():
    assert auth.normalizar_email("  DUEÑO@Agropix.COM ") == "dueno@agropix.com"
    assert auth.normalizar_email("dueno@agropix.com") in auth.USUARIOS_AUTORIZADOS


@sin_passwords
def test_alias_con_enie_permite_entrar():
    assert auth.verificar_credenciales("DUEÑO@Agropix.com", PASSWORDS["dueno@agropix.com"])


@sin_passwords
def test_ningun_archivo_versionado_tiene_las_passwords_en_texto_plano():
    raiz = Path(auth.__file__).resolve().parent.parent
    revisados = 0
    for archivo in raiz.rglob("*"):
        if not archivo.is_file() or "venv" in archivo.parts or ".git" in archivo.parts:
            continue
        if archivo.suffix not in {".py", ".txt", ".toml", ".md", ".json", ".ini"}:
            continue
        texto = archivo.read_text(encoding="utf-8", errors="ignore")
        revisados += 1
        for password in PASSWORDS.values():
            assert password not in texto, f"password en texto plano en {archivo}"
    assert revisados > 5


def test_hash_usa_salt_distinto_por_usuario():
    salts = {u["salt"] for u in auth.USUARIOS_AUTORIZADOS.values()}
    assert len(salts) == len(auth.USUARIOS_AUTORIZADOS)


def test_generar_credencial_verifica_contra_su_password():
    salt_b64, hash_b64 = auth.generar_credencial("OtraClave!2026")
    salt = base64.b64decode(salt_b64)
    assert base64.b64encode(auth.hash_password("OtraClave!2026", salt)).decode() == hash_b64
    assert base64.b64encode(auth.hash_password("otraclave!2026", salt)).decode() != hash_b64


class SesionFalsa(dict):
    """Imita lo que usa auth.py de st.session_state."""


@pytest.fixture
def sesion(monkeypatch):
    falsa = SesionFalsa()
    monkeypatch.setattr(auth.st, "session_state", falsa)
    return falsa


def test_sin_sesion_no_hay_acceso(sesion):
    assert auth.check_authentication() is False
    assert auth.usuario_actual() is None


def test_sesion_activa_renueva_el_plazo(sesion):
    sesion.update(auth_ok=True, auth_ultimo_uso=datetime.now() - timedelta(minutes=29),
                  auth_email="dueno@agropix.com", auth_nombre="Dueño", auth_rol="admin")
    assert auth.check_authentication() is True
    assert datetime.now() - sesion["auth_ultimo_uso"] < timedelta(seconds=5)
    assert auth.usuario_actual()["rol"] == "admin"


def test_timeout_de_30_minutos_cierra_la_sesion(sesion):
    sesion.update(auth_ok=True, auth_email="dueno@agropix.com",
                  auth_ultimo_uso=datetime.now() - timedelta(minutes=31))
    assert auth.check_authentication() is False
    assert "auth_ok" not in sesion
    assert sesion["auth_aviso_timeout"] is True


def test_sesion_sin_marca_de_tiempo_se_descarta(sesion):
    sesion.update(auth_ok=True, auth_email="x")  # session_state manipulado
    assert auth.check_authentication() is False


def test_logout_borra_los_datos_del_cliente(sesion):
    sesion.update(auth_ok=True, auth_email="dueno@agropix.com", auth_ultimo_uso=datetime.now(),
                  datos={"ventas": 1}, datos_completos={"ventas": 1}, _pdf={"bytes": b"x"})
    auth.cerrar_sesion()
    assert not any(c in sesion for c in auth.CLAVES_SESION + auth.CLAVES_DATOS)


def test_bloqueo_tras_cinco_intentos_fallidos(sesion):
    for _ in range(auth.MAX_INTENTOS):
        auth._registrar_fallo("atacante@agropix.com")
    assert auth._bloqueado() is True

    sesion["auth_bloqueo_hasta"] = datetime.now() - timedelta(seconds=1)  # bloqueo vencido
    assert auth._bloqueado() is False
    assert sesion["auth_intentos"] == 0
