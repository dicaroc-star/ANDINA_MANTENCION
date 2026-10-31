"""Contrato explícito con las 11 tablas existentes; no ejecuta DDL."""
def field(name, label, kind='text', required=True, **options):
    return dict(name=name, label=label, kind=kind, required=required, **options)

def text(name, label, length, required=True):
    return field(name, label, required=required, length=length)

def choice(name, label, values, default=None):
    return field(name, label, 'select', options=values.split(), default=default)

def ref(name, label, table):
    return field(name, label, 'ref', table=table)

def date(name, label, required=False, kind='datetime'):
    return field(name, label, kind, required)

def number(name, label, minimum=0, maximum=9999999999, required=True, kind='integer', default=None):
    return field(name, label, kind, required, minimum=minimum, maximum=maximum, default=default)

ORDER_STATES = 'PENDIENTE ASIGNADA EN_PROCESO FINALIZADA CANCELADA'
TABLES = {
 'rol': dict(title='Roles', pk='id_rol', fields=[text('nombre','Nombre',50)]),
 'ubicacion': dict(title='Ubicaciones',pk='id_ubicacion',fields=[text('nombre','Nombre',100)]),
 'activo': dict(title='Activos',pk='id_activo',fields=[
    text('codigo_activo','Código',30),text('nombre','Nombre',100),text('marca','Marca',60,False),
    text('modelo','Modelo',60,False),choice('estado','Estado','OPERATIVO DETENIDO MANTENIMIENTO INACTIVO','OPERATIVO'),ref('id_ubicacion','Ubicación','ubicacion')]),
 'usuario': dict(title='Usuarios',pk='id_usuario',fields=[
    text('nombre','Nombre',100),text('apellido','Apellido',100),field('correo','Correo','email',length=150),
    choice('estado','Estado','ACTIVO INACTIVO','ACTIVO'),ref('id_rol','Rol','rol')]),
 'incidencia': dict(title='Incidencias',pk='id_incidencia',readonly=['id_usuario','fecha_reporte'],fields=[
    ref('id_activo','Activo','activo'),text('descripcion','Descripción',1000),
    choice('prioridad','Prioridad','BAJA MEDIA ALTA CRITICA','MEDIA'),
    choice('estado','Estado','REPORTADA EN_REVISION EN_PROCESO RESUELTA CANCELADA','REPORTADA')]),
 'orden_trabajo': dict(title='Órdenes de trabajo',pk='id_orden',readonly=['fecha_creacion'],fields=[
    ref('id_incidencia','Incidencia','incidencia'),ref('id_usuario_asignado','Usuario asignado','usuario'),
    date('fecha_inicio','Fecha de inicio'),date('fecha_fin','Fecha de término'),
    text('descripcion_trabajo','Descripción del trabajo',1000,False),choice('estado','Estado',ORDER_STATES,'PENDIENTE')]),
 'intervencion': dict(title='Intervenciones',pk='id_intervencion',readonly=['id_usuario'],fields=[
    ref('id_orden','Orden de trabajo','orden_trabajo'),text('diagnostico','Diagnóstico',1000),
    text('trabajo_realizado','Trabajo realizado',2000),date('fecha_inicio','Fecha de inicio',True),
    date('fecha_fin','Fecha de término'),text('observaciones','Observaciones',1000,False)]),
 'repuesto': dict(title='Repuestos',pk='id_repuesto',fields=[
    text('codigo_repuesto','Código',30),text('nombre','Nombre',100),text('descripcion','Descripción',500,False),
    number('stock_actual','Stock actual',default=0),number('stock_minimo','Stock mínimo',default=0),
    number('precio_unitario','Precio unitario',maximum=9999999999.99,kind='money',default=0),choice('estado','Estado','ACTIVO INACTIVO','ACTIVO')]),
 'consumo_repuesto': dict(title='Consumos de repuestos',pk='id_consumo',readonly=['fecha_consumo'],fields=[
    ref('id_intervencion','Intervención','intervencion'),ref('id_repuesto','Repuesto','repuesto'),
    number('cantidad','Cantidad',1),number('precio_unitario','Precio unitario aplicado',maximum=9999999999.99,kind='money')]),
 'mantenimiento_preventivo': dict(title='Mantenimiento preventivo',pk='id_mantenimiento',fields=[
    ref('id_activo','Activo','activo'),ref('id_usuario_responsable','Responsable','usuario'),
    text('descripcion','Descripción',1000),date('fecha_programada','Fecha programada',True,'date'),
    number('frecuencia_dias','Frecuencia (días)',1,99999,False),
    choice('estado','Estado','PROGRAMADO EN_PROCESO COMPLETADO CANCELADO','PROGRAMADO'),
    date('fecha_realizacion','Fecha de realización',False,'date'),text('observaciones','Observaciones',1000,False)]),
 'historial_estado': dict(title='Historial de órdenes',pk='id_historial',fields=[],
    readonly=['id_orden','id_usuario','estado_anterior','estado_nuevo','fecha_cambio','observaciones'])
}

MANAGERS = {'ADMINISTRADOR','SUPERVISOR'}
WRITERS = {
 'rol': {'ADMINISTRADOR'}, 'usuario': {'ADMINISTRADOR'},
 'ubicacion': MANAGERS, 'activo': MANAGERS, 'repuesto': MANAGERS,
 'incidencia': MANAGERS | {'OPERADOR'},
 'orden_trabajo': MANAGERS,
 'intervencion': MANAGERS | {'TECNICO'},
 'consumo_repuesto': MANAGERS | {'TECNICO'},
 'mantenimiento_preventivo': MANAGERS,
 'historial_estado': set()
}
ROLE_NAMES = {'ADMINISTRADOR','SUPERVISOR','TECNICO','OPERADOR'}

def columns(table):
    spec = TABLES[table]
    return [spec['pk']] + [f['name'] for f in spec['fields']] + spec.get('readonly',[])

def can_read(table, role):
    return role in ROLE_NAMES and (table not in ('usuario','rol') or role in MANAGERS)

def can_write(table, role):
    return role in WRITERS[table]
