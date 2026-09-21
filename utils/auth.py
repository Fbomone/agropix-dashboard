"""Autenticacion privada para apps Streamlit (dashboard Agropix).

Uso minimo en el archivo principal, despues de st.set_page_config():

    from utils.auth import check_authentication, logout_button

    usuario = check_authentication()   # corta la ejecucion si no hay sesion valida
    with st.sidebar:
        logout_button()

Donde viven las contrasenas
---------------------------
En NINGUN archivo del repositorio. Se leen de st.secrets["auth_users"], que es:

- en local : .streamlit/secrets.toml, que esta en .gitignore y nunca se pushea
- en Cloud : Settings -> Secrets, cifrados del lado de Streamlit

Si esa seccion no existe, cargar_usuarios() devuelve {} y no entra nadie: no hay
usuario de emergencia ni contrasena por defecto en el codigo.

Las contrasenas se guardan tal cual (no hasheadas) porque asi se administran
desde el panel de Streamlit Cloud sin herramientas extra. La consecuencia a
tener presente: quien tenga acceso a ese panel las ve en claro, asi que no
conviene reusar en Agropix una contrasena personal de otro servicio.

Otras decisiones
----------------
- La sesion vive en st.session_state: es por pestania del navegador y muere al
  cerrarla o al refrescar. No se emiten cookies ni tokens persistentes.
- HTTPS lo provee Streamlit Cloud; este modulo asume transporte cifrado.

El modulo no importa nada del proyecto: se puede copiar a otra app Streamlit.
"""
from __future__ import annotations

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

ARCHIVO_AUDITORIA = Path(os.getenv("AGROPIX_AUDIT_LOG", "data/auditoria.log"))

SECCION_SECRETS = "auth_users"

# Una sola contrasena para todo el equipo, en los secrets como AUTH_PASSWORD.
# Alcanza con eso para habilitar a todos; [auth_users] queda para pisarsela a
# alguien en particular. Lo que se pierde: si se filtra, hay que rotarla para
# todos. Lo que NO se pierde: la auditoria sigue distinguiendo por email, asi
# que igual se ve quien entro y cuando.
CLAVE_COMUN = "AUTH_PASSWORD"

# Quien puede entrar. El valor es la clave dentro de [auth_users]: es el email
# con "@" y "." cambiados por "_", porque TOML no los admite en una clave simple.
# Para dar de alta a alguien: agregar la linea aca y su contrasena en los secrets.
# Sin contrasena cargada el email queda listado pero no entra (ver cargar_usuarios).
EMAILS_AUTORIZADOS: dict[str, str] = {
    "francobomone14@gmail.com": "francobomone14_gmail_com",
    "infoagropix@gmail.com": "infoagropix_gmail_com",
    "matias21tossen@gmail.com": "matias21tossen_gmail_com",
    "fabiocailletbois@gmail.com": "fabiocailletbois_gmail_com",
    "ggaletto.gg@gmail.com": "ggaletto_gg_gmail_com",
    "ignacio.ramello879@gmail.com": "ignacio_ramello879_gmail_com",
    "nicotobaldi55@gmail.com": "nicotobaldi55_gmail_com",
}

# Acceso al panel de administracion. Todos los demas ven el mismo dashboard: el
# rol solo habilita el panel, no cambia los datos que se muestran.
ADMINS: tuple[str, ...] = ("francobomone14@gmail.com", "infoagropix@gmail.com")

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
def _seccion_secrets(nombre: str) -> dict:
    """st.secrets[nombre] como dict, o {} si no hay secrets configurados.

    Sin archivo de secrets Streamlit levanta excepcion en vez de devolver None,
    de ahi el try/except.
    """
    try:
        return dict(st.secrets.get(nombre) or {})
    except Exception:
        return {}


def _password_comun() -> str:
    """AUTH_PASSWORD de los secrets: la clave compartida por todo el equipo."""
    try:
        return str(st.secrets.get(CLAVE_COMUN, "") or "").strip()
    except Exception:
        return ""


def cargar_usuarios() -> dict[str, str]:
    """Usuarios autorizados desde Streamlit Secrets, como {email: contrasena}.

    Cada email de EMAILS_AUTORIZADOS usa su contrasena propia de [auth_users]
    si la tiene, y si no la compartida (AUTH_PASSWORD). Sin ninguna de las dos
    el email queda listado pero no entra: un secret a medio configurar no
    habilita a nadie.

    En local se lee de .streamlit/secrets.toml; en Streamlit Cloud, de
    Settings -> Secrets. Se relee en cada rerun a proposito: cambiar un secret
    en Cloud tiene efecto sin necesidad de un nuevo deploy.
    """
    seccion = _seccion_secrets(SECCION_SECRETS)
    comun = _password_comun()
    usuarios = {
        email: (str(seccion.get(clave, "") or "").strip() or comun)
        for email, clave in EMAILS_AUTORIZADOS.items()
    }
    return {email: password for email, password in usuarios.items() if password}


def normalizar_email(email: str) -> str:
    """Minusculas y sin espacios, para que el login no dependa de como se tipeo."""
    return unicodedata.normalize("NFC", (email or "").strip().lower())


def es_admin(email: str) -> bool:
    """True si el email tiene acceso al panel de administracion."""
    return normalizar_email(email) in ADMINS


def verificar_credenciales(email: str, password: str) -> dict[str, str] | None:
    """Datos del usuario si el par email/contrasena es valido, sino None."""
    if not password:
        return None
    limpio = normalizar_email(email)
    esperada = cargar_usuarios().get(limpio)
    if not esperada:
        return None
    # compare_digest: comparacion de tiempo constante
    if hmac.compare_digest(password.encode("utf-8"), esperada.encode("utf-8")):
        return {"email": limpio, "rol": "admin" if es_admin(limpio) else "usuario"}
    return None


# ---------------------------------------------------------------------------
# Estado de la sesion
# ---------------------------------------------------------------------------
CLAVES_SESION = ("auth_ok", "auth_email", "auth_rol", "auth_inicio", "auth_ultimo_uso")

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


def sesion_valida() -> bool:
    """True si hay sesion valida. Cierra la sesion si paso el timeout de inactividad.

    Es la verificacion pura, sin dibujar nada: la porteria de la app es
    check_authentication().
    """
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
    """Datos del usuario logueado (email, rol), o None si no hay sesion."""
    if not st.session_state.get("auth_ok"):
        return None
    return {"email": st.session_state.get("auth_email", ""),
            "rol": st.session_state.get("auth_rol", "usuario")}


def sesion_es_admin() -> bool:
    """True si quien esta logueado puede ver el panel de administracion."""
    usuario = usuario_actual()
    return bool(usuario) and usuario["rol"] == "admin"


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
    """Dibuja la pantalla de login. No corta la ejecucion: para eso esta check_authentication()."""
    _estilos()
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        st.html(f"""
        <div class="agpx-login">
          <h1>🌱 {EMPRESA} Dashboard</h1>
          <p class="agpx-sub">Acceso privado — ingresá con tu usuario autorizado.</p>
          <div class="agpx-confidencial">
            <strong>⚠️ CONFIDENCIAL</strong><br>
            Información de facturación de {EMPRESA}. El acceso es personal, queda
            registrado y no debe compartirse ni redistribuirse.
          </div>
        </div>
        """)

        if not cargar_usuarios():
            # Sin secrets no puede entrar nadie: conviene decirlo en pantalla en
            # vez de rechazar todos los intentos como si fueran contrasenas malas
            st.error(
                "No hay usuarios configurados: falta la sección `[auth_users]` en los "
                "secrets. En Streamlit Cloud se carga en **Settings → Secrets**; en "
                "local, en `.streamlit/secrets.toml`.",
                icon="⚙️",
            )

        if st.session_state.pop("auth_aviso_timeout", False):
            st.info(
                f"Tu sesión se cerró por {int(TIMEOUT_SESION.total_seconds() // 60)} minutos "
                "de inactividad. Volvé a ingresar.",
                icon="⏳",
            )

        with st.form("agpx_login"):
            email = st.text_input("Email", placeholder="tu-email@gmail.com")
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
                    auth_email=usuario["email"],
                    auth_rol=usuario["rol"],
                    auth_inicio=ahora,
                    auth_ultimo_uso=ahora,
                    auth_intentos=0,
                )
                audit_log("login_ok", usuario["email"], usuario["rol"])
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


def check_authentication() -> dict[str, str]:
    """Portero de la app: muestra el login y corta la ejecucion si no hay sesion valida.

    Devuelve los datos del usuario logueado, asi el archivo principal puede
    usarlos en la bienvenida:

        usuario = check_authentication()
        st.caption(f"Bienvenido: {usuario['email']}")
    """
    if not sesion_valida():
        login_page()
        st.stop()
    return usuario_actual()  # type: ignore[return-value]


def logout_button() -> None:
    """Identidad del usuario + boton de salir. Pensado para usar dentro de st.sidebar."""
    usuario = usuario_actual()
    if not usuario:
        return
    st.divider()
    st.caption(f"👤 {usuario['email']}")
    st.caption(f"🔐 {'Administrador' if usuario['rol'] == 'admin' else 'Usuario'}")
    st.caption(f"⏳ La sesión se cierra tras {_minutos_restantes()} min sin actividad.")
    if st.button("🚪 Cerrar sesión", width="stretch", key="agpx_logout"):
        cerrar_sesion("logout")
        st.rerun()
    st.caption("🔒 Datos confidenciales de Agropix.")


if __name__ == "__main__":
    # Imprime el esqueleto de la seccion [auth_users] para pegar en los secrets.
    # No incluye contrasenas: se completan a mano donde corresponda.
    print(f"[{SECCION_SECRETS}]")
    for email, clave in EMAILS_AUTORIZADOS.items():
        print(f'{clave} = ""   # {email}')
