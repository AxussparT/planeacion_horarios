from src.conexion import get_conexion
from tkinter import messagebox
import mysql.connector
import re

def formatear_hora(hora_str):
    if not hora_str:
        return "00:00:00"
    hora_str = hora_str.strip()
    patron = re.match(r'^(\d{1,2}):(\d{2})$', hora_str)
    if patron:
        h, m = int(patron.group(1)), int(patron.group(2))
        return f"{h:02d}:{m:02d}:00"
    patron2 = re.match(r'^(\d{1,2}):(\d{2}):(\d{2})$', hora_str)
    if patron2:
        h, m, s = int(patron2.group(1)), int(patron2.group(2)), int(patron2.group(3))
        return f"{h:02d}:{m:02d}:{s:02d}"
    return hora_str

def _generar_profesor_id(cursor):
    cursor.execute("SELECT MAX(CAST(SUBSTRING(profesor_id, 2) AS UNSIGNED)) FROM profesores")
    max_id = cursor.fetchone()[0]
    next_num = (max_id if max_id else 0) + 1
    return f"P{next_num:04d}"

def validar_y_registrar_profesor(no_cuenta, nombre_completo, periodos):
    conexion = None
    cursor = None
    transaccion_exitosa = False

    try:
        conexion = get_conexion()
        if conexion is None:
            messagebox.showerror("Error de Conexión", "No se pudo establecer conexión con la base de datos.")
            return False
        cursor = conexion.cursor()

        # Buscar si ya existe un profesor con ese no_cuenta
        cursor.execute("SELECT profesor_id FROM profesores WHERE no_cuenta = %s", (no_cuenta,))
        existente = cursor.fetchone()

        if existente:
            profesor_id = existente[0]
            primer_periodo = periodos[0] if periodos else {}
            cursor.execute("""
                UPDATE profesores
                SET nombre = %s,
                    disponible_inicio = %s,
                    disponible_fin = %s,
                    dias_disponibles = %s
                WHERE profesor_id = %s
            """, (
                nombre_completo,
                formatear_hora(primer_periodo.get('hora_inicio', '')),
                formatear_hora(primer_periodo.get('hora_fin', '')),
                primer_periodo.get('dias', ''),
                profesor_id
            ))

            cursor.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id = %s", (profesor_id,))
            sql_insert_disp = """INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin)
                                 VALUES (%s, %s, %s, %s)"""
            for periodo in periodos:
                dias_str = periodo.get('dias', '')
                hora_i = formatear_hora(periodo.get('hora_inicio', ''))
                hora_f = formatear_hora(periodo.get('hora_fin', ''))
                for dia in [d.strip() for d in dias_str.split(',') if d.strip()]:
                    cursor.execute(sql_insert_disp, (profesor_id, dia, hora_i, hora_f))

            messagebox.showinfo("Actualización Exitosa",
                f"Profesor '{nombre_completo}' actualizado correctamente.")
            transaccion_exitosa = True
            return True
        else:
            profesor_id = _generar_profesor_id(cursor)
            primer_periodo = periodos[0] if periodos else {}
            cursor.execute("""
                INSERT INTO profesores (profesor_id, no_cuenta, nombre, disponible_inicio, disponible_fin, dias_disponibles, en_linea)
                VALUES (%s, %s, %s, %s, %s, %s, 'NO')
            """, (
                profesor_id, no_cuenta, nombre_completo,
                formatear_hora(primer_periodo.get('hora_inicio', '')),
                formatear_hora(primer_periodo.get('hora_fin', '')),
                primer_periodo.get('dias', '')
            ))

            sql_insert_disp = """INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin)
                                 VALUES (%s, %s, %s, %s)"""
            for periodo in periodos:
                dias_str = periodo.get('dias', '')
                hora_i = formatear_hora(periodo.get('hora_inicio', ''))
                hora_f = formatear_hora(periodo.get('hora_fin', ''))
                for dia in [d.strip() for d in dias_str.split(',') if d.strip()]:
                    cursor.execute(sql_insert_disp, (profesor_id, dia, hora_i, hora_f))

            messagebox.showinfo("Éxito", f"Profesor '{nombre_completo}' guardado con ID '{profesor_id}'.")
            transaccion_exitosa = True
            return True

    except mysql.connector.Error as err:
        messagebox.showerror("Error de BD", f"Error al procesar los datos del profesor: {err}")
        return False

    finally:
        if transaccion_exitosa and conexion is not None:
            conexion.commit()
        if cursor is not None:
            cursor.close()
        if conexion is not None and conexion.is_connected():
            conexion.close()
