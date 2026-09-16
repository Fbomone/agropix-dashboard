"""Autenticacion privada para apps Streamlit (dashboard Agropix).

Uso minimo en el archivo principal, despues de st.set_page_config():

    from utils.auth import logout_button, requiere_login

    requiere_login()          # corta la ejecucion si no hay sesion valida
    with st.sidebar:
        logout_button()

Decisiones de seguridad
-----------------------
- Las contrasenas NO viven en el repositorio: se guardan como hash PBKDF2-SHA256
  con salt por usuario (240.000 iteraciones, hashlib de la stdlib). Un hash
  filtrado no permite iniciar sesion ni recuperar la contrasena original.
- La lista de usuarios se puede sobreescribir por completo desde
  st.secrets["usuarios"], asi se rotan claves sin tocar el codigo ni volver a
  deployar (ver .streamlit/secrets.toml.example).
- La sesion vive en st.session_state: es por pestania del navegador y muere al
  cerrarla o al refrescar. No se emiten cookies ni tokens persistentes.
- HTTPS lo provee Streamlit Cloud; este modulo asume transporte cifrado.

El modulo no importa nada del proyecto: se puede copiar a otra app Streamlit.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
EMPRESA = "Agropix"
CONTACTO_SOPORTE = "soporte@agropix.com"

VERDE, AZUL, GRIS = "#2E7D32", "#1565C0", "#5F6B7A"

TIMEOUT_SESION = timedelta(minutes=30)   # inactividad tolerada antes del logout
MAX_INTENTOS = 5                         # intentos fallidos antes del bloqueo
BLOQUEO = timedelta(minutes=5)           # duracion del bloqueo por fuerza bruta

ITERACIONES_PBKDF2 = 240_000
ARCHIVO_AUDITORIA = Path(os.getenv("AGROPIX_AUDIT_LOG", "data/auditoria.log"))

# Usuarios por defecto. `salt` y `hash` son base64; se generan con
# `python -m utils.auth "NuevaPassword"` y se pegan aca o en st.secrets.
USUARIOS_AUTORIZADOS: dict[str, dict[str, str]] = {
    "dueno@agropix.com": {
        "nombre": "Dueño",
        "rol": "admin",
        "salt": "6ID/4B6xrCK3xkU0xgYTrg==",
        "hash": "bXgnz1q8kejoJ0jk7LsFlSsMzUk9EFIZN+9Gu1uofhk=",
    },
    "gerente@agropix.com": {
        "nombre": "Gerencia",
        "rol": "gerente",
        "salt": "0evmkW8s/L7Fpb5qXglzCw==",
        "hash": "SrmcBKq29iqbiZeZf0Vu1SQBFkEboy6NHSAz0JaBuuY=",
    },
    "vendedor@agropix.com": {
        "nombre": "Ventas",
        "rol": "vendedor",
        "salt": "oAO98l0CL78hRyfKZbcnEQ==",
        "hash": "cfiWh6ee3+6QV9e8o9TIalqex6GsRTZg3Xfibt+iAw8=",
    },
}

# "dueño@agropix.com" no es una direccion valida para la mayoria de los
# servidores de correo (la parte local deberia ser ASCII) y es incomoda de
# tipear, asi que el usuario canonico es "dueno@" y el alias con ñ tambien entra.
ALIAS_USUARIOS = {"dueño@agropix.com": "dueno@agropix.com"}

# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------
_logger = logging.getLogger("agropix.auth")


def audit_log(evento: str, email: str = "-", detalle: str = "") -> None:
    """Registra un evento de acceso.

    Escribe en el logger estandar (queda en los logs de Streamlit Cloud, que es
    lo unico realmente persistente alla) y, si el disco lo permite, agrega una
    linea a ARCHIVO_AUDITORIA para revisarla en local. El filesystem de
    Streamlit Cloud es efimero: se borra en cada reinicio del contenedor.
    """
    momento = datetime.now().isoformat(timespec="seconds")
    linea = f"{momento}\t{evento}\t{email}\t{detalle}".rstrip()
    _logger.info("AUDIT %s", linea)
    try:
        ARCHIVO_AUDITORIA.parent.mkdir(parents=True, exist_ok=True)
        with ARCHIVO_AUDITORIA.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass  # sin disco de escritura alcanza con el logger


# ---------------------------------------------------------------------------
# Credenciales
# ---------------------------------------------------------------------------
def hash_password(password: str, salt: bytes) -> bytes:
    """PBKDF2-SHA256 de `password` con `salt`."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERACIONES_PBKDF2)


def generar_credencial(password: str) -> tuple[str, str]:
    """Devuelve (salt_b64, hash_b64) listos para pegar en USUARIOS_AUTORIZADOS."""
    salt = os.urandom(16)
    return (
        base64.b64encode(salt).decode(),
        base64.b64encode(hash_password(password, salt)).decode(),
    )


def usuarios() -> dict[str, dict[str, str]]:
    """Usuarios vigentes: los de st.secrets["usuarios"] si existen, sino los del codigo."""
    try:
        desde_secrets = st.secrets.get("usuarios")
    except Exception:
        # Sin secrets.toml Streamlit levanta excepcion en vez de devolver None
        desde_secrets = None
    if desde_secrets:
        return {str(k).strip().lower(): dict(v) for k, v in dict(desde_secrets).items()}
    return USUARIOS_AUTORIZADOS


def normalizar_email(email: str) -> str:
    """Minusculas, sin espacios y con los alias resueltos al usuario canonico."""
    limpio = unicodedata.normalize("NFC", (email or "").strip().lower())
    return ALIAS_USUARIOS.get(limpio, limpio)


def verificar_credenciales(email: str, password: str) -> dict[str, str] | None:
    """Datos del usuario si el par email/password es valido, sino None."""
    usuario = usuarios().get(normalizar_email(email))
    if not usuario or not password:
        return None
    try:
        salt = base64.b64decode(usuario["salt"])
        esperado = base64.b64decode(usuario["hash"])
    except (KeyError, ValueError):
        _logger.error("Usuario %s mal configurado (salt/hash invalidos)", email)
        return None
    # compare_digest: comparacion de tiempo constante
    if hmac.compare_digest(hash_password(password, salt), esperado):
        return usuario
    return None


# ---------------------------------------------------------------------------
# Estado de la sesion
# ---------------------------------------------------------------------------
CLAVES_SESION = ("auth_ok", "auth_email", "auth_nombre", "auth_rol", "auth_inicio", "auth_ultimo_uso")

# Datos del cliente cacheados en la sesion: no deben sobrevivir al logout
CLAVES_DATOS = ("datos", "datos_completos", "_pdf")


def _minutos_restantes() -> int:
    vencimiento = st.session_state.get("auth_ultimo_uso", datetime.min) + TIMEOUT_SESION
    return max(0, int((vencimiento - datetime.now()).total_seconds() // 60))


def cerrar_sesion(motivo: str = "logout") -> None:
    """Borra la sesion y los datos cacheados, dejando registro del motivo."""
    email = st.session_state.get("auth_email", "-")
    if st.session_state.get("auth_ok"):
        audit_log(f"sesion_cerrada_{motivo}", email)
    for clave in CLAVES_SESION + CLAVES_DATOS:
        st.session_state.pop(clave, None)


def check_authentication() -> bool:
    """True si hay sesion valida. Cierra la sesion si paso el timeout de inactividad."""
    if not st.session_state.get("auth_ok"):
        return False
    ultimo_uso = st.session_state.get("auth_ultimo_uso")
    if not isinstance(ultimo_uso, datetime) or datetime.now() - ultimo_uso > TIMEOUT_SESION:
        cerrar_sesion("timeout")
        st.session_state["auth_aviso_timeout"] = True
        return False
    st.session_state["auth_ultimo_uso"] = datetime.now()  # actividad: renueva el plazo
    return True


def usuario_actual() -> dict[str, str] | None:
    """Datos del usuario logueado (email, nombre, rol) o None."""
    if not st.session_state.get("auth_ok"):
        return None
    return {
        "email": st.session_state.get("auth_email", ""),
        "nombre": st.session_state.get("auth_nombre", ""),
        "rol": st.session_state.get("auth_rol", ""),
    }


def _bloqueado() -> bool:
    hasta = st.session_state.get("auth_bloqueo_hasta")
    if isinstance(hasta, datetime) and datetime.now() < hasta:
        return True
    if hasta:  # bloqueo vencido: se limpia el contador
        st.session_state.pop("auth_bloqueo_hasta", None)
        st.session_state["auth_intentos"] = 0
    return False


def _registrar_fallo(email: str) -> None:
    intentos = st.session_state.get("auth_intentos", 0) + 1
    st.session_state["auth_intentos"] = intentos
    audit_log("login_fallido", email or "-", f"intento {intentos}/{MAX_INTENTOS}")
    if intentos >= MAX_INTENTOS:
        st.session_state["auth_bloqueo_hasta"] = datetime.now() + BLOQUEO
        audit_log("bloqueo_por_intentos", email or "-", f"{int(BLOQUEO.total_seconds() // 60)} min")


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------
def _estilos() -> None:
    st.html(f"""
    <style>
      /* Sin sesion no se muestra la navegacion multipagina */
      [data-testid="stSidebarNav"] {{ display: none; }}
      .agpx-login {{
        border: 1px solid #E3E8EF; border-top: 4px solid {VERDE};
        border-radius: 12px; padding: 1.5rem 1.75rem; margin-bottom: 1rem;
        background: #FFFFFF; box-shadow: 0 2px 10px rgba(16, 24, 40, .06);
      }}
      .agpx-login h1 {{ font-size: 1.6rem; margin: 0 0 .25rem 0; color: {VERDE}; }}
      .agpx-login p.agpx-sub {{ margin: 0; color: {GRIS}; font-size: .95rem; }}
      .agpx-confidencial {{
        display: block; margin-top: 1rem; padding: .6rem .8rem;
        border-left: 4px solid {AZUL}; border-radius: 4px;
        background: #EEF4FB; color: #123B66; font-size: .85rem; line-height: 1.45;
      }}
      .agpx-confidencial strong {{ letter-spacing: .04em; }}
      .agpx-pie {{ text-align: center; color: {GRIS}; font-size: .8rem; margin-top: .5rem; }}
      .agpx-pie a {{ color: {AZUL}; }}
    </style>
    """)


def login_page() -> None:
    """Dibuja la pantalla de login. No corta la ejecucion: para eso esta requiere_login()."""
    _estilos()
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        st.html(f"""
        <div class="agpx-login">
          <h1>🌱 {EMPRESA} Dashboard</h1>
          <p class="agpx-sub">Acceso privado — ingresá con tu usuario corporativo.</p>
          <div class="agpx-confidencial">
            <strong>⚠️ CONFIDENCIAL</strong><br>
            Información de facturación de {EMPRESA}. El acceso es personal, queda
            registrado y no debe compartirse ni redistribuirse.
          </div>
        </div>
        """)

        if st.session_state.pop("auth_aviso_timeout", False):
            st.info(
                f"Tu sesión se cerró por {int(TIMEOUT_SESION.total_seconds() // 60)} minutos "
                "de inactividad. Volvé a ingresar.",
                icon="⏳",
            )

        with st.form("agpx_login"):
            email = st.text_input("Email", placeholder="nombre@agropix.com")
            password = st.text_input("Contraseña", type="password")
            enviar = st.form_submit_button("Ingresar", type="primary", width="stretch")

        if enviar:
            if _bloqueado():
                falta = st.session_state["auth_bloqueo_hasta"] - datetime.now()
                st.error(
                    f"Demasiados intentos fallidos. Probá de nuevo en "
                    f"{int(falta.total_seconds() // 60) + 1} minuto(s).",
                    icon="🚫",
                )
            elif usuario := verificar_credenciales(email, password):
                ahora = datetime.now()
                st.session_state.update(
                    auth_ok=True,
                    auth_email=normalizar_email(email),
                    auth_nombre=usuario.get("nombre", ""),
                    auth_rol=usuario.get("rol", ""),
                    auth_inicio=ahora,
                    auth_ultimo_uso=ahora,
                    auth_intentos=0,
                )
                audit_log("login_ok", st.session_state["auth_email"], usuario.get("rol", ""))
                st.balloons()
                st.rerun()
            else:
                _registrar_fallo(normalizar_email(email))
                restantes = MAX_INTENTOS - st.session_state.get("auth_intentos", 0)
                st.error(
                    "Email o contraseña incorrectos."
                    + (f" Te quedan {restantes} intento(s)." if 0 < restantes <= 2 else ""),
                    icon="🔒",
                )

        st.divider()
        st.html(
            f'<p class="agpx-pie">¿Problemas para entrar? Escribí a '
            f'<a href="mailto:{CONTACTO_SOPORTE}">{CONTACTO_SOPORTE}</a></p>'
        )


def requiere_login() -> dict[str, str]:
    """Portero de la app: muestra el login y corta la ejecucion si no hay sesion valida.

    Devuelve los datos del usuario cuando la sesion es valida.
    """
    if not check_authentication():
        login_page()
        st.stop()
    return usuario_actual()  # type: ignore[return-value]


def logout_button() -> None:
    """Identidad del usuario + boton de salir. Pensado para usar dentro de st.sidebar."""
    usuario = usuario_actual()
    if not usuario:
        return
    st.divider()
    st.caption(f"👤 **{usuario['nombre']}** · {usuario['rol']}")
    st.caption(usuario["email"])
    st.caption(f"⏳ La sesión se cierra tras {_minutos_restantes()} min sin actividad.")
    if st.button("🚪 Cerrar sesión", width="stretch", key="agpx_logout"):
        cerrar_sesion("logout")
        st.rerun()
    st.caption("🔒 Datos confidenciales de Agropix.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print('Uso: python -m utils.auth "LaPasswordNueva"')
        raise SystemExit(1)
    salt_b64, hash_b64 = generar_credencial(sys.argv[1])
    print(f'"salt": "{salt_b64}",')
    print(f'"hash": "{hash_b64}",')
