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

def validar_y_registrar_profesor(cuenta, nombre_completo, periodos, linea):
    conexion = None
    cursor = None
    transaccion_exitosa = False
    if isinstance(linea, str):
        esta_en_linea_nuevo = (linea.strip().lower() == "sí")
    else:
        esta_en_linea_nuevo = bool(linea)
    linea_para_bd_enum = 'SI' if esta_en_linea_nuevo else 'NO'

    try:
        conexion = get_conexion()
        if conexion is None:
            messagebox.showerror("Error de Conexión", "No se pudo establecer conexión con la base de datos.")
            return False
        cursor = conexion.cursor()

        sql_check = "SELECT en_linea FROM profesores WHERE profesor_id = %s"
        cursor.execute(sql_check, (cuenta,))
        resultado = cursor.fetchone()

        if resultado:
            en_linea_db = resultado[0]
            esta_en_linea_db = (en_linea_db == 'SI')

            estado_actual = "Línea/Presencial" if esta_en_linea_db else "Solo Presencial"
            estado_nuevo = "Línea/Presencial" if esta_en_linea_nuevo else "Solo Presencial"

            primer_periodo = periodos[0] if periodos else {}
            sql_update_base = """
                UPDATE profesores
                SET nombre = %s,
                    disponible_inicio = %s,
                    disponible_fin = %s,
                    dias_disponibles = %s,
                    en_linea = %s
                WHERE profesor_id = %s
            """
            cursor.execute(sql_update_base, (
                nombre_completo,
                formatear_hora(primer_periodo.get('hora_inicio', '')),
                formatear_hora(primer_periodo.get('hora_fin', '')),
                primer_periodo.get('dias', ''),
                linea_para_bd_enum, cuenta
            ))

            cursor.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id = %s", (cuenta,))
            sql_insert_disp = """INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin)
                                 VALUES (%s, %s, %s, %s)"""
            for periodo in periodos:
                dias_str = periodo.get('dias', '')
                hora_i = formatear_hora(periodo.get('hora_inicio', ''))
                hora_f = formatear_hora(periodo.get('hora_fin', ''))
                for dia in [d.strip() for d in dias_str.split(',') if d.strip()]:
                    cursor.execute(sql_insert_disp, (cuenta, dia, hora_i, hora_f))

            if esta_en_linea_db and esta_en_linea_nuevo:
                messagebox.showinfo("Actualización Exitosa",
                    f"Profesor '{cuenta}' actualizado. Queda: {estado_nuevo}. Periodos y horarios modificados.")
            else:
                messagebox.showinfo("Actualización Exitosa",
                    f"Profesor '{cuenta}' actualizado a {estado_nuevo}. Periodos y horarios sincronizados.")
            transaccion_exitosa = True
            return True
        else:
            primer_periodo = periodos[0] if periodos else {}
            sql_insert = """INSERT INTO profesores (profesor_id, nombre, disponible_inicio, disponible_fin, dias_disponibles, en_linea)
                            VALUES (%s, %s, %s, %s, %s, %s)"""
            cursor.execute(sql_insert, (
                cuenta, nombre_completo,
                formatear_hora(primer_periodo.get('hora_inicio', '')),
                formatear_hora(primer_periodo.get('hora_fin', '')),
                primer_periodo.get('dias', ''),
                linea_para_bd_enum
            ))

            sql_insert_disp = """INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin)
                                 VALUES (%s, %s, %s, %s)"""
            for periodo in periodos:
                dias_str = periodo.get('dias', '')
                hora_i = formatear_hora(periodo.get('hora_inicio', ''))
                hora_f = formatear_hora(periodo.get('hora_fin', ''))
                for dia in [d.strip() for d in dias_str.split(',') if d.strip()]:
                    cursor.execute(sql_insert_disp, (cuenta, dia, hora_i, hora_f))

            estado_linea = "Línea/Presencial" if esta_en_linea_nuevo else "Solo Presencial"
            messagebox.showinfo("Éxito", f"Profesor '{cuenta}' guardado correctamente como **{estado_linea}**.")
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
