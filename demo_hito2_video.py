"""Graba una demostración reproducible de AndinaMantención con datos sintéticos.

No usa Oracle real, credenciales del alumno ni el sitio público de Render.
El video representa la interfaz y servicios reales de la rama main en un servidor local.
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread
from wsgiref.simple_server import make_server
import shutil

from playwright.async_api import async_playwright
from security import hash_password
from test_transactions import Connection, Pool
from server import Application
from web import Settings, create_wsgi

BASE = 'http://127.0.0.1:8765'
EMAIL = 'demostracion@andina.example.test'
PASSWORD = 'DemoTemporal2026!'
OUT = Path('video_hito2')
OUT.mkdir(exist_ok=True)


def fixture():
    connection = Connection()  # Solo SQLite efímera de test.
    db = connection.db
    db.execute('UPDATE usuario SET nombre=?, apellido=?, correo=?, clave_hash=? WHERE id_usuario=1',
               ('Usuario', 'Demo', EMAIL, hash_password(PASSWORD)))
    db.execute("INSERT INTO ubicacion(nombre) VALUES ('PLANTA DEMOSTRACION')")
    db.execute("""INSERT INTO activo(codigo_activo,nombre,marca,modelo,estado,id_ubicacion)
                  VALUES ('DEMO-001','Equipo de ensayo','Marca de prueba','Modelo de prueba','OPERATIVO',1)""")
    db.execute("""INSERT INTO incidencia(id_activo,id_usuario,descripcion,prioridad,estado,fecha_reporte)
                  VALUES (1,1,'Vibración de ejemplo para demostración','MEDIA','REPORTADA',?)""",
               (datetime.now()-timedelta(days=1),))
    db.execute("""INSERT INTO orden_trabajo(id_incidencia,id_usuario_asignado,descripcion_trabajo,estado,fecha_creacion)
                  VALUES (1,1,'Inspeccionar y diagnosticar (ejemplo)','PENDIENTE',?)""",
               (datetime.now(),))
    db.execute("""INSERT INTO repuesto(codigo_repuesto,nombre,descripcion,stock_actual,stock_minimo,precio_unitario,estado)
                  VALUES ('DEMO-REP','Repuesto de prueba','Solo demostración',5,2,1000,'ACTIVO')""")
    db.execute("""INSERT INTO mantenimiento_preventivo(id_activo,id_usuario_responsable,descripcion,fecha_programada,frecuencia_dias,estado)
                  VALUES (1,1,'Inspección programada de ejemplo',?,30,'PROGRAMADO')""",
               (datetime.now()+timedelta(days=4),))
    db.commit()
    return connection


async def record():
    connection = fixture()
    app = create_wsgi(Application(Pool(connection)), Settings(BASE, 'ADMIN', production=False))
    server = make_server('127.0.0.1', 8765, app)
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 720},
                record_video_dir=str(OUT),
                record_video_size={'width': 1280, 'height': 720},
                reduced_motion='reduce',
            )
            page = await context.new_page()
            page.set_default_timeout(20000)
            await page.goto(BASE, wait_until='domcontentloaded')
            await page.wait_for_selector('#email')
            await page.wait_for_timeout(3000)
            await page.locator('#email').fill(EMAIL)
            await page.locator('#password').fill(PASSWORD)
            await page.wait_for_timeout(1200)
            await page.locator('#login-submit').click()
            await page.wait_for_selector('#app:not([hidden])', timeout=20000)
            await page.wait_for_timeout(4200)
            # Los controles son los de la aplicación, no capturas inventadas.
            async def visit(name, hold=2700):
                await page.locator(f'#navigation [data-view="{name}"]').click()
                await page.wait_for_timeout(hold)

            await visit('activo', 3000)
            details = page.locator('#records [data-detail]')
            if await details.count():
                await details.first.click()
                await page.wait_for_timeout(4200)  # Muestra el QR real de un activo ficticio
                await page.evaluate("document.querySelector('#detail').close()")
                await page.wait_for_timeout(500)
            await visit('incidencia', 3000)
            await visit('orden_trabajo', 3000)
            await visit('mantenimiento_preventivo', 3000)
            await visit('repuesto', 2800)
            await visit('dashboard', 1800)
            # Flujo real de generación y envío de incidencia sobre la base de prueba
            await page.locator('#dashboard-report-failure').click()
            await page.wait_for_selector('#field-id_activo')
            await page.locator('#field-id_activo').select_option('1')
            await page.locator('#field-descripcion').fill('Reporte de prueba para la demostración del Hito 2.')
            await page.wait_for_timeout(3200)
            await page.locator('#save-record').click()
            await page.wait_for_timeout(4500)
            await page.screenshot(path=str(OUT/'captura_final.png'), full_page=False)
            clip = await page.video.path()
            await context.close()
            await browser.close()
            shutil.copy2(clip, OUT/'demo_original.webm')
    finally:
        server.shutdown()
        t.join(timeout=5)
        connection.db.close()


if __name__ == '__main__':
    asyncio.run(record())
