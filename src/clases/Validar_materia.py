from src.conexion import get_conexion
from tkinter import messagebox
import mysql.connector

def validar_y_registrar_materia(clave, nombre, horas_semana, semestre, tipo):
    """
    Función que maneja la lógica de validación, INSERT y UPDATE para materias.
    Ahora incluye el campo 'tipo' (Normal, Tecnológica, Laboratorio).
    """
    print(f"Iniciando registro/actualización para: {clave} - {nombre} (Tipo: {tipo})...")
    conexion = None 
    cursor = None
    transaccion_exitosa = False

    # Prepara y limpia las variables de entrada
    clave = str(clave).strip()
    nombre = str(nombre).strip()
    horas_semana_str = str(horas_semana).strip()
    tipo = str(tipo).strip() # Limpiamos el nuevo campo
    
    # Asigna el ID del semestre o None si el valor no es un dígito
    semestre_id = int(semestre) if str(semestre).strip().isdigit() else None
    
    # Validación simple de campos obligatorios
    if not clave or not nombre or not tipo:
        messagebox.showerror("Error de Datos", "La clave, el nombre y el tipo de materia son obligatorios.")
        return False

    try:
        conexion = get_conexion() 
        if conexion is None:
            messagebox.showerror("Error de Conexión", "No se pudo establecer conexión con la base de datos.")
            return False

        cursor = conexion.cursor()
        
        # 1. BÚSQUEDA: Verificar si la materia ya existe usando la clave
        sql_check = "SELECT nombre FROM materias WHERE materia_id = %s"
        cursor.execute(sql_check, (clave,))
        resultado = cursor.fetchone()
        
        if resultado:
            # --- Materia YA existe: Preguntar para actualizar ---
            nombre_db = resultado[0]
            
            mensaje_confirmacion = (
                f"La materia con clave '{clave}' ya existe.\n\n"
                f"Nombre actual: {nombre_db}\n"
                f"Nombre nuevo: {nombre}\n\n"
                f"¿Desea actualizar TODOS los datos (incluyendo el tipo: {tipo})?"
            )
            
            if messagebox.askyesno("Materia Existente", mensaje_confirmacion):
                # ACTUALIZACIÓN: Incluimos el campo 'tipo'
                sql_update = """
                    UPDATE materias 
                    SET nombre = %s,
                        horas_semana = %s,
                        semestre_id = %s,
                        tipo = %s
                    WHERE materia_id = %s
                """
                # Los valores en el orden correcto para el SQL anterior
                valores_update = (nombre, horas_semana_str, semestre_id, tipo, clave) 
                
                cursor.execute(sql_update, valores_update)
                messagebox.showinfo("Actualización Exitosa", f"Materia '{clave}' actualizada correctamente.")
                transaccion_exitosa = True
                return True
            else:
                messagebox.showinfo("Actualización Cancelada", "No se realizaron cambios.")
                return True

        else:
            # --- Materia NO existe: Insertar nuevo registro con 'tipo' ---
            sql_insert = """
                INSERT INTO materias (materia_id, nombre, horas_semana, semestre_id, tipo) 
                VALUES (%s, %s, %s, %s, %s)
            """
            valores_insert = (clave, nombre, horas_semana_str, semestre_id, tipo)
            
            cursor.execute(sql_insert, valores_insert)
            
            messagebox.showinfo("Éxito", f"Materia '{nombre}' guardada correctamente.")
            transaccion_exitosa = True
            return True

    except mysql.connector.Error as err:
        messagebox.showerror("Error de BD", f"Error al procesar la materia: {err}")
        return False
            
    finally:
        if transaccion_exitosa and conexion is not None:
            conexion.commit()
            print("Transacción finalizada con COMMIT.")
        
        if cursor is not None:
            cursor.close()
        if conexion is not None and conexion.is_connected():
            conexion.close()