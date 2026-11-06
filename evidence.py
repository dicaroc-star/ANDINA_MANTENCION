"""Fotografías privadas en Oracle; nunca se guardan en el disco efímero del alojamiento."""
import base64
import binascii
import io
from PIL import Image, ImageOps, UnidentifiedImageError
import oracledb
from service import AppError, one, query

MAX_FILES=3
MAX_BYTES=2_000_000
MAX_REQUEST=8_100_000

def available(connection):
    try:
        query(connection,'SELECT id_evidencia FROM incidencia_evidencia WHERE 1=0')
        return True
    except oracledb.Error as error:
        if getattr(error.args[0] if error.args else None,'code',0) in (942,1031):
            return False
        raise

def normalize(files):
    if not isinstance(files,list) or len(files)>MAX_FILES:
        raise AppError('Puedes adjuntar hasta 3 fotografías.')
    result=[]
    for item in files:
        if not isinstance(item,dict) or set(item)-{'nombre','contenido'}:
            raise AppError('La fotografía no tiene un formato válido.')
        encoded=item.get('contenido')
        if not isinstance(encoded,str) or len(encoded)>((MAX_BYTES+2)//3)*4:
            raise AppError('Cada fotografía debe ocupar como máximo 2 MB.',413)
        try:
            raw=base64.b64decode(encoded,validate=True)
            if not raw or len(raw)>MAX_BYTES:raise ValueError()
            with Image.open(io.BytesIO(raw)) as original:
                if original.format not in ('JPEG','PNG','WEBP') or original.width*original.height>12_500_000:
                    raise ValueError()
                original.load()
                photo=ImageOps.exif_transpose(original).convert('RGB')
                photo.thumbnail((1600,1600))
                output=io.BytesIO()
                photo.save(output,format='JPEG',quality=82,optimize=True)
                content=output.getvalue()
                if len(content)>MAX_BYTES:raise ValueError()
                # No se conserva EXIF ni ubicación GPS; el nombre mostrado tampoco es una ruta.
                name=item.get('nombre','fotografia')
                if not isinstance(name,str):raise ValueError()
                name=name.replace('\\','/').rsplit('/',1)[-1]
                name=''.join(c for c in name if c.isprintable())[:100] or 'fotografia'
                result.append(dict(nombre=name,contenido=content,ancho=photo.width,alto=photo.height))
        except (ValueError,binascii.Error,UnidentifiedImageError,OSError,Image.DecompressionBombError):
            raise AppError('La imagen no es válida. Usa fotografías JPG, PNG o WebP de hasta 2 MB.') from None
    return result

def attach(connection,incident,user,files):
    for position,photo in enumerate(files,1):
        with connection.cursor() as cursor:
            cursor.setinputsizes(contenido=oracledb.DB_TYPE_BLOB)
            cursor.execute('''INSERT INTO incidencia_evidencia
             (id_incidencia,id_usuario,posicion,nombre,contenido,ancho,alto)
             VALUES (:incidencia,:usuario,:posicion,:nombre,:contenido,:ancho,:alto)''',
             dict(incidencia=incident,usuario=user['id_usuario'],posicion=position,**photo))

def listing(connection,incident):
    if not one(connection,'SELECT id_incidencia FROM incidencia WHERE id_incidencia=:id',dict(id=incident)):
        raise AppError('La incidencia no existe.',404)
    if not available(connection):return []
    return query(connection,'''SELECT id_evidencia,nombre,ancho,alto,fecha_creacion FROM incidencia_evidencia
     WHERE id_incidencia=:id ORDER BY posicion''',dict(id=incident))

def read(connection,identifier):
    if not available(connection):raise AppError('Fotografía no encontrada.',404)
    row=one(connection,'SELECT contenido FROM incidencia_evidencia WHERE id_evidencia=:id',dict(id=identifier))
    if not row:raise AppError('Fotografía no encontrada.',404)
    value=row['contenido']
    return value.read() if hasattr(value,'read') else bytes(value)
