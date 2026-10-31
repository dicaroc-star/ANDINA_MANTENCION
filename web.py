"""Entrada WSGI para HTTPS detrás de un proxy de alojamiento.

Reutiliza las operaciones de V2; no usa el servidor de desarrollo HTTP.
"""
from dataclasses import dataclass
from email.message import Message
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import urlsplit
from zipfile import ZipFile
import atexit
import io
import json
import os
import re
import time
from collections import OrderedDict, deque
from threading import Lock
import hashlib

import oracledb
from server import Application, Handler
from service import AppError, query, serial
from schema import TABLES, columns


class ConfigError(ValueError):
    """Solo mensajes escritos por la aplicación, sin valores de secretos."""


def startup_error(error):
    if isinstance(error,ConfigError):
        return 'CONFIGURACION: '+str(error)
    detail=error.args[0] if error.args else None
    code=getattr(detail,'full_code','')
    if isinstance(code,str) and re.fullmatch(r'(ORA|DPY|DPI)-\d+',code):
        return 'CONEXION ORACLE: '+code+'. Revisa credenciales, permisos y acceso de red.'
    return f'No se pudo iniciar ({type(error).__name__}). Revisa la última etapa indicada; no se muestran detalles sensibles.'


@dataclass(frozen=True)
class Settings:
    origin: str
    schema: str
    production: bool = True

    @property
    def host(self):
        return urlsplit(self.origin).netloc

    @property
    def cookie(self):
        return '__Host-andina_session' if self.production else 'andina_session'

    @classmethod
    def from_env(cls):
        origin=(os.environ.get('PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL','')).strip().rstrip('/')
        try:
            parsed=urlsplit(origin)
            valid_host=parsed.hostname
        except ValueError:
            raise ConfigError('PUBLIC_URL no tiene un formato válido. Usa la URL HTTPS de tu servicio, sin rutas.') from None
        if parsed.scheme!='https' or not valid_host or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ConfigError('Configura PUBLIC_URL con la URL HTTPS de tu servicio, sin rutas ni credenciales.')
        schema=os.environ.get('DB_SCHEMA','ADMIN').strip().upper()
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,29}',schema):
            raise ConfigError('DB_SCHEMA debe ser un nombre de esquema válido; para las tablas actuales usa ADMIN.')
        return cls(origin,schema)


class LoginLimiter:
    """Una instancia/proceso. Límites independientes por cuenta e IP, sin guardar correos."""
    def __init__(self):
        self.buckets=OrderedDict()
        self.lock=Lock()

    def check(self,ip,email):
        now=time.monotonic()
        keys=[('ip:'+ip,120),('account:'+hashlib.sha256(email.strip().lower().encode()).hexdigest(),8)]
        with self.lock:
            for key,limit in keys:
                bucket=self.buckets.setdefault(key,deque())
                while bucket and now-bucket[0]>60:
                    bucket.popleft()
                if len(bucket)>=limit:
                    raise AppError('Demasiados intentos. Espera un minuto antes de volver a entrar.',429)
            for key,_ in keys:
                self.buckets[key].append(now)
                self.buckets.move_to_end(key)
            while len(self.buckets)>10000:
                self.buckets.popitem(last=False)


class WebHandler(Handler):
    def __init__(self,application,settings,environ):
        self.server=SimpleNamespace(application=application)
        self.settings=settings
        self.environ=environ
        self.path=environ.get('PATH_INFO','/')
        if environ.get('QUERY_STRING'):
            self.path+='?'+environ['QUERY_STRING']
        self.command=environ.get('REQUEST_METHOD','GET')
        self.headers=Message()
        for key,value in environ.items():
            if key.startswith('HTTP_'):
                self.headers[key[5:].replace('_','-')]=value
        for key,name in [('CONTENT_TYPE','Content-Type'),('CONTENT_LENGTH','Content-Length')]:
            if environ.get(key):
                self.headers[name]=environ[key]
        self.rfile=environ['wsgi.input']
        self.result=None

    def guard(self,mutation):
        if self.headers.get('Host','').lower()!=self.settings.host.lower():
            raise AppError('Dirección del sitio no permitida.',403)
        if self.settings.production and self.environ.get('wsgi.url_scheme')!='https':
            raise AppError('Usa la dirección HTTPS de la aplicación.',403)
        if self.headers.get('Sec-Fetch-Site')=='cross-site':
            raise AppError('Solicitud de otro sitio rechazada.',403)
        if mutation:
            if self.headers.get('Origin')!=self.settings.origin:
                raise AppError('Origen de la solicitud no permitido.',403)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                raise AppError('Se requiere contenido JSON.',415)

    def cookie_token(self):
        cookie=SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie',''))
            return cookie[self.settings.cookie].value if self.settings.cookie in cookie else ''
        except Exception:
            return ''

    def read_body(self):
        data=super().read_body()
        if urlsplit(self.path).path in ('/api/login','/api/password'):
            email=data.get('correo','')
            # Para cambiar clave el límite se aplica por sesión y dirección.
            if urlsplit(self.path).path=='/api/password':
                email='session:'+self.cookie_token()
            if not isinstance(email,str) or len(email)>256:
                raise AppError('Credenciales inválidas.',401)
            self.app.limiter.check(self.environ.get('REMOTE_ADDR','unknown'),email)
        return data

    def respond(self,status,body,content_type='application/json; charset=utf-8',cookie=None):
        if not isinstance(body,bytes):
            body=json.dumps(body,ensure_ascii=False,default=serial).encode('utf-8')
        headers=[('Content-Type',content_type),('Content-Length',str(len(body))),
                 ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),
                 ('Referrer-Policy','no-referrer'),('X-Frame-Options','DENY'),
                 ('Permissions-Policy','camera=(), microphone=(), geolocation=()'),
                 ('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]
        if self.settings.production:
            headers.append(('Strict-Transport-Security','max-age=31536000'))
        if cookie:
            cookie=cookie.replace('andina_session=',self.settings.cookie+'=',1)
            if self.settings.production:
                cookie+='; Secure'
            headers.append(('Set-Cookie',cookie))
        self.result=(f'{status} {HTTPStatus(status).phrase}',headers,[body])


def create_wsgi(application,settings):
    application.limiter=LoginLimiter()
    # El límite local global no se aplica en internet; WebHandler limita por cuenta/IP.
    application.check_attempts=lambda:None

    def wsgi(environ,start_response):
        handler=WebHandler(application,settings,environ)
        path=environ.get('PATH_INFO','/')
        method=environ.get('REQUEST_METHOD','GET')
        if method not in ('GET','POST'):
            handler.respond(405,dict(error='Método no permitido.'))
        elif path=='/health/live' and method=='GET':
            # El healthcheck del proveedor puede usar un Host interno. No devuelve datos de Oracle.
            handler.respond(200,dict(status='ok'))
        elif path=='/health/ready' and method=='GET':
            try:
                handler.guard(False)
                with application.pool.acquire() as connection:
                    connection.call_timeout=5000
                    query(connection,'SELECT 1 AS value FROM dual')
                handler.respond(200,dict(status='ready'))
            except Exception:
                handler.respond(503,dict(error='Servicio temporalmente no disponible.'))
        else:
            handler.dispatch(method=='POST')
        if handler.result is None:
            handler.respond(500,dict(error='No se pudo completar la solicitud.'))
        status,headers,body=handler.result
        start_response(status,headers)
        return body
    return wsgi


def build_application():
    print('INICIO 1/4: comprobando variables de configuración.',flush=True)
    settings=Settings.from_env()
    user=os.environ.get('DB_USER','').strip()
    if not user or user.upper() in ('ADMIN','SYS','SYSTEM'):
        raise ConfigError('DB_USER falta o usa una cuenta administrativa. Configura ANDINA_APP.')
    required=['DB_PASSWORD','DB_SERVICE','WALLET_PASSWORD']
    missing=[name for name in required if not os.environ.get(name)]
    if missing:
        raise ConfigError('Faltan estas variables: '+', '.join(missing)+'. Revisa sus nombres exactos en Environment.')
    temp=TemporaryDirectory(prefix='andina-web-wallet-')
    try:
        if os.name=='posix':
            os.chmod(temp.name,0o700)
        print('INICIO 2/4: comprobando archivos secretos del Wallet.',flush=True)
        # En Render se montan secretos de texto en /etc/secrets; no entran a la imagen.
        for filename in ('tnsnames.ora','ewallet.pem'):
            path=Path(os.environ.get('WALLET_DIR','/etc/secrets'))/filename
            if not path.is_file() or path.stat().st_size>2_000_000:
                raise ConfigError('No se encuentra un archivo secreto válido llamado '+filename+'. Revisa Secret Files y WALLET_DIR=/etc/secrets.')
            content=path.read_bytes()
            if filename=='ewallet.pem' and not re.search(rb'-----BEGIN (?:ENCRYPTED PRIVATE KEY|PRIVATE KEY|RSA PRIVATE KEY)-----',content):
                raise ConfigError('ewallet.pem no contiene una clave PEM. Copia el contenido completo del archivo ewallet.pem; no el de tnsnames.ora.')
            if filename=='tnsnames.ora':
                alias=os.environ['DB_SERVICE'].strip()
                if not re.search(r'(?im)^\s*'+re.escape(alias)+r'\s*=',content.decode('utf-8-sig')):
                    raise ConfigError('DB_SERVICE no coincide con un alias de tnsnames.ora. Comprueba basedatos2026_high y el contenido del archivo.')
            destination=Path(temp.name,filename)
            destination.write_bytes(content)
            if os.name=='posix':
                os.chmod(destination,0o600)
        def configure(connection,tag):
            with connection.cursor() as cursor:
                cursor.execute("ALTER SESSION SET TIME_ZONE='America/Santiago'")
                cursor.execute(f'ALTER SESSION SET CURRENT_SCHEMA={settings.schema}')
        print('INICIO 3/4: conectando a Oracle con la cuenta técnica.',flush=True)
        pool=oracledb.create_pool(user=user,password=os.environ['DB_PASSWORD'],dsn=os.environ['DB_SERVICE'].strip(),
             config_dir=temp.name,wallet_location=temp.name,wallet_password=os.environ['WALLET_PASSWORD'],
             min=1,max=4,increment=1,session_callback=configure,
             getmode=oracledb.POOL_GETMODE_TIMEDWAIT,wait_timeout=10000)
        try:
            print('INICIO 4/4: comprobando tablas y administrador activo.',flush=True)
            with pool.acquire() as connection:
                connection.call_timeout=20000
                for table in TABLES:
                    query(connection,f"SELECT {','.join(columns(table))} FROM {table} WHERE 1=0")
                ready=query(connection,"""SELECT u.id_usuario FROM usuario u JOIN rol r ON r.id_rol=u.id_rol
                 WHERE u.estado='ACTIVO' AND r.nombre='ADMINISTRADOR' AND u.clave_hash LIKE 'pbkdf2_sha256$%'
                 FETCH FIRST 1 ROWS ONLY""")
                if not ready:
                    raise ConfigError('No hay un administrador activo con contraseña configurada en DB_SCHEMA. Revisa el esquema o activa el administrador desde la versión local.')
        except Exception:
            pool.close()
            raise
    except Exception:
        temp.cleanup()
        raise
    def cleanup():
        try:
            pool.close(force=True)
        finally:
            temp.cleanup()
    atexit.register(cleanup)
    return create_wsgi(Application(pool),settings)


def main():
    from waitress import serve
    try:
        app=build_application()
    except Exception as error:
        # No imprimir textos de excepciones que puedan contener configuración sensible.
        print(startup_error(error),flush=True)
        raise SystemExit(1)
    port=int(os.environ.get('PORT','10000'))
    options=dict(host='0.0.0.0',port=port,threads=8,connection_limit=100,
                 channel_timeout=30,max_request_body_size=32768,expose_tracebacks=False,
                 clear_untrusted_proxy_headers=True)
    # Render termina TLS y entrega el tráfico por su proxy. Otros entornos deben declarar su proxy exacto.
    proxy=os.environ.get('TRUSTED_PROXY')
    if proxy:
        options.update(trusted_proxy=proxy,trusted_proxy_headers={'x-forwarded-proto'},trusted_proxy_count=1)
    serve(app,**options)

if __name__=='__main__':
    main()
