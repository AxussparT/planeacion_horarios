from src.conexion import obtener_cursor
from tkinter import messagebox
import sqlite3

class grupo:
    def __init__(self, grupo_id, nivel):
        self.grupo_id = str(grupo_id).strip().upper()
        self.nivel = str(nivel).strip()
        self.exito = False

        if not self.grupo_id or len(self.grupo_id) > 20:
            messagebox.showerror("Error de Datos", "El grupo es obligatorio y debe tener hasta 20 caracteres.")
            return

        if (
            not self.nivel.isascii()
            or not self.nivel.isdigit()
            or len(self.nivel) > 2
        ):
            messagebox.showerror("Error de Datos", "El semestre debe ser un número entero de hasta 2 dígitos.")
            return

        self.exito = self.procesar_datos()

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
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"Error al guardar el grupo: {err}")
                return False
