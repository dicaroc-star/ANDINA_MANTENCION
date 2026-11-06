"""Pruebas locales sin conectar a Oracle ni usar datos del alumno."""
import copy
from datetime import datetime, timedelta
from decimal import Decimal
import io
import json
import unittest
from unittest.mock import patch

from schema import TABLES, can_read, can_write
from security import hash_password, verify_password, Sessions
from service import AppError, Service, validate, check_dates, version, public_row
from server import Handler, Application


class SecurityTests(unittest.TestCase):
    def test_password_hash_salted_and_verified(self):
        first=hash_password('UnaClavePropia123!')
        second=hash_password('UnaClavePropia123!')
        self.assertNotEqual(first,second)
        self.assertLessEqual(len(first),255)
        self.assertTrue(verify_password('UnaClavePropia123!',first))
        self.assertFalse(verify_password('Incorrecta',first))
        self.assertFalse(verify_password('PENDIENTE_HASH','PENDIENTE_HASH'))

    def test_invalid_password_lengths(self):
        for value in ('corta','x'*129,None):
            with self.assertRaises(ValueError):
                hash_password(value)

    def test_sessions_expire_and_revoke(self):
        sessions=Sessions()
        first,csrf=sessions.create(1)
        second,_=sessions.create(2)
        self.assertEqual(sessions.get(first)['csrf'],csrf)
        sessions.revoke_user(1)
        self.assertIsNone(sessions.get(first))
        self.assertIsNotNone(sessions.get(second))
        sessions.items[second]['expires']=0
        self.assertIsNone(sessions.get(second))

    def test_permissions(self):
        self.assertFalse(can_write('historial_estado','ADMINISTRADOR'))
        self.assertFalse(can_read('usuario','OPERADOR'))
        self.assertFalse(can_write('usuario','SUPERVISOR'))
        self.assertTrue(can_write('incidencia','OPERADOR'))
        self.assertTrue(can_write('consumo_repuesto','TECNICO'))
        self.assertFalse(can_write('orden_trabajo','TECNICO'))
        self.assertFalse(can_read('activo','ROL_DESCONOCIDO'))


class ValidationTests(unittest.TestCase):
    def test_matches_eleven_tables(self):
        self.assertEqual(len(TABLES),11)
        self.assertNotIn('clave_hash',[field['name'] for field in TABLES['usuario']['fields']])

    def test_incident_defaults_and_readonly(self):
        clean=validate('incidencia',{'id_activo':1,'descripcion':'Falla informada'},True)
        self.assertEqual(clean['estado'],'REPORTADA')
        self.assertEqual(clean['prioridad'],'MEDIA')
        with self.assertRaises(AppError):
            validate('incidencia',{'id_activo':1,'descripcion':'Falla','id_usuario':99},True)

    def test_numbers_reject_fraction_negative_nan_and_infinity(self):
        for value in (-1,1.5,'NaN','Infinity',True):
            with self.assertRaises(AppError):
                validate('consumo_repuesto',dict(id_intervencion=1,id_repuesto=2,cantidad=value,precio_unitario='1.00'))
        for value in ('-0.01','1.001','Infinity'):
            with self.assertRaises(AppError):
                validate('consumo_repuesto',dict(id_intervencion=1,id_repuesto=2,cantidad=1,precio_unitario=value))

    def test_required_and_lengths_and_enum(self):
        for description in ('',' '*4,'x'*1001):
            with self.assertRaises(AppError):
                validate('incidencia',dict(id_activo=1,descripcion=description),True)
        with self.assertRaises(AppError):
            validate('incidencia',dict(id_activo=1,descripcion='Prueba',estado='INVENTADO'),True)

    def test_dates_and_order_transitions(self):
        now=datetime.now()
        old=dict(fecha_creacion=now-timedelta(hours=1),estado='EN_PROCESO')
        check_dates('orden_trabajo',dict(estado='FINALIZADA',fecha_inicio=now-timedelta(minutes=30),fecha_fin=now),old)
        for data in (dict(estado='FINALIZADA',fecha_inicio=None,fecha_fin=now),
                     dict(estado='FINALIZADA',fecha_inicio=now,fecha_fin=now-timedelta(minutes=1)),
                     dict(estado='PENDIENTE',fecha_inicio=now,fecha_fin=None)):
            with self.assertRaises(AppError):
                check_dates('orden_trabajo',data,old)
        with self.assertRaises(AppError):
            check_dates('mantenimiento_preventivo',dict(estado='COMPLETADO',fecha_realizacion=None))

    def test_timezone_not_silently_discarded(self):
        with self.assertRaises(AppError):
            validate('intervencion',dict(id_orden=1,diagnostico='D',trabajo_realizado='T',fecha_inicio='2026-10-31T12:00:00+03:00'))

    def test_user_password_required_on_create_not_update(self):
        data=dict(nombre='Prueba',apellido='Local',correo='local@example.test',estado='ACTIVO',id_rol=1)
        with self.assertRaises(AppError):
            validate('usuario',data,True)
        self.assertNotIn('clave_hash',validate('usuario',data,False))

    def test_public_user_never_exposes_hash_and_has_version(self):
        row=dict(id_usuario=1,nombre='Prueba',clave_hash='secreto')
        output=public_row(row)
        self.assertNotIn('clave_hash',output)
        self.assertEqual(output['__version'],version(row))
        self.assertNotEqual(version(row),version({**row,'nombre':'Otro'}))


class FakeCursor:
    def __init__(self,connection):
        self.connection=connection

    def __enter__(self):
        return self

    def __exit__(self,*args):
        return False

    def execute(self,sql,binds):
        if sql.startswith('UPDATE repuesto SET stock_actual'):
            self.connection.rows[binds['id']]['stock_actual']=binds['balance']
        else:
            raise AssertionError('SQL inesperado en prueba de stock')

class StockConnection:
    def __init__(self):
        self.rows={1:dict(stock_actual=5,codigo_repuesto='PRUEBA-A',estado='ACTIVO'),2:dict(stock_actual=2,codigo_repuesto='PRUEBA-B',estado='ACTIVO')}

    def cursor(self):
        return FakeCursor(self)

class StockTests(unittest.TestCase):
    def setUp(self):
        self.service=Service(None)
        self.connection=StockConnection()
        self.service.require=lambda connection,table,identifier,lock=False:connection.rows[identifier]

    def test_consume_and_correct_same_part(self):
        self.service.adjust_stock(self.connection,dict(id_repuesto=1,cantidad=3),None)
        self.assertEqual(self.connection.rows[1]['stock_actual'],2)
        self.service.adjust_stock(self.connection,dict(id_repuesto=1,cantidad=1),dict(id_repuesto=1,cantidad=3))
        self.assertEqual(self.connection.rows[1]['stock_actual'],4)

    def test_change_part_restores_original_stock(self):
        self.connection.rows[1]['stock_actual']=2
        self.service.adjust_stock(self.connection,dict(id_repuesto=2,cantidad=2),dict(id_repuesto=1,cantidad=3))
        self.assertEqual(self.connection.rows[1]['stock_actual'],5)
        self.assertEqual(self.connection.rows[2]['stock_actual'],0)

    def test_negative_stock_rejected(self):
        with self.assertRaises(AppError):
            self.service.adjust_stock(self.connection,dict(id_repuesto=1,cantidad=6),None)
        self.assertEqual(self.connection.rows[1]['stock_actual'],5)

    def test_inactive_part_rejected(self):
        self.connection.rows[1]['estado']='INACTIVO'
        with self.assertRaises(AppError):
            self.service.adjust_stock(self.connection,dict(id_repuesto=1,cantidad=1),None)

    def test_operator_cannot_edit_someone_else_incident(self):
        row=dict(id_incidencia=1,id_activo=1,id_usuario=2,descripcion='Prueba',prioridad='MEDIA',estado='REPORTADA',fecha_reporte=datetime.now())
        data=dict(id_activo=1,descripcion='Cambio',prioridad='MEDIA',estado='REPORTADA',__version=version(row))
        with patch('service.one',return_value=row):
            with self.assertRaises(AppError) as caught:
                self.service.save(self.connection,'incidencia',1,data,dict(id_usuario=1,rol='OPERADOR'))
        self.assertEqual(caught.exception.status,403)

    def test_stale_update_rejected(self):
        row=dict(id_incidencia=1,id_usuario=1,estado='REPORTADA')
        with patch('service.one',return_value=row):
            with self.assertRaises(AppError) as caught:
                self.service.save(self.connection,'incidencia',1,{'__version':'old'},dict(id_usuario=1,rol='ADMINISTRADOR',correo='dcaro@andinamantencion.cl',estado='ACTIVO'))
        self.assertEqual(caught.exception.status,409)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application=Application(None)

    def handler(self,method,path,body=None,headers=None):
        raw=b'' if body is None else json.dumps(body).encode()
        request=(f'{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:8765\r\n'+
                 ''.join(f'{key}: {value}\r\n' for key,value in (headers or {}).items())+
                 (f'Content-Length: {len(raw)}\r\n' if raw else '')+'\r\n').encode()+raw
        class Socket:
            def __init__(self):
                self.output=io.BytesIO()
            def makefile(self,*args,**kwargs):
                return io.BytesIO(request)
            def sendall(self,data):
                self.output.write(data)
            def settimeout(self,value):
                pass
        socket=Socket()
        class Server:
            application=self.application
        Handler(socket,('127.0.0.1',1),Server())
        return socket.output.getvalue()

    def test_static_allowlist_and_security_headers(self):
        result=self.handler('GET','/')
        self.assertIn(b'200 OK',result)
        self.assertIn(b'Content-Security-Policy:',result)
        self.assertIn(b'Cache-Control: no-store',result)
        for path in ('/server.py','/security.py','/../server.py','/Wallet.zip'):
            self.assertIn(b'404 Not Found',self.handler('GET',path))

    def test_cross_origin_mutation_denied(self):
        self.assertIn(b'403 Forbidden',self.handler('POST','/api/login',{},dict(Origin='http://other.test',**{'Content-Type':'application/json'})))

    def test_host_rebinding_denied(self):
        # El método guard se prueba directamente con el Host de un dominio ajeno.
        handler=object.__new__(Handler)
        handler.connection=type('Socket',(),{'settimeout':lambda *args:None})()
        handler.headers={'Host':'attacker.example:8765'}
        with self.assertRaises(AppError) as caught:
            handler.guard(False)
        self.assertEqual(caught.exception.status,403)

    def test_csrf_and_inactive_user_denied(self):
        token,csrf=self.application.sessions.create(1)
        handler=object.__new__(Handler)
        handler.server=type('Server',(),{'application':self.application})()
        handler.headers={'Cookie':f'andina_session={token}','X-CSRF-Token':'incorrect'}
        active=dict(id_usuario=1,estado='ACTIVO',rol='ADMINISTRADOR')
        with patch.object(self.application.service,'user',return_value=active):
            with self.assertRaises(AppError) as caught:
                handler.authenticate(None,True)
            self.assertEqual(caught.exception.status,403)
            handler.headers['X-CSRF-Token']=csrf
            self.assertEqual(handler.authenticate(None,True)[0],active)
        with patch.object(self.application.service,'user',return_value={**active,'estado':'INACTIVO'}):
            with self.assertRaises(AppError) as caught:
                handler.authenticate(None)
            self.assertEqual(caught.exception.status,401)

    def test_login_throttle(self):
        self.application.login_attempts.clear()
        for _ in range(8):
            self.application.check_attempts()
        with self.assertRaises(AppError) as caught:
            self.application.check_attempts()
        self.assertEqual(caught.exception.status,429)

if __name__=='__main__':
    unittest.main()

