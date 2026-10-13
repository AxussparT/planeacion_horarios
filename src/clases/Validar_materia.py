from src.conexion import get_conexion
from tkinter import messagebox
import sqlite3

def validar_y_registrar_materia(clave, nombre, horas_semana, semestre, tipo):
    print(f"Iniciando registro/actualización para: {clave} - {nombre} (Tipo: {tipo})...")

    clave = str(clave).strip().upper()
    nombre = str(nombre).strip().upper()
    horas_str = str(horas_semana).strip()
    tipo = str(tipo).strip().upper()
    
    semestre_str = str(semestre or "").strip()
    if semestre_str and (
        not semestre_str.isascii()
        or not semestre_str.isdigit()
        or len(semestre_str) > 2
    ):
        messagebox.showerror("Error de Datos", "El semestre debe ser un número entero de hasta 2 dígitos.")
        return False
    semestre_id = int(semestre_str) if semestre_str else None
    
    if not clave or not nombre or not tipo:
        messagebox.showerror("Error de Datos", "La clave, el nombre y el tipo de materia son obligatorios.")
        return False
    
    if len(clave) > 20 or len(nombre) > 255 or len(tipo) > 50:
        messagebox.showerror("Error de Datos", "La clave admite hasta 20 caracteres, el nombre hasta 255 y el tipo hasta 50.")
        return False
    if not horas_str.isascii() or not horas_str.isdigit() or len(horas_str) > 2:
        messagebox.showerror("Error de Datos", "Las horas semanales deben ser un número entero de hasta 2 dígitos.")
        return False

    from src.conexion import obtener_cursor
    with obtener_cursor() as ctx:
        if ctx is None:
            messagebox.showerror("Error de Conexión", "No se pudo conectar a la base de datos.")
            return False
        cur, conn = ctx
        
        try:
            sql_check = "SELECT nombre FROM materias WHERE materia_id = %s"
            cur.execute(sql_check, (clave,))
            resultado = cur.fetchone()
            
            if resultado:
                nombre_db = resultado[0]
                mensaje = (
                    f"La materia con clave '{clave}' ya existe.\n\n"
                    f"Nombre actual: {nombre_db}\n"
                    f"Nombre nuevo: {nombre}\n\n"
                    f"¿Desea actualizar TODOS los datos (incluyendo el tipo: {tipo})?"
                )
                if messagebox.askyesno("Materia Existente", mensaje):
                    sql_update = """
                        UPDATE materias SET nombre=%s, horas_semana=%s, semestre_id=%s, tipo=%s
                        WHERE materia_id=%s
                    """
                    cur.execute(sql_update, (nombre, horas_str, semestre_id, tipo, clave))
                    messagebox.showinfo("Éxito", f"Materia '{clave}' actualizada correctamente.")
                    return True
                else:
                    messagebox.showinfo("Cancelado", "No se realizaron cambios.")
                    return False
            else:
                sql_insert = """
                    INSERT INTO materias (materia_id, nombre, horas_semana, semestre_id, tipo)
                    VALUES (%s, %s, %s, %s, %s)
                """
                cur.execute(sql_insert, (clave, nombre, horas_str, semestre_id, tipo))
                messagebox.showinfo("Éxito", f"Materia '{nombre}' guardada correctamente.")
                return True
        
        except sqlite3.Error as err:
            conn.rollback()
            messagebox.showerror("Error BD", f"Error al procesar la materia: {err}")
            return False