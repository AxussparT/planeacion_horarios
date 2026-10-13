import os
import sys
import tkinter as tk
from tkinter import messagebox

from src.conexion import get_conexion


def ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


def main():
    root = tk.Tk()
    try:
        icono = tk.PhotoImage(file=ruta_recurso("src/UI/SAGA.png"))
        root.iconphoto(True, icono)
    except (OSError, tk.TclError) as err:
        print(f"No se pudo cargar el ícono: {err}")

    conn = get_conexion()
    if conn is None:
        messagebox.showerror(
            "Error de Base de Datos",
            "No se pudo crear o abrir la base de datos SQLite local."
        )
        root.destroy()
        return
    conn.close()

    from src.UI.ventana_principal import VentanaPrincipal

    app = VentanaPrincipal(root)
    app.mostrar_datos_profesor()
    app.mostrar_datos_materias()
    app.mostrar_datos_salones()
    app.mostrar_datos_grupos()
    root.mainloop()


if __name__ == "__main__":
    main()
