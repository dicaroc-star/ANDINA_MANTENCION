"""Pruebas WSGI HTTPS con una base efímera de pruebas, sin Oracle del alumno."""
import io
import json
import os
import re
import unittest
from unittest.mock import patch
from web import Settings, LoginLimiter, create_wsgi
from server import Application
from test_transactions import Connection, Pool

class WebTests(unittest.TestCase):
    def setUp(self):
        self.connection=Connection()
        self.core=Application(Pool(self.connection))
        self.app=create_wsgi(self.core,Settings('https://andina.example.test','ADMIN'))

    def tearDown(self):
        self.connection.db.close()

    def request(self,path='/',method='GET',body=None,cookie='',csrf='',host='andina.example.test',origin='https://andina.example.test',scheme='https'):
        encoded=json.dumps(body).encode() if body is not None else b''
        environ={'PATH_INFO':path,'QUERY_STRING':'','REQUEST_METHOD':method,'HTTP_HOST':host,
                 'HTTP_ORIGIN':origin,'HTTP_COOKIE':cookie,'HTTP_X_CSRF_TOKEN':csrf,
                 'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(encoded)),
                 'REMOTE_ADDR':'192.0.2.1','wsgi.url_scheme':scheme,'wsgi.input':io.BytesIO(encoded)}
        captured={}
        def start(status,headers):
            captured.update(status=status,headers=dict(headers))
        raw=b''.join(self.app(environ,start))
        captured['raw']=raw
        if captured['headers']['Content-Type'].startswith('application/json'):
            captured['body']=json.loads(raw)
        return captured

    def login(self):
        result=self.request('/api/login','POST',dict(correo='test@example.test',password='ContraseñaLocal123!'))
        self.assertTrue(result['status'].startswith('200'))
        return result['headers']['Set-Cookie'].split(';')[0],result['body']['csrf']

    def test_https_host_origin_and_methods(self):
        self.assertTrue(self.request(scheme='http')['status'].startswith('403'))
        self.assertTrue(self.request(host='attacker.test')['status'].startswith('403'))
        self.assertTrue(self.request('/api/login','POST',{},origin='https://attacker.test')['status'].startswith('403'))
        self.assertTrue(self.request('/','DELETE')['status'].startswith('405'))

    def test_only_public_assets_and_security_headers(self):
        result=self.request()
        self.assertTrue(result['status'].startswith('200'))
        self.assertIn('Strict-Transport-Security',result['headers'])
        for path in ('/.env','/web.py','/server.py','/ewallet.pem','/tnsnames.ora'):
            self.assertTrue(self.request(path)['status'].startswith('404'))

    def test_registered_login_secure_cookie_csrf_write_logout(self):
        cookie,csrf=self.login()
        self.assertTrue(cookie.startswith('__Host-andina_session='))
        result=self.request('/api/login','POST',dict(correo='test@example.test',password='ContraseñaLocal123!'))
        self.assertIn('; Secure',result['headers']['Set-Cookie'])
        self.assertIn('HttpOnly',result['headers']['Set-Cookie'])
        self.assertIn('SameSite=Strict',result['headers']['Set-Cookie'])
        unauthorized=self.request('/api/records/ubicacion','POST',dict(id=None,data=dict(nombre='TEST WEB')),cookie=cookie)
        self.assertTrue(unauthorized['status'].startswith('403'))
        saved=self.request('/api/records/ubicacion','POST',dict(id=None,data=dict(nombre='TEST WEB')),cookie,csrf)
        self.assertTrue(saved['status'].startswith('200'))
        self.assertEqual(saved['body']['id'],1)
        result=self.request('/api/logout','POST',{},cookie,csrf)
        self.assertIn('Max-Age=0',result['headers']['Set-Cookie'])
        self.assertIn('; Secure',result['headers']['Set-Cookie'])
        self.assertTrue(self.request('/api/me',cookie=cookie)['status'].startswith('401'))

    def test_unknown_or_inactive_user_cannot_enter(self):
        result=self.request('/api/login','POST',dict(correo='not-registered@example.test',password='ContraseñaLocal123!'))
        self.assertTrue(result['status'].startswith('401'))
        self.connection.db.execute("UPDATE usuario SET estado='INACTIVO' WHERE id_usuario=1")
        self.connection.commit()
        result=self.request('/api/login','POST',dict(correo='test@example.test',password='ContraseñaLocal123!'))
        self.assertTrue(result['status'].startswith('401'))

    def test_password_change_from_another_process_invalidates_session(self):
        cookie,_=self.login()
        self.connection.db.execute("UPDATE usuario SET clave_hash='CAMBIO_EXTERNO' WHERE id_usuario=1")
        self.connection.commit()
        self.assertTrue(self.request('/api/me',cookie=cookie)['status'].startswith('401'))

    def test_limiter_independent_accounts(self):
        limiter=LoginLimiter()
        for _ in range(8):
            limiter.check('192.0.2.1','one@example.test')
        from service import AppError
        with self.assertRaises(AppError):
            limiter.check('192.0.2.2','one@example.test')
        limiter.check('192.0.2.1','other@example.test')

    def test_origin_from_env_rejects_unsafe_values(self):
        for origin in ('http://andina.test','https://andina.test/path','https://user:pass@andina.test',''):
            with patch.dict(os.environ,{'PUBLIC_URL':origin,'RENDER_EXTERNAL_URL':''}):
                with self.assertRaises(ValueError):
                    Settings.from_env()
        with patch.dict(os.environ,{'PUBLIC_URL':'','RENDER_EXTERNAL_URL':'https://my-service.onrender.com'}):
            self.assertEqual(Settings.from_env().host,'my-service.onrender.com')

if __name__=='__main__':
    unittest.main()
