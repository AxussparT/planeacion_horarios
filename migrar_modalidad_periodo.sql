ALTER TABLE profesor_disponibilidad ADD COLUMN modalidad VARCHAR(30) NOT NULL DEFAULT 'Presencial';

ALTER TABLE profesor_disponibilidad MODIFY modalidad VARCHAR(30) NOT NULL DEFAULT 'Presencial'