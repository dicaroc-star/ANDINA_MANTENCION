-- Ejecutar una vez como propietario de las tablas existentes (ADMIN).
-- Agrega almacenamiento de fotografías; no modifica ni borra las 11 tablas actuales.
-- La cuenta técnica ANDINA_APP solo recibe SELECT e INSERT sobre esta tabla nueva.
DECLARE
  existe NUMBER;
BEGIN
  SELECT COUNT(*) INTO existe FROM user_tables WHERE table_name='INCIDENCIA_EVIDENCIA';
  IF existe=0 THEN
    EXECUTE IMMEDIATE 'CREATE TABLE incidencia_evidencia (
      id_evidencia NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      id_incidencia NUMBER NOT NULL REFERENCES incidencia(id_incidencia),
      id_usuario NUMBER NOT NULL REFERENCES usuario(id_usuario),
      posicion NUMBER(1) NOT NULL CHECK (posicion BETWEEN 1 AND 3),
      nombre VARCHAR2(100 CHAR) NOT NULL,
      contenido BLOB NOT NULL,
      ancho NUMBER(4) NOT NULL CHECK (ancho BETWEEN 1 AND 1600),
      alto NUMBER(4) NOT NULL CHECK (alto BETWEEN 1 AND 1600),
      fecha_creacion TIMESTAMP DEFAULT LOCALTIMESTAMP NOT NULL,
      CONSTRAINT uq_evidencia_incidencia UNIQUE (id_incidencia,posicion)
    )';
  END IF;
END;
/
GRANT SELECT, INSERT ON incidencia_evidencia TO ANDINA_APP;
