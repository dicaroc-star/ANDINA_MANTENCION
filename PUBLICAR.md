# AndinaMantención — preparación para acceso desde otros computadores

## Estado de esta entrega

El código está adaptado para un alojamiento Python con HTTPS y conexión real a Oracle Cloud. **Todavía no está publicado y no tiene una URL pública verificada.** Descargar estos archivos no cambia el servidor que ya está abierto en tu PC.

Se conservan las 11 tablas, los registros y las cuentas de aplicación existentes. No hay registro público de usuarios: el administrador crea cada cuenta. Cualquier usuario registrado puede entrar si está ACTIVO, tiene una contraseña real configurada y su rol es uno de los cuatro admitidos. El correo es un identificador; no se comprueba que exista un buzón ni se envían emails.

## Qué cambió para la web

- Servidor WSGI Waitress en lugar del servidor HTTP de desarrollo para la publicación.
- Dirección HTTPS configurada por alojamiento; validación de Host y Origin para esa dirección.
- Cookie `__Host-andina_session` con Secure, HttpOnly, SameSite=Strict y Path=/, sin Domain.
- Cabeceras de seguridad, protección CSRF y límites de intentos independientes por cuenta. El límite adicional por dirección usa REMOTE_ADDR sin confiar en X-Forwarded-For.
- Los datos y formularios se mantienen detrás del acceso. Solo la página de login y sus archivos públicos se entregan sin sesión.
- La conexión se configura con secretos del alojamiento. El sitio público no solicita Wallet ni credenciales en el navegador, y no permite activar administradores desde una ruta pública.
- Se exige una cuenta técnica distinta de ADMIN, SYS y SYSTEM. El esquema propietario se selecciona mediante CURRENT_SCHEMA para consultar las tablas existentes sin moverlas.
- Cambiar una contraseña invalida también sesiones cuyo proceso no recibió la revocación, porque cada solicitud verifica una huella de la credencial actual.
- Una sola instancia/proceso con sesiones en memoria durante una hora. Un reinicio cierra las sesiones; los datos permanecen en Oracle. No escalar a varias instancias hasta añadir almacenamiento compartido de sesiones y límites.

El paquete es una base para publicación académica con medidas de seguridad adicionales. No equivale a una auditoría de seguridad ni a una certificación de producción.

## Paso 1 — conectar el alojamiento

Se preparó configuración para Render. Instala y conecta la integración Render en Codex, o crea tu cuenta directamente en https://dashboard.render.com/. Los pasos de registro y aceptación de términos los realizas tú.

La publicación necesita acceso a una cuenta del alojamiento. La integración no estaba conectada al preparar este paquete. No se creó un servicio, no se contrató ningún plan y no se generó una dirección pública.

Render puede desplegar este Dockerfile desde un repositorio Git conectado o una imagen. La raíz del repositorio debe contener los archivos de este paquete, especialmente Dockerfile y render.yaml; si usas una subcarpeta, configúrala como Root Directory. Para Git, sube solo el código, nunca Wallet, claves, archivos .pem/.ora ni .env con secretos.

## Paso 2 — preparar la cuenta Oracle de privilegios limitados

En tu computador, con la carpeta extraída:

1. Abre **PREPARAR_CUENTA.cmd**.
2. Introduce el Wallet y las claves Oracle de la misma manera que en la prueba local.
3. El programa muestra qué cuenta creará: **ANDINA_APP**.
4. Revisa los permisos y escribe **CREAR** solamente si quieres aplicarlos.
5. Establece una contraseña propia para esa cuenta técnica. No es tu contraseña para entrar a la página.

El programa crea un usuario de base de datos, concede CREATE SESSION y ALTER SESSION y permisos sobre las tablas del propietario. Puede leer las 11 tablas; insertar/actualizar las operativas; y leer/insertar historial_estado. No concede DELETE, CREATE TABLE, DBA ni privilegios ANY. El historial no se puede actualizar con esta cuenta.

La creación y los GRANT son DDL: Oracle los confirma individualmente. Si falla a mitad, revisa los permisos ya aplicados con el administrador; el programa no promete deshacer DDL. Si ANDINA_APP ya existe, no la cambia ni restablece su contraseña automáticamente. Este preparador se ejecuta localmente; no se incluye en la imagen del sitio.

No se crea otra base de datos ni se copian tus tablas. El administrador de aplicación que ya activaste conserva su contraseña.

## Paso 3 — secretos de Render

En el servicio, sección **Environment**, introduce los valores directamente allí:

| Variable | Valor |
|---|---|
| DB_USER | ANDINA_APP |
| DB_SCHEMA | ADMIN, si ese usuario es el propietario de las tablas |
| DB_SERVICE | basedatos2026_high |
| DB_PASSWORD | Contraseña de la cuenta técnica ANDINA_APP |
| WALLET_PASSWORD | Contraseña establecida al descargar el Wallet |
| WALLET_DIR | /etc/secrets |
| TRUSTED_PROXY | * exclusivamente detrás del proxy del alojamiento |

La aplicación usa **RENDER_EXTERNAL_URL** automáticamente como origen permitido. Si agregas un dominio propio, define PUBLIC_URL con el origen HTTPS exacto, por ejemplo `https://tu-dominio.example`, sin rutas, y verifica que ese dominio ya sirve el sitio. No uses la dirección de ejemplo como si fuera una URL real.

En **Secret Files**, crea dos secretos de texto con los nombres exactos:

- **tnsnames.ora**: contenido de ese archivo dentro del Wallet.
- **ewallet.pem**: contenido de ese archivo dentro del Wallet.

Estos contenidos son secretos: no los pegues en el chat, no los subas al repositorio y no los incorpores a la imagen Docker. La lista de COPY del Dockerfile solo incluye código y archivos públicos; .dockerignore aplica una lista permitida de archivos. El proceso copia los dos secretos a una carpeta temporal de acceso restringido y los mantiene mientras el servidor funciona.

## Paso 4 — red hacia Oracle

La conexión que funcionó desde tu PC no demuestra todavía que Oracle acepte al servidor del alojamiento.

Si Oracle tiene una lista de redes permitidas, obtén las redes de salida del servicio Render desde **Connect → Outbound** y configura solo las redes que correspondan en Oracle con el administrador. No desactives mTLS, la validación de certificados ni la autenticación para resolver un error de conexión. El Wallet y la contraseña técnica siguen siendo obligatorios.

## Paso 5 — desplegar y comprobar

El Dockerfile instala python-oracledb y Waitress y ejecuta `python web.py`. El servicio escucha en 0.0.0.0 y el puerto PORT que proporciona el alojamiento. Esto corresponde a un contenedor detrás del proxy HTTPS, no a exponer tu PC por internet.

`TRUSTED_PROXY=*` se limita a la red de entrada gestionada del proveedor y solo permite X-Forwarded-Proto. Fuera de ese entorno, especifica la IP exacta del proxy y evita acceso directo al puerto del proceso. No se confía en Host ni X-Forwarded-Host de un tercero.

El manifiesto fija **una instancia** y plan **free**, para evaluar sin contratar un plan de pago. Render advierte que Free no es para producción: se suspende por inactividad, puede tardar en arrancar y está sujeto a límites de uso. Para disponibilidad continua, revisa y aprueba un plan de pago desde tu cuenta; no se contrata automáticamente. Oracle sigue almacenando los datos aunque el alojamiento reinicie.

`/health/live` solo comprueba que el proceso responde, sin revelar datos. `/health/ready` verifica una consulta mínima a Oracle bajo el origen HTTPS permitido. Además, el arranque valida que existan las 11 tablas y un administrador activo con contraseña configurada.

No compartas una dirección hasta que el despliegue termine correctamente. Después:

1. Abre la URL HTTPS publicada desde una ventana privada.
2. Comprueba que sin sesión no se pueden consultar los módulos.
3. Entra con tu cuenta existente y revisa EXT-001 y los indicadores.
4. Desde Usuarios crea/activa la cuenta del profesor, si todavía no existe. Datos acordados: Federico / Lohse Rowe / federico.lohse@andinamantencion.example. Rol propuesto: SUPERVISOR; puede modificar datos operativos. Define su contraseña directamente en la app y comunícasela por un medio privado. Este paquete no crea esa cuenta automáticamente.
5. Prueba acceso con esa cuenta desde otro navegador. Rechaza un correo no registrado, clave incorrecta y usuario INACTIVO.
6. Prueba un guardado de incidencia marcado como prueba, y confirma su persistencia en SQL Developer.
7. Cierra sesión y comprueba que ya no se pueden consultar datos.

Las sesiones de la versión local y del sitio público son independientes. Para compartir el acceso entrega la URL HTTPS publicada; nunca el Wallet, la contraseña de Oracle ni la cuenta técnica.

## Verificación realizada

Las pruebas automáticas usan datos efímeros y un adaptador de pruebas SQLite, no el Oracle del alumno. Cubren el servicio, los flujos de mantenimiento y las solicitudes WSGI: HTTPS, Host, Origin, cookie Secure, CSRF, usuarios no registrados/inactivos, límites por cuenta y revocación tras cambio externo de contraseña. Se comprobó la configuración de Waitress 3.0.2 con el paquete oficial instalado para pruebas.

No se ejecutó el contenedor Docker ni se validó una conexión desde Render a tu Oracle. No se accedió al Wallet ni a las contraseñas del usuario en este entorno. La publicación y la prueba desde un segundo computador están pendientes.

Pruebas: `py -m unittest -v test_web test_app test_transactions` y, con Node, `node test_frontend.cjs`.

## Referencias oficiales

- Render, servicios web y HTTPS: https://render.com/docs/web-services
- Secretos y archivos: https://render.com/docs/configure-environment-variables
- Redes de salida: https://render.com/docs/outbound-ip-addresses
- Limitaciones Free: https://render.com/docs/free
- Waitress detrás de un proxy: https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html
