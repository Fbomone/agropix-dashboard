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

| Usuario | Clave en `[auth_users]` | Rol |
|---|---|---|
| `francobomone14@gmail.com` | `francobomone14_gmail_com` | usuario |
| `infoagropix@gmail.com` | `infoagropix_gmail_com` | **admin** |
| `nfoagropix@gmail.com` | `nfoagropix_gmail_com` | **admin** |
| `matias21tossen@gmail.com` | `matias21tossen_gmail_com` | usuario |
| `fabiocailletbois@gmail.com` | `fabiocailletbois_gmail_com` | usuario |
| `ggaletto.gg@gmail.com` | `ggaletto_gg_gmail_com` | usuario |
| `ignacio.ramello879@gmail.com` | `ignacio_ramello879_gmail_com` | usuario |
| `nicotobaldi55@gmail.com` | `nicotobaldi55_gmail_com` | usuario |

Los 5 usuarios nuevos **todavía no tienen contraseña en los secrets**: figuran en
la lista pero no pueden entrar hasta que se les cargue una. El panel de
administración, pestaña *Validación*, muestra cuáles están habilitados.

`nfoagropix@` (sin la "i") y `infoagropix@` están los dos como admin porque la
especificación usa el primero y veníamos usando el segundo. Tener el de más no
abre nada: sin contraseña en los secrets ninguno entra.

El rol sólo habilita el panel de administración; los datos que ve cada uno son
los mismos.

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

**Email.** Hay dos vías y se elige sola: si está `[smtp]` cargado gana ése, si
no, `[sendgrid]`. El botón de enviar no aparece hasta que una de las dos esté
configurada, y dice cuál falta.

*Gmail (recomendada).* No necesita cuenta de terceros. En los secrets:

```toml
[smtp]
user = "infoagropix@gmail.com"
password = "xxxx xxxx xxxx xxxx"   # App Password, NO la contraseña de la cuenta
```

El App Password sale de <https://myaccount.google.com/apppasswords> y requiere
tener la verificación en dos pasos activada. Gmail admite ~500 destinatarios por
día: con 7 personas una vez por semana sobra. Si Google rechaza la contraseña,
el panel lo dice con esas palabras en vez de un error genérico.

*SendGrid.* Requiere crear la cuenta y verificar el remitente en *Settings →
Sender Authentication*, sino la API devuelve 403 aunque la key sea válida. Plan
gratis: 100 mails/día.

---

## 6. Panel de administración

Sólo para los admins, en la barra de navegación como **Administración**. Cuatro
pestañas:

| Pestaña | Para qué |
|---|---|
| **Envío de prueba** | Genera el PDF de un período y lo manda, con resultado por destinatario. Arranca con sólo el admin tildado. |
| **Validación** | Consulta la API de SendGrid sin enviar nada: comprueba la key y que el remitente esté verificado. Lista qué usuarios tienen contraseña cargada. |
| **Historial** | Los envíos registrados, con estado OK / parcial / error y el detalle por destinatario. |
| **Sistema** | Versión de la app, versiones reales de Python y las librerías, filas leídas de cada Sheet, período cubierto, últimos accesos y un reporte técnico descargable. |

**La página no está en `pages/`.** Con esa carpeta Streamlit arma su navegación
vieja y una URL directa ejecuta la página *sin pasar por app.py*: el panel
quedaría accesible sin login. Acá `app.py` sólo la declara cuando la sesión es de
un admin, así que para el resto no existe ni como URL — y la página revalida el
rol por su cuenta.

El envío del panel manda **un mail por destinatario** en vez de uno con siete
destinatarios: cuesta siete llamadas pero permite decir exactamente a quién
llegó. Con 7 destinatarios el plan gratis (100/día) no se mueve.

El historial vive en `data/envios.jsonl`, que en Streamlit Cloud **se borra en
cada reinicio**. Lo que persiste son los logs de *Manage app → Logs* y el
Activity Feed de SendGrid.

---

## 7. Reporte semanal automático (GitHub Actions)

Lunes 8:00 ART, con el PDF de 4 carillas adjunto. Reporta la semana que acaba
de cerrar: el mail del lunes 21/09 trae del lunes 14/09 al domingo 20/09.

**Por qué no corre dentro de la app:** Streamlit Community Cloud duerme la app
cuando nadie la visita y mata el proceso. Un scheduler con `schedule` en un
thread se muere con ella y no se despierta solo: los lunes sin visitas el mail
no saldría, y sin aviso. El cron de Actions corre en GitHub, no depende de que
la app esté viva.

`.github/workflows/reporte-semanal.yml` → cron `0 11 * * 1`. Argentina usa
UTC-3 todo el año (no mueve los relojes desde 2009), así que 11:00 UTC = 8:00 ART
de forma estable.

### Secrets que hay que cargar en GitHub

Settings → Secrets and variables → Actions → *New repository secret*:

| Secret | Qué es |
|---|---|
| `GOOGLE_CREDENTIALS_JSON` | el contenido completo de `credentials.json`, pegado tal cual |
| `CRM_SHEET_ID`, `VENTAS_SHEET_ID` | los IDs de los dos Sheets |
| `CRM_TAB`, `VENTAS_TAB` | `Trabajos` y `Ventas` |
| `SENDGRID_API_KEY` | la API key real (no el placeholder) |
| `EMAIL_REMITENTE` | Single Sender verificado en SendGrid |
| `EMAIL_DESTINATARIOS` | opcional: reemplaza la lista de `utils/reporte_semanal.py` |

Son **secrets de GitHub**, aparte de los de Streamlit Cloud: son dos entornos
distintos y cada uno necesita los suyos.

### Probarlo sin esperar al lunes

Actions → *Reporte semanal Agropix* → **Run workflow**, con `dry_run` en `true`:
genera el PDF y lo deja como artifact descargable, sin enviar nada. En local:

```bash
python scripts/enviar_reporte_semanal.py --dry-run --desde 2026-09-07 --hasta 2026-09-13
# deja el PDF y el HTML del mail en ./salida/
```

El período por defecto es la **última semana completa** (lunes a domingo), no
lunes-a-hoy: así los números son comparables entre envíos.

Si la semana no tuvo movimiento el mail se manda igual, diciéndolo. Un silencio
no se distingue de un envío que falló.

---

## 8. Tests

```bash
pip install -r requirements-dev.txt
pytest                                    # 194 tests, ninguno se saltea

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
