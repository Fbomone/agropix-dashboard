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
- [x] Reporte semanal automático: GitHub Actions viernes 9:30 ART (ver DEPLOY.md)
- [ ] Mobile: solo las tarjetas de KPI son responsive; faltan gráficos, tablas
      y modo oscuro
- [ ] Chat con IA (fase 2)

## Setup local
- Python 3.14, venv en /venv
- Requiere credentials.json (service account de Google Cloud) en la raíz
- Requiere .env con CRM_SHEET_ID, VENTAS_SHEET_ID, CRM_TAB, VENTAS_TAB
- Correr: streamlit run app.py
- Tests: pip install -r requirements-dev.txt && pytest

## Accesos
- La app pide login. Usuarios y rotación de contraseñas: DEPLOY.md
- Las contraseñas se guardan hasheadas (PBKDF2); nunca en texto plano en el repo