"""Servidor local académico: Oracle real, sesiones en memoria y archivos públicos permitidos."""
from collections import deque
from contextlib import closing
from datetime import datetime
from getpass import getpass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from urllib.parse import urlsplit, parse_qs
from zipfile import ZipFile, BadZipFile
import hmac
import hashlib
import json
import secrets
import sys
import time
import webbrowser

import oracledb
from schema import TABLES, columns, ROLE_NAMES
from security import Sessions, hash_password, verify_password
from service import Service, AppError, query, one, serial

ROOT=Path(__file__).resolve().parent
HOST='127.0.0.1'
PORT=8765
ORIGIN=f'http://{HOST}:{PORT}'
PUBLIC={'/':('index.html','text/html; charset=utf-8'),
        '/index.html':('index.html','text/html; charset=utf-8'),
        '/app.js':('app.js','text/javascript; charset=utf-8'),
        '/styles.css':('styles.css','text/css; charset=utf-8')}

def configure_session(connection,requested_tag):
    # LOCALTIMESTAMP usa la zona de la sesión: la fijamos para coincidir con la interfaz chilena.
    with connection.cursor() as cursor:
        cursor.execute("ALTER SESSION SET TIME_ZONE='America/Santiago'")

class Application:
    def __init__(self,pool):
        self.service=Service(pool)
        self.pool=pool
        self.sessions=Sessions()
        self.login_attempts=deque()
        self.login_lock=Lock()
        self.dummy_hash=hash_password(secrets.token_urlsafe(24))

    def check_attempts(self):
        with self.login_lock:
            now=time.monotonic()
            while self.login_attempts and now-self.login_attempts[0]>60:
                self.login_attempts.popleft()
            if len(self.login_attempts)>=8:
                raise AppError('Demasiados intentos. Espera un minuto e inténtalo de nuevo.',429)
            self.login_attempts.append(now)

class Handler(BaseHTTPRequestHandler):
    server_version='AndinaMantencion/2'
    sys_version=''

    def log_message(self,*args):
        # Nunca registrar cuerpos de solicitudes, contraseñas o cookies.
        pass

    @property
    def app(self):
        return self.server.application

    def respond(self,status,body,content_type='application/json; charset=utf-8',cookie=None):
        if not isinstance(body,bytes):
            body=json.dumps(body,ensure_ascii=False,default=serial).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if cookie:
            self.send_header('Set-Cookie',cookie)
        self.end_headers()
        self.wfile.write(body)

    def guard(self,mutation):
        self.connection.settimeout(15)
        if self.headers.get('Host')!=f'{HOST}:{PORT}':
            raise AppError('Abre la aplicación con la dirección local indicada por el servidor.',403)
        if self.headers.get('Sec-Fetch-Site')=='cross-site':
            raise AppError('Solicitud de otro sitio rechazada.',403)
        if mutation:
            if self.headers.get('Origin')!=ORIGIN:
                raise AppError('Origen de la solicitud no permitido.',403)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                raise AppError('Se requiere contenido JSON.',415)

    def read_body(self):
        if self.headers.get('Transfer-Encoding'):
            raise AppError('Formato de solicitud no permitido.')
        try:
            size=int(self.headers.get('Content-Length','0'))
        except ValueError:
            raise AppError('Tamaño de solicitud inválido.')
        if not 0<size<=32768:
            raise AppError('La solicitud está vacía o es demasiado grande.',413)
        try:
            body=json.loads(self.rfile.read(size))
        except (ValueError,UnicodeError):
            raise AppError('El formulario no es válido.')
        if not isinstance(body,dict):
            raise AppError('Se esperaba un formulario JSON.')
        return body

    def cookie_token(self):
        cookie=SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie',''))
            return cookie['andina_session'].value if 'andina_session' in cookie else ''
        except Exception:
            return ''

    def authenticate(self,connection,mutation=False):
        session=self.app.sessions.get(self.cookie_token())
        if not session:
            raise AppError('Inicia sesión para continuar.',401)
        user=self.app.service.user(connection,session['user_id'])
        if not user or user['estado']!='ACTIVO' or user['rol'] not in ROLE_NAMES:
            self.app.sessions.remove(self.cookie_token())
            raise AppError('La cuenta no está habilitada.',401)
        if session.get('credential'):
            account=one(connection,'SELECT clave_hash FROM usuario WHERE id_usuario=:id',dict(id=user['id_usuario']))
            fingerprint=hashlib.sha256(account['clave_hash'].encode()).hexdigest() if account else ''
            if not hmac.compare_digest(session['credential'],fingerprint):
                self.app.sessions.remove(self.cookie_token())
                raise AppError('La contraseña cambió. Inicia sesión nuevamente.',401)
        if mutation and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']):
            raise AppError('La sesión del formulario no es válida. Recarga la página.',403)
        return user,session

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self,mutation):
        try:
            self.guard(mutation)
            parsed=urlsplit(self.path)
            path=parsed.path
            if not mutation and path in PUBLIC:
                filename,mime=PUBLIC[path]
                self.respond(200,(ROOT/filename).read_bytes(),mime)
                return
            if not path.startswith('/api/'):
                raise AppError('Página no encontrada.',404)
            body=self.read_body() if mutation else None
            with self.app.pool.acquire() as connection:
                connection.call_timeout=20000
                if mutation and path=='/api/login':
                    self.app.check_attempts()
                    email=body.get('correo','')
                    password=body.get('password','')
                    if not isinstance(email,str) or not isinstance(password,str) or len(email)>150 or len(password)>128:
                        raise AppError('Credenciales inválidas.',401)
                    rows=query(connection,'''SELECT u.id_usuario,u.clave_hash,u.estado,r.nombre AS rol
                     FROM usuario u JOIN rol r ON r.id_rol=u.id_rol WHERE LOWER(u.correo)=:email''',dict(email=email.strip().lower()))
                    record=rows[0] if len(rows)==1 else None
                    valid=verify_password(password,record['clave_hash'] if record and record['clave_hash'].startswith('pbkdf2_') else self.app.dummy_hash)
                    if not record or not valid or record['estado']!='ACTIVO' or record['rol'] not in ROLE_NAMES:
                        raise AppError('Correo o contraseña incorrectos, o cuenta sin activar.',401)
                    self.app.sessions.remove(self.cookie_token())
                    token,csrf=self.app.sessions.create(record['id_usuario'],hashlib.sha256(record['clave_hash'].encode()).hexdigest())
                    user=self.app.service.user(connection,record['id_usuario'])
                    self.respond(200,dict(user=user,csrf=csrf),cookie=f'andina_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600')
                    return
                user,session=self.authenticate(connection,mutation)
                if path=='/api/me' and not mutation:
                    self.respond(200,dict(user=user,csrf=session['csrf']))
                elif path=='/api/logout' and mutation:
                    self.app.sessions.remove(self.cookie_token())
                    self.respond(200,dict(ok=True),cookie='andina_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                elif path=='/api/password' and mutation:
                    current=body.get('current','')
                    updated=body.get('password','')
                    if not isinstance(current,str) or len(current)>128:
                        raise AppError('Contraseña actual inválida.')
                    self.app.check_attempts()
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT clave_hash FROM usuario WHERE id_usuario=:id FOR UPDATE WAIT 5',dict(id=user['id_usuario']))
                        encoded=cursor.fetchone()[0]
                        if not verify_password(current,encoded):
                            raise AppError('La contraseña actual no es correcta.')
                        try:
                            updated_hash=hash_password(updated)
                        except ValueError as error:
                            raise AppError(str(error))
                        cursor.execute('UPDATE usuario SET clave_hash=:encoded WHERE id_usuario=:id',dict(encoded=updated_hash,id=user['id_usuario']))
                    connection.commit()
                    self.app.sessions.revoke_user(user['id_usuario'])
                    self.respond(200,dict(ok=True),cookie='andina_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                elif path=='/api/meta' and not mutation:
                    self.respond(200,self.app.service.metadata(user['rol'],user))
                elif path=='/api/lookups' and not mutation:
                    self.respond(200,self.app.service.lookups(connection))
                elif path=='/api/dashboard' and not mutation:
                    self.respond(200,self.app.service.dashboard(connection))
                elif path.startswith('/api/records/'):
                    table=path.removeprefix('/api/records/')
                    if table not in TABLES:
                        raise AppError('Módulo no encontrado.',404)
                    if mutation:
                        identifier=body.get('id')
                        if identifier is not None and (type(identifier) is not int or identifier<=0):
                            raise AppError('Identificador inválido.')
                        try:
                            saved=self.app.service.save(connection,table,identifier,body.get('data'),user)
                            connection.commit()
                        except Exception:
                            connection.rollback()
                            raise
                        if table=='usuario' and identifier is not None:
                            self.app.sessions.revoke_user(identifier)
                        self.respond(200,dict(id=saved,message='Registro guardado en Oracle.'))
                    else:
                        params=parse_qs(parsed.query)
                        try:
                            page=int(params.get('page',['1'])[0])
                            if not 1<=page<=1000000:
                                raise ValueError()
                        except ValueError:
                            raise AppError('Página inválida.')
                        result=self.app.service.list_rows(connection,table,user['rol'],page,params.get('q',[''])[0],params.get('state',[''])[0])
                        self.respond(200,result)
                else:
                    raise AppError('Ruta no encontrada.',404)
        except AppError as error:
            self.respond(error.status,dict(error=str(error)))
        except oracledb.Error as error:
            detail=error.args[0] if error.args else None
            code=getattr(detail,'code',0)
            messages={1:'Ya existe un registro con ese código, nombre o correo.',
                      2291:'La referencia seleccionada ya no existe. Actualiza la lista.',
                      2290:'El registro no cumple una restricción del modelo de datos.',
                      1400:'Falta un campo obligatorio.',12899:'Un texto supera la longitud permitida.',
                      30006:'El registro está ocupado. Espera y vuelve a intentarlo.',
                      60:'Otra operación estaba modificando estos registros. Inténtalo de nuevo.'}
            public_code=getattr(detail,'full_code','ERROR_ORACLE')
            self.respond(409 if code in messages else 503,dict(error=messages.get(code,f'No se pudo completar la operación en Oracle ({public_code}). Revisa la ventana del servidor y la conexión.')))
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            pass
        except Exception as error:
            print(f'Error interno: {type(error).__name__}. No se guardó una operación incompleta.')
            self.respond(500,dict(error='Error interno del servidor. Revisa la ventana del programa.'))

def bootstrap(connection):
    rows=query(connection,"""SELECT u.id_usuario,u.correo,u.nombre,u.apellido FROM usuario u
      JOIN rol r ON r.id_rol=u.id_rol WHERE r.nombre='ADMINISTRADOR' AND u.estado='ACTIVO'
      AND u.clave_hash='PENDIENTE_HASH' ORDER BY u.id_usuario""")
    ready=one(connection,"""SELECT COUNT(*) AS total FROM usuario u JOIN rol r ON r.id_rol=u.id_rol
      WHERE r.nombre='ADMINISTRADOR' AND u.estado='ACTIVO' AND u.clave_hash LIKE 'pbkdf2_sha256$%'""")['total']
    if ready:
        print('Ya existe un administrador con contraseña configurada.')
        return
    if not rows:
        raise AppError('No hay administrador activo con PENDIENTE_HASH para activar. Revisa la tabla usuario.')
    print('\nPRIMER ACCESO REAL: activar un administrador existente.')
    for row in rows:
        print(f"  ID {row['id_usuario']} · {row['correo']} · {row['nombre']} {row['apellido']}")
    choice=input(f"ID a activar [{rows[0]['id_usuario']}]: ").strip() or str(rows[0]['id_usuario'])
    selected=next((row for row in rows if str(row['id_usuario'])==choice),None)
    if not selected:
        raise AppError('ID no válido; no se hicieron cambios.')
    email=input('Correo de acceso [diego.caro@andinamantencion.example]: ').strip().lower() or 'diego.caro@andinamantencion.example'
    # Valida el correo con la misma regla que el formulario de usuarios.
    import re
    if len(email)>150 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
        raise AppError('Correo inválido; no se hicieron cambios.')
    print(f"Se actualizarán SOLO correo y clave_hash del usuario ID {selected['id_usuario']}.")
    print(f"Correo: {selected['correo']} -> {email}. Nombre y rol se conservan.")
    if input('Escribe SI para aplicar esta configuración: ').strip().upper()!='SI':
        raise AppError('Activación cancelada; no se hicieron cambios.')
    while True:
        password=getpass('Nueva contraseña de la APP (12 a 128 caracteres): ')
        confirmation=getpass('Repite la nueva contraseña: ')
        if password!=confirmation:
            print('No coinciden. Vuelve a escribirlas.')
            continue
        try:
            encoded=hash_password(password)
            break
        except ValueError as error:
            print(error)
    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE usuario SET correo=:email,clave_hash=:encoded WHERE id_usuario=:id AND clave_hash='PENDIENTE_HASH'",dict(email=email,encoded=encoded,id=selected['id_usuario']))
            if cursor.rowcount!=1:
                raise AppError('El usuario cambió. Reinicia para consultar su estado actual.')
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    print('Administrador activado. Usa ese correo y la nueva contraseña en la página.')

def main():
    print('\nANDINAMANTENCION V2 - APLICACION LOCAL CON ORACLE REAL')
    print('Las operaciones de la página guardan datos en tus tablas existentes.')
    print('Mantén esta ventana abierta mientras uses la aplicación. Ctrl+C para detener.\n')
    wallet=Path(input('Arrastra el ZIP original del Wallet y pulsa Enter: ').strip().strip('"'))
    if not wallet.is_file() or wallet.suffix.lower()!='.zip':
        raise AppError('No se encontró el ZIP del Wallet.')
    user=input('Usuario de Oracle [ADMIN]: ').strip() or 'ADMIN'
    service=input('Servicio [basedatos2026_high]: ').strip() or 'basedatos2026_high'
    password=getpass('Contraseña de Oracle (no se muestra): ')
    wallet_password=getpass('Contraseña del Wallet (no se muestra): ')
    with TemporaryDirectory(prefix='andina-v2-wallet-') as directory:
        with ZipFile(wallet) as archive:
            for filename in ('tnsnames.ora','ewallet.pem'):
                items=[item for item in archive.infolist() if Path(item.filename).name==filename]
                if len(items)!=1 or items[0].file_size>2_000_000:
                    raise AppError(f'El Wallet no contiene un {filename} válido.')
                Path(directory,filename).write_bytes(archive.read(items[0]))
        with closing(oracledb.create_pool(user=user,password=password,dsn=service,config_dir=directory,
                                 wallet_location=directory,wallet_password=wallet_password,
                                 min=1,max=4,increment=1,getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
                                 wait_timeout=10000,session_callback=configure_session)) as pool:
            with pool.acquire() as connection:
                connection.call_timeout=20000
                for table in TABLES:
                    query(connection,f"SELECT {','.join(columns(table))} FROM {table} WHERE 1=0")
                query(connection,'SELECT clave_hash FROM usuario WHERE 1=0')
                bootstrap(connection)
            with ThreadingHTTPServer((HOST,PORT),Handler) as server:
                server.daemon_threads=False
                server.application=Application(pool)
                print(f'\nSERVIDOR LISTO: {ORIGIN}')
                print('Si no abre automáticamente, copia esa dirección en Chrome o Edge.')
                print('Para terminar: cierra sesión en la página y presiona Ctrl+C aquí.\n')
                webbrowser.open(ORIGIN)
                try:
                    server.serve_forever(poll_interval=.5)
                except KeyboardInterrupt:
                    print('\nServidor detenido.')

if __name__=='__main__':
    try:
        main()
    except (KeyboardInterrupt,EOFError):
        print('\nInicio cancelado.')
    except AppError as error:
        print(f'\n{error}')
        sys.exit(1)
    except oracledb.Error as error:
        detail=error.args[0] if error.args else None
        print('\nNo se pudo iniciar Oracle. Código:',getattr(detail,'full_code','ERROR_ORACLE'))
        print('Comprueba Wallet, claves, servicio y que las 11 tablas estén en este usuario.')
        sys.exit(1)
    except (OSError,BadZipFile,RuntimeError) as error:
        print(f'\nNo se pudo iniciar ({type(error).__name__}). Revisa el Wallet y que el puerto 8765 esté libre.')
        sys.exit(1)
