from io import BytesIO
import unittest
from PIL import Image
import qr_assets
import test_web

class QRTests(unittest.TestCase):
    setUp=test_web.WebTests.setUp
    tearDown=test_web.WebTests.tearDown
    request=test_web.WebTests.request
    login=test_web.WebTests.login

    def test_qr_is_authenticated_and_links_to_asset_report(self):
        self.connection.db.execute("INSERT INTO ubicacion(nombre) VALUES ('QR TEST')")
        self.connection.db.execute("INSERT INTO activo(codigo_activo,nombre,estado,id_ubicacion) VALUES ('QR TEST&1','QR TEST','OPERATIVO',1)")
        self.connection.db.commit()
        cookie,_=self.login()
        response=self.request('/api/activos/1/qr',cookie=cookie)
        self.assertTrue(response['status'].startswith('200'))
        self.assertEqual(response['headers']['Content-Type'],'image/png')
        with Image.open(BytesIO(response['raw'])) as image:
            self.assertGreater(image.width,100)
            self.assertEqual(image.width,image.height)
        self.assertEqual(qr_assets.report_url('https://andina.example.test','QR TEST&1'),'https://andina.example.test/?reportar=QR+TEST%261')
        self.assertTrue(self.request('/api/activos/1/qr')['status'].startswith('401'))

if __name__=='__main__':unittest.main()
