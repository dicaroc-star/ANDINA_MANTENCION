"""Activación local supervisada de almacenamiento de fotos, sin guardar credenciales."""
from datetime import datetime
from getpass import getpass
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import json
import re
import oracledb

ROOT=Path(__file__).resolve().parent
RESULT=ROOT.parent/'output'/'activacion_fotos_resultado.json'

def main():
    print('\nANDINAMANTENCION - ACTIVAR FOTOGRAFIAS\n')
    print('Agrega la tabla INCIDENCIA_EVIDENCIA y permite a ANDINA_APP leer y guardar fotos.')
    print('No borra ni modifica registros existentes. Las claves no se guardan.\n')
    wallet=Path(input('Arrastra aqui el ZIP del Wallet y pulsa Enter: ').strip().strip('"'))
    if not wallet.is_file() or wallet.suffix.lower()!='.zip':
        raise ValueError('No se encontro el archivo ZIP del Wallet.')
    owner=input('Usuario propietario de las tablas [ADMIN]: ').strip() or 'ADMIN'
    service=input('Servicio Oracle [basedatos2026_high]: ').strip() or 'basedatos2026_high'
    password=getpass('Clave de Oracle del propietario (oculta): ')
    wallet_password=getpass('Clave del Wallet (oculta): ')
    with TemporaryDirectory(prefix='andina-fotos-wallet-') as directory:
        with ZipFile(wallet) as archive:
            for name in ('tnsnames.ora','ewallet.pem'):
                entries=[entry for entry in archive.infolist() if Path(entry.filename).name==name]
                if len(entries)!=1 or entries[0].file_size>2_000_000:raise ValueError('Wallet no valido.')
                Path(directory,name).write_bytes(archive.read(entries[0]))
        params=oracledb.ConnectParams(user=owner,password=password,config_dir=directory,wallet_location=directory,wallet_password=wallet_password)
        params.parse_connect_string(service)
        params.set(retry_count=0,retry_delay=0,tcp_connect_timeout=20)
        with oracledb.connect(params=params) as connection:
            connection.call_timeout=20000
            with connection.cursor() as cursor:
                cursor.execute('SELECT id_incidencia FROM incidencia WHERE 1=0')
                cursor.execute("SELECT username FROM all_users WHERE username='ANDINA_APP'")
                if not cursor.fetchone():raise ValueError('No se encontro la cuenta tecnica ANDINA_APP.')
                print('\nConexion y tablas existentes verificadas.')
                print('Se ejecutara ACTIVAR_FOTOS.sql: crear solo la tabla de fotos si falta,')
                print('y conceder SELECT e INSERT sobre esa tabla a ANDINA_APP.')
                print('Oracle confirma cada instruccion de estructura por separado.\n')
                if input('Escribe ACTIVAR para aplicar este cambio: ').strip()!='ACTIVAR':
                    print('Cancelado. No se aplicaron cambios.');return
                sql=(ROOT/'ACTIVAR_FOTOS.sql').read_text(encoding='utf-8')
                for statement in re.split(r'(?m)^/\s*$',sql):
                    statement=statement.strip()
                    if statement:
                        if not statement.lstrip().startswith('--') and not statement.startswith('DECLARE'):statement=statement.rstrip(';')
                        cursor.execute(statement)
                cursor.execute('SELECT id_evidencia,contenido,ancho,alto FROM incidencia_evidencia WHERE 1=0')
                cursor.execute("SELECT privilege FROM user_tab_privs_made WHERE table_name='INCIDENCIA_EVIDENCIA' AND grantee='ANDINA_APP'")
                if not {'SELECT','INSERT'}<={row[0] for row in cursor.fetchall()}:
                    raise ValueError('Falta verificar los permisos de fotografias.')
                RESULT.parent.mkdir(exist_ok=True)
                RESULT.write_text(json.dumps(dict(activado=True,tabla='INCIDENCIA_EVIDENCIA',fecha=datetime.now().isoformat()),indent=2),encoding='utf-8')
                print('\nFOTOGRAFIAS ACTIVADAS CORRECTAMENTE.')
                print('Vuelve al chat y avisa: Listo. Recarga la aplicacion despues de publicarla.')

if __name__=='__main__':
    try:main()
    except (KeyboardInterrupt,EOFError):print('\nActivacion cancelada.')
    except ValueError as error:print('\nNo se completo:',error)
    except oracledb.Error as error:
        detail=error.args[0] if error.args else None
        print('\nOracle no completo la activacion. Codigo:',getattr(detail,'full_code','ERROR_ORACLE'))
        print('Revisa Wallet, claves y que uses el propietario de las tablas.')
    except Exception as error:print('\nNo se completo la activacion:',type(error).__name__)
    input('\nPulsa Enter para cerrar esta ventana...')
