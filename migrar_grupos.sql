-- Migración: Reemplazar campo nombre por nivel en tabla grupos
-- Ejecutar: mysql -u root -p bd_seso < migrar_grupos.sql

ALTER TABLE grupos ADD COLUMN nivel INT DEFAULT NULL AFTER grupo_id;

-- Extraer semestre del grupo_id (ej. S1A -> 1)
UPDATE grupos SET nivel = CAST(REGEXP_SUBSTR(grupo_id, 'S([0-9])', 1, 1, 'e', 1) AS UNSIGNED) WHERE nivel IS NULL;

UPDATE grupos SET nivel = 0 WHERE nivel IS NULL;

-- Eliminar columna nombre (ya no se usa)
ALTER TABLE grupos DROP COLUMN nombre;
