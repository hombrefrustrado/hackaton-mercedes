-- ====================================================================
-- Script de Administración de Base de Datos Oracle (admin.sql)
-- ====================================================================

-- 1. Crear el Tablespace con un límite máximo de almacenamiento de 1 GB.
-- Se crea con un tamaño inicial de 100 MB y se auto-extiende en fragmentos de 50 MB.
CREATE TABLESPACE tbs_finops
  DATAFILE 'tbs_finops.dbf' 
  SIZE 100M 
  AUTOEXTEND ON NEXT 50M 
  MAXSIZE 1G;

-- 2. Crear el usuario en la base de datos.
-- NOTA: "USER" es una palabra reservada en Oracle SQL, por lo que es mandatorio
-- escribirla entre comillas dobles ("user") para evitar errores de sintaxis.
CREATE USER "user" IDENTIFIED BY "user_password_123"
  DEFAULT TABLESPACE tbs_finops;

-- 3. Otorgar privilegios de conexión y creación de objetos al usuario.
-- El rol CONNECT permite iniciar sesión (CREATE SESSION).
-- El rol RESOURCE otorga permisos estándar de desarrollo (crear tablas, secuencias, tipos, procedimientos, etc.).
GRANT CONNECT, RESOURCE TO "user";

-- Otorgamos privilegios del sistema de forma explícita por seguridad y consistencia en versiones recientes de Oracle.
GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, CREATE SEQUENCE, CREATE PROCEDURE TO "user";

-- 4. Asignar la cuota de almacenamiento de 1 GB (igual que el límite del tablespace) al usuario.
ALTER USER "user" QUOTA 1G ON tbs_finops;
