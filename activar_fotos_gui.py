"""Asistente visual local. Las contraseñas solo se entregan al controlador Oracle."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import json,re,threading
import tkinter as tk
from tkinter import filedialog,messagebox,ttk
import oracledb

ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT.parent/'output'

def status(stage,code=None):
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT/'activacion_fotos_estado.json').write_text(json.dumps(dict(estado=stage,codigo=code,fecha=datetime.now().isoformat())),encoding='utf-8')

def activate(wallet,password,wallet_password):
    status('conectando')
    with TemporaryDirectory(prefix='andina-fotos-') as directory:
        with ZipFile(wallet) as archive:
            for name in ('tnsnames.ora','ewallet.pem'):
                entries=[e for e in archive.infolist() if Path(e.filename).name==name]
                if len(entries)!=1 or entries[0].file_size>2_000_000:raise ValueError('Wallet no válido.')
                Path(directory,name).write_bytes(archive.read(entries[0]))
        params=oracledb.ConnectParams(user='ADMIN',password=password,config_dir=directory,wallet_location=directory,wallet_password=wallet_password)
        params.parse_connect_string('basedatos2026_high')
        params.set(retry_count=0,retry_delay=0,tcp_connect_timeout=20)
        with oracledb.connect(params=params) as connection:
            connection.call_timeout=20000
            with connection.cursor() as cursor:
                cursor.execute('SELECT id_incidencia FROM incidencia WHERE 1=0')
                cursor.execute("SELECT username FROM all_users WHERE username='ANDINA_APP'")
                if not cursor.fetchone():raise ValueError('Esta conexión no contiene la cuenta ANDINA_APP del proyecto.')
                status('conexion_verificada')
                for statement in re.split(r'(?m)^/\s*$',(ROOT/'ACTIVAR_FOTOS.sql').read_text(encoding='utf-8')):
                    statement=statement.strip()
                    if statement:
                        if statement.startswith('GRANT'):statement=statement.rstrip(';')
                        cursor.execute(statement)
                cursor.execute('SELECT id_evidencia,contenido FROM incidencia_evidencia WHERE 1=0')
                cursor.execute("SELECT privilege FROM user_tab_privs_made WHERE table_name='INCIDENCIA_EVIDENCIA' AND grantee='ANDINA_APP'")
                if not {'SELECT','INSERT'}<={r[0] for r in cursor.fetchall()}:raise ValueError('No se pudieron verificar los permisos de las fotografías.')
    (OUTPUT/'activacion_fotos_resultado.json').write_text(json.dumps(dict(activado=True,tabla='INCIDENCIA_EVIDENCIA',fecha=datetime.now().isoformat())),encoding='utf-8')
    status('activado')

def main():
    window=tk.Tk();window.title('AndinaMantención · Activar fotografías');window.geometry('680x560');window.resizable(False,False)
    pane=ttk.Frame(window,padding=28);pane.pack(fill='both',expand=True)
    ttk.Label(pane,text='Activar fotografías en AndinaMantención',font=('Segoe UI',17,'bold')).pack(anchor='w',pady=(0,12))
    ttk.Label(pane,text='Esta ventana es local. Las claves no se muestran ni se guardan en archivos.\nLa conexión se realiza directamente a tu base Oracle.',wraplength=610).pack(anchor='w',pady=(0,18))
    wallet=tk.StringVar(value=str(Path.home()/'Downloads'/'Wallet_basedatos2026.zip'))
    oracle=tk.StringVar();wallet_key=tk.StringVar();feedback=tk.StringVar(value='Introduce las dos claves y pulsa Activar fotografías.')
    ttk.Label(pane,text='Archivo Wallet ZIP').pack(anchor='w')
    row=ttk.Frame(pane);row.pack(fill='x',pady=(5,14))
    ttk.Entry(row,textvariable=wallet).pack(side='left',fill='x',expand=True)
    def browse():
        path=filedialog.askopenfilename(parent=window,title='Seleccionar Wallet',filetypes=[('Wallet ZIP','*.zip')])
        if path:wallet.set(path)
    ttk.Button(row,text='Buscar…',command=browse).pack(side='left',padx=(8,0))
    ttk.Label(pane,text='Contraseña de la base de datos Oracle (usuario ADMIN)').pack(anchor='w')
    first=ttk.Entry(pane,textvariable=oracle,show='●');first.pack(fill='x',pady=(5,14))
    ttk.Label(pane,text='Contraseña del Wallet (la elegida al descargar el ZIP)').pack(anchor='w')
    ttk.Entry(pane,textvariable=wallet_key,show='●').pack(fill='x',pady=(5,16))
    ttk.Label(pane,text='Al activar se crea la tabla de fotos si falta y se concede a ANDINA_APP\npermiso para leer e insertar fotografías. No se borran ni cambian los registros\nexistentes. Oracle confirma cada instrucción de estructura por separado.',wraplength=610).pack(anchor='w',pady=(0,18))
    ttk.Label(pane,textvariable=feedback,wraplength=610).pack(anchor='w',pady=(0,14))
    def finish(error=None):
        oracle.set('');wallet_key.set('');button.configure(state='normal')
        if error:
            feedback.set(error)
            messagebox.showerror('No se pudo activar',error,parent=window)
        else:
            feedback.set('FOTOGRAFÍAS ACTIVADAS CORRECTAMENTE. Vuelve al chat; ya puedes cerrar esta ventana.')
            messagebox.showinfo('AndinaMantención','Fotografías activadas correctamente. Vuelve al chat.',parent=window)
    def start():
        if not Path(wallet.get()).is_file():feedback.set('Selecciona el ZIP válido del Wallet.');return
        if not oracle.get() or not wallet_key.get():feedback.set('Falta introducir una de las dos contraseñas.');return
        values=(wallet.get(),oracle.get(),wallet_key.get())
        button.configure(state='disabled');feedback.set('Conectando y verificando tu proyecto en Oracle…')
        def worker():
            try:activate(*values)
            except oracledb.Error as error:
                code=getattr(error.args[0] if error.args else None,'full_code','ERROR_ORACLE')
                status('error_oracle',code)
                descriptions={'ORA-01017':'La contraseña de ADMIN no es correcta.','ORA-28000':'La cuenta ADMIN está bloqueada.','DPY-6005':'No se pudo conectar. Revisa el Wallet y su contraseña.'}
                message=descriptions.get(code,'Oracle no completó la activación. Revisa las claves y la conexión.')+' Código: '+code
                window.after(0,lambda value=message:finish(value))
            except Exception as error:
                status('error',type(error).__name__)
                message=str(error) if isinstance(error,ValueError) else 'No se pudo completar la activación ('+type(error).__name__+').'
                window.after(0,lambda value=message:finish(value))
            else:window.after(0,finish)
        threading.Thread(target=worker,daemon=True).start()
    button=ttk.Button(pane,text='Activar fotografías',command=start);button.pack(anchor='e')
    status('esperando_claves');first.focus_set();window.mainloop()

if __name__=='__main__':main()
