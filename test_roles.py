"""Flujos completos con cuentas separadas y permisos según el rol autorizado."""
from datetime import datetime,timedelta
import unittest
import test_transactions as fixtures
from service import AppError

class RoleWorkflowTests(unittest.TestCase):
    setUp=fixtures.IntegrationTests.setUp
    tearDown=fixtures.IntegrationTests.tearDown
    save=fixtures.IntegrationTests.save
    row=fixtures.IntegrationTests.row
    edit=fixtures.IntegrationTests.edit

    def actor_for(self,role,email):
        roles=self.connection.db.execute('SELECT id_rol FROM rol WHERE nombre=?',(role,)).fetchone()
        role_id=roles[0] if roles else self.save('rol',dict(nombre=role))
        identifier=self.save('usuario',dict(nombre=role,apellido='PRUEBA',correo=email,estado='ACTIVO',id_rol=role_id,password='ClavePruebasRoles123!'))
        return self.service.user(self.connection,identifier)

    def test_supervisor_technician_operator_and_history(self):
        supervisor=self.actor_for('SUPERVISOR','supervisor@example.test')
        technician=self.actor_for('TECNICO','tecnico@example.test')
        other=self.actor_for('TECNICO','otro@example.test')
        operator=self.actor_for('OPERADOR','planta@example.test')
        location=self.save('ubicacion',dict(nombre='UBICACION ROLES'),actor=supervisor)
        asset=self.save('activo',dict(codigo_activo='ROL-001',nombre='EQUIPO ROLES',id_ubicacion=location),actor=supervisor)
        incident=self.save('incidencia',dict(id_activo=asset,descripcion='REPORTE PLANTA'),actor=operator)
        self.assertEqual(self.row('incidencia',incident)['id_usuario'],operator['id_usuario'])
        self.save('incidencia',self.edit('incidencia',incident,estado='EN_REVISION'),incident,actor=supervisor)
        with self.assertRaises(AppError):self.save('incidencia',self.edit('incidencia',incident,estado='RESUELTA'),incident,actor=operator)
        order=self.save('orden_trabajo',dict(id_incidencia=incident,id_usuario_asignado=technician['id_usuario'],estado='ASIGNADA'),actor=supervisor)
        start=(datetime.now()+timedelta(minutes=1)).isoformat()
        self.save('orden_trabajo',self.edit('orden_trabajo',order,estado='EN_PROCESO',fecha_inicio=start),order,actor=supervisor)
        intervention=self.save('intervencion',dict(id_orden=order,diagnostico='DIAGNOSTICO TECNICO',trabajo_realizado='REPARACION',fecha_inicio=start),actor=technician)
        with self.assertRaises(AppError):self.save('intervencion',self.edit('intervencion',intervention,diagnostico='OTRO TECNICO'),intervention,actor=other)
        part=self.save('repuesto',dict(codigo_repuesto='ROL-REP',nombre='REPUESTO ROLES',stock_actual=5,stock_minimo=2,precio_unitario=10),actor=supervisor)
        self.save('consumo_repuesto',dict(id_intervencion=intervention,id_repuesto=part,cantidad=2,precio_unitario=10),actor=technician)
        self.assertEqual(self.row('repuesto',part)['stock_actual'],3)
        with self.assertRaises(AppError):self.save('consumo_repuesto',dict(id_intervencion=intervention,id_repuesto=part,cantidad=1,precio_unitario=10),actor=other)
        with self.assertRaises(AppError):self.save('orden_trabajo',dict(id_incidencia=incident,id_usuario_asignado=technician['id_usuario']),actor=operator)
        end=(datetime.now()+timedelta(minutes=2)).isoformat()
        self.save('orden_trabajo',self.edit('orden_trabajo',order,estado='FINALIZADA',fecha_inicio=start,fecha_fin=end),order,actor=supervisor)
        self.assertEqual(self.connection.db.execute('SELECT COUNT(*) FROM historial_estado WHERE id_orden=?',(order,)).fetchone()[0],3)
        self.assertFalse(self.service.metadata('SUPERVISOR',supervisor)['usuario']['writable'])
        self.assertTrue(self.service.metadata('TECNICO',technician)['intervencion']['writable'])
        self.assertFalse(self.service.metadata('OPERADOR',operator)['activo']['writable'])
        self.assertNotIn('usuario',self.service.metadata('OPERADOR',operator))

    def test_alternate_admin_can_manage_and_inactive_users_cannot(self):
        admin=self.actor_for('ADMINISTRADOR','admin2@example.test')
        self.save('ubicacion',dict(nombre='UBICACION ADMIN2'),actor=admin)
        admin['estado']='INACTIVO'
        with self.assertRaises(AppError):self.save('ubicacion',dict(nombre='NO GUARDAR'),actor=admin)

if __name__=='__main__':unittest.main()
