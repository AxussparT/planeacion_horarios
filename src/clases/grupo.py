from src.conexion import obtener_cursor
from tkinter import messagebox
import mysql.connector

class grupo:
    def __init__(self, grupo_id, nivel):
        self.grupo_id = str(grupo_id).strip().upper()
        self.nivel = str(nivel).strip()

        if not self.grupo_id:
            messagebox.showerror("Error de Datos", "El grupo es obligatorio.")
            return

        if not self.nivel.isdigit():
            messagebox.showerror("Error de Datos", "El semestre debe ser un número válido.")
            return

        self.procesar_datos()

    def procesar_datos(self):
        with obtener_cursor() as ctx:
            if ctx is None:
                return False
            cur, conn = ctx
            try:
                cur.execute("SELECT grupo_id FROM grupos WHERE grupo_id = %s", (self.grupo_id,))
                if cur.fetchone():
                    cur.execute("UPDATE grupos SET nivel = %s WHERE grupo_id = %s", (self.nivel, self.grupo_id))
                    messagebox.showinfo("Éxito", f"Grupo '{self.grupo_id}' actualizado correctamente")
                else:
                    cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, %s)", (self.grupo_id, self.nivel))
                    messagebox.showinfo("Éxito", f"Grupo '{self.grupo_id}' guardado correctamente")
                return True
            except mysql.connector.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"Error al guardar el grupo: {err}")
                return False
