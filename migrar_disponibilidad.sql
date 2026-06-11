-- ============================================================
-- MIGRACIÓN: Soporte multi-periodo para profesores
-- ============================================================
-- Ejecutar en MySQL Workbench o línea de comandos:
-- mysql -u root -p123456 bd_seso < migrar_disponibilidad.sql
-- ============================================================

-- 1. Crear tabla de disponibilidad por período
CREATE TABLE IF NOT EXISTS profesor_disponibilidad (
    id INT AUTO_INCREMENT PRIMARY KEY,
    profesor_id VARCHAR(20) NOT NULL,
    dia VARCHAR(15) NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    FOREIGN KEY (profesor_id) REFERENCES profesores(profesor_id) ON DELETE CASCADE,
    INDEX idx_profesor_id (profesor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Migrar datos existentes de profesores a la nueva tabla
--    (convierte el campo dias_disponibles separado por comas en filas individuales)
INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin)
SELECT 
    p.profesor_id,
    TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(p.dias_disponibles, ',', n.n), ',', -1)) AS dia,
    p.disponible_inicio,
    p.disponible_fin
FROM profesores p
CROSS JOIN (
    SELECT 1 AS n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6
) n
WHERE n.n <= LENGTH(p.dias_disponibles) - LENGTH(REPLACE(p.dias_disponibles, ',', '')) + 1
  AND p.dias_disponibles IS NOT NULL
  AND p.dias_disponibles != ''
  AND p.disponible_inicio IS NOT NULL
  AND p.disponible_fin IS NOT NULL;

-- 3. Hacer opcionales las columnas viejas (para que el código nuevo no falle al insertar)
ALTER TABLE profesores
    MODIFY COLUMN disponible_inicio TIME DEFAULT NULL,
    MODIFY COLUMN disponible_fin TIME DEFAULT NULL,
    MODIFY COLUMN dias_disponibles VARCHAR(255) DEFAULT NULL;

-- 4. Verificar migración (opcional - mostrar cuántos registros se migraron)
SELECT CONCAT('Registros migrados: ', COUNT(*)) AS resultado FROM profesor_disponibilidad;
