ALTER TABLE asignaciones ADD COLUMN periodo VARCHAR(10) NOT NULL DEFAULT 'A' AFTER grupo_id;
ALTER TABLE asignaciones ADD COLUMN hora_inicio TIME NULL AFTER periodo;
ALTER TABLE asignaciones ADD COLUMN hora_fin TIME NULL AFTER hora_inicio;
ALTER TABLE asignaciones ADD COLUMN modalidad VARCHAR(30) NOT NULL DEFAULT 'Presencial' AFTER hora_fin;
