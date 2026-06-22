-- Migración: Agregar no_cuenta, resetear en_linea, regenerar profesor_id
-- Ejecutar: mysql -u root -p bd_seso < migrar_profesores.sql

ALTER TABLE profesores ADD COLUMN no_cuenta VARCHAR(20) DEFAULT NULL AFTER profesor_id;

-- Copiar el antiguo profesor_id a no_cuenta (quitando sufijo -L si existe)
UPDATE profesores SET no_cuenta = REPLACE(profesor_id, '-L', '') WHERE no_cuenta IS NULL;

-- Desactivar en_linea para todos (ya no se usa)
UPDATE profesores SET en_linea = 'NO';

-- Regenerar profesor_id como P0001, P0002...
CREATE TEMPORARY TABLE tmp_id_map AS
SELECT profesor_id AS old_id,
       CONCAT('P', LPAD(@rn := @rn + 1, 4, '0')) AS new_id
FROM profesores, (SELECT @rn := 0) AS r
ORDER BY profesor_id;

-- Actualizar asignaciones
UPDATE asignaciones a
JOIN tmp_id_map m ON a.profesor_id = m.old_id
SET a.profesor_id = m.new_id;

-- Actualizar profesor_disponibilidad
UPDATE profesor_disponibilidad pd
JOIN tmp_id_map m ON pd.profesor_id = m.old_id
SET pd.profesor_id = m.new_id;

-- Actualizar profesores
UPDATE profesores p
JOIN tmp_id_map m ON p.profesor_id = m.old_id
SET p.profesor_id = m.new_id;

DROP TEMPORARY TABLE IF EXISTS tmp_id_map;
