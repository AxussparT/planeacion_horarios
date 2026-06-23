-- Renombrar salones EN_LINEA a MEDIACION_TECNOLOGICA
UPDATE salones SET salon_id = REPLACE(salon_id, 'EN_LINEA', 'MEDIACION_TECNOLOGICA') WHERE salon_id LIKE 'EN_LINEA%';
-- Actualizar horarios que referencian esos salones
UPDATE horarios SET salon_id = REPLACE(salon_id, 'EN_LINEA', 'MEDIACION_TECNOLOGICA') WHERE salon_id LIKE 'EN_LINEA%';
