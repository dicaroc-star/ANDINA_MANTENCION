"""Preparación local y explícita de la cuenta técnica. No modifica las 11 tablas."""
from getpass import getpass
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import re
import oracledb
from schema import TABLES
from service import query

def main():
    print('PREPARAR CUENTA TECNICA ANDINA_APP PARA EL ALOJAMIENTO')
    print('Este programa crea un usuario Oracle y le concede permisos sobre las tablas.')
    print('No cambia las cuentas de la tabla usuario ni sus contraseñas de aplicación.\n')
    wallet=Path(input('Arrastra el ZIP original del Wallet: ').strip().strip('"'))
    if not wallet.is_file():
        raise ValueError('No se encontró el Wallet.')
    owner=input('Usuario propietario de las tablas [ADMIN]: ').strip().upper() or 'ADMIN'
    if not re.fullmatch('[A-Z][A-Z0-9_]{0,29}',owner):
        raise ValueError('Nombre de usuario no válido.')
    service=input('Servicio [basedatos2026_high]: ').strip() or 'basedatos2026_high'
    password=getpass('Contraseña Oracle del propietario: ')
    wallet_password=getpass('Contraseña del Wallet: ')
    with TemporaryDirectory(prefix='andina-provision-') as directory:
        with ZipFile(wallet) as archive:
            for filename in ('tnsnames.ora','ewallet.pem'):
                items=[item for item in archive.infolist() if Path(item.filename).name==filename]
                if len(items)!=1 or items[0].file_size>2_000_000:
                    raise ValueError('Wallet no válido.')
                Path(directory,filename).write_bytes(archive.read(items[0]))
        with oracledb.connect(user=owner,password=password,dsn=service,config_dir=directory,
                              wallet_location=directory,wallet_password=wallet_password) as connection:
            existing=query(connection,"SELECT username FROM all_users WHERE username='ANDINA_APP'")
            if existing:
                print('ANDINA_APP ya existe. No se cambiará su contraseña ni sus permisos.')
                print('Para reutilizarla, revisa la cuenta con el administrador de Oracle.')
                return
            for table in TABLES:
                query(connection,f'SELECT 1 FROM {owner}.{table} WHERE 1=0')
            print(f'\nSe creará ANDINA_APP con CREATE SESSION y ALTER SESSION.')
            print(f'Podrá leer las 11 tablas de {owner}; insertar y editar las operativas;')
            print('y solo leer/insertar historial_estado. No podrá borrar registros ni crear tablas.')
            print('La creación y cada GRANT se confirman automáticamente por Oracle (DDL).')
            if input('Escribe CREAR para aplicar estos permisos: ').strip()!='CREAR':
                print('Cancelado. No se hicieron cambios.')
                return
            while True:
                technical_password=getpass('Nueva contraseña de ANDINA_APP (12-30 caracteres): ')
                confirm=getpass('Repite la contraseña de ANDINA_APP: ')
                if technical_password!=confirm:
                    print('No coinciden.')
                elif not 12<=len(technical_password)<=30 or any(char in technical_password for char in ('"','\r','\n','\x00')):
                    print('Usa de 12 a 30 caracteres, sin comillas dobles ni saltos de línea.')
                else:
                    break
            with connection.cursor() as cursor:
                # Oracle no admite bind variables para IDENTIFIED BY. El identificador es fijo;
                # la contraseña está entre comillas y se rechazan comillas dobles/controles.
                cursor.execute(f'CREATE USER ANDINA_APP IDENTIFIED BY "{technical_password}"')
                cursor.execute('GRANT CREATE SESSION, ALTER SESSION TO ANDINA_APP')
                for table in TABLES:
                    privileges='SELECT, INSERT' if table=='historial_estado' else 'SELECT, INSERT, UPDATE'
                    cursor.execute(f'GRANT {privileges} ON {owner}.{table} TO ANDINA_APP')
            print('\nCuenta técnica creada. Guarda su contraseña en el gestor de secretos del alojamiento.')
            print('DB_USER=ANDINA_APP; DB_SCHEMA='+owner+'; DB_SERVICE='+service)
            print('No compartas su contraseña ni el Wallet en el chat.')

if __name__=='__main__':
    try:
        main()
    except (KeyboardInterrupt,EOFError):
        print('\nCancelado.')
    except oracledb.Error as error:
        detail=error.args[0] if error.args else None
        print('No se pudo completar la preparación. Código:',getattr(detail,'full_code','ERROR_ORACLE'))
        print('Si ya se creó ANDINA_APP, puede faltar algún GRANT. Revisa los permisos antes de publicar.')
        raise SystemExit(1)
    except Exception as error:
        print('No se pudo preparar la cuenta:',type(error).__name__)
        raise SystemExit(1)
