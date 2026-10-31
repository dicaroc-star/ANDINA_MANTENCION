"""Integración del servicio y HTTP con un adaptador SQLite SOLO para pruebas.

No prueba red, TLS ni el dialecto Oracle real. No lo usa server.py.
"""
from datetime import datetime, timedelta
from decimal import Decimal
import io
import json
import re
import sqlite3
import unittest

from schema import TABLES, columns
from security import hash_password
from service import Service, AppError, public_row
from server import Handler, Application

sqlite3.register_adapter(Decimal,str)
sqlite3.register_adapter(datetime,lambda value:value.isoformat(' '))
sqlite3.register_converter('TIMESTAMP',lambda value:datetime.fromisoformat(value.decode()))

class Output:
    def __init__(self):
        self.value=None
    def getvalue(self):
        return [self.value]

class Cursor:
    def __init__(self,connection):
        self.inner=connection.db.cursor()
    def __enter__(self):
        return self
    def __exit__(self,*args):
        self.inner.close()
    def var(self,*args):
        return Output()
    @property
    def description(self):
        return self.inner.description
    @property
    def rowcount(self):
        return self.inner.rowcount
    def execute(self,sql,binds=None):
        binds=dict(binds or {})
        if sql.startswith('LOCK TABLE'):
            return
        sql=re.sub(r' FOR UPDATE WAIT 5$','',sql)
        output=binds.pop('new_id',None)
        if output:
            sql=re.sub(r' RETURNING \w+ INTO :new_id$','',sql)
        sql=re.sub(r' OFFSET :skip ROWS FETCH NEXT 25 ROWS ONLY$', ' LIMIT 25 OFFSET :skip',sql)
        sql=re.sub(r' FETCH FIRST (\d+) ROWS ONLY$',r' LIMIT \1',sql)
        self.inner.execute(sql,binds)
        if output:
            output.value=self.inner.lastrowid
    def fetchall(self):
        return self.inner.fetchall()
    def fetchone(self):
        return self.inner.fetchone()

class Connection:
    def __init__(self):
        self.db=sqlite3.connect(':memory:',detect_types=sqlite3.PARSE_DECLTYPES)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.create_function('TO_CHAR',1,lambda value:None if value is None else str(value))
        for table,spec in TABLES.items():
            declarations=[f"{spec['pk']} INTEGER PRIMARY KEY AUTOINCREMENT"]
            for field in spec['fields']:
                kind=field['kind']
                datatype='TIMESTAMP' if kind in ('date','datetime') else 'INTEGER' if kind in ('integer','ref') else 'NUMERIC' if kind=='money' else 'TEXT'
                declaration=f"{field['name']} {datatype}"
                if field['required']:
                    declaration+=' NOT NULL'
                if kind=='ref':
                    declaration+=f" REFERENCES {field['table']}({TABLES[field['table']]['pk']})"
                declarations.append(declaration)
            for name in spec.get('readonly',[]):
                if name.startswith('fecha_'):
                    declarations.append(f"{name} TIMESTAMP DEFAULT (datetime('now','localtime'))")
                elif name in ('id_usuario','id_orden'):
                    target='usuario' if name=='id_usuario' else 'orden_trabajo'
                    declarations.append(f'{name} INTEGER REFERENCES {target}({TABLES[target]["pk"]})')
                else:
                    declarations.append(f'{name} TEXT')
            if table=='usuario':
                declarations.append('clave_hash TEXT NOT NULL')
            self.db.execute(f"CREATE TABLE {table} ({','.join(declarations)})")
        self.db.execute("INSERT INTO rol(nombre) VALUES ('ADMINISTRADOR')")
        self.db.execute('INSERT INTO usuario(nombre,apellido,correo,estado,id_rol,clave_hash) VALUES (?,?,?,?,?,?)',('CUENTA','TEST','test@example.test','ACTIVO',1,hash_password('ContraseñaLocal123!')))
        self.db.commit()
    def cursor(self):
        return Cursor(self)
    def commit(self):
        self.db.commit()
    def rollback(self):
        self.db.rollback()
    def __enter__(self):
        return self
    def __exit__(self,*args):
        self.rollback()

class Pool:
    def __init__(self,connection):
        self.connection=connection
    def acquire(self):
        return self.connection

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.connection=Connection()
        self.service=Service(Pool(self.connection))
        self.actor=dict(id_usuario=1,rol='ADMINISTRADOR')
    def tearDown(self):
        self.connection.db.close()
    def save(self,table,data,identifier=None,actor=None):
        try:
            result=self.service.save(self.connection,table,identifier,data,actor or self.actor)
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise
    def row(self,table,identifier):
        rows=self.service.list_rows(self.connection,table,'ADMINISTRADOR')['rows']
        return next(row for row in rows if row[TABLES[table]['pk']]==identifier)
    def edit(self,table,identifier,**changes):
        row=self.row(table,identifier)
        return {**{field['name']:row[field['name']] for field in TABLES[table]['fields']},'__version':row['__version'],**changes}
    def setup_order(self):
        location=self.save('ubicacion',dict(nombre='UBICACION TEST'))
        asset=self.save('activo',dict(codigo_activo='TEST-1',nombre='ACTIVO TEST',id_ubicacion=location))
        incident=self.save('incidencia',dict(id_activo=asset,descripcion='INCIDENCIA TEST'))
        order=self.save('orden_trabajo',dict(id_incidencia=incident,id_usuario_asignado=1))
        return asset,incident,order
    def start_order(self,order):
        self.save('orden_trabajo',self.edit('orden_trabajo',order,estado='ASIGNADA'),order)
        start=(datetime.now()+timedelta(hours=1)).isoformat()
        self.save('orden_trabajo',self.edit('orden_trabajo',order,estado='EN_PROCESO',fecha_inicio=start),order)
        return start

    def test_complete_maintenance_workflow_and_history(self):
        asset,incident,order=self.setup_order()
        start=self.start_order(order)
        intervention=self.save('intervencion',dict(id_orden=order,diagnostico='DIAGNOSTICO TEST',trabajo_realizado='TRABAJO TEST',fecha_inicio=start))
        part=self.save('repuesto',dict(codigo_repuesto='REP-TEST',nombre='REPUESTO TEST',stock_actual=5,stock_minimo=2,precio_unitario='10.00'))
        consumption=self.save('consumo_repuesto',dict(id_intervencion=intervention,id_repuesto=part,cantidad=3,precio_unitario='10.00'))
        self.assertEqual(self.row('repuesto',part)['stock_actual'],2)
        self.save('consumo_repuesto',self.edit('consumo_repuesto',consumption,cantidad=2),consumption)
        self.assertEqual(self.row('repuesto',part)['stock_actual'],3)
        end=(datetime.now()+timedelta(hours=2)).isoformat()
        self.save('intervencion',self.edit('intervencion',intervention,fecha_inicio=start,fecha_fin=end),intervention)
        self.save('orden_trabajo',self.edit('orden_trabajo',order,estado='FINALIZADA',fecha_inicio=start,fecha_fin=end),order)
        history=self.service.list_rows(self.connection,'historial_estado','ADMINISTRADOR')['rows']
        self.assertEqual([row['estado_nuevo'] for row in reversed(history)],['PENDIENTE','ASIGNADA','EN_PROCESO','FINALIZADA'])
        self.assertTrue(all(row['id_usuario']==1 for row in history))
        self.save('incidencia',self.edit('incidencia',incident,estado='RESUELTA'),incident)
        preventive=self.save('mantenimiento_preventivo',dict(id_activo=asset,id_usuario_responsable=1,descripcion='PREVENTIVO TEST',fecha_programada='2026-11-01',frecuencia_dias=30))
        self.save('mantenimiento_preventivo',self.edit('mantenimiento_preventivo',preventive,fecha_programada='2026-11-01',estado='COMPLETADO',fecha_realizacion='2026-11-01'),preventive)
        dashboard=self.service.dashboard(self.connection)
        self.assertEqual(dashboard['stats']['Incidencias abiertas'],0)
        self.assertEqual(dashboard['stats']['Órdenes en proceso'],0)
        self.assertEqual(dashboard['stats']['Activos operativos'],1)
        self.assertEqual(len(self.service.lookups(self.connection)['activo']),1)

    def test_failed_consumption_rolls_back_stock_and_record(self):
        _,_,order=self.setup_order()
        start=self.start_order(order)
        intervention=self.save('intervencion',dict(id_orden=order,diagnostico='TEST',trabajo_realizado='TEST',fecha_inicio=start))
        part=self.save('repuesto',dict(codigo_repuesto='TEST',nombre='TEST',stock_actual=3,stock_minimo=0,precio_unitario=1))
        with self.assertRaises(AppError):
            self.save('consumo_repuesto',dict(id_intervencion=intervention,id_repuesto=part,cantidad=4,precio_unitario=1))
        self.assertEqual(self.row('repuesto',part)['stock_actual'],3)
        self.assertEqual(self.service.list_rows(self.connection,'consumo_repuesto','ADMINISTRADOR')['total'],0)

    def test_injected_failure_after_stock_change_rolls_back(self):
        from unittest.mock import patch
        _,_,order=self.setup_order()
        start=self.start_order(order)
        intervention=self.save('intervencion',dict(id_orden=order,diagnostico='TEST',trabajo_realizado='TEST',fecha_inicio=start))
        part=self.save('repuesto',dict(codigo_repuesto='TEST',nombre='TEST',stock_actual=3,stock_minimo=0,precio_unitario=1))
        real_require=self.service.require
        def fail_reference(connection,table,identifier,lock=False):
            if table=='repuesto' and not lock:
                raise AppError('Fallo de referencia después del ajuste de stock')
            return real_require(connection,table,identifier,lock)
        with patch.object(self.service,'require',side_effect=fail_reference):
            with self.assertRaises(AppError):
                self.save('consumo_repuesto',dict(id_intervencion=intervention,id_repuesto=part,cantidad=1,precio_unitario=1))
        self.assertEqual(self.row('repuesto',part)['stock_actual'],3)

    def test_last_administrator_protection_and_password_updates(self):
        with self.assertRaises(AppError):
            self.save('usuario',self.edit('usuario',1,estado='INACTIVO'),1)
        self.assertEqual(self.row('usuario',1)['estado'],'ACTIVO')
        role=self.save('rol',dict(nombre='TECNICO'))
        identifier=self.save('usuario',dict(nombre='TECNICO',apellido='TEST',correo='tecnico@example.test',estado='ACTIVO',id_rol=role,password='ClaveTecnico123!'))
        self.assertNotIn('clave_hash',self.row('usuario',identifier))
        self.save('usuario',self.edit('usuario',identifier,password='NuevaClaveLocal123!'),identifier)

    def test_search_is_bound_and_pagination(self):
        for number in range(27):
            self.save('ubicacion',dict(nombre=f'LOCAL TEST {number}'))
        first=self.service.list_rows(self.connection,'ubicacion','ADMINISTRADOR',1)
        second=self.service.list_rows(self.connection,'ubicacion','ADMINISTRADOR',2)
        self.assertEqual(first['total'],27)
        self.assertEqual(len(first['rows']),25)
        self.assertEqual(len(second['rows']),2)
        self.assertEqual(self.service.list_rows(self.connection,'ubicacion','ADMINISTRADOR',search="' OR 1=1 --")['total'],0)

    def test_cannot_rename_role_with_assigned_users(self):
        with self.assertRaises(AppError):
            self.save('rol',self.edit('rol',1,nombre='TECNICO'),1)
        self.assertEqual(self.row('rol',1)['nombre'],'ADMINISTRADOR')

    def test_http_login_session_write_logout_and_password_change(self):
        application=Application(Pool(self.connection))
        def request(method,path,body=None,cookie='',csrf=''):
            raw=b'' if body is None else json.dumps(body).encode()
            source=(f'{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:8765\r\nOrigin: http://127.0.0.1:8765\r\nContent-Type: application/json\r\nCookie: {cookie}\r\nX-CSRF-Token: {csrf}\r\nContent-Length: {len(raw)}\r\n\r\n').encode()+raw
            class Socket:
                output=io.BytesIO()
                def makefile(self,*args,**kwargs):return io.BytesIO(source)
                def sendall(self,data):self.output.write(data)
                def settimeout(self,value):pass
            socket=Socket()
            server=type('Server',(),{'application':application})()
            Handler(socket,('127.0.0.1',1),server)
            header,payload=socket.output.getvalue().split(b'\r\n\r\n',1)
            return header.decode(),json.loads(payload)
        header,_=request('GET','/api/dashboard')
        self.assertIn('401 Unauthorized',header)
        header,result=request('POST','/api/login',dict(correo='test@example.test',password='incorrecta'))
        self.assertIn('401 Unauthorized',header)
        header,result=request('POST','/api/login',dict(correo='test@example.test',password='ContraseñaLocal123!'))
        self.assertIn('200 OK',header)
        cookie=re.search(r'Set-Cookie: ([^;]+)',header).group(1)
        csrf=result['csrf']
        self.assertNotIn('clave_hash',result['user'])
        header,result=request('POST','/api/records/ubicacion',dict(id=None,data=dict(nombre='LOCAL HTTP TEST')),cookie,csrf)
        self.assertIn('200 OK',header)
        self.assertGreater(result['id'],0)
        header,result=request('GET','/api/meta',cookie=cookie)
        self.assertEqual(len(result),11)
        header,result=request('POST','/api/password',dict(current='ContraseñaLocal123!',password='CambioClave123!'),cookie,csrf)
        self.assertIn('200 OK',header)
        header,result=request('GET','/api/me',cookie=cookie)
        self.assertIn('401 Unauthorized',header)
        header,result=request('POST','/api/login',dict(correo='test@example.test',password='CambioClave123!'))
        self.assertIn('200 OK',header)
        cookie=re.search(r'Set-Cookie: ([^;]+)',header).group(1)
        header,result=request('POST','/api/logout',{},cookie,result['csrf'])
        self.assertIn('200 OK',header)
        header,result=request('GET','/api/me',cookie=cookie)
        self.assertIn('401 Unauthorized',header)

if __name__=='__main__':
    unittest.main()
