# AndinaMantención · entrega del 6 de noviembre de 2026

## Aplicación real

La URL de la aplicación es https://andina-mantencion.onrender.com/. Usa las cuentas y los registros existentes de Oracle. Los servidores locales de vista previa no son la aplicación publicada.

Se incorporó el diseño de las capturas a acceso, panel, reporte de fallas, fichas de activos y detalle lateral de órdenes. La interfaz funciona en escritorio y celular; las fuentes están incluidas localmente.

## Funciones y permisos

- Administración: gestiona usuarios, roles y módulos operativos. La cuenta propietaria conserva su protección existente.
- Supervisión: activos, ubicaciones, incidencias, órdenes, preventivos y repuestos; no administra cuentas ni roles.
- Técnico: registra intervenciones y consumos de sus órdenes asignadas en proceso. No puede modificar trabajo ajeno ni asignar órdenes.
- Planta: registra fallas y puede corregir sus reportes mientras sigan REPORTADA. Los otros módulos son de consulta.
- El historial registra automáticamente las transiciones de las órdenes. Los registros operativos no se borran desde la aplicación.
- El consumo de repuestos ajusta el stock en la misma transacción y rechaza saldos negativos. Se conserva el control de versiones para evitar sobrescribir cambios concurrentes.
- Cada activo dispone de un QR descargable que abre su reporte por código. El envío requiere iniciar sesión; no se crean reportes al escanear.
- Los comprobantes se descargan como texto. Las órdenes conservan su exportación JSON de la página consultada.
- Los indicadores y gráficos se calculan con Oracle; las semanas respetan la fecha de la sesión configurada en America/Santiago.

## Activación de las fotografías

Las fotografías se guardan como BLOB privados en una tabla adicional; no en el disco temporal de Render. Los registros de las 11 tablas originales no se modifican por esta activación.

Ejecutar una vez `ACTIVAR_FOTOS.sql` como propietario de las tablas, o abrir `ACTIVAR_FOTOS.cmd` en Windows y seguir el asistente. El asistente pide el ZIP del Wallet, el usuario propietario y las claves de forma local. No guarda las claves. Muestra el cambio y requiere escribir ACTIVAR antes de ejecutar DDL.

Se crea `incidencia_evidencia`, con referencias a incidencia y usuario, y se concede únicamente SELECT e INSERT sobre esa tabla a ANDINA_APP. Oracle confirma cada instrucción DDL por separado. No se conceden DELETE, privilegios ANY ni permisos de creación de tablas a la cuenta técnica.

Después, recargar la aplicación. Se permiten hasta tres JPG, PNG o WebP; la interfaz ajusta las imágenes y el servidor verifica y vuelve a codificar el contenido. Se eliminan los metadatos EXIF. Reporte y fotografías se confirman juntos; si falla una foto no queda un reporte incompleto. La consulta de fotografías requiere una sesión válida, igual que las incidencias.

Hasta activar la tabla, la aplicación informa que las fotografías no están habilitadas y permite registrar fallas sin adjuntos. No simula que las haya guardado.

## Verificación

Ejecutar con las dependencias de requirements.txt instaladas:

```text
python -m unittest test_app test_transactions test_web test_evidence test_roles test_qr
node test_frontend.cjs
```

Las pruebas Python usan SQLite efímera como adaptador del servicio y WSGI. No reemplazan la verificación del dialecto y los permisos en Oracle real. Se verificó además en navegador un reporte de planta con fotografía, comprobante, recuperación de la fotografía y apertura del formulario mediante QR, utilizando un entorno temporal sin Oracle.

La actualización del código no migra datos ni restablece contraseñas. Las sesiones en memoria se cierran cuando Render reinicia el servicio. No se contrató almacenamiento ni se modificó el plan de alojamiento.
