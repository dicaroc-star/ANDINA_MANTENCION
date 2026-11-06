"""Persistencia, límites y permisos de fotografías con base efímera; nunca usa Oracle real."""
import base64
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
import oracledb
import evidence
import test_web

def photograph():
    out=io.BytesIO()
    Image.new('RGB',(2100,900),(32,90,85)).save(out,format='PNG')
    return dict(nombre='../equipo.png',contenido=base64.b64encode(out.getvalue()).decode())

class PhotoValidationTests(unittest.TestCase):
    def test_reencodes_real_image_and_limits_dimensions(self):
        result=evidence.normalize([photograph()])[0]
        self.assertEqual(result['nombre'],'equipo.png')
        self.assertEqual(result['ancho'],1600)
        self.assertTrue(result['contenido'].startswith(b'\xff\xd8'))
        self.assertLessEqual(result['alto'],1600)

    def test_rejects_untrusted_payloads(self):
        for value in ({},[photograph()]*4,[dict(nombre='x.svg',contenido=base64.b64encode(b'<svg/>').decode())],[dict(nombre='x',contenido='%%%%')],[dict(nombre='x',contenido='a'*2_700_000)]):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(evidence.AppError):evidence.normalize(value)

    def test_missing_storage_is_explicit(self):
        with patch('evidence.query',side_effect=oracledb.DatabaseError(SimpleNamespace(code=942))):
            self.assertFalse(evidence.available(None))

class PhotoWorkflowTests(unittest.TestCase):
    setUp=test_web.WebTests.setUp
    tearDown=test_web.WebTests.tearDown
    request=test_web.WebTests.request
    login=test_web.WebTests.login
    def make_asset(self):
        db=self.connection.db
        db.execute("INSERT INTO ubicacion(nombre) VALUES ('PRUEBA FOTOGRAFIA')")
        db.execute("INSERT INTO activo(codigo_activo,nombre,estado,id_ubicacion) VALUES ('FOTO-TEST','EQUIPO TEST','OPERATIVO',1)")
        db.commit()

    def test_report_and_photo_commit_together_and_require_login(self):
        self.make_asset();cookie,csrf=self.login()
        response=self.request('/api/records/incidencia','POST',dict(id=None,data=dict(id_activo=1,descripcion='PRUEBA CON FOTO',prioridad='MEDIA',estado='REPORTADA'),evidencias=[photograph()]),cookie,csrf)
        self.assertTrue(response['status'].startswith('200'),response.get('body'))
        incident=response['body']['id']
        result=self.request(f'/api/incidencias/{incident}/evidencias',cookie=cookie)
        self.assertEqual(len(result['body']['evidencias']),1)
        identifier=result['body']['evidencias'][0]['id_evidencia']
        image=self.request(f'/api/evidencias/{identifier}',cookie=cookie)
        self.assertEqual(image['headers']['Content-Type'],'image/jpeg')
        self.assertTrue(image['raw'].startswith(b'\xff\xd8'))
        self.assertTrue(self.request(f'/api/evidencias/{identifier}')['status'].startswith('401'))

    def test_photo_failure_rolls_back_report(self):
        self.make_asset();cookie,csrf=self.login()
        with patch('evidence.attach',side_effect=RuntimeError('FALLO SIMULADO')):
            result=self.request('/api/records/incidencia','POST',dict(id=None,data=dict(id_activo=1,descripcion='NO GUARDAR',prioridad='MEDIA',estado='REPORTADA'),evidencias=[photograph()]),cookie,csrf)
        self.assertTrue(result['status'].startswith('500'))
        self.assertEqual(self.connection.db.execute('SELECT COUNT(*) FROM incidencia').fetchone()[0],0)

    def test_storage_missing_and_invalid_file_never_create_report(self):
        self.make_asset();cookie,csrf=self.login()
        payload=dict(id=None,data=dict(id_activo=1,descripcion='NO GUARDAR',prioridad='MEDIA',estado='REPORTADA'),evidencias=[photograph()])
        with patch('evidence.available',return_value=False):
            self.assertTrue(self.request('/api/records/incidencia','POST',payload,cookie,csrf)['status'].startswith('503'))
        payload['evidencias']=[dict(nombre='x',contenido='no-imagen')]
        self.assertTrue(self.request('/api/records/incidencia','POST',payload,cookie,csrf)['status'].startswith('400'))
        self.assertEqual(self.connection.db.execute('SELECT COUNT(*) FROM incidencia').fetchone()[0],0)

if __name__=='__main__':unittest.main()
