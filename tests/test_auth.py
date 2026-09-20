"""Tests de la capa de autenticacion (sin runtime de Streamlit).

Las contrasenas reales no estan aca: los tests arman su propia seccion
[auth_users] de mentira monkeypatcheando cargar_usuarios / _seccion_secrets.
"""
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from utils import auth

# Usuarios de prueba: NO son las contrasenas reales del dashboard
SECRETS_FALSOS = {
    "francobomone14_gmail_com": "clave-de-prueba-franco",
    "infoagropix_gmail_com": "clave-de-prueba-info",
    "matias21tossen_gmail_com": "clave-de-prueba-matias",
    "fabiocailletbois_gmail_com": "clave-de-prueba-fabio",
    "ggaletto_gg_gmail_com": "clave-de-prueba-german",
    "ignacio_ramello879_gmail_com": "clave-de-prueba-ignacio",
    "nicotobaldi55_gmail_com": "clave-de-prueba-nico",
}


@pytest.fixture
def secrets(monkeypatch):
    """Simula st.secrets["auth_users"] con los 3 usuarios autorizados."""
    monkeypatch.setattr(auth, "_seccion_secrets", lambda _n: dict(SECRETS_FALSOS))


@pytest.fixture
def sin_secrets(monkeypatch):
    monkeypatch.setattr(auth, "_seccion_secrets", lambda _n: {})


# ---------------------------------------------------------------------------
# Carga de usuarios desde secrets
# ---------------------------------------------------------------------------
def test_cargar_usuarios_mapea_las_claves_toml_a_emails(secrets):
    assert set(auth.cargar_usuarios()) == {
        "francobomone14@gmail.com",
        "infoagropix@gmail.com",
        "matias21tossen@gmail.com",
        "fabiocailletbois@gmail.com",
        "ggaletto.gg@gmail.com",
        "ignacio.ramello879@gmail.com",
        "nicotobaldi55@gmail.com",
    }


def test_sin_secrets_no_hay_ningun_usuario(sin_secrets):
    assert auth.cargar_usuarios() == {}


def test_usuario_sin_contrasena_cargada_queda_afuera(monkeypatch):
    monkeypatch.setattr(auth, "_seccion_secrets", lambda _n: {
        "francobomone14_gmail_com": "clave",
        "infoagropix_gmail_com": "",       # a medio configurar
        # matias directamente no esta
    })
    assert list(auth.cargar_usuarios()) == ["francobomone14@gmail.com"]


def test_un_email_ajeno_en_los_secrets_no_habilita_a_nadie(monkeypatch):
    """Solo entran los emails de EMAILS_AUTORIZADOS, no lo que diga el secret."""
    monkeypatch.setattr(auth, "_seccion_secrets", lambda _n: {
        "intruso_gmail_com": "clave-inventada",
    })
    assert auth.cargar_usuarios() == {}


def test_ningun_archivo_versionado_tiene_las_contrasenas():
    """Busca el patron de las claves de Agropix en todo el repo.

    Va como regex y no como literal para que este test no sea, el mismo, el
    lugar donde quedan escritas las contrasenas.
    """
    patron = re.compile(r"Agro[A-Za-z]+20\d\d#")
    raiz = Path(auth.__file__).resolve().parent.parent
    revisados = []
    for archivo in raiz.rglob("*"):
        partes = set(archivo.parts)
        if not archivo.is_file() or partes & {"venv", ".git", ".pytest_cache"}:
            continue
        if archivo.suffix not in {".py", ".txt", ".toml", ".md", ".json", ".ini"}:
            continue
        if archivo.name == "secrets.toml":
            continue  # local y fuera del repo: ahi SI van las contrasenas
        texto = archivo.read_text(encoding="utf-8", errors="ignore")
        revisados.append(archivo.name)
        assert not patron.search(texto), f"contrasena en texto plano en {archivo}"
    assert len(revisados) > 5


def test_el_secrets_local_no_se_versiona():
    raiz = Path(auth.__file__).resolve().parent.parent
    versionados = subprocess.run(
        ["git", "ls-files"], cwd=raiz, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert ".streamlit/secrets.toml" not in versionados
    assert ".streamlit/config.toml" in versionados  # el tema si viaja al deploy


# ---------------------------------------------------------------------------
# Verificacion de credenciales
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("email", [
    "francobomone14@gmail.com", "infoagropix@gmail.com", "matias21tossen@gmail.com",
    "fabiocailletbois@gmail.com", "ggaletto.gg@gmail.com",
    "ignacio.ramello879@gmail.com", "nicotobaldi55@gmail.com",
])
def test_los_siete_usuarios_entran(secrets, email):
    clave = auth.cargar_usuarios()[email]
    usuario = auth.verificar_credenciales(email, clave)
    assert usuario["email"] == email
    assert usuario["rol"] == ("admin" if email in auth.ADMINS else "usuario")


def test_email_se_normaliza(secrets):
    clave = SECRETS_FALSOS["francobomone14_gmail_com"]
    assert auth.verificar_credenciales("  FrancoBomone14@Gmail.COM ", clave)


@pytest.mark.parametrize("email,password", [
    ("francobomone14@gmail.com", "clave-de-prueba-FRANCO"),  # otra capitalizacion
    ("francobomone14@gmail.com", "clave-de-prueba-franc"),   # un caracter menos
    ("francobomone14@gmail.com", "clave-de-prueba-franco "),  # espacio de mas
    ("francobomone14@gmail.com", ""),                        # vacia
    ("hackers@hack.com", "wrong"),                           # usuario no autorizado
    ("", ""),
])
def test_credenciales_invalidas(secrets, email, password):
    assert auth.verificar_credenciales(email, password) is None


def test_sin_secrets_no_entra_ni_el_usuario_correcto(sin_secrets):
    assert auth.verificar_credenciales("francobomone14@gmail.com", "lo-que-sea") is None


# ---------------------------------------------------------------------------
# Sesion
# ---------------------------------------------------------------------------
class SesionFalsa(dict):
    """Imita lo que usa auth.py de st.session_state."""


@pytest.fixture
def sesion(monkeypatch):
    falsa = SesionFalsa()
    monkeypatch.setattr(auth.st, "session_state", falsa)
    return falsa


def test_sin_sesion_no_hay_acceso(sesion):
    assert auth.sesion_valida() is False
    assert auth.usuario_actual() is None


def test_sesion_activa_renueva_el_plazo(sesion):
    sesion.update(auth_ok=True, auth_email="francobomone14@gmail.com",
                  auth_ultimo_uso=datetime.now() - timedelta(minutes=29))
    assert auth.sesion_valida() is True
    assert datetime.now() - sesion["auth_ultimo_uso"] < timedelta(seconds=5)
    assert auth.usuario_actual()["email"] == "francobomone14@gmail.com"


def test_timeout_de_30_minutos_cierra_la_sesion(sesion):
    sesion.update(auth_ok=True, auth_email="francobomone14@gmail.com",
                  auth_ultimo_uso=datetime.now() - timedelta(minutes=31))
    assert auth.sesion_valida() is False
    assert "auth_ok" not in sesion
    assert sesion["auth_aviso_timeout"] is True


def test_sesion_sin_marca_de_tiempo_se_descarta(sesion):
    sesion.update(auth_ok=True, auth_email="x")  # session_state manipulado
    assert auth.sesion_valida() is False


def test_logout_borra_los_datos_del_cliente(sesion):
    sesion.update(auth_ok=True, auth_email="francobomone14@gmail.com",
                  auth_ultimo_uso=datetime.now(),
                  datos={"ventas": 1}, datos_completos={"ventas": 1}, _pdf={"bytes": b"x"})
    auth.cerrar_sesion()
    assert not any(c in sesion for c in auth.CLAVES_SESION + auth.CLAVES_DATOS)


def test_bloqueo_tras_cinco_intentos_fallidos(sesion):
    for _ in range(auth.MAX_INTENTOS):
        auth._registrar_fallo("hackers@hack.com")
    assert auth._bloqueado() is True

    sesion["auth_bloqueo_hasta"] = datetime.now() - timedelta(seconds=1)  # bloqueo vencido
    assert auth._bloqueado() is False
    assert sesion["auth_intentos"] == 0


# ---------------------------------------------------------------------------
# Rol de administrador
# ---------------------------------------------------------------------------
def test_los_admins_son_los_declarados():
    assert auth.es_admin("infoagropix@gmail.com")
    assert auth.es_admin("nfoagropix@gmail.com"), "la variante sin la i tambien es admin"


@pytest.mark.parametrize("email", [
    "francobomone14@gmail.com", "matias21tossen@gmail.com", "nicotobaldi55@gmail.com",
])
def test_el_resto_no_es_admin(email):
    assert not auth.es_admin(email)


def test_es_admin_normaliza_el_email():
    assert auth.es_admin("  INFOAGROPIX@Gmail.com ")


def test_todos_los_admins_estan_autorizados():
    """Un admin que no este en EMAILS_AUTORIZADOS no podria ni loguearse."""
    for email in auth.ADMINS:
        assert email in auth.EMAILS_AUTORIZADOS


def test_el_login_deja_el_rol_en_la_sesion(secrets, sesion, monkeypatch):
    monkeypatch.setattr(auth, "_seccion_secrets",
                        lambda _n: {"infoagropix_gmail_com": "clave-admin"})
    usuario = auth.verificar_credenciales("infoagropix@gmail.com", "clave-admin")
    assert usuario["rol"] == "admin"

    sesion.update(auth_ok=True, auth_email=usuario["email"], auth_rol=usuario["rol"],
                  auth_ultimo_uso=datetime.now())
    assert auth.sesion_es_admin() is True
    assert auth.usuario_actual()["rol"] == "admin"


def test_un_usuario_comun_no_es_admin_en_la_sesion(sesion):
    sesion.update(auth_ok=True, auth_email="matias21tossen@gmail.com", auth_rol="usuario",
                  auth_ultimo_uso=datetime.now())
    assert auth.sesion_es_admin() is False


def test_sin_sesion_no_hay_admin(sesion):
    assert auth.sesion_es_admin() is False


def test_el_logout_borra_el_rol(sesion):
    sesion.update(auth_ok=True, auth_email="infoagropix@gmail.com", auth_rol="admin",
                  auth_ultimo_uso=datetime.now())
    auth.cerrar_sesion()
    assert "auth_rol" not in sesion
    assert auth.sesion_es_admin() is False
