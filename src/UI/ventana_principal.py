import tkinter as tk
from tkinter import ttk, font
from PIL import Image, ImageTk
import mysql.connector
from src.conexion import get_conexion
from tkinter import messagebox
from src.UI.ventana_gestion import VentanaGestion
from src.clases.profesor import profesor
from src.clases.materia import materia
from src.clases.salon import salon
from src.clases.grupo import grupo
import os
import sys

def ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base_path, relative_path)

class VentanaPrincipal:

    def __init__(self, master):
        self.master = master
        self.master.title("PLASEM - Control de Personal")
        self.master.state('zoomed')

        self.cache_profesores = []
        self.cache_materias = []
        self.cache_salones = []
        self.cache_grupos = []
        self._last_width = 0
        self._last_height = 0
        self._scale_factor = 1.0
        self.periodos_widgets = []
        self.NOMBRES_DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

        self._fuente_titulo = font.Font(family="Roboto", size=20, weight="bold")
        self._fuente_sub = font.Font(family="Roboto", size=14)
        self._fuente_label = font.Font(family="Roboto", size=12)
        self._fuente_btn = font.Font(family="Roboto", size=14, weight="bold")
        self._fuente_tree_head = font.Font(family="Roboto", size=10, weight="bold")
        self._fuente_tree = font.Font(family="Roboto", size=10)

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

        try:
            image = Image.open(ruta_recurso("assets/fondo.png"))
            self.original_image = image
            self.background_label = tk.Label(self.master)
            self.background_label.place(x=0, y=0, relwidth=1, relheight=1)
            self.master.bind("<Configure>", self.redimensionar_fondo)
        except Exception:
            self.master.config(bg="#0A0F1E")

        self.frame_principal = ttk.Frame(self.master, style='blue.TFrame')
        self.frame_principal.place(relx=0.5, rely=0.5, anchor='center', relwidth=0.94, relheight=0.94)
        self.frame_principal.rowconfigure(0, weight=1)
        self.frame_principal.columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(self.frame_principal)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.tab_personal = ttk.Frame(self.notebook, style='blue.TFrame')
        self.notebook.add(self.tab_personal, text='Personal')
        self.tab_personal.columnconfigure(0, weight=0, minsize=720)
        self.tab_personal.columnconfigure(1, weight=1)
        self.tab_personal.rowconfigure(0, weight=1)

        self.canvas_izq = tk.Canvas(self.tab_personal, highlightthickness=0, background='#0A0F1E')
        self.scrollbar_izq = ttk.Scrollbar(self.tab_personal, orient="vertical", command=self.canvas_izq.yview)
        self.frame_izquierdo_principal = ttk.Frame(self.canvas_izq, style='blue.TFrame')

        self.frame_izquierdo_principal.bind(
            "<Configure>", lambda e: self.canvas_izq.configure(scrollregion=self.canvas_izq.bbox("all"))
        )
        self._canvas_izq_window = self.canvas_izq.create_window((0, 0), window=self.frame_izquierdo_principal, anchor="nw")

        def ajustar_ancho_izq(event):
            self.canvas_izq.itemconfig(self._canvas_izq_window, width=event.width)
        self.canvas_izq.bind("<Configure>", ajustar_ancho_izq)

        self.canvas_izq.configure(yscrollcommand=self.scrollbar_izq.set)

        self.canvas_izq.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.scrollbar_izq.grid(row=0, column=0, sticky="nse")

        # ===== SECCIÓN PROFESORES =====
        lbl_prof = ttk.Label(self.frame_izquierdo_principal, text="PROFESORES", style='fondo.TLabel', font=self._fuente_titulo)
        lbl_prof.pack(pady=(15, 10))

        pf_frame = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        pf_frame.pack(fill='x', padx=25, pady=(0, 5))

        self._crear_campo(pf_frame, "No. Cuenta", "entry_no_cuenta", 0)
        self._crear_campo(pf_frame, "Nombre(s)", "entry_nombre", 1)
        self._crear_campo(pf_frame, "Apellidos", "entry_apellido", 2)
        pf_frame.columnconfigure(1, weight=1)

        # --- Disponibilidad ---
        ttk.Separator(self.frame_izquierdo_principal, orient='horizontal').pack(fill='x', pady=8)
        ttk.Label(self.frame_izquierdo_principal, text="DISPONIBILIDAD (periodos)", style='fondo.TLabel', font=self._fuente_sub).pack(pady=5)
        self.frame_periodos = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        self.frame_periodos.pack(fill='x', padx=15, pady=2)
        self.agregar_periodo_ui()
        self.btn_agregar_periodo = ttk.Button(
            self.frame_izquierdo_principal, text="+ Añadir más",
            command=self.agregar_periodo_ui, style='Danger.TButton'
        )
        self.btn_agregar_periodo.pack(pady=5)

        # --- Botones Profesor ---
        f_btns = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        f_btns.pack(fill='x', padx=25, pady=15)
        f_btns.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(f_btns, text="Guardar", command=self.evento_boton_profesores, style='Danger.TButton').grid(row=0, column=0, padx=4)
        ttk.Button(f_btns, text="Eliminar", command=self.eliminar_profesor, style='Danger.TButton').grid(row=0, column=1, padx=4)
        ttk.Button(f_btns, text="Limpiar", command=self.limpiar_campos_profesor, style='Danger.TButton').grid(row=0, column=2, padx=4)

        # ===== SECCIÓN MATERIAS =====
        ttk.Separator(self.frame_izquierdo_principal, orient='horizontal').pack(fill='x', pady=10)
        lbl_mat = ttk.Label(self.frame_izquierdo_principal, text="MATERIAS", style='fondo.TLabel', font=self._fuente_titulo)
        lbl_mat.pack(pady=(10, 10))

        mf_frame = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        mf_frame.pack(fill='x', padx=25, pady=(0, 5))

        self._crear_campo(mf_frame, "Clave Materia", "entry_materia_clave", 0)
        self._crear_campo(mf_frame, "Nombre Materia", "entry_materia_nom", 1)
        self._crear_campo(mf_frame, "Horas Semana", "entry_materia_horas", 2)
        self._crear_campo(mf_frame, "Semestre", "entry_materia_semestre", 3)

        ttk.Label(mf_frame, text="Prioridad:", style='fondo.TLabel').grid(row=4, column=0, sticky='w', pady=4)
        self.combo_preferencia = ttk.Combobox(mf_frame, width=32, font=self._fuente_label, state='readonly')
        self.combo_preferencia['values'] = ("Normal", "Tecnológica", "Laboratorio", "Auditorio")
        self.combo_preferencia.grid(row=4, column=1, sticky='ew', padx=(12, 0), pady=4)
        mf_frame.columnconfigure(1, weight=1)

        f_btns_materia = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        f_btns_materia.pack(fill='x', padx=25, pady=15)
        f_btns_materia.columnconfigure((0, 1), weight=1)
        ttk.Button(f_btns_materia, text="Agregar Materia", command=self.evento_materias, style='Danger.TButton').grid(row=0, column=0, padx=4)
        ttk.Button(f_btns_materia, text="Eliminar", command=self.eliminar_materia, style='Danger.TButton').grid(row=0, column=1, padx=4)

        # ===== SECCIÓN SALONES =====
        ttk.Separator(self.frame_izquierdo_principal, orient='horizontal').pack(fill='x', pady=10)
        lbl_sal = ttk.Label(self.frame_izquierdo_principal, text="SALONES", style='fondo.TLabel', font=self._fuente_titulo)
        lbl_sal.pack(pady=(10, 10))

        sf_frame = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        sf_frame.pack(fill='x', padx=25, pady=(0, 5))

        self._crear_campo(sf_frame, "Número de aula", "entry_num_aula", 0)
        self._crear_campo(sf_frame, "Capacidad", "entry_capacidad_aula", 1)

        ttk.Label(sf_frame, text="Tipo de aula:", style='fondo.TLabel').grid(row=2, column=0, sticky='w', pady=4)
        self.combo_tipo = ttk.Combobox(sf_frame, width=32, font=self._fuente_label, state='readonly')
        self.combo_tipo['values'] = ("Normal", "Tecnológica", "Laboratorio", "Auditorio")
        self.combo_tipo.grid(row=2, column=1, sticky='ew', padx=(12, 0), pady=4)
        sf_frame.columnconfigure(1, weight=1)

        f_btns_salon = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        f_btns_salon.pack(fill='x', padx=25, pady=15)
        f_btns_salon.columnconfigure((0, 1), weight=1)
        ttk.Button(f_btns_salon, text="Agregar Salon", command=self.evento_Salones, style='Danger.TButton').grid(row=0, column=0, padx=4)
        ttk.Button(f_btns_salon, text="Eliminar", command=self.eliminar_salon, style='Danger.TButton').grid(row=0, column=1, padx=4)

        # ===== SECCIÓN GRUPOS =====
        ttk.Separator(self.frame_izquierdo_principal, orient='horizontal').pack(fill='x', pady=10)
        lbl_grp = ttk.Label(self.frame_izquierdo_principal, text="GRUPOS", style='fondo.TLabel', font=self._fuente_titulo)
        lbl_grp.pack(pady=(10, 10))

        gf_frame = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        gf_frame.pack(fill='x', padx=25, pady=(0, 5))

        self._crear_campo(gf_frame, "Grupo", "entry_grupo_id", 0)
        self._crear_campo(gf_frame, "Semestre", "entry_grupo_nivel", 1)
        gf_frame.columnconfigure(1, weight=1)

        f_btns_grupo = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        f_btns_grupo.pack(fill='x', padx=25, pady=15)
        f_btns_grupo.columnconfigure((0, 1), weight=1)
        ttk.Button(f_btns_grupo, text="Agregar Grupo", command=self.evento_grupos, style='Danger.TButton').grid(row=0, column=0, padx=4)
        ttk.Button(f_btns_grupo, text="Eliminar", command=self.eliminar_grupo, style='Danger.TButton').grid(row=0, column=1, padx=4)

        self.tab_gestion = ttk.Frame(self.notebook, style='blue.TFrame')
        self.notebook.add(self.tab_gestion, text='Gestión')
        self._gestion_control = VentanaGestion(parent_frame=self.tab_gestion)

        self.canvas_der = tk.Canvas(self.tab_personal, highlightthickness=0, background='#0A0F1E')
        self.scrollbar_der = ttk.Scrollbar(self.tab_personal, orient="vertical", command=self.canvas_der.yview)
        self.frame_derecho = ttk.Frame(self.canvas_der, style='blue.TFrame')

        self.frame_derecho.bind(
            "<Configure>", lambda e: self.canvas_der.configure(scrollregion=self.canvas_der.bbox("all"))
        )
        self.canvas_window_der = self.canvas_der.create_window((0, 0), window=self.frame_derecho, anchor="nw")

        def ajustar_ancho_der(event):
            self.canvas_der.itemconfig(self.canvas_window_der, width=event.width)
        self.canvas_der.bind("<Configure>", ajustar_ancho_der)

        self.canvas_der.configure(yscrollcommand=self.scrollbar_der.set)
        self.canvas_der.grid(row=0, column=1, sticky="nsew", padx=(20, 0), pady=10)
        self.scrollbar_der.grid(row=0, column=2, sticky="nse", pady=10)

        self.sv_busqueda = tk.StringVar()
        self.sv_busqueda.trace_add("write", lambda *a: self.filtrar_profesores())
        self.crear_seccion_tabla("Profesores Registrados", "sv_busqueda", "tabla_profesores", ('No. Cuenta', 'Profesor', 'Disponibilidad'))
        self.tabla_profesores.bind("<<TreeviewSelect>>", self.cargar_profesor_seleccionado)

        self.sv_busqueda_mat = tk.StringVar()
        self.sv_busqueda_mat.trace_add("write", lambda *a: self.filtrar_materias())
        self.sv_filtro_semestre = tk.StringVar(value="Todos")
        self.sv_filtro_semestre.trace_add("write", lambda *a: self.filtrar_materias())
        self.crear_seccion_tabla("Materias Registradas", "sv_busqueda_mat", "tabla_materias", ('Clave', 'Nombre', 'Hrs/Sem', 'Semestre', 'preferencia salon'), combo_semestre_var="sv_filtro_semestre")
        self.tabla_materias.bind("<<TreeviewSelect>>", self.cargar_materia_seleccionada)

        self.crear_seccion_tabla("Salones Registrados", None, "tabla_salones", ('Aula', 'Capacidad', 'Tipo'))
        self.tabla_salones.bind("<<TreeviewSelect>>", self.cargar_salon_seleccionado)

        self.sv_busqueda_grupo = tk.StringVar()
        self.sv_busqueda_grupo.trace_add("write", lambda *a: self.filtrar_grupos())
        self.sv_filtro_semestre_grupo = tk.StringVar(value="Todos")
        self.sv_filtro_semestre_grupo.trace_add("write", lambda *a: self.filtrar_grupos())
        self.crear_seccion_tabla("Grupos Registrados", "sv_busqueda_grupo", "tabla_grupos", ('Grupo', 'Semestre'), combo_semestre_var="sv_filtro_semestre_grupo")
        self.tabla_grupos.bind("<<TreeviewSelect>>", self.cargar_grupo_seleccionado)

    # =================== PERIODOS UI ===================

    def agregar_periodo_ui(self, datos=None):
        idx = len(self.periodos_widgets) + 1
        marco = ttk.LabelFrame(self.frame_periodos, text=f"Periodo {idx}", style='blue.TFrame')
        marco.pack(fill='x', pady=4, padx=2)

        f_h = ttk.Frame(marco, style='blue.TFrame')
        f_h.pack(fill='x', pady=2)
        ttk.Label(f_h, text="Horario:", style='fondo.TLabel', font=self._fuente_label).pack(side='left', padx=2)
        entry_i = ttk.Entry(f_h, width=10, font=self._fuente_label)
        entry_i.pack(side='left', padx=2)
        ttk.Label(f_h, text="-", style='fondo.TLabel', font=self._fuente_label).pack(side='left', padx=2)
        entry_f = ttk.Entry(f_h, width=10, font=self._fuente_label)
        entry_f.pack(side='left', padx=2)

        f_dias = ttk.Frame(marco, style='blue.TFrame')
        f_dias.pack(fill='x', pady=2)

        vars_dias = {}
        for i, dia in enumerate(self.NOMBRES_DIAS):
            var = tk.IntVar()
            vars_dias[dia] = var
            fila = i // 3
            col = i % 3
            cb = ttk.Checkbutton(f_dias, text=dia, variable=var, style='Custom.TCheckbutton')
            cb.grid(row=fila, column=col, sticky='w', padx=5, pady=1)

        f_dias.grid_columnconfigure(0, weight=1)
        f_dias.grid_columnconfigure(1, weight=1)
        f_dias.grid_columnconfigure(2, weight=1)

        btn_quitar = ttk.Button(marco, text="Quitar", command=lambda m=marco: self.quitar_periodo_ui(m))
        btn_quitar.pack(pady=2)

        if datos:
            entry_i.insert(0, datos.get('hora_inicio', ''))
            entry_f.insert(0, datos.get('hora_fin', ''))
            for dia in datos.get('dias', []):
                if dia in vars_dias:
                    vars_dias[dia].set(1)

        widget_data = {
            'frame': marco,
            'entry_i': entry_i,
            'entry_f': entry_f,
            'vars': vars_dias,
            'btn_quitar': btn_quitar
        }
        self.periodos_widgets.append(widget_data)
        self._renumerar_periodos()
        return widget_data

    def quitar_periodo_ui(self, marco):
        for w in self.periodos_widgets:
            if w['frame'] == marco:
                self.periodos_widgets.remove(w)
                marco.destroy()
                break
        self._renumerar_periodos()

    def _renumerar_periodos(self):
        for i, w in enumerate(self.periodos_widgets, 1):
            w['frame'].config(text=f"Periodo {i}")

    def obtener_periodos_desde_ui(self):
        periodos = []
        for w in self.periodos_widgets:
            dias_seleccionados = [d for d, v in w['vars'].items() if v.get() == 1]
            if not dias_seleccionados:
                continue
            hora_i = w['entry_i'].get().strip()
            hora_f = w['entry_f'].get().strip()
            if not hora_i or not hora_f:
                continue
            periodos.append({
                'dias': ', '.join(dias_seleccionados),
                'hora_inicio': hora_i,
                'hora_fin': hora_f
            })
        return periodos

    def limpiar_periodos_ui(self):
        for w in list(self.periodos_widgets):
            w['frame'].destroy()
        self.periodos_widgets.clear()
        self.agregar_periodo_ui()

    def cargar_periodos_en_ui(self, periodos_data):
        self.limpiar_periodos_ui()
        if not periodos_data:
            return
        self.periodos_widgets.clear()
        for w in list(self.frame_periodos.winfo_children()):
            w.destroy()
        for pd in periodos_data:
            self.agregar_periodo_ui(pd)
        if not periodos_data:
            self.agregar_periodo_ui()

    # =================== MÉTODOS UI ===================

    def cargar_materia_seleccionada(self, event):
        item = self.tabla_materias.focus()
        if not item:
            return
        v = self.tabla_materias.item(item, "values")
        self.limpiar_campos_materia()
        self.entry_materia_clave.insert(0, v[0])
        self.entry_materia_nom.insert(0, v[1])
        self.entry_materia_horas.insert(0, v[2])
        self.entry_materia_semestre.insert(0, v[3])
        if len(v) > 4:
            self.combo_preferencia.set(v[4])

    def _crear_campo(self, parent, label, attr, row):
        ttk.Label(parent, text=label, style='fondo.TLabel').grid(row=row, column=0, sticky='w', pady=4)
        e = ttk.Entry(parent, width=34, font=self._fuente_label)
        e.grid(row=row, column=1, sticky='ew', padx=(12, 0), pady=4)
        setattr(self, attr, e)

    def crear_seccion_tabla(self, titulo, var_busq, attr_tabla, cols, combo_semestre_var=None):
        ttk.Label(self.frame_derecho, text=titulo, font=self._fuente_sub, style='fondo.TLabel').pack(pady=(12, 4))
        if var_busq:
            f = ttk.Frame(self.frame_derecho, style='blue.TFrame')
            f.pack(fill='x', padx=5)
            ttk.Label(f, text="Buscar:", font=self._fuente_label, style='fondo.TLabel').pack(side='left', padx=(5, 2))
            e = ttk.Entry(f, textvariable=getattr(self, var_busq), width=25, font=self._fuente_label)
            e.pack(side='left', fill='x', expand=True, padx=(0, 5))
            if combo_semestre_var:
                ttk.Label(f, text="Semestre:", font=self._fuente_label, style='fondo.TLabel').pack(side='left', padx=(10, 2))
                combo = ttk.Combobox(f, textvariable=getattr(self, combo_semestre_var), width=8, state='readonly', font=self._fuente_label)
                combo['values'] = ("Todos", "1", "2", "3", "4", "5", "6", "7", "8", "9")
                combo.pack(side='left', padx=5)
        frame_t = ttk.Frame(self.frame_derecho)
        frame_t.pack(fill='both', expand=True, pady=(2, 8))
        t = ttk.Treeview(frame_t, columns=cols, show='headings', height=12)
        for c in cols:
            t.heading(c, text=c)
            t.column(c, width=110, anchor='center')
        t.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(frame_t, orient="vertical", command=t.yview)
        t.configure(yscroll=sb.set)
        sb.pack(side='right', fill='y')
        setattr(self, attr_tabla, t)

    # =================== LÓGICA PROFESORES ===================

    def limpiar_campos_profesor(self):
        self.entry_no_cuenta.config(state='normal')
        self.entry_no_cuenta.delete(0, tk.END)
        self.entry_nombre.delete(0, tk.END)
        self.entry_apellido.delete(0, tk.END)
        self.limpiar_periodos_ui()

    def cargar_profesor_seleccionado(self, event):
        item = self.tabla_profesores.focus()
        if not item:
            return
        v = self.tabla_profesores.item(item, "values")
        self.limpiar_campos_profesor()

        no_cuenta = v[0]
        nombre = v[1] if len(v) > 1 else ''
        self.entry_no_cuenta.insert(0, no_cuenta)
        nombres = nombre.split(" ", 1)
        self.entry_nombre.insert(0, nombres[0])
        if len(nombres) > 1:
            self.entry_apellido.insert(0, nombres[1])

        self._profesor_id_seleccionado = None
        for d in self.cache_profesores:
            if d[1] == no_cuenta:
                self._profesor_id_seleccionado = d[0]
                break
        if not self._profesor_id_seleccionado:
            self._profesor_id_seleccionado = no_cuenta

        conn = get_conexion()
        if conn:
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(
                    """SELECT dia, hora_inicio, hora_fin
                       FROM profesor_disponibilidad
                       WHERE profesor_id = %s
                       ORDER BY id""",
                    (v[0],)
                )
                filas = cur.fetchall()
                periodos_agrupados = {}
                for f in filas:
                    clave = (str(f['hora_inicio']), str(f['hora_fin']))
                    if clave not in periodos_agrupados:
                        h_i = ':'.join(str(f['hora_inicio']).split(':')[:2])
                        h_f = ':'.join(str(f['hora_fin']).split(':')[:2])
                        periodos_agrupados[clave] = {'hora_inicio': h_i, 'hora_fin': h_f, 'dias': []}
                    periodos_agrupados[clave]['dias'].append(f['dia'])
                self.cargar_periodos_en_ui(list(periodos_agrupados.values()))
            except Exception:
                self.cargar_periodos_en_ui([])
            finally:
                cur.close()
                conn.close()
        else:
            self.cargar_periodos_en_ui([])

    def evento_boton_profesores(self):
        no_cuenta = self.entry_no_cuenta.get().strip()
        full_n = f"{self.entry_nombre.get()} {self.entry_apellido.get()}".strip()

        periodos = self.obtener_periodos_desde_ui()
        if not periodos:
            messagebox.showwarning("Aviso", "Debe agregar al menos un periodo con días y horario.")
            return

        if not no_cuenta:
            messagebox.showwarning("Aviso", "El número de cuenta es obligatorio.")
            return

        if profesor(no_cuenta, full_n, periodos):
            self.mostrar_datos_profesor()
            self._gestion_control.cargar_combos_bd()
            self.limpiar_campos_profesor()

    def eliminar_profesor(self):
        pid = getattr(self, '_profesor_id_seleccionado', None)
        if not pid:
            pid = self.entry_no_cuenta.get().strip()
        if not pid:
            return
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar al profesor {pid}? Esto borrará también sus asignaciones y horarios."):
            from src.conexion import obtener_cursor
            exito = False
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id = %s", (pid,))
                    cur.execute("DELETE FROM horarios WHERE asignacion_id IN (SELECT asignacion_id FROM asignaciones WHERE profesor_id = %s)", (pid,))
                    cur.execute("DELETE FROM asignaciones WHERE profesor_id = %s", (pid,))
                    cur.execute("DELETE FROM profesores WHERE profesor_id = %s", (pid,))
                    exito = True
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
            if exito:
                self._gestion_control.cargar_combos_bd()
                self.mostrar_datos_profesor()
                self.limpiar_campos_profesor()
                messagebox.showinfo("Éxito", "Profesor eliminado correctamente.")

    def mostrar_datos_profesor(self):
        self.cache_profesores.clear()
        conn = get_conexion()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT p.profesor_id, p.no_cuenta, p.nombre,
                           GROUP_CONCAT(CONCAT(pd.dia, ' ', pd.hora_inicio, '-', pd.hora_fin) ORDER BY pd.id SEPARATOR '; ') AS disponibilidad
                    FROM profesores p
                    LEFT JOIN profesor_disponibilidad pd ON p.profesor_id = pd.profesor_id
                    GROUP BY p.profesor_id, p.no_cuenta, p.nombre
                    ORDER BY p.nombre
                """)
                self.cache_profesores = cur.fetchall()
            except Exception:
                cur.execute("SELECT profesor_id, no_cuenta, nombre, '' as disponibilidad FROM profesores")
                self.cache_profesores = cur.fetchall()
            finally:
                cur.close()
                conn.close()
        self.refrescar_tabla_prof(self.cache_profesores)

    def refrescar_tabla_prof(self, datos):
        self.tabla_profesores.delete(*self.tabla_profesores.get_children())
        for d in datos:
            prof_id = d[0]
            no_cuenta = d[1] if len(d) > 1 and d[1] is not None else ''
            nombre = d[2] if len(d) > 2 else ''
            disp = d[3] if len(d) > 3 else ''
            self.tabla_profesores.insert("", "end", values=(no_cuenta, nombre, disp))

    def filtrar_profesores(self):
        t = self.sv_busqueda.get().lower()
        f = [p for p in self.cache_profesores if t in str(p[0]).lower() or t in str(p[1]).lower() or t in str(p[2]).lower()]
        self.refrescar_tabla_prof(f)

    # =================== LÓGICA MATERIAS ===================

    def evento_materias(self):
        c = self.entry_materia_clave.get()
        n = self.entry_materia_nom.get()
        h = self.entry_materia_horas.get()
        s = self.entry_materia_semestre.get()
        t = self.combo_preferencia.get()
        if materia(c, n, h, s, t):
            self.mostrar_datos_materias()
            self._gestion_control.cargar_combos_bd()
            for e in [self.entry_materia_clave, self.entry_materia_nom, self.entry_materia_horas, self.entry_materia_semestre]:
                e.delete(0, tk.END)

    def mostrar_datos_materias(self):
        self.cache_materias.clear()
        conn = get_conexion()
        cur = conn.cursor()
        cur.execute("SELECT materia_id, nombre, horas_semana, semestre_id, tipo FROM materias")
        self.cache_materias = cur.fetchall()
        conn.close()
        self.refrescar_tabla_mat(self.cache_materias)

    def refrescar_tabla_mat(self, datos):
        self.tabla_materias.delete(*self.tabla_materias.get_children())
        for d in datos:
            self.tabla_materias.insert("", "end", values=d)

    def filtrar_materias(self):
        t = self.sv_busqueda_mat.get().lower()
        s = self.sv_filtro_semestre.get()
        f = []
        for m in self.cache_materias:
            coincide_texto = (t in str(m[0]).lower() or t in m[1].lower())
            coincide_sem = (s == "Todos" or str(m[3]) == s)
            if coincide_texto and coincide_sem:
                f.append(m)
        self.refrescar_tabla_mat(f)

    def limpiar_campos_materia(self):
        self.entry_materia_clave.delete(0, tk.END)
        self.entry_materia_nom.delete(0, tk.END)
        self.entry_materia_horas.delete(0, tk.END)
        self.entry_materia_semestre.delete(0, tk.END)
        self.combo_preferencia.set("")

    # =================== LÓGICA SALONES ===================

    def evento_Salones(self):
        aula = self.entry_num_aula.get()
        cap = self.entry_capacidad_aula.get()
        tipo = self.combo_tipo.get()
        if salon(numero_aula=aula, capacidad=cap, tipo=tipo):
            self.mostrar_datos_salones()
            self.entry_num_aula.delete(0, tk.END)
            self.entry_capacidad_aula.delete(0, tk.END)
            self.combo_tipo.set("")

    def mostrar_datos_salones(self):
        conn = get_conexion()
        cur = conn.cursor()
        cur.execute("SELECT salon_id, capacidad, tipo FROM salones")
        res = cur.fetchall()
        conn.close()
        self.tabla_salones.delete(*self.tabla_salones.get_children())
        for r in res:
            self.tabla_salones.insert("", "end", values=r)

    def eliminar_salon(self):
        aula_id = self.entry_num_aula.get().strip()
        if not aula_id:
            return
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar el aula {aula_id}?\nSe eliminarán también sus horarios asignados."):
            from src.conexion import obtener_cursor
            exito = False
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM horarios WHERE salon_id = %s", (aula_id,))
                    cur.execute("DELETE FROM salones WHERE salon_id = %s", (aula_id,))
                    exito = True
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
            if exito:
                self.mostrar_datos_salones()
                self.limpiar_campos_salon()
                messagebox.showinfo("Éxito", "Salón eliminado correctamente.")

    def limpiar_campos_salon(self):
        self.entry_num_aula.delete(0, tk.END)
        self.entry_capacidad_aula.delete(0, tk.END)
        self.combo_tipo.set("")

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

    def eliminar_materia(self):
        materia_id = self.entry_materia_clave.get().strip()
        if not materia_id:
            return
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar la materia con clave '{materia_id}'?"):
            from src.conexion import obtener_cursor
            exito = False
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM asignaciones WHERE materia_id = %s", (materia_id,))
                    cur.execute("DELETE FROM materias WHERE materia_id = %s", (materia_id,))
                    exito = True
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
            if exito:
                self.mostrar_datos_materias()
                self.limpiar_campos_materia()
                messagebox.showinfo("Éxito", "Materia eliminada correctamente.")

    # =================== LÓGICA GRUPOS ===================

    def cargar_grupo_seleccionado(self, event):
        item = self.tabla_grupos.focus()
        if not item:
            return
        v = self.tabla_grupos.item(item, "values")
        self.entry_grupo_id.delete(0, tk.END)
        self.entry_grupo_nivel.delete(0, tk.END)
        self.entry_grupo_id.insert(0, v[0])
        self.entry_grupo_nivel.insert(0, v[1])

    def evento_grupos(self):
        g = self.entry_grupo_id.get()
        n = self.entry_grupo_nivel.get()
        if grupo(g, n):
            self.mostrar_datos_grupos()
            self._gestion_control.cargar_combos_bd()
            self.entry_grupo_id.delete(0, tk.END)
            self.entry_grupo_nivel.delete(0, tk.END)

    def eliminar_grupo(self):
        grupo_id = self.entry_grupo_id.get().strip().upper()
        if not grupo_id:
            return
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar el grupo '{grupo_id}'?"):
            from src.conexion import obtener_cursor
            exito = False
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM horarios WHERE asignacion_id IN (SELECT asignacion_id FROM asignaciones WHERE grupo_id = %s)", (grupo_id,))
                    cur.execute("DELETE FROM asignaciones WHERE grupo_id = %s", (grupo_id,))
                    cur.execute("DELETE FROM grupos WHERE grupo_id = %s", (grupo_id,))
                    exito = True
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
            if exito:
                self.mostrar_datos_grupos()
                self._gestion_control.cargar_combos_bd()
                self.entry_grupo_id.delete(0, tk.END)
                self.entry_grupo_nivel.delete(0, tk.END)
                messagebox.showinfo("Éxito", "Grupo eliminado correctamente.")

    def mostrar_datos_grupos(self):
        self.cache_grupos = []
        conn = get_conexion()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT grupo_id, nivel FROM grupos ORDER BY nivel, grupo_id")
                self.cache_grupos = cur.fetchall()
            except Exception:
                self.cache_grupos = []
            finally:
                cur.close()
                conn.close()
        self.refrescar_tabla_grp(self.cache_grupos)

    def refrescar_tabla_grp(self, datos):
        if hasattr(self, 'tabla_grupos'):
            self.tabla_grupos.delete(*self.tabla_grupos.get_children())
            for d in datos:
                self.tabla_grupos.insert("", "end", values=d)

    def filtrar_grupos(self):
        t = self.sv_busqueda_grupo.get().lower()
        s = self.sv_filtro_semestre_grupo.get()
        if not hasattr(self, 'cache_grupos'):
            self.mostrar_datos_grupos()
            return
        f = [g for g in self.cache_grupos if (t in str(g[0]).lower() or t in str(g[1]).lower()) and (s == "Todos" or str(g[1]) == s)]
        self.refrescar_tabla_grp(f)

    # =================== ESCALADO ===================

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
        self.tab_personal.columnconfigure(0, weight=0, minsize=max(500, int(720 * min(escala, 1.2))))

    def redimensionar_fondo(self, event):
        if event.widget is self.master:
            if event.width != self._last_width or event.height != self._last_height:
                self._last_width, self._last_height = event.width, event.height
                img = self.original_image.resize((event.width, event.height), Image.LANCZOS)
                self.bg_img = ImageTk.PhotoImage(img)
                self.background_label.config(image=self.bg_img)
                self._rescale_ui()
