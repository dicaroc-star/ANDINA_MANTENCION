"""Operaciones transaccionales sobre el esquema Oracle del alumno."""
import hashlib
import json
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

import oracledb
from schema import TABLES, ORDER_STATES, ROLE_NAMES, columns, can_read, can_write
from security import hash_password

class AppError(Exception):
    def __init__(self,message,status=400):
        super().__init__(message)
        self.status=status

def serial(value):
    if isinstance(value,(datetime,date)):
        return value.isoformat()
    if isinstance(value,Decimal):
        return str(value)
    raise TypeError(type(value).__name__)

def query(connection,sql,binds=None):
    with connection.cursor() as cursor:
        cursor.execute(sql,binds or {})
        names=[column[0].lower() for column in cursor.description]
        return [dict(zip(names,row)) for row in cursor.fetchall()]

def one(connection,sql,binds=None):
    rows=query(connection,sql,binds)
    return rows[0] if rows else None

def version(row):
    # Incluye el hash de la clave solo en el cálculo interno, nunca en la respuesta.
    return hashlib.sha256(json.dumps(row,sort_keys=True,default=serial).encode()).hexdigest()

def public_row(row):
    result={k:v for k,v in row.items() if k!='clave_hash'}
    result['__version']=version(row)
    return result

def validate(table,data,creating=False):
    if not isinstance(data,dict):
        raise AppError('Se esperaba un objeto JSON.')
    spec=TABLES[table]
    allowed={field['name'] for field in spec['fields']} | {'__version'}
    if table=='usuario':
        allowed.add('password')
    if set(data)-allowed:
        raise AppError('El formulario incluye campos no permitidos.')
    clean={}
    for field in spec['fields']:
        name=field['name']
        value=data.get(name,field.get('default') if creating else None)
        if value is None or value=='':
            if field['required']:
                raise AppError(f"Completa el campo {field['label']}.")
            clean[name]=None
            continue
        kind=field['kind']
        if kind in ('text','email','select'):
            if not isinstance(value,str):
                raise AppError(f"Valor inválido en {field['label']}.")
            value=value.strip()
            if not value and field['required']:
                raise AppError(f"Completa el campo {field['label']}.")
            if len(value)>field.get('length',100):
                raise AppError(f"{field['label']}: texto demasiado largo.")
            if kind=='select' and value not in field['options']:
                raise AppError(f"Estado o selección inválida en {field['label']}.")
            if kind=='email':
                value=value.lower()
                if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
                    raise AppError('Escribe un correo válido.')
        elif kind in ('integer','ref','money'):
            try:
                if isinstance(value,bool):
                    raise ValueError()
                value=Decimal(str(value))
                if not value.is_finite():
                    raise ValueError()
                if kind!='money' and value!=value.to_integral_value():
                    raise ValueError()
                if kind=='money' and value!=value.quantize(Decimal('.01')):
                    raise ValueError()
                if not Decimal(str(field.get('minimum',1)))<=value<=Decimal(str(field.get('maximum',999999999999999999))):
                    raise ValueError()
                value=int(value) if kind!='money' else value
            except (ValueError,InvalidOperation):
                raise AppError(f"Número inválido en {field['label']}.")
        elif kind in ('date','datetime'):
            try:
                value=datetime.fromisoformat(value) if kind=='datetime' else datetime.combine(date.fromisoformat(value),datetime.min.time())
                if value.tzinfo is not None:
                    raise ValueError()
            except (ValueError,TypeError):
                raise AppError(f"Fecha inválida en {field['label']}.")
        clean[name]=value
    if table=='rol' and clean['nombre'] not in ROLE_NAMES:
        raise AppError('Usa ADMINISTRADOR, SUPERVISOR, TECNICO u OPERADOR. Los permisos están definidos para esos roles.')
    if table=='usuario' and (data.get('password') or creating):
        try:
            clean['clave_hash']=hash_password(data.get('password'))
        except ValueError as error:
            raise AppError(str(error))
    return clean

ORDER_NEXT={
 'PENDIENTE':{'ASIGNADA','CANCELADA'},
 'ASIGNADA':{'PENDIENTE','EN_PROCESO','CANCELADA'},
 'EN_PROCESO':{'FINALIZADA','CANCELADA'},
 'FINALIZADA':set(),'CANCELADA':set()
}

def check_dates(table,data,old=None):
    start,end=data.get('fecha_inicio'),data.get('fecha_fin')
    if table in ('orden_trabajo','intervencion') and end and (not start or end<start):
        raise AppError('La fecha de término requiere una fecha de inicio anterior o igual.')
    if table=='orden_trabajo':
        created=old['fecha_creacion'] if old else datetime.now()
        if start and start<created:
            raise AppError('El inicio no puede ser anterior a la creación de la orden.')
        state=data['estado']
        if old and state!=old['estado'] and state not in ORDER_NEXT[old['estado']]:
            raise AppError('Cambio de estado no permitido para esta orden.')
        if not old and state not in ('PENDIENTE','ASIGNADA'):
            raise AppError('Crea la orden como PENDIENTE o ASIGNADA; después registra su avance.')
        if state in ('EN_PROCESO','FINALIZADA') and not start:
            raise AppError('Registra la fecha de inicio de la orden.')
        if state=='FINALIZADA' and not end:
            raise AppError('Registra la fecha de término para finalizar la orden.')
    if table=='mantenimiento_preventivo':
        if data['estado']=='COMPLETADO' and not data.get('fecha_realizacion'):
            raise AppError('Registra la fecha de realización para completar el mantenimiento.')
        if data['estado']!='COMPLETADO' and data.get('fecha_realizacion'):
            raise AppError('La fecha de realización corresponde al estado COMPLETADO.')

class Service:
    def __init__(self,pool):
        self.pool=pool

    def user(self,connection,identifier):
        return one(connection,'''SELECT u.id_usuario,u.nombre,u.apellido,u.correo,u.estado,
                          r.nombre AS rol FROM usuario u JOIN rol r ON r.id_rol=u.id_rol
                          WHERE u.id_usuario=:id''',dict(id=identifier))

    def metadata(self,role):
        return {name:{**spec, 'columns':columns(name),'writable':can_write(name,role)}
                for name,spec in TABLES.items() if can_read(name,role)}

    def list_rows(self,connection,table,role,page=1,search='',state=''):
        if table not in TABLES or not can_read(table,role):
            raise AppError('No tienes permiso para consultar este módulo.',403)
        spec=TABLES[table]
        parts,binds=[],{}
        if search:
            names=[f['name'] for f in spec['fields'] if f['kind'] in ('text','email')]
            names.append(spec['pk'])
            # Búsqueda literal: % y _ no se interpretan como comodines.
            parts.append('('+' OR '.join(f"INSTR(LOWER(TO_CHAR({name})),:search)>0" for name in names)+')')
            binds['search']=search.lower()[:150]
        if state:
            if not any(f['name']=='estado' for f in spec['fields']):
                raise AppError('Este módulo no tiene filtro de estado.')
            parts.append('estado=:state')
            binds['state']=state
        where=' WHERE '+' AND '.join(parts) if parts else ''
        total=one(connection,f'SELECT COUNT(*) AS total FROM {table}'+where,binds)['total']
        names=columns(table)+(['clave_hash'] if table=='usuario' else [])
        rows=query(connection,f"SELECT {','.join(names)} FROM {table}{where} ORDER BY {spec['pk']} DESC OFFSET :skip ROWS FETCH NEXT 25 ROWS ONLY",{**binds,'skip':(page-1)*25})
        return dict(rows=[public_row(row) for row in rows],total=total,page=page)

    def lookups(self,connection):
        statements={
         'rol':"SELECT id_rol AS id,nombre AS label FROM rol ORDER BY nombre",
         'ubicacion':"SELECT id_ubicacion AS id,nombre AS label FROM ubicacion ORDER BY nombre",
         'activo':"SELECT id_activo AS id,codigo_activo||' · '||nombre AS label,estado FROM activo ORDER BY codigo_activo",
         'usuario':"SELECT id_usuario AS id,nombre||' '||apellido AS label,estado FROM usuario ORDER BY nombre,apellido",
         'incidencia':"SELECT id_incidencia AS id,'#'||id_incidencia||' · '||SUBSTR(descripcion,1,90) AS label,estado FROM incidencia ORDER BY id_incidencia DESC",
         'orden_trabajo':"SELECT id_orden AS id,'Orden #'||id_orden||' · '||estado AS label,estado,id_usuario_asignado FROM orden_trabajo ORDER BY id_orden DESC",
         'intervencion':"SELECT id_intervencion AS id,'Intervención #'||id_intervencion||' · Orden #'||id_orden AS label,id_usuario,id_orden FROM intervencion ORDER BY id_intervencion DESC",
         'repuesto':"SELECT id_repuesto AS id,codigo_repuesto||' · '||nombre AS label,estado,stock_actual,precio_unitario FROM repuesto ORDER BY codigo_repuesto"
        }
        # Catálogos con búsqueda propia en pantalla; límite explícito para este proyecto académico.
        results={table:query(connection,sql+' FETCH FIRST 2001 ROWS ONLY') for table,sql in statements.items()}
        if any(len(rows)>2000 for rows in results.values()):
            raise AppError('Un catálogo supera 2000 registros. Se requiere ampliar el selector con búsqueda paginada.',409)
        return results

    def dashboard(self,connection):
        stats={
         'Activos operativos':"SELECT COUNT(*) AS value FROM activo WHERE estado='OPERATIVO'",
         'Incidencias abiertas':"SELECT COUNT(*) AS value FROM incidencia WHERE estado IN ('REPORTADA','EN_REVISION','EN_PROCESO')",
         'Órdenes en proceso':"SELECT COUNT(*) AS value FROM orden_trabajo WHERE estado='EN_PROCESO'",
         'Preventivos programados':"SELECT COUNT(*) AS value FROM mantenimiento_preventivo WHERE estado='PROGRAMADO'",
         'Repuestos bajo mínimo':"SELECT COUNT(*) AS value FROM repuesto WHERE estado='ACTIVO' AND stock_actual<stock_minimo"
        }
        return dict(stats={label:one(connection,sql)['value'] for label,sql in stats.items()},
                    incidencias=query(connection,'''SELECT i.id_incidencia,a.codigo_activo,i.descripcion,i.prioridad,i.estado,i.fecha_reporte
                     FROM incidencia i JOIN activo a ON a.id_activo=i.id_activo ORDER BY i.id_incidencia DESC FETCH FIRST 5 ROWS ONLY'''))

    def save(self,connection,table,identifier,data,user):
        if not isinstance(data,dict):
            raise AppError('Se esperaba un formulario JSON.')
        role=user['rol']
        if table not in TABLES or not can_write(table,role):
            raise AppError('No tienes permiso para guardar en este módulo.',403)
        spec=TABLES[table]
        pk=spec['pk']
        # Serializa administración de usuarios con una fila conocida: no requiere LOCK ANY TABLE.
        if table=='usuario':
            admin_role=one(connection,"SELECT id_rol FROM rol WHERE nombre='ADMINISTRADOR' FOR UPDATE WAIT 5")
            if not admin_role:
                raise AppError('Falta el rol ADMINISTRADOR. Revisa el modelo de datos.')
        old=None
        if identifier is not None:
            names=columns(table)+(['clave_hash'] if table=='usuario' else [])
            old=one(connection,f"SELECT {','.join(names)} FROM {table} WHERE {pk}=:id FOR UPDATE WAIT 5",dict(id=identifier))
            if not old:
                raise AppError('El registro ya no existe.',404)
            if data.get('__version')!=version(old):
                raise AppError('El registro cambió desde que lo abriste. Actualiza la lista y vuelve a editar.',409)
        clean=validate(table,data,creating=old is None)
        check_dates(table,clean,old)
        if table=='incidencia':
            if role=='OPERADOR':
                if old and (old['id_usuario']!=user['id_usuario'] or old['estado']!='REPORTADA'):
                    raise AppError('Solo puedes editar tus incidencias mientras estén REPORTADAS.',403)
                if clean['estado']!='REPORTADA':
                    raise AppError('El supervisor gestiona el estado de las incidencias.',403)
            if old is None:
                clean['id_usuario']=user['id_usuario']
        if table=='intervencion':
            if old and clean['id_orden']!=old['id_orden']:
                raise AppError('No se puede trasladar una intervención a otra orden.')
            order=self.require(connection,'orden_trabajo',clean['id_orden'],lock=True)
            if order['estado']!='EN_PROCESO':
                raise AppError('La orden debe estar EN_PROCESO para registrar o editar intervenciones.')
            if role=='TECNICO' and (order['id_usuario_asignado']!=user['id_usuario'] or (old and old['id_usuario']!=user['id_usuario'])):
                raise AppError('Solo puedes intervenir órdenes asignadas a ti y editar tus propias intervenciones.',403)
            if old is None:
                clean['id_usuario']=user['id_usuario']
        if table=='consumo_repuesto':
            if old and clean['id_intervencion']!=old['id_intervencion']:
                raise AppError('No se puede trasladar un consumo a otra intervención.')
            intervention=self.require(connection,'intervencion',clean['id_intervencion'])
            order=self.require(connection,'orden_trabajo',intervention['id_orden'],lock=True)
            if order['estado']!='EN_PROCESO':
                raise AppError('La orden debe estar EN_PROCESO para registrar o corregir consumos.')
            if role=='TECNICO' and (intervention['id_usuario']!=user['id_usuario'] or order['id_usuario_asignado']!=user['id_usuario']):
                raise AppError('Solo puedes registrar consumos de tus intervenciones en órdenes asignadas a ti.',403)
            self.adjust_stock(connection,clean,old)
        # Verifica referencias y usuarios activos, sin aceptar nombres de tabla del cliente.
        for field in spec['fields']:
            if field['kind']=='ref':
                target=self.require(connection,field['table'],clean[field['name']])
                if field['table']=='usuario' and target['estado']!='ACTIVO':
                    raise AppError('El usuario seleccionado está inactivo.')
        if table=='rol' and old and clean['nombre']!=old['nombre']:
            assigned=one(connection,'SELECT COUNT(*) AS total FROM usuario WHERE id_rol=:id',dict(id=identifier))['total']
            if assigned:
                raise AppError('Este rol tiene usuarios asociados. No se puede cambiar su nombre y alterar sus permisos.')
        if table=='usuario':
            target_role=self.require(connection,'rol',clean['id_rol'])['nombre']
            if target_role not in ROLE_NAMES:
                raise AppError('El rol seleccionado no tiene permisos definidos.')
            if old and old['estado']=='ACTIVO':
                previous_role=self.require(connection,'rol',old['id_rol'])['nombre']
                if previous_role=='ADMINISTRADOR' and old['clave_hash'].startswith('pbkdf2_sha256$') and (clean['estado']!='ACTIVO' or target_role!='ADMINISTRADOR'):
                    count=one(connection,"SELECT COUNT(*) AS total FROM usuario u JOIN rol r ON r.id_rol=u.id_rol WHERE u.estado='ACTIVO' AND r.nombre='ADMINISTRADOR' AND u.clave_hash LIKE 'pbkdf2_sha256$%'")['total']
                    if count<=1:
                        raise AppError('Debe quedar al menos un administrador activo.')
        with connection.cursor() as cursor:
            if old is None:
                output=cursor.var(oracledb.NUMBER)
                cursor.execute(f"INSERT INTO {table} ({','.join(clean)}) VALUES ({','.join(':'+key for key in clean)}) RETURNING {pk} INTO :new_id",{**clean,'new_id':output})
                identifier=int(output.getvalue()[0])
            else:
                cursor.execute(f"UPDATE {table} SET {','.join(key+'=:'+key for key in clean)} WHERE {pk}=:record_id",{**clean,'record_id':identifier})
            if table=='orden_trabajo' and (old is None or old['estado']!=clean['estado']):
                cursor.execute('''INSERT INTO historial_estado (id_orden,id_usuario,estado_anterior,estado_nuevo,observaciones)
                 VALUES (:order_id,:user_id,:previous,:next,:note)''',dict(order_id=identifier,user_id=user['id_usuario'],previous=old['estado'] if old else None,next=clean['estado'],note='Cambio registrado desde AndinaMantención.'))
        return identifier

    def require(self,connection,table,identifier,lock=False):
        # Solamente se llama con constantes internas o referencias del contrato.
        names=columns(table)
        row=one(connection,f"SELECT {','.join(names)} FROM {table} WHERE {TABLES[table]['pk']}=:id"+(' FOR UPDATE WAIT 5' if lock else ''),dict(id=identifier))
        if not row:
            raise AppError(f'No existe el registro seleccionado en {TABLES[table]["title"]}.')
        return row

    def adjust_stock(self,connection,data,old):
        deltas={data['id_repuesto']:-data['cantidad']}
        if old:
            deltas[old['id_repuesto']]=deltas.get(old['id_repuesto'],0)+old['cantidad']
        for identifier in sorted(deltas):
            row=self.require(connection,'repuesto',identifier,lock=True)
            delta=deltas[identifier]
            if identifier==data['id_repuesto'] and row['estado']!='ACTIVO':
                raise AppError('El repuesto seleccionado está inactivo.')
            balance=row['stock_actual']+delta
            if balance<0:
                raise AppError(f'Stock insuficiente para {row["codigo_repuesto"]}: disponible {row["stock_actual"]}.',409)
            if balance>9999999999:
                raise AppError('El stock resultante supera el máximo permitido.')
            with connection.cursor() as cursor:
                cursor.execute('UPDATE repuesto SET stock_actual=:balance WHERE id_repuesto=:id',dict(balance=balance,id=identifier))
