# Deploy en Streamlit Community Cloud

Repo: `Fbomone/agropix-dashboard` (privado — **mantenerlo así**).
Streamlit Community Cloud deploya repos privados en el plan gratis.

---

## 1. Login: cómo están guardadas las contraseñas

Las 3 contraseñas **no están en el repositorio**. `utils/auth.py` guarda, por
usuario, un `salt` aleatorio y el hash PBKDF2-SHA256 de la contraseña
(240.000 iteraciones). Con el hash no se puede iniciar sesión ni recuperar la
contraseña original.

| Usuario                | Rol      |
|------------------------|----------|
| `dueno@agropix.com`    | admin    |
| `gerente@agropix.com`  | gerente  |
| `vendedor@agropix.com` | vendedor |

`dueño@agropix.com` (con ñ) funciona como alias de `dueno@`: la parte local de
una dirección de correo debería ser ASCII, así que el usuario canónico es sin ñ.

### Rotar una contraseña

```bash
python -m utils.auth "LaPasswordNueva"      # imprime "salt" y "hash"
```

Dos opciones con esa salida:

- **Sin deploy** (recomendado): pegarla en la tabla `[usuarios."email"]` de los
  Secrets de Streamlit Cloud. Si esa tabla existe, reemplaza por completo a
  `USUARIOS_AUTORIZADOS` del código.
- **Con deploy**: reemplazar `salt`/`hash` en `utils/auth.py` y pushear.

### Lo que el login hace y lo que no

| Sí | No |
|----|----|
| Sesión de 30 min de inactividad, con logout automático | No hay recuperación de contraseña por mail |
| Bloqueo 5 min tras 5 intentos fallidos (por sesión) | El bloqueo es por sesión de navegador, no por IP |
| Log de accesos (`login_ok`, `login_fallido`, `bloqueo`, cierres) | No hay 2FA |
| Borra `datos`/`datos_completos`/`_pdf` de la sesión al salir | La URL de la app sigue siendo pública: cualquiera ve el login |

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
secrets (`SENDGRID_API_KEY`, `EMAIL_REMITENTE`, `EMAIL_DESTINATARIOS`). El
remitente tiene que estar verificado en SendGrid → *Settings → Sender
Authentication*, sino la API devuelve 403 aunque la key sea válida. Plan gratis:
100 mails/día. El envío es manual (un botón); un envío programado necesita un
scheduler externo, que Community Cloud no tiene.

---

## 6. Tests

```bash
pip install -r requirements-dev.txt
pytest                                     # 72 tests; 9 se saltean

# Incluyendo los que necesitan las contraseñas reales:
AGROPIX_TEST_PASS_DUENO='...' AGROPIX_TEST_PASS_GERENTE='...' \
AGROPIX_TEST_PASS_VENDEDOR='...' pytest
```

`tests/test_auth.py` y `tests/test_email_sender.py` no tocan red.
`tests/test_app_login.py` corre `app.py` de verdad con `AppTest` y verifica que
sin sesión válida **no se lee Google Sheets**.
