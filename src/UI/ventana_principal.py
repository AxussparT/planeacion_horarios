import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import mysql.connector
from src.conexion import get_conexion
from tkinter import messagebox
from src.UI.ventana_gestion import VentanaGestion
from src.clases.validacion_bd import validar_y_registrar_profesor 
from src.clases.profesor import profesor 
from src.clases.materia import materia
from src.clases.salon import salon

class VentanaPrincipal:
    
    def __init__(self, master):
        self.master = master
        self.master.title("PLASEM - Sistema de Gestión")
        self.master.state('zoomed')
        
        # --- CACHÉ DE DATOS ---
        self.cache_profesores = []
        self.cache_materias = []
        self.cache_salones = []
        self._last_width = 0
        self._last_height = 0
        self.dias_seleccionados = ""
        
        # --- ESTILOS ---
        estilo = ttk.Style()
        estilo.theme_use('clam')
        estilo.configure('blue.TFrame', background='#0A0F1E')
        estilo.configure('Custom.TCheckbutton', font=('Roboto', 14), background='#0A0F1E', foreground='#ffffff')
        estilo.configure('Danger.TButton', font=('Roboto', 14, 'bold'), background='#6D583A', foreground='#000000', padding=10)
        estilo.configure('Treeview.Heading', font=('Roboto', 10, 'bold'), background='#2f4a23', foreground='#ffffff')
        estilo.configure('fondo.TLabel', background='#0A0F1E', foreground='#ffffff')
        
        # --- CARGA DE FONDO ---
        try:
            image = Image.open(r"assets/fondo.png")
            self.original_image = image
            self.background_label = tk.Label(self.master)
            self.background_label.place(x=0, y=0, relwidth=1, relheight=1)
            self.master.bind("<Configure>", self.redimensionar_fondo)
        except Exception as e:
            self.master.config(bg="grey")
        
        # --- CONTENEDOR PRINCIPAL CENTRADO ---
        # Este frame agrupa todo y se mantiene al centro de la pantalla
        self.frame_principal = ttk.Frame(self.master, borderwidth=0, relief="solid", style='blue.TFrame')
        frame_ancho = 1200
        frame_alto = 800
        self.frame_principal.place(relx=0.5, rely=0.5, anchor='center', width=frame_ancho, height=frame_alto)
        
        # Configuración de pesos para dividir 40% formularios y 60% tablas
        self.frame_principal.columnconfigure(0, weight=1) 
        self.frame_principal.columnconfigure(1, weight=2) 
        self.frame_principal.rowconfigure(0, weight=1)

        # --- SECCIÓN IZQUIERDA: FORMULARIOS (Con Scroll) ---
        self.canvas_izquierdo = tk.Canvas(self.frame_principal, highlightthickness=0, background='#0A0F1E')
        self.scrollbar_izquierdo = ttk.Scrollbar(self.frame_principal, orient="vertical", command=self.canvas_izquierdo.yview)
        self.frame_izquierdo_principal = ttk.Frame(self.canvas_izquierdo, style='blue.TFrame')
        
        self.frame_izquierdo_principal.bind(
            "<Configure>", lambda e: self.canvas_izquierdo.configure(scrollregion=self.canvas_izquierdo.bbox("all"))
        )
        self.canvas_izquierdo.create_window((0, 0), window=self.frame_izquierdo_principal, anchor="nw", width=400)
        self.canvas_izquierdo.configure(yscrollcommand=self.scrollbar_izquierdo.set)

        self.canvas_izquierdo.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.scrollbar_izquierdo.grid(row=0, column=0, sticky="nse")
        
        # --- WIDGETS DE FORMULARIO (Centrados con pack) ---
        ttk.Button(self.frame_izquierdo_principal, text="Abrir ventana gestión materias", command=self.abrir_ventana_gestion, style='Danger.TButton').pack(pady=10)

        ttk.Label(self.frame_izquierdo_principal, text="PROFESORES", font=("Roboto", 20, "bold"), style='fondo.TLabel').pack(pady=15)
        
        # Entradas Profesor
        self.crear_label_entry("No. Cuenta", "entry_no_cuenta")
        self.crear_label_entry("Nombre(s)", "entry_nombre")
        self.crear_label_entry("Apellidos", "entry_apellido")
        
        ttk.Label(self.frame_izquierdo_principal, text="¿En línea?:", style='fondo.TLabel').pack(pady=3)
        self.combo_linea = ttk.Combobox(self.frame_izquierdo_principal, width=25, font=("Roboto", 12), state='readonly')
        self.combo_linea['values'] = ("Sí", "No")
        self.combo_linea.pack(pady=5)
        
        ttk.Label(self.frame_izquierdo_principal, text="Horario (Inicio - Fin):", style='fondo.TLabel').pack(pady=3)
        f_h = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame'); f_h.pack()
        self.entry_horario_i = ttk.Entry(f_h, width=12, font=("Roboto", 12)); self.entry_horario_i.pack(side='left', padx=2)
        self.entry_horario_f = ttk.Entry(f_h, width=12, font=("Roboto", 12)); self.entry_horario_f.pack(side='left', padx=2)
        
        # Días
        ttk.Label(self.frame_izquierdo_principal, text="Días Disponibles:", style='fondo.TLabel').pack(pady=10)
        f_dias = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame'); f_dias.pack()
        self.vars_dias = {d: tk.IntVar() for d in ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]}
        for dia, var in self.vars_dias.items():
            ttk.Checkbutton(f_dias, text=dia, variable=var, style='Custom.TCheckbutton', command=self.actualizar_dias_string).pack(anchor='w', padx=50)

        # Botones de Acción
        f_btns = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame'); f_btns.pack(pady=20)
        ttk.Button(f_btns, text="Confirmar", command=self.evento_boton_profesores, style='Danger.TButton').pack(side='left', padx=10)
        ttk.Button(f_btns, text="Limpiar", command=self.limpiar_campos_profesor, style='Danger.TButton').pack(side='left', padx=10)

        ttk.Separator(self.frame_izquierdo_principal, orient='horizontal').pack(fill='x', pady=20)

        # MATERIAS
        ttk.Label(self.frame_izquierdo_principal, text="MATERIAS", font=("Roboto", 20, "bold"), style='fondo.TLabel').pack(pady=10)
        self.crear_label_entry("Clave Materia", "entry_materia_clave")
        self.crear_label_entry("Nombre Materia", "entry_materia_nom")
        self.crear_label_entry("Horas Semana", "entry_materia_horas")
        self.crear_label_entry("Semestre", "entry_materia_semestre")
        ttk.Button(self.frame_izquierdo_principal, text="Agregar Materia", command=self.evento_materias, style='Danger.TButton').pack(pady=10)

        # SALONES
        ttk.Separator(self.frame_izquierdo_principal, orient='horizontal').pack(fill='x', pady=20)
        self.crear_label_entry("Número de aula", "entry_num_aula")
        self.crear_label_entry("Capacidad", "entry_capacidad_aula")
        ttk.Label(self.frame_izquierdo_principal, text="Tipo de aula:", style='fondo.TLabel').pack()
        self.combo_tipo = ttk.Combobox(self.frame_izquierdo_principal, width=25, font=("Roboto", 12), state='readonly')
        self.combo_tipo['values'] = ("Normal", "Tecnológica", "Laboratorio")
        self.combo_tipo.pack(pady=5)
        ttk.Button(self.frame_izquierdo_principal, text="Agregar Salón", command=self.evento_Salones, style='Danger.TButton').pack(pady=10)

        # --- SECCIÓN DERECHA: TABLAS ---
        self.frame_derecho = ttk.Frame(self.frame_principal, style='blue.TFrame')
        self.frame_derecho.grid(row=0, column=1, sticky="nsew", padx=20, pady=10)

        # Profesores Almacenados
        self.sv_busqueda = tk.StringVar(); self.sv_busqueda.trace_add("write", lambda *a: self.filtrar_profesores())
        self.crear_seccion_tabla("Profesores Almacenados", "sv_busqueda", "tabla_profesores", 
                                 ('Cuenta', 'Profesor', 'Dias', 'Horario', 'En línea'))
        self.tabla_profesores.bind("<<TreeviewSelect>>", self.cargar_profesor_seleccionado)

        # Materias Almacenadas
        self.sv_busqueda_mat = tk.StringVar(); self.sv_busqueda_mat.trace_add("write", lambda *a: self.filtrar_materias())
        self.crear_seccion_tabla("Materias Almacenadas", "sv_busqueda_mat", "tabla_materias", 
                                 ('Clave', 'Nombre', 'Hrs/Sem', 'Semestre'))

        # Salones Almacenados
        self.crear_seccion_tabla("Salones Almacenados", None, "tabla_salones", ('Aula', 'Capacidad', 'Tipo'))

    # --- MÉTODOS DE APOYO UI ---
    def crear_label_entry(self, txt, attr):
        ttk.Label(self.frame_izquierdo_principal, text=txt, style='fondo.TLabel').pack()
        e = ttk.Entry(self.frame_izquierdo_principal, width=30, font=("Roboto", 12))
        e.pack(pady=5); setattr(self, attr, e)

    def crear_seccion_tabla(self, titulo, var_busq, attr_tabla, cols):
        ttk.Label(self.frame_derecho, text=titulo, font=("Roboto", 16, "bold"), style='fondo.TLabel').pack(pady=(15, 5))
        if var_busq:
            f = ttk.Frame(self.frame_derecho, style='blue.TFrame'); f.pack(fill='x')
            ttk.Label(f, text="Buscar:", style='fondo.TLabel').pack(side='left', padx=5)
            ttk.Entry(f, textvariable=getattr(self, var_busq), width=35).pack(side='left', padx=5)
        
        frame_t = ttk.Frame(self.frame_derecho); frame_t.pack(fill='both', expand=True, pady=5)
        t = ttk.Treeview(frame_t, columns=cols, show='headings', height=6)
        for c in cols: t.heading(c, text=c); t.column(c, width=100, anchor='center')
        t.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(frame_t, orient="vertical", command=t.yview); t.configure(yscroll=sb.set); sb.pack(side='right', fill='y')
        setattr(self, attr_tabla, t)

    # --- LÓGICA DE DATOS ---
    def actualizar_dias_string(self):
        sel = [d for d, v in self.vars_dias.items() if v.get() == 1]
        self.dias_seleccionados = ", ".join(sel)

    def limpiar_campos_profesor(self):
        self.entry_no_cuenta.config(state='normal')
        self.entry_no_cuenta.delete(0, tk.END)
        self.entry_nombre.delete(0, tk.END)
        self.entry_apellido.delete(0, tk.END)
        self.entry_horario_i.delete(0, tk.END)
        self.entry_horario_f.delete(0, tk.END)
        self.combo_linea.set("")
        for v in self.vars_dias.values(): v.set(0)
        self.dias_seleccionados = ""

    def cargar_profesor_seleccionado(self, event):
        item = self.tabla_profesores.focus()
        if not item: return
        v = self.tabla_profesores.item(item, "values")
        self.limpiar_campos_profesor()
        self.entry_no_cuenta.insert(0, v[0])
        self.entry_no_cuenta.config(state='readonly') # Bloqueo de ID para evitar duplicados
        
        nombres = v[1].split(" ")
        self.entry_nombre.insert(0, nombres[0])
        if len(nombres) > 1: self.entry_apellido.insert(0, " ".join(nombres[1:]))
        
        self.combo_linea.set("Sí" if v[4] == "SI" else "No")
        if "-" in v[3]:
            i, f = v[3].split("-"); self.entry_horario_i.insert(0, i); self.entry_horario_f.insert(0, f)
        for d in v[2].split(", "):
            if d in self.vars_dias: self.vars_dias[d].set(1)
        self.actualizar_dias_string()

    def evento_boton_profesores(self):
        self.entry_no_cuenta.config(state='normal')
        c = self.entry_no_cuenta.get()
        full_n = f"{self.entry_nombre.get()} {self.entry_apellido.get()}".strip()
        if validar_y_registrar_profesor(c, full_n, self.dias_seleccionados, self.entry_horario_i.get(), self.entry_horario_f.get(), self.combo_linea.get()):
            self.mostrar_datos_profesor()
            self.limpiar_campos_profesor()
            messagebox.showinfo("Éxito", "Profesor procesado correctamente.")

    def mostrar_datos_profesor(self):
        self.cache_profesores.clear()
        conn = get_conexion(); cur = conn.cursor()
        cur.execute("SELECT profesor_id, nombre, dias_disponibles, CONCAT(disponible_inicio,'-',disponible_fin), en_linea FROM profesores")
        self.cache_profesores = cur.fetchall(); conn.close()
        self.refrescar_tabla_prof(self.cache_profesores)

    def refrescar_tabla_prof(self, datos):
        self.tabla_profesores.delete(*self.tabla_profesores.get_children())
        for d in datos: self.tabla_profesores.insert("", "end", values=d)

    def filtrar_profesores(self):
        t = self.sv_busqueda.get().lower()
        f = [p for p in self.cache_profesores if t in p[0].lower() or t in p[1].lower()]
        self.refrescar_tabla_prof(f)

    def evento_materias(self):
        c = self.entry_materia_clave.get(); n = self.entry_materia_nom.get()
        h = self.entry_materia_horas.get(); s = self.entry_materia_semestre.get()
        if materia(c, n, h, s):
            self.mostrar_datos_materias()
            for e in [self.entry_materia_clave, self.entry_materia_nom, self.entry_materia_horas, self.entry_materia_semestre]: e.delete(0, tk.END)

    def mostrar_datos_materias(self):
        self.cache_materias.clear()
        conn = get_conexion(); cur = conn.cursor()
        cur.execute("SELECT materia_id, nombre, horas_semana, semestre_id FROM materias")
        self.cache_materias = cur.fetchall(); conn.close()
        self.refrescar_tabla_mat(self.cache_materias)

    def refrescar_tabla_mat(self, datos):
        self.tabla_materias.delete(*self.tabla_materias.get_children())
        for d in datos: self.tabla_materias.insert("", "end", values=d)

    def filtrar_materias(self):
        t = self.sv_busqueda_mat.get().lower()
        f = [m for m in self.cache_materias if t in str(m[0]).lower() or t in m[1].lower()]
        self.refrescar_tabla_mat(f)

    def evento_Salones(self):
        a, c, t = self.entry_num_aula.get(), self.entry_capacidad_aula.get(), self.combo_tipo.get()
        if salon(a, c, t):
            self.mostrar_datos_salones()
            self.entry_num_aula.delete(0, tk.END); self.entry_capacidad_aula.delete(0, tk.END); self.combo_tipo.set("")

    def mostrar_datos_salones(self):
        conn = get_conexion(); cur = conn.cursor()
        cur.execute("SELECT salon_id, capacidad, tipo FROM salones")
        res = cur.fetchall(); conn.close()
        self.tabla_salones.delete(*self.tabla_salones.get_children())
        for r in res: self.tabla_salones.insert("", "end", values=r)

    def abrir_ventana_gestion(self):
        VentanaGestion(self.master)

    def redimensionar_fondo(self, event):
        if event.widget is self.master:
            if event.width != self._last_width or event.height != self._last_height:
                self._last_width, self._last_height = event.width, event.height
                img = self.original_image.resize((event.width, event.height), Image.LANCZOS)
                self.bg_img = ImageTk.PhotoImage(img)
                self.background_label.config(image=self.bg_img)

if __name__ == "__main__":
    root = tk.Tk()
    app = VentanaPrincipal(root)
    app.mostrar_datos_profesor()
    app.mostrar_datos_materias()
    app.mostrar_datos_salones()
    root.mainloop()