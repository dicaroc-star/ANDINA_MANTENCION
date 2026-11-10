"""Pruebas del Sprint 2: alertas de mantenimiento preventivo.

Usan SQLite efímera (adaptador de test); no alteran Oracle ni Render.
"""
from datetime import date, datetime, timedelta
import unittest
from unittest.mock import patch

import service
from service import Service, preventive_alert_status
from test_transactions import Connection, Pool


class PreventiveAlertTests(unittest.TestCase):
    def setUp(self):
        self.connection = Connection()
        self.svc = Service(Pool(self.connection))
        self.today = date(2026, 11, 10)
        self.connection.db.execute("INSERT INTO ubicacion(nombre) VALUES ('ZONA PRUEBA')")
        self.connection.db.execute(
            "INSERT INTO activo(codigo_activo,nombre,estado,id_ubicacion) "
            "VALUES ('TEST-S2','MAQUINA PRUEBA','OPERATIVO',1)"
        )
        self.connection.db.commit()

    def tearDown(self):
        self.connection.db.close()

    def insert_preventive(self, label, when, state='PROGRAMADO'):
        self.connection.db.execute(
            "INSERT INTO mantenimiento_preventivo("
            "id_activo,id_usuario_responsable,descripcion,fecha_programada,estado) "
            "VALUES (1,1,?,?,?)",
            (label, datetime.combine(when, datetime.min.time()), state)
        )
        self.connection.db.commit()

    def test_classification_boundaries(self):
        cases = [
            (self.today - timedelta(days=1), 'Vencido'),
            (self.today, 'Próximo'),
            (self.today + timedelta(days=1), 'Próximo'),
            (self.today + timedelta(days=7), 'Próximo'),
            (self.today + timedelta(days=8), None),
        ]
        for scheduled, expected in cases:
            with self.subTest(scheduled=scheduled):
                self.assertEqual(preventive_alert_status(scheduled, self.today), expected)
                self.assertEqual(preventive_alert_status(datetime.combine(scheduled, datetime.min.time()), self.today), expected)
                self.assertEqual(preventive_alert_status(scheduled.isoformat(), self.today), expected)

    def test_dashboard_includes_only_active_preventives_in_window(self):
        rows = [
            ('VENCIDO', self.today - timedelta(days=1), 'PROGRAMADO'),
            ('HOY', self.today, 'PROGRAMADO'),
            ('SIETE', self.today + timedelta(days=7), 'PROGRAMADO'),
            ('FUERA', self.today + timedelta(days=8), 'PROGRAMADO'),
            ('COMPLETADO', self.today - timedelta(days=1), 'COMPLETADO'),
        ]
        for row in rows:
            self.insert_preventive(*row)

        original_one = service.one

        def fixed_today(connection, sql, binds=None):
            if sql == 'SELECT CURRENT_DATE AS hoy FROM dual':
                return {'hoy': datetime.combine(self.today, datetime.min.time())}
            return original_one(connection, sql, binds)

        with patch('service.one', side_effect=fixed_today):
            dashboard = self.svc.dashboard(self.connection)

        alerts = dashboard['alertas_preventivos']
        self.assertEqual([alert['descripcion'] for alert in alerts], ['VENCIDO', 'HOY', 'SIETE'])
        self.assertEqual([alert['tipo_alerta'] for alert in alerts], ['Vencido', 'Próximo', 'Próximo'])
        self.assertTrue(all(alert['codigo_activo'] == 'TEST-S2' for alert in alerts))
        self.assertTrue(all(alert['responsable_nombre'] == 'CUENTA' for alert in alerts))
        self.assertEqual(dashboard['stats']['Preventivos programados'], 4)
        self.assertEqual(self.connection.db.execute(
            "SELECT COUNT(*) FROM mantenimiento_preventivo").fetchone()[0], 5)

    def test_no_alerts_when_no_preventive_exists(self):
        original_one = service.one

        def fixed_today(connection, sql, binds=None):
            if sql == 'SELECT CURRENT_DATE AS hoy FROM dual':
                return {'hoy': self.today}
            return original_one(connection, sql, binds)

        with patch('service.one', side_effect=fixed_today):
            result = self.svc.dashboard(self.connection)
        self.assertEqual(result['alertas_preventivos'], [])


if __name__ == '__main__':
    unittest.main()
