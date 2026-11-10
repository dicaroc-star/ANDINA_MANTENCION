# Sprint 2 — AndinaMantención

**Asignatura:** Ingeniería de Requisitos · Duoc UC  
**Proyecto:** Sistema de Gestión de Mantenimiento Industrial — Manufacturas Andina S.A.  
**Estado:** Planificado (pendiente de desarrollo, pruebas y validación)  
**Rama de trabajo:** `sprint-2-alertas-20261110`  
**Fecha de planificación:** 10-11-2026

> Esta planificación es una propuesta técnica. La pauta oficial de Sprint 2 no se ha compartido; revisar requisitos de evaluación antes de entregar.

## 1. Objetivo del Sprint

Transformar los datos de mantenimiento y repuestos en **alertas operativas accionables**, de modo que el supervisor identifique con rapidez los preventivos vencidos o próximos y los repuestos bajo el mínimo, sin modificar las 11 tablas originales de Oracle.

## 2. Línea base verificada en GitHub

- Existe autenticación con distintos roles y permisos.
- Hay CRUD de activos, incidencias, órdenes de trabajo, preventivos y repuestos.
- Los activos tienen QR para abrir un formulario de reporte tras autenticación.
- El tablero ya presenta indicadores agregados, incluidos «Preventivos programados» y «Repuestos bajo mínimo», y muestra hasta tres preventivos programados.
- El consumo de repuestos tiene lógica transaccional y se preserva el historial de órdenes.

Lo anterior describe código y documentación en `main`; el funcionamiento con Oracle real deberá comprobarse en las pruebas del Sprint.

## 3. Historias de usuario y criterios de aceptación

### HU-S2-01 · Alertas de preventivos — Alta

**Como supervisor**, quiero ver en el panel los mantenimientos preventivos vencidos y aquellos que vencen durante los próximos 7 días, para priorizar intervenciones.

**Aceptación:**
- Mostrar únicamente preventivos con estado `PROGRAMADO`.
- Clasificar por fecha programada: `Vencido` si es anterior a la fecha actual de la sesión Oracle; `Próximo` si es hoy o durante los 7 días siguientes.
- Cada alerta muestra código del activo, descripción, fecha programada y responsable cuando esté disponible.
- Permitir abrir el módulo de mantenimiento preventivo desde la alerta.
- Mostrar un estado vacío claro cuando no existan resultados.
- No mutar datos desde la consulta.

### HU-S2-02 · Repuestos críticos — Alta

**Como supervisor**, quiero identificar los repuestos activos cuya existencia llegó al mínimo establecido para gestionar su reposición.

**Aceptación:**
- Mostrar repuestos con `estado='ACTIVO'`, `stock_minimo > 0` y `stock_actual <= stock_minimo`.
- Mostrar código, nombre, stock actual, mínimo y unidades faltantes para superar el umbral.
- Acceso directo al módulo de repuestos.
- No permitir que una consulta de alertas modifique existencias.
- Respetar los permisos actuales de lectura.

### HU-S2-03 · Tablero de alertas — Media

**Como administrador o supervisor**, quiero consultar las alertas en un único apartado del tablero, para decidir qué revisar primero.

**Aceptación:**
- Contadores y listados concuerdan con la misma consulta de datos.
- Indicadores con textos legibles en celular y escritorio.
- Visualizar estado de carga, error de consulta y mensaje de lista vacía.
- Evitar que una alerta incluya contraseñas, credenciales o datos no necesarios.

### HU-S2-04 · Filtros y seguimiento — Media

**Como supervisor**, quiero filtrar incidencias por prioridad y preventivos por estado/vencimiento para reducir el tiempo de búsqueda.

**Aceptación:**
- Filtrar prioridad de incidencias: BAJA, MEDIA, ALTA y CRITICA.
- Filtrar preventivos por PROGRAMADO, EN_PROCESO, COMPLETADO y CANCELADO, y visualizar su proximidad temporal.
- Al limpiar filtros vuelve la lista completa permitida al usuario.
- No altera la paginación ni la edición existente.

## 4. Plan técnico

1. Crear consultas de alertas reutilizando el esquema Oracle actual, con fecha según la sesión configurada en `America/Santiago`.
2. Exponer datos mediante API autenticada; verificar permisos en servidor, no solo en interfaz.
3. Agregar tarjetas/listas del tablero y enlaces a los módulos correspondientes, conservando el estilo de AndinaMantención.
4. Incorporar los filtros por prioridad y vencimiento sin romper las búsquedas existentes.
5. Agregar pruebas unitarias y de integración, documentar resultados y actualizar `README.md`.

**Archivos potenciales:** `service.py`, `server.py`, `web.py`, `app.js`, `stitch-templates.js`, `styles.css`, pruebas de Python/JavaScript.

## 5. Pruebas y evidencias esperadas

- Preventivo vencido / con fecha de hoy / dentro de 7 días / fuera de la ventana; verificar clasificación.
- Repuesto con stock por debajo / igual / por encima del mínimo y mínimo 0; verificar inclusión.
- Probar acceso con administrador, supervisor, técnico y planta (según permiso).
- Comprobar que ninguna alerta modifica Oracle; probar lista vacía y error de consulta.
- Ejecutar pruebas existentes: `python -m unittest test_app test_transactions test_web test_evidence test_roles test_qr` y `node test_frontend.cjs`; añadir las pruebas específicas del Sprint 2.
- Registrar capturas del tablero, preventivos y repuestos; video corto de flujo real.
- Verificar en aplicación desplegada con Oracle, aparte de las pruebas SQLite locales.
- Mantener el diagrama de las 11 tablas como evidencia del modelo.

## 6. Definición de terminado (DoD)

- [ ] HU-S2-01 a HU-S2-04 implementadas en rama Sprint 2.
- [ ] Pruebas nuevas y anteriores ejecutadas y resultados documentados.
- [ ] Verificación real en Oracle y validación de permisos.
- [ ] Interfaz comprobada en escritorio y celular.
- [ ] Evidencias (capturas, video, esquema y commits) reunidas.
- [ ] Cambios revisados y, solo entonces, integrados a `main`.

## 7. Nota de alcance

No se crearán datos falsos de maquinaria, ni enlaces QR inventados. Las alertas se calculan sobre los registros existentes y no requieren nuevas tablas. La fecha de entrega del Sprint 2 dependerá de la pauta oficial de la asignatura.
