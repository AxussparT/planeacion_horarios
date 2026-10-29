from src.conexion import get_conexion
from tkinter import messagebox
import sqlite3
import unicodedata

def normalizar_tipo(tipo):
    if not tipo:
        return 'NORMAL'
    t = ''.join(ch for ch in unicodedata.normalize('NFD', str(tipo)) if unicodedata.category(ch) != 'Mn').upper()
    if 'TEC' in t or 'COMPUT' in t:
        return 'TECNOLOGICA'
    if 'LAB' in t:
        return 'LABORATORIO'
    if 'AUD' in t:
        return 'AUDITORIO'
    return 'NORMAL'

class salon:
    def __init__(self, numero_aula, capacidad, tipo):
        self.numero_aula = str(numero_aula).strip().upper()
        self.capacidad = str(capacidad).strip()
        self.tipo = normalizar_tipo(tipo)
        self.exito = False

        if not self.numero_aula or len(self.numero_aula) > 4:
            messagebox.showerror("Error de Datos", "El número de aula es obligatorio y debe tener hasta 4 caracteres.")
            return
        if (
            not self.capacidad.isascii()
            or not self.capacidad.isdigit()
            or len(self.capacidad) > 3
        ):
            messagebox.showerror("Error de Datos", "La capacidad debe ser un número entero de hasta 3 dígitos.")
            return
        if not self.tipo or len(self.tipo) > 50:
            messagebox.showerror("Error de Datos", "El tipo de salón es obligatorio y no puede exceder 50 caracteres.")
            return
        
        self.exito = self.procesar_datos()
        
    def procesar_datos(self):
        from src.conexion import obtener_cursor
        with obtener_cursor() as ctx:
            if ctx is None:
                return False
            cur, conn = ctx
            try:
                sql = "INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, %s, %s)"
                cur.execute(sql, (self.numero_aula, self.capacidad, self.tipo))
                messagebox.showinfo("Éxito", f"Salón '{self.numero_aula}' guardado correctamente.")
                return True
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"Error al guardar el salón: {err}")
                return False
