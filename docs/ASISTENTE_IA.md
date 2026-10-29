# Asistente IA — Especificación (fase 2 de NOTAS.md: "Chat con IA")

Chat dentro del dashboard para que los usuarios hagan preguntas en lenguaje
natural sobre los datos de servicios y equipos de Agropix.

**Costo cero:** usa el plan gratuito de Groq (API compatible con OpenAI).
**Principio central:** el LLM NUNCA calcula ni ve las tablas crudas. Elige una
herramienta, la herramienta calcula con las funciones que ya existen en
`utils/data.py` y `utils/comisiones.py`, y el LLM redacta la respuesta con ese
resultado. Así los números del chat son idénticos a los de las tarjetas.

---

## 1. Archivos a crear / modificar

| Archivo | Acción |
|---|---|
| `utils/herramientas_chat.py` | NUEVO. Funciones-herramienta + sus esquemas JSON (`HERRAMIENTAS`). |
| `utils/agente.py` | NUEVO. Cliente Groq, prompt de sistema, bucle de tool calling, límites y errores. |
| `paginas/5_Asistente.py` | NUEVO. UI del chat. |
| `app.py` | Registrar la página: `st.Page("paginas/5_Asistente.py", title="Asistente IA", icon="💬")` después de "Venta de Equipos". |
| `requirements.txt` | Agregar `openai>=1.40` (bajo un bloque `# --- Asistente IA (Groq) ---`). |
| `.streamlit/secrets.toml.example` | Agregar `GROQ_API_KEY` y `GROQ_MODEL` con placeholders y comentario. |
| `tests/test_herramientas_chat.py` | NUEVO. Ver sección 7. |
| `tests/test_agente.py` | NUEVO. Bucle con cliente falso (sin red). |
| `NOTAS.md` | Marcar "Chat con IA (fase 2)" como hecho y documentar decisiones. |
| `DEPLOY.md` | Sección "Asistente IA": cómo cargar la key en Streamlit Cloud. |

No tocar la lógica de negocio existente. Si hace falta un cálculo nuevo, va en
`herramientas_chat.py` reutilizando funciones existentes.

---

## 2. Configuración (secrets)

```toml
# --- Asistente IA (Groq, plan gratuito) ---
# Key en https://console.groq.com/keys . Sin esta clave la página del asistente
# muestra un aviso y no rompe el resto de la app.
GROQ_API_KEY = "gsk_reemplazar"
# Modelo con soporte de tool calling. Si Groq lo da de baja, se cambia acá sin redeploy.
GROQ_MODEL = "openai/gpt-oss-120b"
# Respaldo si el principal da error de modelo o límite
GROQ_MODEL_RESPALDO = "llama-3.3-70b-versatile"
# Preguntas por usuario por día (protege la cuota gratuita compartida)
CHAT_LIMITE_DIARIO = 30
```

Cliente:
```python
from openai import OpenAI
cliente = OpenAI(api_key=st.secrets["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1",
                 timeout=30, max_retries=1)
```
Si falta `GROQ_API_KEY`: la página muestra `st.info` explicando cómo configurarlo y hace `st.stop()`.

---

## 3. Datos que usan las herramientas

`app.py` ya deja en `st.session_state`:
- `datos_completos`: el dict de `construir_datos()` sin filtrar.
- `datos`: el mismo dict con los filtros del sidebar aplicados (`aplicar_filtros`).
- `estados_trabajo`: (key del multiselect) estados seleccionados.

Regla: cada herramienta recibe `desde` / `hasta` opcionales (strings `YYYY-MM-DD`).
- Si **no** vienen → usar `st.session_state["datos"]` (lo mismo que ve el usuario en pantalla).
- Si vienen → `aplicar_filtros(datos_completos, desde, hasta, estados_trabajo_actuales)`.

Para que sea testeable, las funciones puras reciben `datos: dict` como primer
parámetro; un despachador `ejecutar(nombre, argumentos, contexto)` resuelve
de dónde salen los datos. Nada de `st.*` dentro de las funciones puras.

---

## 4. Herramientas (MVP)

Todas devuelven un `dict` serializable a JSON, chico (máx. 15 filas en listas),
montos redondeados a 2 decimales, y una clave `"periodo"` con desde/hasta
efectivos. Si no hay datos: `{"sin_datos": true, "periodo": ...}`.

| Nombre | Parámetros | Implementación (reutilizar) |
|---|---|---|
| `kpis_generales` | desde, hasta | `kpis_comisiones(servicios, equipos)` → ingresos, comision_cobrada, por_cobrar, pct_cobranza, generada/cobrada equipos, generado/cobrado servicios, volumen_equipos, hectareas, cantidad_servicios, clientes. Es lo que muestra el Reporte General. |
| `ingresos_por_periodo` | granularidad (Semanal/Mensual/Trimestral/Anual), desde, hasta | `ingresos_por_periodo(servicios, equipos, granularidad)` y/o `comisiones_por_mes`. Últimos 15 períodos como máximo. |
| `top_clientes` | n (1–15, default 10), desde, hasta | `comisiones.top_clientes(servicios, equipos, top=n)` |
| `ranking_vendedores` | desde, hasta | `ranking_vendedores(equipos)` |
| `comisiones_por_canal` | desde, hasta | `comisiones_por_canal(equipos)` |
| `equipos_por_modelo` | solo_principales (bool), desde, hasta | `equipos_por_modelo(unidades, solo_principales)` + `cobertura_atribucion(unidades)` (incluir siempre la cobertura para avisar los modelos sin precio de lista). |
| `resumen_servicios` | agrupar_por (servicio/cultivo/trabajo/estado), desde, hasta | `kpis_servicios(servicios)` + groupby de `vigentes(servicios)` por la columna pedida: cantidad, hectáreas, monto. |
| `pendientes_de_cobro` | desde, hasta | Servicios con `estado_cobro == POR_COBRAR` y equipos con `cobrado == False` (vigentes), agrupados por cliente: monto/comisión pendiente, ordenados desc, top 15 + total. |
| `buscar_cliente` | nombre | Búsqueda sin tildes/mayúsculas (usar `normalizar`) en servicios y equipos: trabajos, hectáreas, monto servicios, equipos comprados, comisión, pendiente. Si hay varias coincidencias, devolver la lista de nombres (máx. 10) para que el modelo pida aclaración. |
| `resumen_operadores` | desde, hasta | `resumen_operadores(datos["operadores"])` filtrado por fecha si corresponde. |
| `calidad_de_datos` | — | `alertas_calidad` ya calculada en `datos["calidad"]`: cantidad por tipo, sin filas sensibles. |

Esquemas: formato OpenAI `tools=[{"type": "function", "function": {name, description, parameters}}]`.
Descripciones en español, claras, diciendo QUÉ preguntas responde cada una
(ej. "Usar para: cuánto facturamos, ingresos totales, hectáreas trabajadas...").
Validar argumentos (fechas parseables, n en rango, enums) y devolver
`{"error": "..."}` en vez de lanzar excepción.

---

## 5. Agente (`utils/agente.py`)

- `responder(pregunta, historial, contexto) -> Respuesta` donde `Respuesta`
  tiene `texto: str` y `pasos: list[dict]` (herramienta, argumentos, resultado resumido) para la trazabilidad.
- Bucle: enviar mensajes + `tools` con `tool_choice="auto"`, `temperature=0.1`.
  Si vuelven `tool_calls`, ejecutar cada una con `ejecutar(...)`, agregar los
  mensajes `role="tool"` y repetir. **Máximo 5 vueltas**; si se agota, responder
  con lo que haya y avisarlo.
- Historial: mandar solo los últimos 6 turnos (usuario/asistente) para cuidar tokens.
  No reenviar resultados de herramientas de turnos anteriores.
- Respaldo: si el modelo principal da 404/400 de modelo o 429, reintentar una vez con `GROQ_MODEL_RESPALDO`.
- Errores → mensajes para el usuario (nunca traceback):
  - 429: "El asistente alcanzó el límite gratuito por ahora. Probá de nuevo en un minuto."
  - timeout/conexión: "No pude conectarme con el servicio de IA. Probá de nuevo."
  - sin key: ver sección 2.
- Límite por usuario: contador en un `@st.cache_resource` (dict
  `{(email, fecha_iso): cantidad}`) para que valga entre sesiones del mismo
  usuario. Al superar `CHAT_LIMITE_DIARIO`: mensaje y no se llama a la API.
  Los admins (`sesion_es_admin()`) sin límite.
- Auditoría: `audit_log("chat_pregunta", email, f"herramientas={...}")`. No
  loguear el texto de la pregunta ni la respuesta.

### Prompt de sistema (constante `PROMPT_SISTEMA`)

```
Sos el asistente de datos de Agropix, empresa argentina de aplicaciones y
fumigaciones con drones y venta de drones. Respondés en español rioplatense,
claro y breve, a usuarios internos del dashboard.

REGLAS
- Todos los números salen de las herramientas. Nunca inventes, estimes ni
  calcules cifras por tu cuenta (salvo restas o porcentajes simples sobre
  valores que te devolvió una herramienta). Si no hay herramienta para algo,
  decilo y sugerí qué pantalla del dashboard mirar.
- Si la pregunta no indica período, usá el período de los filtros actuales
  ({periodo_actual}) y mencionalo en la respuesta.
- Montos en dólares con formato US$ 12.345 (punto de miles). Hectáreas: "1.234 ha".
- Respuesta corta: 1 a 4 oraciones o una lista breve / tabla markdown chica.
- Si una herramienta devuelve sin_datos o error, explicalo en simple.
- Solo temas de los datos de Agropix. Para otra cosa, decí amablemente que
  solo podés ayudar con el reporte.

DEFINICIONES DE NEGOCIO
- Ingresos Agropix = Valor total de ventas de servicios + Comisión $ de equipos.
- La factura de equipos NO es ingreso: es "volumen intermediado" (informativo).
- Estados de trabajo que cuentan como venta por defecto: Cobro recibido,
  Facturado esperando cobro, Trabajo realizado. Los trabajos cancelados y los
  equipos devueltos nunca suman ingreso.
- Servicio cobrado = "Cobro recibido"; el resto de lo vendido está por cobrar.
- Equipos: cobrado según la columna Cobrado de la planilla de Ventas.
- Las hectáreas por operador pueden superar las del trabajo (trabajan en
  simultáneo sobre el mismo lote).
- El reparto de comisión por modelo depende del precio de lista; si la
  herramienta informa cobertura incompleta, avisalo.
- Marcas principales de equipos: Agras T y Mavic; accesorios: MIXER JR, RTK, PIX4D.
```
`{periodo_actual}` se completa con el rango del sidebar (dd/mm/aaaa – dd/mm/aaaa)
y los estados de trabajo seleccionados.

---

## 6. Página (`paginas/5_Asistente.py`)

- Título "💬 Asistente IA" + caption: "Preguntá sobre servicios, equipos,
  clientes y cobranzas. Usa el período y los estados del filtro de la izquierda
  salvo que indiques otro."
- Historial en `st.session_state["chat_mensajes"]`; render con `st.chat_message`.
- Si el historial está vacío: 4 botones de preguntas sugeridas en columnas:
  - "¿Cuánto ingresó Agropix en el período?"
  - "¿Quiénes son los 5 mejores clientes?"
  - "¿Qué está pendiente de cobro?"
  - "¿Cómo vienen los ingresos mes a mes?"
- `st.chat_input("Escribí tu pregunta…")`; durante la llamada `st.spinner("Pensando…")`.
- Debajo de cada respuesta del asistente: `st.expander("🔎 Cómo lo calculé")`
  con las herramientas usadas y sus parámetros (no el JSON completo).
- Botón "🗑️ Nueva conversación" que limpia el historial.
- Caption fijo abajo: "Las respuestas se generan con IA a partir de los datos
  del dashboard. Verificá cifras importantes en los reportes."
- Contador visible: "Te quedan N preguntas hoy".

Pop-up (opcional, fase 2.1): en `1_Reporte_General.py`, un `st.popover("💬 Preguntar")`
con un `st.text_input` + respuesta única reutilizando `agente.responder` (sin historial).

---

## 7. Tests (sin red, sin Google Sheets)

`tests/test_herramientas_chat.py` (usar/extender los fixtures de `tests/conftest.py`):
- **Consistencia:** `kpis_generales(datos)` devuelve exactamente los mismos
  valores que `kpis_comisiones(...)` sobre los mismos datos; ídem `top_clientes`,
  `ranking_vendedores`, `equipos_por_modelo`.
- Filtro por fecha: con `desde/hasta` usa `aplicar_filtros` y el resultado cambia
  como corresponde.
- Datos vacíos → `sin_datos: true`, sin excepción.
- Argumentos inválidos (fecha mal, n=100, enum desconocido) → `{"error": ...}`.
- Todo resultado es `json.dumps`-able y las listas tienen ≤ 15 elementos.
- `buscar_cliente` ignora tildes y mayúsculas.
- Cada herramienta en `HERRAMIENTAS` tiene su función y viceversa.

`tests/test_agente.py` con un cliente falso que simula respuestas de la API:
- Llama la herramienta pedida y arma la respuesta final.
- Corta a las 5 vueltas.
- 429 → mensaje amable; usa modelo de respaldo una vez.
- Límite diario por usuario; admin sin límite.

Correr `pytest` completo: todos los tests existentes deben seguir pasando.

---

## 8. Criterios de aceptación

1. "¿Cuánto ingresó Agropix?" con los filtros por defecto devuelve el mismo
   número que la tarjeta INGRESOS del Reporte General.
2. "¿Quién es el mejor cliente en 2025?" usa `top_clientes` con desde/hasta de 2025.
3. Sin `GROQ_API_KEY` la app sigue funcionando y la página muestra el aviso.
4. Nunca se envían filas crudas de las planillas a Groq: solo resultados agregados de herramientas.
5. La página solo es accesible con login (hereda el `check_authentication` de `app.py`).

---

## 9. Registro de implementación (29/10/2026)

Rama `feature/asistente-ia`. Implementado según esta especificación, en el orden
herramientas → agente → página → configuración y documentación.

### Archivos

| Archivo | Qué quedó |
|---|---|
| `utils/herramientas_chat.py` | Las 11 herramientas de la sección 4, `HERRAMIENTAS` (esquemas OpenAI) y `ejecutar()`, que nunca lanza. |
| `utils/agente.py` | `responder()`, `PROMPT_SISTEMA` literal, bucle de 5 vueltas, respaldo, mensajes de error, límite diario y auditoría. |
| `paginas/5_Asistente.py` | UI de la sección 6. Solo lee la sesión. |
| `app.py` | Una línea: el `st.Page` después de "Venta de Equipos". |
| `utils/auth.py` | Una línea: `chat_mensajes` en `CLAVES_DATOS`, así el historial se borra al cerrar sesión o por timeout. |
| `requirements.txt`, `.streamlit/secrets.toml.example`, `NOTAS.md`, `DEPLOY.md` | Dependencia, secrets, decisiones y la sección 9 de DEPLOY.md (carga de la key en Cloud). |
| `tests/test_herramientas_chat.py`, `tests/test_agente.py`, `tests/test_pagina_asistente.py` | 87 tests nuevos sin red. Suite completa: 461 tests (antes 374). |

No se modificó la lógica de negocio (`utils/data.py`, `utils/comisiones.py`) ni
las otras páginas.

### Garantía: el chat no modifica los datos

El reporte en producción es la referencia, así que el chat solo lee
`st.session_state["datos"]` y `["datos_completos"]`. No los reescribe, no relee
Google Sheets ni limpia la caché. Cuando el modelo pide otras fechas,
`aplicar_filtros` arma un dict nuevo. Dos tests lo verifican celda por celda:
`test_las_herramientas_no_modifican_los_datos` (las 11 herramientas, con y sin
fechas) y `test_el_chat_no_modifica_los_datos_del_dashboard` (la página real con
`AppTest`).

### Decisiones donde esta especificación era ambigua

- "Últimos 6 turnos" = últimos 6 mensajes (3 preguntas + 3 respuestas), solo el texto.
- `desde` sin `hasta` (o al revés): el extremo que falta es la primera o última fecha con datos.
- `pendientes_de_cobro` usa `estado_cobro == POR_COBRAR`, literal. Con el filtro
  por defecto coincide con la tarjeta "por cobrar". Si se tildan estados que no
  son venta, la tarjeta los cuenta como por cobrar y el chat no.
- `agrupar_por="estado"` agrupa por "Última acción", el estado del filtro.
- Porcentajes como fracción con 4 decimales; montos con 2.
- `buscar_cliente` no tiene fechas: busca en el período de pantalla.
- El límite diario se cuenta en hora argentina. Las preguntas que terminan en
  error no descuentan. Vive en memoria y se reinicia con la app.
- Las respuestas que fueron error no se reenvían al modelo como historial.
- Con el límite agotado el input se desactiva y se muestra el aviso.

### Verificación con datos reales (29/10/2026, local)

Sheets reales, filtros por defecto, Groq con `openai/gpt-oss-120b`:

| Criterio | Pregunta | Herramienta elegida | Resultado |
|---|---|---|---|
| 1 | "¿Cuánto ingresó Agropix en el período?" | `kpis_generales` con el período del filtro | Mismo número que la tarjeta INGRESOS, al centavo. 3,0 s. |
| 2 | "¿Quién es el mejor cliente en 2025?" | `top_clientes` con `n=1`, 2025-01-01 a 2025-12-31 | Correcto. 1,8 s. |
| 3 | Sin `GROQ_API_KEY` | — | Aviso en la página; el resto de la app funciona (test con `AppTest`). |
| 4 | Filas crudas | — | A Groq solo llegan agregados (test `test_nunca_viajan_filas_crudas`). |
| 5 | Login | — | La página está en `st.navigation` de `app.py`, detrás de `check_authentication`. |

Observación: el modelo a veces escribe montos con centavos (US$ 1.234,56) aunque
el prompt pide `US$ 12.345`. Es solo formato: el número es el de la herramienta.

### Lección de configuración

La key tiene que ir **antes de cualquier `[sección]`** del `secrets.toml`. En la
primera carga quedó debajo de `[gcp_service_account]` y después de `[sendgrid]`:
TOML la asigna a esa tabla y la app ve el asistente como "no configurado". Está
advertido en `secrets.toml.example` y en DEPLOY.md.

### Pendiente

- Fase 2.1 (opcional): popover "💬 Preguntar" en el Reporte General.
- Cargar el bloque de Groq en los secrets de Streamlit Cloud (DEPLOY.md, sección 9).
