from src.conexion import get_conexion
from tkinter import messagebox
import mysql.connector

def validar_y_registrar_profesor(cuenta, nombre_completo, dias, hora_entrada, hora_salida, linea):
    """
    Función que maneja toda la lógica de negocio (validación, INSERT y UPDATE)
    para el registro de profesores.
    """
    print("Iniciando validación y registro de datos del profesor...")
    conexion = None 
    cursor = None
    transaccion_exitosa = False
    if isinstance(linea, str):
        esta_en_linea_nuevo = (linea.strip().lower() == "sí") 
    else:
        esta_en_linea_nuevo = bool(linea)
    linea_para_bd_enum = 'SI' if esta_en_linea_nuevo else 'NO'
    dias = str(dias) if dias is not None else ""
    
    try:
        conexion = get_conexion() 
        if conexion is None:
            messagebox.showerror("Error de Conexión", "No se pudo establecer conexión con la base de datos.")
            return False
        cursor = conexion.cursor()
        
        sql_check = "SELECT en_linea, dias_disponibles FROM profesores WHERE profesor_id = %s"
        cursor.execute(sql_check, (cuenta,))
        resultado = cursor.fetchone()
          
        if resultado:
            en_linea_db = resultado[0]
            dias_db = resultado[1] 
            esta_en_linea_db = (en_linea_db == 'SI') 
            
            sql_update_base = """
                UPDATE profesores 
                SET nombre = %s,
                    disponible_inicio = %s,
                    disponible_fin = %s,
                    dias_disponibles = %s,
                    en_linea = %s
                WHERE profesor_id = %s
            """
            
            estado_actual = "Línea/Presencial" if esta_en_linea_db else "Solo Presencial"
            estado_nuevo = "Línea/Presencial" if esta_en_linea_nuevo else "Solo Presencial"

            # -----------------------------------------------------------
            # CASO A
            # -----------------------------------------------------------
            if esta_en_linea_db:
                
                if esta_en_linea_nuevo:
                    messagebox.showwarning("Advertencia", 
                        f"El profesor con cuenta '{cuenta}' ya estaba como **{estado_actual}**.\nSe actualizarán días, horas y disponibilidad. (Queda: **{estado_nuevo}**)."
                    )
                    
                else: 
                    messagebox.showinfo("Actualización", 
                        f"El profesor '{cuenta}' ya estaba como **{estado_actual}**.\nSe actualizará a **{estado_nuevo}** y se reemplazarán los días y horas."
                    )

                #se dejo solo esta line de valores_update simplificar
                valores_update = (nombre_completo, hora_entrada, hora_salida, dias, linea_para_bd_enum, cuenta)
                cursor.execute(sql_update_base, valores_update)
                messagebox.showinfo("Actualización Exitosa", f"Profesor '{cuenta}' Actualizado. Queda: {estado_nuevo}. Días y horarios modificados.")
                transaccion_exitosa = True
                return True


            # -----------------------------------------------------------
            # CASO B (El profesor NO estaba en línea originalmente)
            # -----------------------------------------------------------
            elif not esta_en_linea_db:
                
                if esta_en_linea_nuevo:
                    messagebox.showinfo("Actualización", 
                        f"El profesor '{cuenta}' ya está en formato {estado_actual}.\nSe actualizará a disponible en {estado_nuevo} y se reemplazarán los datos."
                    )
                else: 
                    messagebox.showwarning("Actualización", 
                        f"El profesor con cuenta '{cuenta}' ya está registrado en formato {estado_actual}.\nSe actualizarán los días y horarios. (Sigue: {estado_nuevo})."
                    )

                # Definimos los valores una sola vez incluyendo el nombre_completo
                valores_update = (nombre_completo, hora_entrada, hora_salida, dias, linea_para_bd_enum, cuenta)
                
                # Ejecutamos la actualización
                cursor.execute(sql_update_base, valores_update)
                
                messagebox.showinfo("Actualización Exitosa", f"Profesor '{cuenta}' actualizado. Datos de nombre y horarios sincronizados.")
                transaccion_exitosa = True
                return True
            
            # -----------------------------------------------------------
            # CASO C: El profesor NO existe (Alta nueva)
            # -----------------------------------------------------------
        else:
            sql_insert = "INSERT INTO profesores (profesor_id, nombre, disponible_inicio, disponible_fin, dias_disponibles, en_linea) VALUES (%s, %s, %s, %s, %s, %s)"
            valores_insert = (cuenta, nombre_completo, hora_entrada, hora_salida, dias, linea_para_bd_enum)
            
            cursor.execute(sql_insert, valores_insert)
            
            estado_linea = "Línea/Presencial" if esta_en_linea_nuevo else "Solo Presencial"
            messagebox.showinfo("Éxito", f"Profesor con el número de cuenta '{cuenta}' guardado correctamente como **{estado_linea}**.")
            transaccion_exitosa = True
            return True

    except mysql.connector.Error as err:
        messagebox.showerror("Error de BD", f"Error al procesar los datos del profesor: {err}")
        return False
            
    finally:
        if transaccion_exitosa and conexion is not None:
            conexion.commit()
            print("Transacción finalizada con COMMIT.")
        
        if cursor is not None:
            cursor.close()
        if conexion is not None and conexion.is_connected():
            conexion.close()
            print("Conexión cerrada.")
