import tkinter as tk
import os
import sys
from src.UI.ventana_principal import VentanaPrincipal

def ruta_recurso(relative_path):
    """ Obtiene la ruta absoluta al recurso, funciona para el modo de desarrollo y para el .exe """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

if __name__ == "__main__":
    root = tk.Tk()
    
    # --- CORRECCIÓN: El ícono se le asigna a 'root', no a 'app' ---
    try:
        # Asegúrate de que el nombre del archivo sea exactamente igual (respeta mayúsculas/minúsculas)
        ruta_icono = ruta_recurso('src/UI/logo ph.png') 
        icono = tk.PhotoImage(file=ruta_icono)
        root.iconphoto(True, icono)
    except Exception as e:
        print(f"No se pudo cargar el ícono: {e}")

    app = VentanaPrincipal(root)
    app.mostrar_datos_profesor()
    app.mostrar_datos_materias()
    app.mostrar_datos_salones()
    root.mainloop()