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
  cerrarla o al refrescar. Para no pedir la contrasena cada vez, el login deja
  (si se tilda "Recordarme") una cookie firmada que dura DURACION_RECORDAR y
  rearma la sesion al volver a abrir el link. La firma usa la contrasena del
  usuario: cambiar AUTH_PASSWORD (o la propia) invalida todas sus cookies.
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

VERDE, AZUL, GRIS = "#2E7D32", "#1565C0", "#5F6B7A"

TIMEOUT_SESION = timedelta(minutes=30)   # inactividad tolerada antes del logout
MAX_INTENTOS = 5                         # intentos fallidos antes del bloqueo
BLOQUEO = timedelta(minutes=5)           # duracion del bloqueo por fuerza bruta

COOKIE_SESION = "agpx_sesion"            # "Recordarme": evita reloguearse en cada visita
DURACION_RECORDAR = timedelta(days=30)

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
# Recordarme (cookie firmada)
# ---------------------------------------------------------------------------
def _firma(email: str, vence: int, clave: str) -> str:
    return hmac.new(clave.encode("utf-8"), f"{email}|{vence}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def crear_token(email: str, ahora: datetime | None = None) -> str | None:
    """Valor de la cookie "Recordarme" para email, o None si no esta autorizado.

    Es "email|vencimiento|firma" en base64url (sin caracteres raros para una
    cookie). La firma va con la contrasena vigente del usuario.
    """
    limpio = normalizar_email(email)
    clave = cargar_usuarios().get(limpio)
    if not clave:
        return None
    vence = int(((ahora or datetime.now()) + DURACION_RECORDAR).timestamp())
    crudo = f"{limpio}|{vence}|{_firma(limpio, vence, clave)}"
    return base64.urlsafe_b64encode(crudo.encode("utf-8")).decode("ascii")


def verificar_token(token: str | None, ahora: datetime | None = None) -> dict[str, str] | None:
    """Datos del usuario si la cookie es valida y no vencio, sino None."""
    try:
        email, vence_txt, firma = base64.urlsafe_b64decode(
            (token or "").encode("ascii")).decode("utf-8").split("|")
        vence = int(vence_txt)
    except (ValueError, UnicodeError):
        return None
    if vence < (ahora or datetime.now()).timestamp():
        return None
    clave = cargar_usuarios().get(email)
    if not clave or not hmac.compare_digest(firma, _firma(email, vence, clave)):
        return None
    return {"email": email, "rol": "admin" if es_admin(email) else "usuario"}


def _cookie_del_navegador() -> str | None:
    """La cookie "Recordarme", vista desde el servidor o desde el navegador.

    st.context.cookies es lo que llego al conectar, pero Streamlit Cloud no
    siempre la reenvia: por eso tambien vale la que leyo el JS del componente.
    Ninguna de las dos ve un logout sin recargar, de ahi la marca
    auth_cookie_revocada en cerrar_sesion().
    """
    try:
        valor = st.context.cookies.get(COOKIE_SESION)
    except Exception:
        valor = None
    if isinstance(valor, str) and valor:  # AppTest devuelve un mock
        return valor
    return st.session_state.get("auth_cookie_navegador") or None


# Lee y escribe la cookie en el navegador y le devuelve a Python lo que hay.
# window.__agpxCookie evita mandar el mismo valor en cada rerun (seria un loop).
_JS_COOKIE = """
export default function (component) {
  const { data, setStateValue } = component;
  const nombre = data.nombre;
  if (typeof data.escribir === "string") {
    const vida = data.escribir ? data.segundos : 0;
    document.cookie = `${nombre}=${data.escribir}; max-age=${vida}; path=/; SameSite=Lax; Secure`;
  }
  const par = document.cookie.split("; ").find((c) => c.startsWith(nombre + "="));
  const valor = par ? par.slice(nombre.length + 1) : "";
  if (window.__agpxCookie !== valor) {
    window.__agpxCookie = valor;
    setStateValue("valor", valor);
  }
}
"""


def _sincronizar_cookie() -> None:
    """Monta el componente de la cookie y guarda en la sesion lo que leyo.

    Graba (token) o borra ("") la cookie que dejo pendiente el login o el
    logout. Se monta en cada run, con key fija, para que su estado persista.
    """
    pendiente = st.session_state.pop("auth_cookie_pendiente", None)
    try:
        componente = st.components.v2.component("agpx_cookie", js=_JS_COOKIE)
        resultado = componente(
            key="agpx_cookie",
            data={"nombre": COOKIE_SESION, "escribir": pendiente,
                  "segundos": int(DURACION_RECORDAR.total_seconds())},
            default={"valor": None},
            on_valor_change=lambda: None,
        )
        valor = getattr(resultado, "valor", None)
    except Exception:
        _logger.exception("no se pudo montar el componente de la cookie")
        return
    if isinstance(valor, str):
        st.session_state["auth_cookie_navegador"] = valor


# ---------------------------------------------------------------------------
# Estado de la sesion
# ---------------------------------------------------------------------------
CLAVES_SESION = ("auth_ok", "auth_email", "auth_rol", "auth_inicio", "auth_ultimo_uso")

# Datos del cliente cacheados en la sesion: no deben sobrevivir al logout
CLAVES_DATOS = ("datos", "datos_completos", "_pdf", "chat_mensajes")


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
    if motivo == "logout":
        # Salir a mano tambien olvida el equipo: se borra la cookie y, como
        # st.context.cookies la sigue viendo hasta recargar, se ignora aca
        st.session_state["auth_cookie_revocada"] = True
        st.session_state["auth_cookie_pendiente"] = ""


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


def _abrir_sesion(usuario: dict[str, str]) -> None:
    ahora = datetime.now()
    st.session_state.update(
        auth_ok=True,
        auth_email=usuario["email"],
        auth_rol=usuario["rol"],
        auth_inicio=ahora,
        auth_ultimo_uso=ahora,
        auth_intentos=0,
    )


def entrar_con_cookie() -> bool:
    """Abre la sesion desde la cookie "Recordarme" si es valida. True si entro."""
    if st.session_state.get("auth_cookie_revocada"):
        return False
    usuario = verificar_token(_cookie_del_navegador())
    if not usuario:
        return False
    _abrir_sesion(usuario)
    st.session_state.pop("auth_aviso_timeout", None)
    audit_log("login_cookie", usuario["email"], usuario["rol"])
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
            recordar = st.checkbox(
                f"Recordarme en este equipo ({DURACION_RECORDAR.days} días)", value=True,
                help="Destildalo en una computadora compartida.",
            )
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
                _abrir_sesion(usuario)
                st.session_state.pop("auth_cookie_revocada", None)
                if recordar:
                    # Se escribe en el proximo run: st.rerun() cortaria este
                    st.session_state["auth_cookie_pendiente"] = crear_token(usuario["email"])
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


def check_authentication() -> dict[str, str]:
    """Portero de la app: muestra el login y corta la ejecucion si no hay sesion valida.

    Devuelve los datos del usuario logueado, asi el archivo principal puede
    usarlos en la bienvenida:

        usuario = check_authentication()
        st.caption(f"Bienvenido: {usuario['email']}")
    """
    _sincronizar_cookie()
    if not sesion_valida() and not entrar_con_cookie():
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
