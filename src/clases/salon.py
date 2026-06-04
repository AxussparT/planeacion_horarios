from src.conexion import get_conexion
from tkinter import messagebox
import mysql.connector

class salon:
    def __init__(self, numero_aula, capacidad, tipo):
        self.numero_aula = str(numero_aula).strip()
        self.capacidad = str(capacidad).strip()
        self.tipo = str(tipo).strip()
        
        if not self.capacidad.isdigit():
            messagebox.showerror("Error de Datos", "La capacidad debe ser un número válido.")
            return
        
        if not self.numero_aula:
            messagebox.showerror("Error de Datos", "El número de aula es obligatorio.")
            return
        
        self.procesar_datos()
        
    def procesar_datos(self):
        from src.conexion import obtener_cursor
        with obtener_cursor() as ctx:
            if ctx is None:
                return False
            cur, conn = ctx
            try:
                sql = "INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, %s, %s)"
                cur.execute(sql, (self.numero_aula, self.capacidad, self.tipo))
                messagebox.showinfo("Éxito", f"Salón '{self.numero_aula}' guardado correctamente")
                return True
            except mysql.connector.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"Error al guardar el salón: {err}")
                return False