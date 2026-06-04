import tkinter as tk
from tkinter import ttk, font
from PIL import Image, ImageTk
import mysql.connector
from src.conexion import get_conexion
from tkinter import messagebox
from src.UI.ventana_gestion import VentanaGestion
from src.clases.validacion_bd import validar_y_registrar_profesor 
from src.clases.profesor import profesor 
from src.clases.materia import materia
from src.clases.salon import salon 
import os
import sys

def ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base_path, relative_path)

#python -m src.UI.ventana_principal

class VentanaPrincipal:
    
    def __init__(self, master):
        self.master = master
        self.master.title("PLASEM - Control de Personal")
        self.master.state('zoomed')
        
        self.cache_profesores = []
        self.cache_materias = []
        self.cache_salones = []
        self._last_width = 0
        self._last_height = 0
        self._scale_factor = 1.0
        self.dias_seleccionados = ""
        
        # --- FUENTES ESCALABLES ---
        self._fuente_titulo = font.Font(family="Roboto", size=20, weight="bold")
        self._fuente_sub = font.Font(family="Roboto", size=14)
        self._fuente_label = font.Font(family="Roboto", size=12)
        self._fuente_btn = font.Font(family="Roboto", size=14, weight="bold")
        self._fuente_tree_head = font.Font(family="Roboto", size=10, weight="bold")
        self._fuente_tree = font.Font(family="Roboto", size=10)
        
        # --- ESTILOS ---
        estilo = ttk.Style()
        estilo.theme_use('clam')
        estilo.configure('blue.TFrame', background='#0A0F1E')
        estilo.configure('Custom.TCheckbutton', font=self._fuente_sub, background='#0A0F1E', foreground='#ffffff')
        estilo.configure('Danger.TButton', font=self._fuente_btn, background='#6D583A', foreground='#000000', padding=10)
        estilo.configure('Treeview.Heading', font=self._fuente_tree_head, background='#2f4a23', foreground='#ffffff')
        estilo.configure('Treeview', font=self._fuente_tree, rowheight=25)
        estilo.configure('fondo.TLabel', font=self._fuente_label, background='#0A0F1E', foreground='#ffffff')
        estilo.configure('TNotebook', background='#0A0F1E', borderwidth=0)
        estilo.configure('TNotebook.Tab', background='#1a1f3e', foreground='#ffffff', padding=[10, 2])
        estilo.map('TNotebook.Tab', background=[('selected', '#0A0F1E')], foreground=[('selected', '#6D583A')])
        
        # --- CARGA DE FONDO ---
        try:
            image = Image.open(ruta_recurso("assets/fondo.png"))
            self.original_image = image
            self.background_label = tk.Label(self.master)
            self.background_label.place(x=0, y=0, relwidth=1, relheight=1)
            self.master.bind("<Configure>", self.redimensionar_fondo)
        except Exception:
            self.master.config(bg="#0A0F1E")
        
        # --- CONTENEDOR PRINCIPAL CENTRADO ---
        self.frame_principal = ttk.Frame(self.master, style='blue.TFrame')
        self.frame_principal.place(relx=0.5, rely=0.5, anchor='center', relwidth=0.94, relheight=0.94)
        self.frame_principal.rowconfigure(0, weight=1)
        self.frame_principal.columnconfigure(0, weight=1)

        # --- NOTEBOOK PRINCIPAL ---
        self.notebook = ttk.Notebook(self.frame_principal)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        # --- TAB 0: PERSONAL ---
        self.tab_personal = ttk.Frame(self.notebook, style='blue.TFrame')
        self.notebook.add(self.tab_personal, text='Personal')
        self.tab_personal.columnconfigure(0, weight=0, minsize=420)
        self.tab_personal.columnconfigure(1, weight=1)
        self.tab_personal.rowconfigure(0, weight=1)

        # --- SECCIÓN IZQUIERDA: FORMULARIOS ---
        self.canvas_izq = tk.Canvas(self.tab_personal, highlightthickness=0, background='#0A0F1E')
        self.scrollbar_izq = ttk.Scrollbar(self.tab_personal, orient="vertical", command=self.canvas_izq.yview)
        self.frame_izquierdo_principal = ttk.Frame(self.canvas_izq, style='blue.TFrame')
        
        self.frame_izquierdo_principal.bind(
            "<Configure>", lambda e: self.canvas_izq.configure(scrollregion=self.canvas_izq.bbox("all"))
        )
        self._canvas_izq_window = self.canvas_izq.create_window((0, 0), window=self.frame_izquierdo_principal, anchor="nw", width=400)
        self.canvas_izq.configure(yscrollcommand=self.scrollbar_izq.set)

        self.canvas_izq.grid(row=0, column=0, sticky="nsw", padx=10, pady=10)
        self.scrollbar_izq.grid(row=0, column=0, sticky="nse")

        # --- FORMULARIO PROFESORES ---
        lbl_prof = ttk.Label(self.frame_izquierdo_principal, text="PROFESORES", style='fondo.TLabel')
        lbl_prof.configure(font=self._fuente_titulo)
        lbl_prof.pack(pady=10)
        self.crear_label_entry("No. Cuenta", "entry_no_cuenta")
        self.crear_label_entry("Nombre(s)", "entry_nombre")
        self.crear_label_entry("Apellidos", "entry_apellido")
        
        ttk.Label(self.frame_izquierdo_principal, text="¿En línea?:", style='fondo.TLabel').pack()
        self.combo_linea = ttk.Combobox(self.frame_izquierdo_principal, width=25, font=self._fuente_label, state='readonly')
        self.combo_linea['values'] = ("Sí", "No","Ambos")
        self.combo_linea.pack(pady=5)
        
        ttk.Label(self.frame_izquierdo_principal, text="Horario (Inicio - Fin):", style='fondo.TLabel').pack()
        f_h = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame'); f_h.pack()
        self.entry_horario_i = ttk.Entry(f_h, width=12, font=self._fuente_label); self.entry_horario_i.pack(side='left', padx=2)
        self.entry_horario_f = ttk.Entry(f_h, width=12, font=self._fuente_label); self.entry_horario_f.pack(side='left', padx=2)
        
        f_dias = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame'); f_dias.pack(pady=10)
        self.vars_dias = {d: tk.IntVar() for d in ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]}
        for dia, var in self.vars_dias.items():
            ttk.Checkbutton(f_dias, text=dia, variable=var, style='Custom.TCheckbutton', command=self.actualizar_dias_string).pack(anchor='w', padx=50)

        f_btns = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame'); f_btns.pack(pady=20)
        ttk.Button(f_btns, text="Guardar", command=self.evento_boton_profesores, style='Danger.TButton').pack(side='left', padx=10)
        ttk.Button(f_btns, text="Eliminar", command=self.eliminar_profesor, style='Danger.TButton').pack(side='left', padx=10)
        ttk.Button(f_btns, text="Limpiar", command=self.limpiar_campos_profesor, style='Danger.TButton').pack(side='left', padx=10)

        ttk.Separator(self.frame_izquierdo_principal, orient='horizontal').pack(fill='x', pady=20)

        # --- FORMULARIO MATERIAS ---
        lbl_mat = ttk.Label(self.frame_izquierdo_principal, text="MATERIAS", style='fondo.TLabel')
        lbl_mat.configure(font=self._fuente_titulo)
        lbl_mat.pack(pady=10)
        self.crear_label_entry("Clave Materia", "entry_materia_clave")
        self.crear_label_entry("Nombre Materia", "entry_materia_nom")
        self.crear_label_entry("Horas Semana", "entry_materia_horas")
        self.crear_label_entry("Semestre", "entry_materia_semestre")
        # Eliminamos la línea conflictiva y dejamos solo el label y el combobox
        ttk.Label(self.frame_izquierdo_principal, text="Prioridad/Preferencia:", style='fondo.TLabel').pack()
        self.combo_preferencia = ttk.Combobox(self.frame_izquierdo_principal, width=25, font=self._fuente_label, state='readonly')
        self.combo_preferencia['values'] = ("Normal", "Tecnológica", "Laboratorio")
        self.combo_preferencia.pack(pady=5)
        # --- CONTENEDOR DE BOTONES Materias ---
        f_btns_materia = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        f_btns_materia.pack(pady=20)
        ttk.Button(f_btns_materia, text="Agregar Materia", command=self.evento_materias, style='Danger.TButton').pack(side='left', padx=10)
        
        # Botón Eliminar 
        ttk.Button(f_btns_materia, text="Eliminar", command=self.eliminar_materia, style='Danger.TButton').pack(side='left', padx=10)

        ttk.Separator(self.frame_izquierdo_principal, orient='horizontal').pack(fill='x', pady=20)

        # --- FORMULARIO SALONES ---
        lbl_sal = ttk.Label(self.frame_izquierdo_principal, text="SALONES", style='fondo.TLabel')
        lbl_sal.configure(font=self._fuente_titulo)
        lbl_sal.pack(pady=10)
        self.crear_label_entry("Número de aula", "entry_num_aula")
        self.crear_label_entry("Capacidad", "entry_capacidad_aula")
        ttk.Label(self.frame_izquierdo_principal, text="Tipo de aula:", style='fondo.TLabel').pack()
        self.combo_tipo = ttk.Combobox(self.frame_izquierdo_principal, width=25, font=self._fuente_label, state='readonly')
        self.combo_tipo['values'] = ("Normal", "Tecnológica", "Laboratorio")
        self.combo_tipo.pack(pady=5)
        
        # --- CONTENEDOR DE BOTONES del formulario salon ---
        f_btns_salon = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        f_btns_salon.pack(pady=20) 
        ttk.Button(f_btns_salon, text="Agregar Salon", command=self.evento_Salones, style='Danger.TButton').pack(side='left', padx=10)
        
        # Botón Eliminar
        ttk.Button(f_btns_salon, text="Eliminar", command=self.eliminar_salon, style='Danger.TButton').pack(side='left', padx=10)

        # --- TAB 1: GESTIÓN ---
        self.tab_gestion = ttk.Frame(self.notebook, style='blue.TFrame')
        self.notebook.add(self.tab_gestion, text='Gestión')
        self._gestion_control = VentanaGestion(parent_frame=self.tab_gestion)

        # --- SECCIÓN DERECHA: TABLAS ---
        self.frame_derecho = ttk.Frame(self.tab_personal, style='blue.TFrame')
        self.frame_derecho.grid(row=0, column=1, sticky="nsew", padx=20, pady=10)

        # Tabla Profesores
        self.sv_busqueda = tk.StringVar(); self.sv_busqueda.trace_add("write", lambda *a: self.filtrar_profesores())
        self.crear_seccion_tabla("Profesores Registrados", "sv_busqueda", "tabla_profesores", ('Cuenta', 'Profesor', 'Dias', 'Horario', 'En línea'))
        self.tabla_profesores.bind("<<TreeviewSelect>>", self.cargar_profesor_seleccionado)

        # Tabla Materias
        self.sv_busqueda_mat = tk.StringVar(); self.sv_busqueda_mat.trace_add("write", lambda *a: self.filtrar_materias())
        self.crear_seccion_tabla("Materias Registradas", "sv_busqueda_mat", "tabla_materias", ('Clave', 'Nombre', 'Hrs/Sem', 'Semestre','preferencia salon'))
        self.tabla_materias.bind("<<TreeviewSelect>>", self.cargar_materia_seleccionada)

        # Tabla Salones
# Tabla Salones
        self.crear_seccion_tabla("Salones Registrados", None, "tabla_salones", ('Aula', 'Capacidad', 'Tipo'))
        self.tabla_salones.bind("<<TreeviewSelect>>", self.cargar_salon_seleccionado) # <--- LÍNEA NUEVA

    # --- MÉTODOS UI ---
    def cargar_materia_seleccionada(self, event):
        item = self.tabla_materias.focus()
        if not item: 
            return
            
        # Extraer valores de la fila
        v = self.tabla_materias.item(item, "values")
        
        # Limpiar y rellenar los campos
        self.limpiar_campos_materia()
        
        self.entry_materia_clave.insert(0, v[0])
        self.entry_materia_nom.insert(0, v[1])
        self.entry_materia_horas.insert(0, v[2])
        self.entry_materia_semestre.insert(0, v[3])
        
        # Cargar el tipo en el Combobox
        if len(v) > 4:
            self.combo_preferencia.set(v[4])
    
    def crear_label_entry(self, txt, attr):
        ttk.Label(self.frame_izquierdo_principal, text=txt, style='fondo.TLabel').pack()
        e = ttk.Entry(self.frame_izquierdo_principal, width=30, font=self._fuente_label)
        e.pack(pady=5, fill='x', padx=10); setattr(self, attr, e)

    def crear_seccion_tabla(self, titulo, var_busq, attr_tabla, cols):
        lbl = ttk.Label(self.frame_derecho, text=titulo, style='fondo.TLabel')
        lbl.configure(font=self._fuente_titulo)
        lbl.pack(pady=(15, 5))
        if var_busq:
            f = ttk.Frame(self.frame_derecho, style='blue.TFrame'); f.pack(fill='x')
            ttk.Label(f, text="Buscar:", style='fondo.TLabel').pack(side='left', padx=5)
            ttk.Entry(f, textvariable=getattr(self, var_busq), width=25, font=self._fuente_label).pack(side='left', padx=5, fill='x', expand=True)
        
        frame_t = ttk.Frame(self.frame_derecho); frame_t.pack(fill='both', expand=True, pady=5)
        t = ttk.Treeview(frame_t, columns=cols, show='headings', height=8)
        for c in cols: t.heading(c, text=c); t.column(c, width=100, anchor='center', minwidth=60)
        t.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(frame_t, orient="vertical", command=t.yview); t.configure(yscroll=sb.set); sb.pack(side='right', fill='y')
        setattr(self, attr_tabla, t)

    # --- LÓGICA PROFESORES ---
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
        self.entry_no_cuenta.config(state='readonly') 
        nombres = v[1].split(" ", 1)
        self.entry_nombre.insert(0, nombres[0])
        if len(nombres) > 1: self.entry_apellido.insert(0, nombres[1])
        
        # --- CORRECCIÓN: Arreglar el texto del Combobox para evitar errores de acento ---
        valor_bd_linea = str(v[4]).strip().upper()
        if valor_bd_linea == "SI" or valor_bd_linea == "SÍ":
            self.combo_linea.set("Sí")
        elif valor_bd_linea == "NO":
            self.combo_linea.set("No")
        else:
            self.combo_linea.set(v[4])
            
        if "-" in v[3]:
            horas = v[3].split("-")
            self.entry_horario_i.insert(0, horas[0].strip())
            if len(horas) > 1: self.entry_horario_f.insert(0, horas[1].strip())
            
        dias_db = v[2].split(", ")
        for dia in dias_db:
            if dia.strip() in self.vars_dias: self.vars_dias[dia.strip()].set(1)
        self.actualizar_dias_string()

    def evento_boton_profesores(self):
        self.entry_no_cuenta.config(state='normal')
        cuenta_base = self.entry_no_cuenta.get().strip()
        full_n = f"{self.entry_nombre.get()} {self.entry_apellido.get()}".strip()
        
        # --- CORRECCIÓN: Normalizamos la opción (mayúsculas, sin espacios) ---
        opcion_linea = self.combo_linea.get().strip().upper()
        
        hora_i = self.entry_horario_i.get()
        hora_f = self.entry_horario_f.get()

        if not cuenta_base:
            messagebox.showwarning("Aviso", "El número de cuenta es obligatorio.")
            return

        exito = False
        conn = get_conexion()
        cur = conn.cursor()

        try:
            # 1. Registro o Actualización Presencial
            # Buscamos "NO" o "AMBOS"
            if opcion_linea in ["NO", "AMBOS"]:
                # Le quitamos el "-L" por si el usuario cargó la cuenta en línea por error
                cuenta_presencial = cuenta_base.replace("-L", "") 
                existe_presencial = any(p[0] == cuenta_presencial for p in self.cache_profesores)
                
                if existe_presencial:
                    cur.execute("""
                        UPDATE profesores 
                        SET nombre=%s, dias_disponibles=%s, disponible_inicio=%s, disponible_fin=%s, en_linea='NO' 
                        WHERE profesor_id=%s
                    """, (full_n, self.dias_seleccionados, hora_i, hora_f, cuenta_presencial))
                    exito = True
                else:
                    if validar_y_registrar_profesor(cuenta_presencial, full_n, self.dias_seleccionados, hora_i, hora_f, "No"):
                        exito = True

            # 2. Registro o Actualización En Línea 
            # Aceptamos "SÍ", "SI" y "AMBOS"
            if opcion_linea in ["SÍ", "SI", "AMBOS"]:
                cuenta_linea = cuenta_base if cuenta_base.endswith("-L") else f"{cuenta_base}-L"
                existe_linea = any(p[0] == cuenta_linea for p in self.cache_profesores)
                
                if existe_linea:
                    cur.execute("""
                        UPDATE profesores 
                        SET nombre=%s, dias_disponibles=%s, disponible_inicio=%s, disponible_fin=%s, en_linea='SI' 
                        WHERE profesor_id=%s
                    """, (full_n, self.dias_seleccionados, hora_i, hora_f, cuenta_linea))
                    exito = True
                else:
                    if validar_y_registrar_profesor(cuenta_linea, full_n, self.dias_seleccionados, hora_i, hora_f, "Sí"):
                        exito = True

            if exito:
                conn.commit()
                self.mostrar_datos_profesor()
                self.limpiar_campos_profesor()
                messagebox.showinfo("Éxito", "Datos del profesor guardados/actualizados correctamente.")
            else:
                messagebox.showwarning("Atención", "No se realizó ningún cambio. Verifique la opción de modalidad seleccionada.")
                
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"Fallo al guardar: {e}")
        finally:
            cur.close()
            conn.close()

    def eliminar_profesor(self):
        self.entry_no_cuenta.config(state='normal')
        pid = self.entry_no_cuenta.get().strip()
        
        if not pid: 
            return
            
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar al profesor {pid}? Esto borrará también sus asignaciones y horarios."):
            from src.conexion import obtener_cursor
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM horarios WHERE asignacion_id IN (SELECT asignacion_id FROM asignaciones WHERE profesor_id = %s)", (pid,))
                    cur.execute("DELETE FROM asignaciones WHERE profesor_id = %s", (pid,))
                    cur.execute("DELETE FROM profesores WHERE profesor_id = %s", (pid,))
                    messagebox.showinfo("Éxito", "Profesor eliminado correctamente.")
                    self.mostrar_datos_profesor()
                    self.limpiar_campos_profesor()
                except Exception as e: 
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
    
    def cargar_salon_seleccionado(self, event):
        item = self.tabla_salones.focus()
        if not item: 
            return
            
        v = self.tabla_salones.item(item, "values")
        self.limpiar_campos_salon()
        
        self.entry_num_aula.insert(0, v[0])
        self.entry_capacidad_aula.insert(0, v[1])
        if len(v) > 2:
            self.combo_tipo.set(v[2])

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

    # --- LÓGICA MATERIAS ---
    def evento_materias(self):
        c, n, h, s, = self.entry_materia_clave.get(), self.entry_materia_nom.get(), self.entry_materia_horas.get(), self.entry_materia_semestre.get()
        t=self.combo_preferencia.get()
        if materia(c, n, h, s,t):
            self.mostrar_datos_materias()
            for e in [self.entry_materia_clave, self.entry_materia_nom, self.entry_materia_horas, self.entry_materia_semestre]: e.delete(0, tk.END)

    def mostrar_datos_materias(self):
        self.cache_materias.clear()
        conn = get_conexion(); cur = conn.cursor()
        cur.execute("SELECT materia_id, nombre, horas_semana, semestre_id,tipo FROM materias")
        self.cache_materias = cur.fetchall(); conn.close()
        self.refrescar_tabla_mat(self.cache_materias)

    def refrescar_tabla_mat(self, datos):
        self.tabla_materias.delete(*self.tabla_materias.get_children())
        for d in datos: self.tabla_materias.insert("", "end", values=d)

    def filtrar_materias(self):
        t = self.sv_busqueda_mat.get().lower()
        f = [m for m in self.cache_materias if t in str(m[0]).lower() or t in m[1].lower()]
        self.refrescar_tabla_mat(f)

    # --- LÓGICA SALONES (RESTAURADA) ---
    def evento_Salones(self):
        aula = self.entry_num_aula.get()
        cap = self.entry_capacidad_aula.get()
        tipo = self.combo_tipo.get()
        # Llama a la clase salon para registrar en BD
        if salon(numero_aula=aula, capacidad=cap, tipo=tipo):
            self.mostrar_datos_salones()
            self.entry_num_aula.delete(0, tk.END)
            self.entry_capacidad_aula.delete(0, tk.END)
            self.combo_tipo.set("")

    def mostrar_datos_salones(self):
        conn = get_conexion(); cur = conn.cursor()
        cur.execute("SELECT salon_id, capacidad, tipo FROM salones")
        res = cur.fetchall(); conn.close()
        self.tabla_salones.delete(*self.tabla_salones.get_children())
        for r in res: self.tabla_salones.insert("", "end", values=r)

    def eliminar_salon(self):
        aula_id = self.entry_num_aula.get().strip()

        if not aula_id:
            return
        
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar el aula {aula_id}?\nSe eliminarán también sus horarios asignados."):
            from src.conexion import obtener_cursor
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM horarios WHERE salon_id = %s", (aula_id,))
                    cur.execute("DELETE FROM salones WHERE salon_id = %s", (aula_id,))
                    
                    messagebox.showinfo("Éxito", "Salón eliminado correctamente.")
                    self.mostrar_datos_salones()
                    self.limpiar_campos_salon()
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
    
    def limpiar_campos_salon(self):
        # Lógica para limpiar los campos
        self.entry_num_aula.delete(0, tk.END)
        self.entry_capacidad_aula.delete(0, tk.END)
        self.combo_tipo.set("")
        

    def eliminar_materia(self):
        materia_id = self.entry_materia_clave.get().strip()
        if not materia_id:
            return

        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar la materia con clave '{materia_id}'?"):
            from src.conexion import obtener_cursor
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM asignaciones WHERE materia_id = %s", (materia_id,))
                    cur.execute("DELETE FROM materias WHERE materia_id = %s", (materia_id,))
                    messagebox.showinfo("Éxito", "Materia eliminada correctamente.")
                    self.mostrar_datos_materias()
                    self.limpiar_campos_materia()
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))

    def limpiar_campos_materia(self):
        self.entry_materia_clave.delete(0, tk.END)
        self.entry_materia_nom.delete(0, tk.END)
        self.entry_materia_horas.delete(0, tk.END)
        self.entry_materia_semestre.delete(0, tk.END)
        self.combo_preferencia.set("")

    def _rescale_ui(self):
        w = self.master.winfo_width()
        h = self.master.winfo_height()
        if w < 100 or h < 100:
            return
        escala = min(w / 1920, h / 1080)
        escala = max(0.5, min(escala, 2.0))
        if abs(escala - self._scale_factor) < 0.05:
            return
        self._scale_factor = escala
        tam_titulo = max(14, int(20 * escala))
        tam_sub = max(10, int(14 * escala))
        tam_label = max(9, int(12 * escala))
        tam_btn = max(10, int(14 * escala))
        tam_tree_h = max(8, int(10 * escala))
        tam_tree = max(8, int(10 * escala))
        self._fuente_titulo.configure(size=tam_titulo)
        self._fuente_sub.configure(size=tam_sub)
        self._fuente_label.configure(size=tam_label)
        self._fuente_btn.configure(size=tam_btn)
        self._fuente_tree_head.configure(size=tam_tree_h)
        self._fuente_tree.configure(size=tam_tree)
        estilo = ttk.Style()
        estilo.configure('Treeview', rowheight=max(20, int(25 * escala)))
        for t in [self.tabla_profesores, self.tabla_materias, self.tabla_salones]:
            if hasattr(t, 'column'):
                for c in t['columns']:
                    t.column(c, width=max(60, int(100 * escala)))
        self.tab_personal.columnconfigure(0, weight=0, minsize=max(350, int(420 * min(escala, 1.2))))

    def redimensionar_fondo(self, event):
        if event.widget is self.master:
            if event.width != self._last_width or event.height != self._last_height:
                self._last_width, self._last_height = event.width, event.height
                img = self.original_image.resize((event.width, event.height), Image.LANCZOS)
                self.bg_img = ImageTk.PhotoImage(img)
                self.background_label.config(image=self.bg_img)
                self._rescale_ui()

    

"""if __name__ == "__main__":
    root = tk.Tk()
    app = VentanaPrincipal(root)
    app.mostrar_datos_profesor(); app.mostrar_datos_materias(); app.mostrar_datos_salones()
    root.mainloop()"""