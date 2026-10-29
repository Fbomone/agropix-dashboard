# Agropix Dashboard — Notas

## Decisiones de negocio
- Ingreso Agropix = Valor total de ventas (servicios) + Comisión $ (equipos)
- La factura de equipos NO es ingreso: es volumen intermediado
- Estados que cuentan como venta: Cobro recibido, Facturado esperando cobro,
  Trabajo realizado
- Has por operador puede superar las has del trabajo (trabajan en simultáneo
  sobre el mismo lote)

## Pendientes de Matías
- [ ] Precio de lista: MIXER JR, T50, T55, Pix4D, RTK. **Hoy limita el reparto
      de comisión por modelo a 22 de 65 unidades (34%)**; con esos 5 cargados
      queda completo. Las unidades se cuentan igual sin el precio.
- [ ] Confirmar si T55 = T551 / T552 / T553
- [ ] 8 trabajos cobrados/realizados sin monto cargado
- [ ] Filas 77 y 78 de Trabajos: fecha de contacto inválida

## Pendientes técnicos
- [x] Deploy: Streamlit Community Cloud (ver DEPLOY.md)
- [x] credentials.json via st.secrets[gcp_service_account] para el deploy
- [x] Login privado con timeout de 30 min (utils/auth.py)
- [x] Envío por mail con SendGrid (utils/email_sender.py) — manual, con botón
- [ ] Envío *programado* por mail: Community Cloud no tiene scheduler
- [ ] Precios de lista: persisten en JSON dentro del contenedor, se pierden al
      reiniciar en Cloud. Mover a un Sheet o DB.
- [x] Comisiones como métrica central: utils/comisiones.py + tarjetas de KPI,
      tabs, top clientes, vendedores por comisión cobrada y corte por canal
- [x] Reporte semanal automático: GitHub Actions lunes 8:00 ART (ver DEPLOY.md)
- [ ] Mobile: solo las tarjetas de KPI son responsive; faltan gráficos, tablas
      y modo oscuro
- [x] Chat con IA (fase 2): página "Asistente IA" con Groq (plan gratis).
      Spec en docs/ASISTENTE_IA.md, carga de la key en DEPLOY.md
- [ ] Chat con IA fase 2.1 (opcional): popover "💬 Preguntar" en el Reporte General

## Asistente IA — decisiones
- El LLM nunca ve las planillas ni calcula: elige una herramienta de
  utils/herramientas_chat.py, que reutiliza las funciones de data.py y
  comisiones.py, y redacta con el resultado agregado. Mismos números que las tarjetas
- El chat solo LEE los datos de la sesión: no modifica `datos` ni
  `datos_completos`, no relee Sheets ni toca la caché (hay tests que lo verifican)
- Sin fechas en la pregunta usa el período y los estados del filtro; con fechas
  aplica aplicar_filtros sobre los datos completos con los estados actuales
- Si el modelo da solo `desde` (o solo `hasta`), el otro extremo es la primera
  (o última) fecha con datos
- pendientes_de_cobro toma servicios con estado "Por cobrar", como pide la spec.
  Con el filtro por defecto coincide con la tarjeta; si se tildan estados que no
  son venta (presupuesto, consulta…), la tarjeta los suma como por cobrar y el
  chat no
- buscar_cliente busca dentro del período de pantalla
- Porcentajes como fracción con 4 decimales (0.8734); montos con 2
- Historial: viajan los últimos 6 mensajes (3 preguntas + 3 respuestas), solo el
  texto. Las respuestas que fueron error no se reenvían
- Límite diario por usuario en memoria (`st.cache_resource`), día en hora
  argentina. Se reinicia si se reinicia la app. Las preguntas que fallan
  (429, timeout) no descuentan. Admins sin límite
- El historial del chat se borra al cerrar sesión o por timeout (CLAVES_DATOS)
- Auditoría `chat_pregunta`: herramientas y modelo, nunca el texto

## Setup local
- Python 3.14, venv en /venv
- Requiere credentials.json (service account de Google Cloud) en la raíz
- Requiere .env con CRM_SHEET_ID, VENTAS_SHEET_ID, CRM_TAB, VENTAS_TAB
- Correr: streamlit run app.py
- Tests: pip install -r requirements-dev.txt && pytest

## Accesos
- La app pide login. Usuarios y rotación de contraseñas: DEPLOY.md
- Las contraseñas se guardan hasheadas (PBKDF2); nunca en texto plano en el repo