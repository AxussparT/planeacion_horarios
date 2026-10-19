# -*- coding: utf-8 -*-
"""
Módulo de Gestión de Puntos de Restauración y Respaldo Rápido (SAGA 2.0)
Permite capturar instantáneas (snapshots) completas de asignaciones y horarios
para poder deshacer (rollback) cambios masivos o reacomodos con un solo clic.
"""

import datetime
import sqlite3
from src.conexion import obtener_cursor, obtener_cursor_dict

class GestorRestauracion:
    @classmethod
    def inicializar_tablas(cls):
        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            cur.execute("""
                CREATE TABLE IF NOT EXISTS puntos_restauracion (
                    punto_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    descripcion TEXT,
                    fecha_creacion TEXT NOT NULL,
                    total_asignaciones INTEGER DEFAULT 0,
                    total_horarios INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS snapshot_asignaciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    punto_id INTEGER NOT NULL,
                    asignacion_id INTEGER,
                    profesor_id TEXT,
                    materia_id TEXT,
                    grupo_id TEXT,
                    estado TEXT,
                    periodo TEXT,
                    hora_inicio TEXT,
                    hora_fin TEXT,
                    dias TEXT,
                    modalidad TEXT,
                    FOREIGN KEY (punto_id) REFERENCES puntos_restauracion(punto_id) ON DELETE CASCADE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS snapshot_horarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    punto_id INTEGER NOT NULL,
                    horario_id INTEGER,
                    asignacion_id INTEGER,
                    salon_id TEXT,
                    dia TEXT,
                    hora_inicio TEXT,
                    hora_fin TEXT,
                    FOREIGN KEY (punto_id) REFERENCES puntos_restauracion(punto_id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    @classmethod
    def crear_punto(cls, nombre=None, descripcion=""):
        cls.inicializar_tablas()
        ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not nombre:
            nombre = f"Respaldo {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}"

        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "No se pudo conectar a la base de datos."}
            cur, conn = ctx
            try:
                # Contar asignaciones y horarios actuales
                cur.execute("SELECT COUNT(*) FROM asignaciones WHERE (estado IS NULL OR estado != 'cancelada')")
                n_asig = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM horarios")
                n_hor = cur.fetchone()[0]

                # Insertar registro de snapshot
                cur.execute("""
                    INSERT INTO puntos_restauracion (nombre, descripcion, fecha_creacion, total_asignaciones, total_horarios)
                    VALUES (%s, %s, %s, %s, %s)
                """, (nombre, descripcion, ahora, n_asig, n_hor))
                punto_id = cur.lastrowid

                # Copiar asignaciones actuales
                cur.execute("""
                    INSERT INTO snapshot_asignaciones (
                        punto_id, asignacion_id, profesor_id, materia_id, grupo_id,
                        estado, periodo, hora_inicio, hora_fin, dias, modalidad
                    )
                    SELECT %s, asignacion_id, profesor_id, materia_id, grupo_id,
                           estado, periodo, hora_inicio, hora_fin, dias, modalidad
                    FROM asignaciones
                """, (punto_id,))

                # Copiar horarios actuales
                cur.execute("""
                    INSERT INTO snapshot_horarios (
                        punto_id, horario_id, asignacion_id, salon_id, dia, hora_inicio, hora_fin
                    )
                    SELECT %s, horario_id, asignacion_id, salon_id, dia, hora_inicio, hora_fin
                    FROM horarios
                """, (punto_id,))

                conn.commit()
                return {
                    "exito": True,
                    "punto_id": punto_id,
                    "nombre": nombre,
                    "fecha": ahora,
                    "total_asignaciones": n_asig,
                    "total_horarios": n_hor
                }
            except sqlite3.Error as err:
                conn.rollback()
                return {"exito": False, "mensaje": f"Error al crear punto de restauración: {err}"}

    @classmethod
    def listar_puntos(cls):
        cls.inicializar_tablas()
        with obtener_cursor_dict() as ctx:
            if not ctx:
                return []
            cur, conn = ctx
            cur.execute("""
                SELECT punto_id, nombre, descripcion, fecha_creacion, total_asignaciones, total_horarios
                FROM puntos_restauracion
                ORDER BY punto_id DESC
            """)
            return cur.fetchall()

    @classmethod
    def restaurar_punto(cls, punto_id):
        cls.inicializar_tablas()
        with obtener_cursor() as ctx:
            if not ctx:
                return {"exito": False, "mensaje": "No se pudo conectar a la base de datos."}
            cur, conn = ctx
            try:
                # Verificar existencia del snapshot
                cur.execute("SELECT nombre, fecha_creacion, total_asignaciones, total_horarios FROM puntos_restauracion WHERE punto_id = %s", (punto_id,))
                row = cur.fetchone()
                if not row:
                    return {"exito": False, "mensaje": "El punto de restauración seleccionado no existe."}
                nom, fecha, n_asig, n_hor = row

                # Crear un punto de seguridad previo al rollback por si el usuario desea revertir
                cls.crear_punto(nombre=f"Auto-respaldo antes de restaurar '{nom}'", descripcion="Creado automáticamente antes de rollback")

                # Vaciar asignaciones y horarios actuales
                cur.execute("DELETE FROM horarios")
                cur.execute("DELETE FROM asignaciones")

                # Restaurar asignaciones
                cur.execute("""
                    INSERT INTO asignaciones (
                        asignacion_id, profesor_id, materia_id, grupo_id,
                        estado, periodo, hora_inicio, hora_fin, dias, modalidad
                    )
                    SELECT asignacion_id, profesor_id, materia_id, grupo_id,
                           estado, periodo, hora_inicio, hora_fin, dias, modalidad
                    FROM snapshot_asignaciones
                    WHERE punto_id = %s
                """, (punto_id,))

                # Restaurar horarios
                cur.execute("""
                    INSERT INTO horarios (
                        horario_id, asignacion_id, salon_id, dia, hora_inicio, hora_fin
                    )
                    SELECT horario_id, asignacion_id, salon_id, dia, hora_inicio, hora_fin
                    FROM snapshot_horarios
                    WHERE punto_id = %s
                """, (punto_id,))

                conn.commit()
                return {
                    "exito": True,
                    "nombre": nom,
                    "fecha": fecha,
                    "total_asignaciones": n_asig,
                    "total_horarios": n_hor
                }
            except sqlite3.Error as err:
                conn.rollback()
                return {"exito": False, "mensaje": f"Error al restaurar punto: {err}"}

    @classmethod
    def eliminar_punto(cls, punto_id):
        with obtener_cursor() as ctx:
            if not ctx:
                return False
            cur, conn = ctx
            try:
                cur.execute("DELETE FROM snapshot_horarios WHERE punto_id = %s", (punto_id,))
                cur.execute("DELETE FROM snapshot_asignaciones WHERE punto_id = %s", (punto_id,))
                cur.execute("DELETE FROM puntos_restauracion WHERE punto_id = %s", (punto_id,))
                conn.commit()
                return True
            except sqlite3.Error:
                conn.rollback()
                return False
