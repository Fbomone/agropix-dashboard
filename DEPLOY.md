# Deploy en Streamlit Community Cloud

Repo: `Fbomone/agropix-dashboard` (privado — **mantenerlo así**).
Streamlit Community Cloud deploya repos privados en el plan gratis.

---

## 1. Login: cómo se usa y cómo están guardadas las contraseñas

`app.py` sólo necesita dos líneas:

```python
from utils.auth import check_authentication, logout_button

usuario = check_authentication()   # muestra el login y corta si no hay sesión
with st.sidebar:
    logout_button()
```

`check_authentication()` devuelve un dict con el `email` del usuario, que es lo
que alimenta la línea de bienvenida del encabezado. La verificación pura, sin
dibujar nada, es `sesion_valida()`.

### Dónde están las contraseñas

En **ningún archivo del repositorio**. Se leen de `st.secrets["auth_users"]`:

- local → `.streamlit/secrets.toml` (en `.gitignore`, nunca se pushea)
- Cloud → *Manage app → Settings → Secrets*, cifrados del lado de Streamlit

Sin esa sección no entra nadie: no hay usuario de emergencia ni contraseña por
defecto en el código. La pantalla de login lo avisa explícitamente en vez de
rechazar los intentos como si fueran contraseñas equivocadas.

| Usuario | Clave en `[auth_users]` |
|---|---|
| `francobomone14@gmail.com` | `francobomone14_gmail_com` |
| `infoagropix@gmail.com` | `infoagropix_gmail_com` |
| `matias21tossen@gmail.com` | `matias21tossen_gmail_com` |

La clave del secret es el email con `@` y `.` cambiados por `_`, porque TOML no
los acepta en una clave simple.

Las contraseñas se guardan tal cual, sin hashear, para poder administrarlas
desde el panel de Cloud sin herramientas extra. La contrapartida: quien tenga
acceso a ese panel las ve en claro, así que conviene que nadie reuse ahí una
contraseña personal de otro servicio.

### Dar de alta, dar de baja o rotar

- **Rotar**: cambiar el valor en Secrets y guardar. Tiene efecto sin redeploy,
  porque los usuarios se releen en cada rerun.
- **Dar de baja**: borrar esa línea de Secrets. El email queda sin contraseña
  cargada y deja de entrar.
- **Dar de alta**: agregar el email a `EMAILS_AUTORIZADOS` en `utils/auth.py`
  (esto sí requiere push) y su contraseña en Secrets. Una contraseña en Secrets
  para un email que no esté en esa lista **no habilita a nadie**.

`python -m utils.auth` imprime el esqueleto de la sección `[auth_users]`, sin
contraseñas, para pegar y completar.

### Lo que el login hace y lo que no

| Sí | No |
|----|----|
| Sesión de 30 min de inactividad, con logout automático | No hay recuperación de contraseña por mail |
| Bloqueo 5 min tras 5 intentos fallidos (por sesión) | El bloqueo es por sesión de navegador, no por IP |
| Log de accesos (`login_ok`, `login_fallido`, `bloqueo`, cierres) | No hay 2FA |
| Borra `datos`/`datos_completos`/`_pdf` de la sesión al salir | No hay roles ni permisos: los 3 usuarios ven lo mismo |

**Auditoría:** `audit_log()` escribe al logger estándar (visible en *Manage app →
Logs* de Streamlit Cloud) y, si el disco es escribible, a `data/auditoria.log`.
En Streamlit Cloud el filesystem es **efímero**: el archivo se borra en cada
reinicio del contenedor. Los logs de la consola son la fuente real.

---

## 2. Secrets (obligatorio antes del primer deploy)

En el contenedor de Streamlit Cloud **no existen `.env` ni `credentials.json`**
(ambos están en `.gitignore`, y así debe seguir). Sin secrets la app arranca,
muestra el login y falla recién al leer Google Sheets.

1. Copiar `.streamlit/secrets.toml.example` completo.
2. share.streamlit.io → la app → **Settings → Secrets** → pegar y completar.
   **El cuadro reemplaza todo lo que haya**: copiá antes lo que ya esté cargado,
   sobre todo si `[gcp_service_account]` ya tiene la service account de verdad.
3. El bloque `[gcp_service_account]` es el contenido de `credentials.json`.
   En la `private_key`, los saltos de línea van como `\n` (el código los
   des-escapa solo).
4. Compartir los dos Google Sheets con el `client_email` de la service account.

Prioridad de configuración: variables de entorno primero, después `st.secrets`.
Así en local podés apuntar a otro Sheet sin tocar el deploy.

---

## 3. Deploy

```bash
git push origin main
```

share.streamlit.io → **New app** → repo `Fbomone/agropix-dashboard`, branch
`main`, main file `app.py`. Cada push a `main` redeploya solo.

En **Advanced settings** elegir la versión de Python más alta disponible.
`requirements.txt` usa pisos de versión (`>=`), no pines exactos, justamente
porque el intérprete de Cloud puede no ser el 3.14 de local.

HTTPS lo pone Streamlit; no hay nada que configurar.

---

## 4. Verificar después del deploy

- [ ] La URL muestra el login, no el dashboard.
- [ ] Contraseña incorrecta → error; 5 fallos → bloqueo de 5 min.
- [ ] Login correcto → carga el Reporte General con datos del Sheet.
- [ ] Sidebar: usuario, rol y botón **Cerrar sesión** funcionando.
- [ ] Logout → vuelve al login y los filtros se resetean.
- [ ] **Exportar reporte PDF** → ver punto 5.
- [ ] *Manage app → Logs*: aparecen las líneas `AUDIT ... login_ok ...`.

---

## 5. Puntos frágiles conocidos

**PDF (`kaleido`).** El render de gráficos Plotly a imagen necesita un
navegador. Se agregó `packages.txt` con `chromium` para que Cloud lo instale por
apt. Si el PDF falla igual, el error aparece en los logs; el resto del dashboard
sigue funcionando (la exportación está en un `try/except`).

**Precios de lista.** `paginas/4_Configuracion.py` guarda en
`precios_lista.json`, dentro del contenedor. En Cloud eso se **pierde en cada
reinicio**. Si los precios tienen que persistir, hay que moverlos a un Sheet o
a una DB.

**Email (SendGrid).** El botón "Enviar por mail" aparece sólo si están los tres
secrets. Se aceptan dos formas equivalentes: claves planas
(`SENDGRID_API_KEY`, `EMAIL_REMITENTE`, `EMAIL_DESTINATARIOS`) o la tabla
`[sendgrid]` con `api_key` / `from_email` / `destinatarios`. El
remitente tiene que estar verificado en SendGrid → *Settings → Sender
Authentication*, sino la API devuelve 403 aunque la key sea válida. Plan gratis:
100 mails/día. El envío es manual (un botón); un envío programado necesita un
scheduler externo, que Community Cloud no tiene.

---

## 6. Tests

```bash
pip install -r requirements-dev.txt
pytest                                     # 96 tests, ninguno se saltea

# Incluyendo los que necesitan las contraseñas reales:
AGROPIX_TEST_PASS_DUENO='...' AGROPIX_TEST_PASS_GERENTE='...' \
AGROPIX_TEST_PASS_VENDEDOR='...' pytest
```

Ningún test toca la red. `tests/test_app_login.py` corre `app.py` de verdad con
`AppTest` y verifica que sin sesión válida **no se lee Google Sheets**.

Los tests no usan las contraseñas reales: arman su propio `[auth_users]` de
mentira. Verificado además contra los secrets y los Sheets reales en local: los
3 usuarios entran, el dashboard carga 11 KPIs y 2 tablas, y el logout vuelve al
login limpiando los datos de la sesión.
