-- ============================================================
-- SCRIPT COMPLETO: Crear BD bd_seso desde cero
-- Uso: mysql -u root -p < setup_bd.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS bd_seso DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE bd_seso;

-- ==================== TABLAS ====================

CREATE TABLE IF NOT EXISTS profesores (
    profesor_id VARCHAR(20) PRIMARY KEY,
    no_cuenta VARCHAR(20) DEFAULT NULL,
    nombre VARCHAR(255) NOT NULL,
    disponible_inicio TIME DEFAULT NULL,
    disponible_fin TIME DEFAULT NULL,
    dias_disponibles VARCHAR(255) DEFAULT NULL,
    en_linea VARCHAR(10) DEFAULT 'NO'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS profesor_disponibilidad (
    id INT AUTO_INCREMENT PRIMARY KEY,
    profesor_id VARCHAR(20) NOT NULL,
    dia VARCHAR(15) NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    modalidad VARCHAR(30) NOT NULL DEFAULT 'Presencial',
    FOREIGN KEY (profesor_id) REFERENCES profesores(profesor_id) ON DELETE CASCADE,
    INDEX idx_profesor_id (profesor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS materias (
    materia_id VARCHAR(20) PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL,
    horas_semana DECIMAL(5,2) NOT NULL DEFAULT 0,
    semestre_id INT DEFAULT NULL,
    tipo VARCHAR(50) NOT NULL DEFAULT 'Normal'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS grupos (
    grupo_id VARCHAR(20) PRIMARY KEY,
    nivel INT DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS asignaciones (
    asignacion_id INT AUTO_INCREMENT PRIMARY KEY,
    profesor_id VARCHAR(20) NOT NULL,
    materia_id VARCHAR(20) NOT NULL,
    grupo_id VARCHAR(20) NOT NULL,
    periodo VARCHAR(10) NOT NULL DEFAULT 'A',
    hora_inicio TIME NULL,
    hora_fin TIME NULL,
    modalidad VARCHAR(30) NOT NULL DEFAULT 'Presencial',
    estado VARCHAR(20) DEFAULT 'pendiente',
    FOREIGN KEY (profesor_id) REFERENCES profesores(profesor_id) ON DELETE CASCADE,
    FOREIGN KEY (materia_id) REFERENCES materias(materia_id) ON DELETE CASCADE,
    FOREIGN KEY (grupo_id) REFERENCES grupos(grupo_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS salones (
    salon_id VARCHAR(50) PRIMARY KEY,
    capacidad INT NOT NULL DEFAULT 0,
    tipo VARCHAR(50) NOT NULL DEFAULT 'Normal'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS horarios (
    horario_id INT AUTO_INCREMENT PRIMARY KEY,
    asignacion_id INT NOT NULL,
    salon_id VARCHAR(50) NOT NULL,
    dia VARCHAR(15) NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    FOREIGN KEY (asignacion_id) REFERENCES asignaciones(asignacion_id) ON DELETE CASCADE,
    FOREIGN KEY (salon_id) REFERENCES salones(salon_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS semestres (
    id_semestre INT PRIMARY KEY,
    nombre VARCHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ==================== DATOS INICIALES ====================

INSERT IGNORE INTO semestres (id_semestre, nombre) VALUES
(1, 'Primer Semestre'),
(2, 'Segundo Semestre'),
(3, 'Tercer Semestre'),
(4, 'Cuarto Semestre'),
(5, 'Quinto Semestre'),
(6, 'Sexto Semestre'),
(7, 'Séptimo Semestre'),
(8, 'Octavo Semestre'),
(9, 'Noveno Semestre'),
(10, 'Décimo Semestre');

SELECT 'BD bd_seso creada correctamente.' AS resultado;
