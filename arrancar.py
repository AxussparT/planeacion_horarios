import tkinter as tk
from tkinter import ttk, messagebox
import os
import sys
from src.conexion import get_conexion, guardar_config, _ruta_usuario

def ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

def _config_existe():
    return os.path.exists(_ruta_usuario("config.json"))

class SetupDialog:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Configuración de Base de Datos")
        self.root.geometry("480x350")
        self.root.resizable(False, False)
        try:
            ruta_icono = ruta_recurso('src/UI/SAGA.png')
            icono = tk.PhotoImage(file=ruta_icono)
            self.root.iconphoto(True, icono)
        except Exception:
            pass

        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text="Configuración de conexión MySQL",
                  font=('Arial', 14, 'bold')).pack(pady=(0, 15))
        ttk.Label(frame, text="Ingresa los datos del servidor MySQL remoto:",
                  font=('Arial', 10)).pack(pady=(0, 15))

        campos = ttk.Frame(frame)
        campos.pack()

        ttk.Label(campos, text="Host:").grid(row=0, column=0, sticky='w', pady=4, padx=(0, 8))
        self.host = ttk.Entry(campos, width=30)
        self.host.insert(0, "localhost")
        self.host.grid(row=0, column=1, pady=4)

        ttk.Label(campos, text="Puerto:").grid(row=1, column=0, sticky='w', pady=4, padx=(0, 8))
        self.port = ttk.Entry(campos, width=30)
        self.port.insert(0, "3306")
        self.port.grid(row=1, column=1, pady=4)

        ttk.Label(campos, text="Usuario:").grid(row=2, column=0, sticky='w', pady=4, padx=(0, 8))
        self.user = ttk.Entry(campos, width=30)
        self.user.insert(0, "root")
        self.user.grid(row=2, column=1, pady=4)

        ttk.Label(campos, text="Contraseña:").grid(row=3, column=0, sticky='w', pady=4, padx=(0, 8))
        self.password = ttk.Entry(campos, width=30, show="*")
        self.password.grid(row=3, column=1, pady=4)

        ttk.Label(campos, text="Base de datos:").grid(row=4, column=0, sticky='w', pady=4, padx=(0, 8))
        self.database = ttk.Entry(campos, width=30)
        self.database.insert(0, "bd_seso")
        self.database.grid(row=4, column=1, pady=4)

        ttk.Label(frame, text="", font=('Arial', 8)).pack()
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Probar conexión", command=self._probar).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Guardar y continuar", command=self._guardar).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Salir", command=self.root.destroy).pack(side='left', padx=5)

        self.resultado = False
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self.root.mainloop()

    def _probar(self):
        import mysql.connector
        try:
            conn = mysql.connector.connect(
                host=self.host.get().strip(),
                port=self.port.get().strip(),
                user=self.user.get().strip(),
                password=self.password.get(),
                database=self.database.get().strip(),
                connect_timeout=5
            )
            conn.close()
            messagebox.showinfo("Éxito", "Conexión exitosa a la base de datos.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo conectar:\n{e}")

    def _guardar(self):
        host = self.host.get().strip()
        port = self.port.get().strip()
        user = self.user.get().strip()
        password = self.password.get()
        database = self.database.get().strip()
        if not host or not port or not user or not database:
            messagebox.showerror("Error", "Todos los campos son obligatorios (contraseña opcional).")
            return
        if guardar_config(host, port, user, password, database):
            self.resultado = True
            self.root.destroy()

if __name__ == "__main__":
    if not _config_existe():
        dialogo = SetupDialog()
        if not dialogo.resultado:
            sys.exit(0)

    root = tk.Tk()
    try:
        ruta_icono = ruta_recurso('src/UI/SAGA.png')
        icono = tk.PhotoImage(file=ruta_icono)
        root.iconphoto(True, icono)
    except Exception as e:
        print(f"No se pudo cargar el ícono: {e}")

    conn = get_conexion()
    if conn is None:
        messagebox.showerror("Error de Conexión",
            "No se pudo conectar a la base de datos.\n"
            "Verifica la configuración en config.json o elimina el archivo para reconfigurar.")
        root.destroy()
        sys.exit(1)
    conn.close()

    from src.UI.ventana_principal import VentanaPrincipal
    app = VentanaPrincipal(root)
    app.mostrar_datos_profesor()
    app.mostrar_datos_materias()
    app.mostrar_datos_salones()
    app.mostrar_datos_grupos()
    root.mainloop()
