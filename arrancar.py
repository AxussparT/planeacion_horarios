import tkinter as tk
from src.UI.ventana_principal import VentanaPrincipal

if __name__ == "__main__":
    root = tk.Tk()
    app = VentanaPrincipal(root)
    app.mostrar_datos_profesor()
    app.mostrar_datos_materias()
    app.mostrar_datos_salones()
    root.mainloop()