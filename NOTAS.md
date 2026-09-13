# Agropix Dashboard — Notas

## Decisiones de negocio
- Ingreso Agropix = Valor total de ventas (servicios) + Comisión $ (equipos)
- La factura de equipos NO es ingreso: es volumen intermediado
- Estados que cuentan como venta: Cobro recibido, Facturado esperando cobro,
  Trabajo realizado
- Has por operador puede superar las has del trabajo (trabajan en simultáneo
  sobre el mismo lote)

## Pendientes de Matías
- [ ] Precio de lista: MIXER JR (14u), T50 (3u), Pix4D, RTK, T55
- [ ] Confirmar si T55 = T551 / T552 / T553
- [ ] 8 trabajos cobrados/realizados sin monto cargado
- [ ] Filas 77 y 78 de Trabajos: fecha de contacto inválida

## Pendientes técnicos
- [ ] Deploy (Render o Railway)
- [ ] credentials.json como variable de entorno para el deploy
- [ ] Envío automático por mail
- [ ] Chat con IA (fase 2)

## Setup local
- Python 3.14, venv en /venv
- Requiere credentials.json (service account de Google Cloud) en la raíz
- Requiere .env con CRM_SHEET_ID, VENTAS_SHEET_ID, CRM_TAB, VENTAS_TAB
- Correr: streamlit run app.py