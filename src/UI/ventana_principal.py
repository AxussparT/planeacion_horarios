import tkinter as tk
from tkinter import ttk, font
from PIL import Image, ImageTk
import sqlite3
import math
import json
from src.conexion import get_conexion
from tkinter import filedialog, messagebox
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
        self.master.title("SAGA")
        self.master.state('zoomed')
        self.master.protocol("WM_DELETE_WINDOW", self._confirmar_cierre)

        self.cache_profesores = []
        self.cache_materias = []
        self.cache_salones = []
        self.cache_grupos = []
        self._after_busqueda_profesores_id = None
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
        self._crear_campo(pf_frame, "Nombre completo", "entry_nombre_completo", 1)
        self._crear_campo(pf_frame, "Correo institucional", "entry_correo_institucional", 2)
        self._limitar_entrada(self.entry_no_cuenta, 10, solo_digitos=True)
        self._limitar_entrada(self.entry_nombre_completo, 255)
        self._limitar_entrada(self.entry_correo_institucional, 255)
        pf_frame.columnconfigure(1, weight=1)

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
        self._limitar_entrada(self.entry_materia_clave, 20)
        self._limitar_entrada(self.entry_materia_nom, 255)
        self._limitar_entrada(self.entry_materia_horas, 2, solo_digitos=True)
        self._limitar_entrada(self.entry_materia_semestre, 2, solo_digitos=True)

        ttk.Label(mf_frame, text="Prioridad:", style='fondo.TLabel').grid(row=4, column=0, sticky='w', pady=4)
        self.combo_preferencia = ttk.Combobox(mf_frame, width=32, font=self._fuente_label, state='readonly')
        self.combo_preferencia['values'] = ("Normal", "Laboratorio de computación", "Laboratorio", "Auditorio")
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
        self._limitar_entrada(self.entry_num_aula, 4)
        self._limitar_entrada(self.entry_capacidad_aula, 3, solo_digitos=True)

        ttk.Label(sf_frame, text="Tipo de aula:", style='fondo.TLabel').grid(row=2, column=0, sticky='w', pady=4)
        self.combo_tipo = ttk.Combobox(sf_frame, width=32, font=self._fuente_label, state='readonly')
        self.combo_tipo['values'] = ("Normal", "Laboratorio de computación", "Laboratorio", "Auditorio")
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
        self._limitar_entrada(self.entry_grupo_id, 20)
        self._limitar_entrada(self.entry_grupo_nivel, 2, solo_digitos=True)
        gf_frame.columnconfigure(1, weight=1)

        self.entry_grupo_nivel.bind("<KeyRelease>", lambda e: self._on_cambio_semestre_grupo())
        self.entry_grupo_nivel.bind("<FocusOut>", lambda e: self._on_cambio_semestre_grupo())

        lbl_mat_grp = ttk.Label(self.frame_izquierdo_principal, text="Materias del semestre:", style='fondo.TLabel', font=self._fuente_sub)
        lbl_mat_grp.pack(anchor='w', padx=25, pady=(8, 2))

        self.frame_contenedor_mat_grp = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        self.frame_contenedor_mat_grp.pack(fill='x', padx=25, pady=(0, 5))

        self.canvas_mat_grp = tk.Canvas(self.frame_contenedor_mat_grp, height=130, highlightthickness=1, highlightbackground='#2A3656', background='#0D152A')
        self.sb_mat_grp = ttk.Scrollbar(self.frame_contenedor_mat_grp, orient='vertical', command=self.canvas_mat_grp.yview)
        self.frame_mat_grp_checks = ttk.Frame(self.canvas_mat_grp, style='blue.TFrame')

        self.frame_mat_grp_checks.bind(
            '<Configure>', lambda e: self.canvas_mat_grp.configure(scrollregion=self.canvas_mat_grp.bbox('all'))
        )
        self._canvas_mat_grp_window = self.canvas_mat_grp.create_window((0, 0), window=self.frame_mat_grp_checks, anchor='nw')

        def _ajustar_ancho_mat_grp(event):
            self.canvas_mat_grp.itemconfig(self._canvas_mat_grp_window, width=event.width)
        self.canvas_mat_grp.bind('<Configure>', _ajustar_ancho_mat_grp)

        def _scroll_mat_grp(event):
            self.canvas_mat_grp.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.canvas_mat_grp.bind("<MouseWheel>", _scroll_mat_grp)
        self.frame_mat_grp_checks.bind("<MouseWheel>", _scroll_mat_grp)

        self.canvas_mat_grp.configure(yscrollcommand=self.sb_mat_grp.set)
        self.canvas_mat_grp.pack(side='left', fill='both', expand=True)
        self.sb_mat_grp.pack(side='right', fill='y')

        self.materias_grupo_vars = {}
        self._lbl_hint_mat_grp = ttk.Label(self.frame_mat_grp_checks, text="Ingresa un semestre para seleccionar materias", style='fondo.TLabel', foreground='#7E8B9B', font=self._fuente_sub)
        self._lbl_hint_mat_grp.pack(padx=10, pady=10)

        f_btns_grupo = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        f_btns_grupo.pack(fill='x', padx=25, pady=15)
        f_btns_grupo.columnconfigure((0, 1), weight=1)
        ttk.Button(f_btns_grupo, text="Agregar Grupo", command=self.evento_grupos, style='Danger.TButton').grid(row=0, column=0, padx=4)
        ttk.Button(f_btns_grupo, text="Eliminar", command=self.eliminar_grupo, style='Danger.TButton').grid(row=0, column=1, padx=4)
        ttk.Button(f_btns_grupo, text="Iniciar Preasignación", command=self.iniciar_preasignacion, style='Danger.TButton').grid(row=1, column=0, columnspan=2, padx=4, pady=(8, 0), sticky='ew')

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
        self.sv_busqueda.trace_add("write", lambda *a: self._programar_filtro_profesores())
        f_acciones_catalogo = ttk.Frame(self.frame_derecho, style='blue.TFrame')
        f_acciones_catalogo.pack(fill='x', padx=5, pady=(8, 2))
        ttk.Button(
            f_acciones_catalogo,
            text="Exportar datos",
            command=self.exportar_datos_personal
        ).pack(side='right', padx=3)
        ttk.Button(
            f_acciones_catalogo,
            text="Importar datos",
            command=self.importar_datos_personal
        ).pack(side='right', padx=3)
        self.crear_seccion_tabla("Profesores Registrados", "sv_busqueda", "tabla_profesores", ('No. Cuenta', 'Profesor', 'Correo institucional'))
        self.tabla_profesores.column('Correo institucional', width=240, anchor='w')
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

    @staticmethod
    def _ui_tipo_materia_salon(tipo_db):
        if not tipo_db:
            return "Normal"
        t = str(tipo_db).strip().upper()
        if t in ("TECNOLOGICA", "TECNOLÓGICA", "LABORATORIO DE COMPUTACION", "LABORATORIO DE COMPUTACIÓN"):
            return "Laboratorio de computación"
        elif t == "LABORATORIO":
            return "Laboratorio"
        elif t == "AUDITORIO":
            return "Auditorio"
        elif t == "NORMAL":
            return "Normal"
        return str(tipo_db).title()

    @staticmethod
    def _db_tipo_materia_salon(tipo_ui):
        if not tipo_ui:
            return "NORMAL"
        t = str(tipo_ui).strip().upper()
        if t in ("LABORATORIO DE COMPUTACION", "LABORATORIO DE COMPUTACIÓN", "TECNOLOGICA", "TECNOLÓGICA"):
            return "TECNOLOGICA"
        elif t == "LABORATORIO":
            return "LABORATORIO"
        elif t == "AUDITORIO":
            return "AUDITORIO"
        elif t == "NORMAL":
            return "NORMAL"
        return t

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
            self.combo_preferencia.set(self._ui_tipo_materia_salon(v[4]))

    def _crear_campo(self, parent, label, attr, row):
        ttk.Label(parent, text=label, style='fondo.TLabel').grid(row=row, column=0, sticky='w', pady=4)
        e = ttk.Entry(parent, width=34, font=self._fuente_label)
        e.grid(row=row, column=1, sticky='ew', padx=(12, 0), pady=4)
        setattr(self, attr, e)

    def _limitar_entrada(self, entry, max_length, solo_digitos=False):
        def validar(valor_propuesto, accion):
            if accion == "-1":
                return True
            if len(valor_propuesto) > max_length:
                return False
            return (
                not solo_digitos
                or not valor_propuesto
                or (valor_propuesto.isascii() and valor_propuesto.isdigit())
            )

        validar_cmd = (self.master.register(validar), "%P", "%d")
        entry.configure(validate="key", validatecommand=validar_cmd)

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
        self.entry_nombre_completo.delete(0, tk.END)
        self.entry_correo_institucional.delete(0, tk.END)
        self._profesor_id_seleccionado = None

    def cargar_profesor_seleccionado(self, event):
        item = self.tabla_profesores.focus()
        if not item:
            return
        v = self.tabla_profesores.item(item, "values")
        self.limpiar_campos_profesor()

        no_cuenta = v[0]
        nombre = v[1] if len(v) > 1 else ''
        correo = v[2] if len(v) > 2 else ''
        self.entry_no_cuenta.insert(0, no_cuenta)
        self.entry_nombre_completo.insert(0, nombre)
        self.entry_correo_institucional.insert(0, correo)

        self._profesor_id_seleccionado = None
        for d in self.cache_profesores:
            if d[1] == no_cuenta:
                self._profesor_id_seleccionado = d[0]
                break
        if not self._profesor_id_seleccionado:
            self._profesor_id_seleccionado = no_cuenta

    def evento_boton_profesores(self):
        self.master.update_idletasks()
        no_cuenta = self.entry_no_cuenta.get().strip()
        full_n = self.entry_nombre_completo.get().strip().upper()
        correo = self.entry_correo_institucional.get().strip() or None

        if not no_cuenta.isascii() or not no_cuenta.isdigit() or len(no_cuenta) > 10:
            messagebox.showwarning("Aviso", "El número de cuenta debe contener de 1 a 10 dígitos.")
            return
        if not full_n or len(full_n) > 255:
            messagebox.showwarning("Aviso", "El nombre del profesor es obligatorio y no puede exceder 255 caracteres.")
            return
        if correo and len(correo) > 255:
            messagebox.showwarning("Aviso", "El correo institucional no puede exceder 255 caracteres.")
            return

        periodos = self.obtener_periodos_desde_ui()
        registro = profesor(no_cuenta, full_n, periodos, correo)
        if not registro.exito:
            return
        self.limpiar_campos_profesor()
        self._refresh_all()

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
                self.limpiar_campos_profesor()
                self._refresh_all()
                messagebox.showinfo("Éxito", "Profesor eliminado correctamente.")

    def mostrar_datos_profesor(self):
        self.cache_profesores.clear()
        conn = get_conexion()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT profesor_id, no_cuenta, nombre, correo_institucional
                    FROM profesores
                    ORDER BY nombre
                """)
                self.cache_profesores = cur.fetchall()
            except sqlite3.Error as err:
                messagebox.showerror("Error de Base de Datos", f"No se pudieron cargar los profesores: {err}")
            finally:
                cur.close()
                conn.close()
        self.refrescar_tabla_prof(self.cache_profesores)

    def refrescar_tabla_prof(self, datos):
        children = self.tabla_profesores.get_children()
        if children:
            self.tabla_profesores.delete(*children)
        for d in datos:
            prof_id = d[0]
            no_cuenta = d[1] if len(d) > 1 and d[1] is not None else ''
            nombre = d[2] if len(d) > 2 else ''
            correo = d[3] if len(d) > 3 and d[3] is not None else ''
            self.tabla_profesores.insert("", "end", values=(no_cuenta, nombre, correo))

    def _programar_filtro_profesores(self):
        if self._after_busqueda_profesores_id is not None:
            self.master.after_cancel(self._after_busqueda_profesores_id)
        self._after_busqueda_profesores_id = self.master.after(
            200, self._filtrar_profesores_diferido
        )

    def _filtrar_profesores_diferido(self):
        self._after_busqueda_profesores_id = None
        self.filtrar_profesores()

    def filtrar_profesores(self):
        t = self.sv_busqueda.get().lower()
        f = [
            p for p in self.cache_profesores
            if any(t in str(valor or '').lower() for valor in p[:4])
        ]
        self.refrescar_tabla_prof(f)

    def exportar_datos_personal(self):
        carpeta_descargas = os.path.join(os.path.expanduser("~"), "Downloads")
        filepath = filedialog.asksaveasfilename(
            title="Exportar datos de Personal",
            defaultextension=".json",
            filetypes=[("Archivos JSON", "*.json")],
            initialdir=carpeta_descargas,
            initialfile="datos_personal.json"
        )
        if not filepath:
            return

        conn = get_conexion()
        if conn is None:
            messagebox.showerror("Error de conexión", "No se pudo conectar con la base de datos.")
            return

        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT profesor_id, no_cuenta, nombre, correo_institucional "
                "FROM profesores ORDER BY nombre"
            )
            profesores_rows = cur.fetchall()
            cur.execute(
                "SELECT profesor_id, dia, hora_inicio, hora_fin "
                "FROM profesor_disponibilidad ORDER BY id"
            )
            disponibilidad_por_profesor = {}
            for profesor_id, dia, hora_inicio, hora_fin in cur.fetchall():
                disponibilidad_por_profesor.setdefault(str(profesor_id), []).append({
                    "dia": dia,
                    "hora_inicio": str(hora_inicio),
                    "hora_fin": str(hora_fin)
                })

            profesores = [
                {
                    "profesor_id": profesor_id,
                    "no_cuenta": no_cuenta,
                    "nombre": nombre,
                    "correo_institucional": correo,
                    "disponibilidad": disponibilidad_por_profesor.get(str(profesor_id), [])
                }
                for profesor_id, no_cuenta, nombre, correo in profesores_rows
            ]

            cur.execute(
                "SELECT materia_id, nombre, horas_semana, semestre_id, tipo "
                "FROM materias ORDER BY materia_id"
            )
            materias = [
                {
                    "materia_id": materia_id,
                    "nombre": nombre,
                    "horas_semana": str(horas_semana),
                    "semestre_id": semestre_id,
                    "tipo": tipo
                }
                for materia_id, nombre, horas_semana, semestre_id, tipo in cur.fetchall()
            ]

            cur.execute("SELECT salon_id, capacidad, tipo FROM salones ORDER BY salon_id")
            salones = [
                {"salon_id": salon_id, "capacidad": capacidad, "tipo": tipo}
                for salon_id, capacidad, tipo in cur.fetchall()
            ]

            cur.execute("SELECT grupo_id, nivel FROM grupos ORDER BY grupo_id")
            grupos = [
                {"grupo_id": grupo_id, "nivel": nivel}
                for grupo_id, nivel in cur.fetchall()
            ]

            datos = {
                "formato": "saga_datos_personal",
                "version": 1,
                "profesores": profesores,
                "materias": materias,
                "salones": salones,
                "grupos": grupos
            }
            with open(filepath, "w", encoding="utf-8") as archivo:
                json.dump(datos, archivo, indent=2, ensure_ascii=False)
        except (OSError, sqlite3.Error) as err:
            messagebox.showerror("Error al exportar", f"No se pudieron exportar los datos: {err}")
            return
        finally:
            cur.close()
            conn.close()

        try:
            en_descargas = os.path.commonpath(
                [os.path.abspath(filepath), os.path.abspath(carpeta_descargas)]
            ) == os.path.abspath(carpeta_descargas)
        except ValueError:
            en_descargas = False

        if en_descargas:
            mensaje = f"El archivo se almacenó correctamente en la carpeta de Descargas:\n{filepath}"
        else:
            mensaje = f"El archivo se almacenó correctamente en:\n{filepath}"
        messagebox.showinfo("Exportación completa", mensaje)

    def _preguntar_coincidencia_catalogo(self, tipo, identificador, descripcion):
        dialogo = tk.Toplevel(self.master)
        dialogo.title("Coincidencia encontrada")
        dialogo.transient(self.master)
        dialogo.resizable(False, False)
        dialogo.grab_set()
        dialogo.resultado = None

        ttk.Label(
            dialogo,
            text=(
                f"Se encontró un registro de {tipo} que coincide con:\n"
                f"{identificador}\n\n{descripcion}\n\n"
                "¿Es el mismo registro? Sí lo actualizará sin crear un duplicado."
            ),
            justify="left",
            wraplength=420
        ).pack(padx=18, pady=(18, 12))

        botones = ttk.Frame(dialogo)
        botones.pack(fill="x", padx=12, pady=(0, 12))

        def cerrar(resultado):
            dialogo.resultado = resultado
            dialogo.destroy()

        ttk.Button(botones, text="Sí", command=lambda: cerrar("si")).pack(side="left", padx=4)
        ttk.Button(
            botones,
            text="No, crear otro",
            command=lambda: cerrar("no")
        ).pack(side="left", padx=4)
        ttk.Button(
            botones,
            text="Sí a todos",
            command=lambda: cerrar("si_todos")
        ).pack(side="right", padx=4)
        dialogo.protocol("WM_DELETE_WINDOW", lambda: cerrar("cancelar"))
        dialogo.bind("<Escape>", lambda event: cerrar("cancelar"))
        dialogo.wait_window()
        return dialogo.resultado

    @staticmethod
    def _nuevo_id_catalogo(base_id, existentes, max_length):
        base_id = str(base_id).strip()
        sufijo_num = 2
        while True:
            sufijo = f"_{sufijo_num}"
            candidato = f"{base_id[:max_length - len(sufijo)]}{sufijo}"
            if candidato not in existentes:
                return candidato
            sufijo_num += 1

    def importar_datos_personal(self):
        filepath = filedialog.askopenfilename(
            title="Importar datos de Personal",
            filetypes=[("Archivos JSON", "*.json")]
        )
        if not filepath:
            return

        try:
            with open(filepath, "r", encoding="utf-8") as archivo:
                datos = json.load(archivo)
        except (OSError, json.JSONDecodeError) as err:
            messagebox.showerror("Archivo inválido", f"No se pudo leer el archivo JSON: {err}")
            return

        if (
            not isinstance(datos, dict)
            or datos.get("formato") != "saga_datos_personal"
            or datos.get("version") != 1
        ):
            messagebox.showerror(
                "Formato no compatible",
                "Selecciona un archivo exportado desde la sección Personal."
            )
            return

        listas = {}
        for entidad in ("profesores", "materias", "salones", "grupos"):
            if entidad not in datos:
                messagebox.showerror(
                    "Archivo inválido",
                    f"El archivo no contiene la sección '{entidad}'."
                )
                return
            registros = datos[entidad]
            if not isinstance(registros, list) or any(not isinstance(registro, dict) for registro in registros):
                messagebox.showerror(
                    "Archivo inválido",
                    f"La sección '{entidad}' debe ser una lista de registros JSON."
                )
                return
            listas[entidad] = registros

        conn = get_conexion()
        if conn is None:
            messagebox.showerror("Error de conexión", "No se pudo conectar con la base de datos.")
            return

        cur = conn.cursor()
        conteos = {"profesores": 0, "materias": 0, "salones": 0, "grupos": 0}
        confirmar_todos = False
        try:
            cur.execute("SELECT profesor_id, no_cuenta, nombre FROM profesores")
            profesores_actuales = cur.fetchall()
            profesor_ids = {str(row[0]) for row in profesores_actuales}
            cur.execute("SELECT materia_id, nombre, semestre_id FROM materias")
            materias_actuales = cur.fetchall()
            materia_ids = {str(row[0]) for row in materias_actuales}
            cur.execute("SELECT salon_id FROM salones")
            salon_ids = {str(row[0]) for row in cur.fetchall()}
            cur.execute("SELECT grupo_id FROM grupos")
            grupo_ids = {str(row[0]) for row in cur.fetchall()}

            for registro in listas["profesores"]:
                cuenta = str(registro.get("no_cuenta") or "").strip()
                nombre = str(registro.get("nombre") or "").strip().upper()
                correo = str(registro.get("correo_institucional") or "").strip() or None
                profesor_id_archivo = str(registro.get("profesor_id") or "").strip().upper()
                disponibilidad = registro.get("disponibilidad", [])
                if not nombre or not isinstance(disponibilidad, list):
                    raise ValueError("Cada profesor debe incluir nombre y una lista de disponibilidad.")
                if len(nombre) > 255 or len(cuenta) > 20 or len(profesor_id_archivo) > 20:
                    raise ValueError(f"Los datos de identificación del profesor '{nombre}' exceden el tamaño permitido.")
                if correo and len(correo) > 255:
                    raise ValueError(f"El correo institucional de '{nombre}' excede 255 caracteres.")

                existente = None
                if profesor_id_archivo:
                    cur.execute("SELECT profesor_id FROM profesores WHERE profesor_id = %s", (profesor_id_archivo,))
                    existente = cur.fetchone()
                if not existente and cuenta:
                    cur.execute("SELECT profesor_id FROM profesores WHERE no_cuenta = %s LIMIT 1", (cuenta,))
                    existente = cur.fetchone()
                if not existente:
                    cur.execute("SELECT profesor_id FROM profesores WHERE nombre = %s LIMIT 1", (nombre,))
                    existente = cur.fetchone()

                mismo = False
                if existente:
                    if not confirmar_todos:
                        decision = self._preguntar_coincidencia_catalogo(
                            "profesor",
                            f"{cuenta or profesor_id_archivo or nombre} - {nombre}",
                            f"Correo institucional: {correo or '(vacío)'}"
                        )
                        if decision == "cancelar" or decision is None:
                            raise InterruptedError("Importación cancelada por el usuario.")
                        if decision == "si_todos":
                            confirmar_todos = True
                            mismo = True
                        else:
                            mismo = decision == "si"
                    else:
                        mismo = True

                if mismo:
                    nuevo_profesor_id = str(existente[0])
                    cur.execute(
                        "UPDATE profesores SET no_cuenta = %s, nombre = %s, correo_institucional = %s "
                        "WHERE profesor_id = %s",
                        (cuenta or None, nombre, correo, nuevo_profesor_id)
                    )
                    cur.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id = %s", (nuevo_profesor_id,))
                else:
                    nuevo_profesor_id = profesor_id_archivo
                    if not nuevo_profesor_id or nuevo_profesor_id in profesor_ids:
                        nuevo_profesor_id = _generar_profesor_id(cur)
                    cur.execute(
                        "INSERT INTO profesores "
                        "(profesor_id, no_cuenta, nombre, correo_institucional, disponible_inicio, "
                        "disponible_fin, dias_disponibles, en_linea) "
                        "VALUES (%s, %s, %s, %s, '00:00:00', '00:00:00', '', 'NO')",
                        (nuevo_profesor_id, cuenta or None, nombre, correo)
                    )
                    profesor_ids.add(nuevo_profesor_id)

                for periodo in disponibilidad:
                    if not isinstance(periodo, dict):
                        raise ValueError(f"La disponibilidad de '{nombre}' contiene un elemento inválido.")
                    dia = str(periodo.get("dia") or "").strip()
                    hora_inicio = str(periodo.get("hora_inicio") or "").strip()
                    hora_fin = str(periodo.get("hora_fin") or "").strip()
                    if not dia or not hora_inicio or not hora_fin:
                        raise ValueError(f"Un periodo de disponibilidad de '{nombre}' está incompleto.")
                    cur.execute(
                        "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin) "
                        "VALUES (%s, %s, %s, %s)",
                        (nuevo_profesor_id, dia, hora_inicio, hora_fin)
                    )
                conteos["profesores"] += 1

            for registro in listas["materias"]:
                materia_id = str(registro.get("materia_id") or "").strip().upper()
                nombre = str(registro.get("nombre") or "").strip().upper()
                horas = str(registro.get("horas_semana") or "").strip()
                semestre = registro.get("semestre_id")
                tipo = str(registro.get("tipo") or "Normal").strip().upper()
                if not materia_id or not nombre or not horas:
                    raise ValueError("Cada materia debe incluir clave, nombre y horas semanales.")
                if len(materia_id) > 20:
                    raise ValueError(f"La clave de materia '{materia_id}' excede 20 caracteres.")
                try:
                    horas_numero = float(horas)
                    if not math.isfinite(horas_numero) or horas_numero < 0:
                        raise ValueError
                    semestre = int(semestre) if semestre not in (None, "") else None
                except (TypeError, ValueError, OverflowError) as err:
                    raise ValueError(f"Los datos numéricos de la materia '{materia_id}' no son válidos.") from err
                if len(nombre) > 255 or len(tipo) > 50:
                    raise ValueError(f"Los datos de la materia '{materia_id}' exceden el tamaño permitido.")

                existente = None
                cur.execute("SELECT materia_id FROM materias WHERE materia_id = %s", (materia_id,))
                existente = cur.fetchone()
                if not existente:
                    cur.execute(
                        "SELECT materia_id FROM materias WHERE LOWER(nombre) = LOWER(%s) "
                        "AND semestre_id <=> %s LIMIT 1",
                        (nombre, semestre)
                    )
                    existente = cur.fetchone()

                mismo = False
                if existente:
                    if not confirmar_todos:
                        decision = self._preguntar_coincidencia_catalogo(
                            "materia",
                            materia_id,
                            f"{nombre} (semestre {semestre or 'sin semestre'})"
                        )
                        if decision == "cancelar" or decision is None:
                            raise InterruptedError("Importación cancelada por el usuario.")
                        if decision == "si_todos":
                            confirmar_todos = True
                            mismo = True
                        else:
                            mismo = decision == "si"
                    else:
                        mismo = True

                if mismo:
                    nuevo_materia_id = str(existente[0])
                    cur.execute(
                        "UPDATE materias SET nombre = %s, horas_semana = %s, semestre_id = %s, tipo = %s "
                        "WHERE materia_id = %s",
                        (nombre, horas, semestre, tipo, nuevo_materia_id)
                    )
                else:
                    nuevo_materia_id = materia_id
                    if nuevo_materia_id in materia_ids:
                        nuevo_materia_id = self._nuevo_id_catalogo(materia_id, materia_ids, 20)
                    cur.execute(
                        "INSERT INTO materias (materia_id, nombre, horas_semana, semestre_id, tipo) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (nuevo_materia_id, nombre, horas, semestre, tipo)
                    )
                    materia_ids.add(nuevo_materia_id)
                conteos["materias"] += 1

            for registro in listas["salones"]:
                salon_id = str(registro.get("salon_id") or "").strip().upper()
                capacidad = registro.get("capacidad", 0)
                tipo = str(registro.get("tipo") or "Normal").strip().upper()
                if not salon_id:
                    raise ValueError("Cada salón debe incluir un número de aula.")
                if capacidad is None:
                    capacidad = 0
                if len(salon_id) > 50:
                    raise ValueError(f"El identificador del salón '{salon_id}' excede 50 caracteres.")
                try:
                    capacidad = int(capacidad)
                except (TypeError, ValueError, OverflowError) as err:
                    raise ValueError(f"La capacidad del salón '{salon_id}' no es válida.") from err
                if capacidad < 0:
                    raise ValueError(f"La capacidad del salón '{salon_id}' no puede ser negativa.")
                if len(tipo) > 50:
                    raise ValueError(f"El tipo del salón '{salon_id}' excede 50 caracteres.")

                cur.execute("SELECT salon_id FROM salones WHERE salon_id = %s", (salon_id,))
                existente = cur.fetchone()
                mismo = False
                if existente:
                    if not confirmar_todos:
                        decision = self._preguntar_coincidencia_catalogo(
                            "salón", salon_id, f"Capacidad: {capacidad}; tipo: {tipo}"
                        )
                        if decision == "cancelar" or decision is None:
                            raise InterruptedError("Importación cancelada por el usuario.")
                        if decision == "si_todos":
                            confirmar_todos = True
                            mismo = True
                        else:
                            mismo = decision == "si"
                    else:
                        mismo = True

                if mismo:
                    nuevo_salon_id = str(existente[0])
                    cur.execute(
                        "UPDATE salones SET capacidad = %s, tipo = %s WHERE salon_id = %s",
                        (capacidad, tipo, nuevo_salon_id)
                    )
                else:
                    nuevo_salon_id = salon_id
                    if nuevo_salon_id in salon_ids:
                        nuevo_salon_id = self._nuevo_id_catalogo(salon_id, salon_ids, 50)
                    cur.execute(
                        "INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, %s, %s)",
                        (nuevo_salon_id, capacidad, tipo)
                    )
                    salon_ids.add(nuevo_salon_id)
                conteos["salones"] += 1

            for registro in listas["grupos"]:
                grupo_id = str(registro.get("grupo_id") or "").strip().upper()
                nivel = registro.get("nivel")
                if not grupo_id:
                    raise ValueError("Cada grupo debe incluir un identificador.")
                if len(grupo_id) > 20:
                    raise ValueError(f"El identificador del grupo '{grupo_id}' excede 20 caracteres.")
                if nivel not in (None, ""):
                    try:
                        nivel = int(nivel)
                    except (TypeError, ValueError, OverflowError) as err:
                        raise ValueError(f"El semestre del grupo '{grupo_id}' no es válido.") from err
                else:
                    nivel = None

                cur.execute("SELECT grupo_id FROM grupos WHERE grupo_id = %s", (grupo_id,))
                existente = cur.fetchone()
                mismo = False
                if existente:
                    if not confirmar_todos:
                        decision = self._preguntar_coincidencia_catalogo(
                            "grupo", grupo_id, f"Semestre: {nivel}"
                        )
                        if decision == "cancelar" or decision is None:
                            raise InterruptedError("Importación cancelada por el usuario.")
                        if decision == "si_todos":
                            confirmar_todos = True
                            mismo = True
                        else:
                            mismo = decision == "si"
                    else:
                        mismo = True

                if mismo:
                    nuevo_grupo_id = str(existente[0])
                    cur.execute(
                        "UPDATE grupos SET nivel = %s WHERE grupo_id = %s",
                        (nivel, nuevo_grupo_id)
                    )
                else:
                    nuevo_grupo_id = grupo_id
                    if nuevo_grupo_id in grupo_ids:
                        nuevo_grupo_id = self._nuevo_id_catalogo(grupo_id, grupo_ids, 20)
                    cur.execute(
                        "INSERT INTO grupos (grupo_id, nivel) VALUES (%s, %s)",
                        (nuevo_grupo_id, nivel)
                    )
                    grupo_ids.add(nuevo_grupo_id)
                conteos["grupos"] += 1

            conn.commit()
        except InterruptedError:
            conn.rollback()
            return
        except (ValueError, sqlite3.Error) as err:
            conn.rollback()
            messagebox.showerror("Error al importar", f"No se importaron los datos: {err}")
            return
        finally:
            cur.close()
            conn.close()

        self._refresh_all()
        resumen = "\n".join(f"{tipo.title()}: {cantidad}" for tipo, cantidad in conteos.items())
        messagebox.showinfo("Importación completa", f"Datos procesados correctamente:\n\n{resumen}")

    # =================== LÓGICA MATERIAS ===================

    def evento_materias(self):
        self.master.update_idletasks()
        c = self.entry_materia_clave.get().strip().upper()
        n = self.entry_materia_nom.get().strip().upper()
        h = self.entry_materia_horas.get().strip()
        s = self.entry_materia_semestre.get().strip()
        t = self._db_tipo_materia_salon(self.combo_preferencia.get())
        if not c or len(c) > 20 or not n or len(n) > 255:
            messagebox.showwarning("Aviso", "La clave es obligatoria (máximo 20 caracteres) y el nombre (máximo 255).")
            return
        if not h.isascii() or not h.isdigit() or len(h) > 2:
            messagebox.showwarning("Aviso", "Las horas semanales deben ser un número entero de hasta 2 dígitos.")
            return
        if s and (not s.isascii() or not s.isdigit() or len(s) > 2):
            messagebox.showwarning("Aviso", "El semestre debe ser un número entero de hasta 2 dígitos.")
            return
        if not t or len(t) > 50:
            messagebox.showwarning("Aviso", "Selecciona un tipo de materia válido.")
            return
        registro = materia(c, n, h, s, t)
        if registro.exito:
            for e in [self.entry_materia_clave, self.entry_materia_nom, self.entry_materia_horas, self.entry_materia_semestre]:
                e.delete(0, tk.END)
            self._refresh_all()

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
            fila = list(d)
            if len(fila) > 4:
                fila[4] = self._ui_tipo_materia_salon(fila[4])
            self.tabla_materias.insert("", "end", values=fila)

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
        self.master.update_idletasks()
        aula = self.entry_num_aula.get().strip().upper()
        cap = self.entry_capacidad_aula.get().strip()
        tipo = self._db_tipo_materia_salon(self.combo_tipo.get())
        if not aula or len(aula) > 4:
            messagebox.showwarning("Aviso", "El número de aula es obligatorio y debe tener hasta 4 caracteres.")
            return
        if not cap.isascii() or not cap.isdigit() or len(cap) > 3:
            messagebox.showwarning("Aviso", "La capacidad debe ser un número entero de hasta 3 dígitos.")
            return
        if not tipo or len(tipo) > 50:
            messagebox.showwarning("Aviso", "Selecciona un tipo de salón válido.")
            return
        registro = salon(numero_aula=aula, capacidad=cap, tipo=tipo)
        if registro.exito:
            self.entry_num_aula.delete(0, tk.END)
            self.entry_capacidad_aula.delete(0, tk.END)
            self.combo_tipo.set("")
            self._refresh_all()

    def mostrar_datos_salones(self):
        conn = get_conexion()
        cur = conn.cursor()
        cur.execute("SELECT salon_id, capacidad, tipo FROM salones")
        res = cur.fetchall()
        conn.close()
        self.tabla_salones.delete(*self.tabla_salones.get_children())
        for r in res:
            if r[0].upper().startswith("MEDIACION_TECNOLOGICA"):
                continue
            fila = list(r)
            if len(fila) > 2:
                fila[2] = self._ui_tipo_materia_salon(fila[2])
            self.tabla_salones.insert("", "end", values=fila)

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
                self.limpiar_campos_salon()
                self._refresh_all()
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
            self.combo_tipo.set(self._ui_tipo_materia_salon(v[2]))

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
                self.limpiar_campos_materia()
                self._refresh_all()
                messagebox.showinfo("Éxito", "Materia eliminada correctamente.")

    # =================== LÓGICA GRUPOS ===================

    def _on_cambio_semestre_grupo(self, materias_preseleccionadas=None):
        sem_str = self.entry_grupo_nivel.get().strip()
        for w in self.frame_mat_grp_checks.winfo_children():
            w.destroy()
        self.materias_grupo_vars.clear()

        if not sem_str or not sem_str.isdigit():
            ttk.Label(
                self.frame_mat_grp_checks,
                text="Ingresa un semestre para seleccionar materias",
                style='fondo.TLabel',
                foreground='#7E8B9B',
                font=self._fuente_sub
            ).pack(padx=10, pady=10)
            return

        sid = int(sem_str)
        conn = get_conexion()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT materia_id, nombre, tipo FROM materias WHERE semestre_id = %s ORDER BY materia_id", (sid,))
        materias_sem = cur.fetchall()
        cur.close()
        conn.close()

        if not materias_sem:
            ttk.Label(
                self.frame_mat_grp_checks,
                text=f"No hay materias registradas para el semestre {sid}",
                style='fondo.TLabel',
                foreground='#FFB020',
                font=self._fuente_sub
            ).pack(padx=10, pady=10)
            return

        for m_id, m_nom, m_tipo in materias_sem:
            marcado = (m_id in materias_preseleccionadas) if materias_preseleccionadas is not None else False
            var = tk.BooleanVar(value=marcado)
            self.materias_grupo_vars[m_id] = (var, m_nom)
            tipo_ui = self._ui_tipo_materia_salon(m_tipo)
            cb = ttk.Checkbutton(
                self.frame_mat_grp_checks,
                text=f"{m_id} - {m_nom} ({tipo_ui})",
                variable=var,
                style='Custom.TCheckbutton'
            )
            cb.pack(fill='x', padx=8, pady=3, anchor='w')
            cb.bind("<MouseWheel>", lambda e: self.canvas_mat_grp.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    def cargar_grupo_seleccionado(self, event):
        item = self.tabla_grupos.focus()
        if not item:
            return
        v = self.tabla_grupos.item(item, "values")
        grupo_id = str(v[0]).strip().upper()
        nivel = str(v[1]).strip()
        self.entry_grupo_id.delete(0, tk.END)
        self.entry_grupo_nivel.delete(0, tk.END)
        self.entry_grupo_id.insert(0, grupo_id)
        self.entry_grupo_nivel.insert(0, nivel)

        materias_vinculadas = set()
        conn = get_conexion()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT materia_id FROM grupo_materias WHERE grupo_id = %s", (grupo_id,))
                materias_vinculadas = {row[0] for row in cur.fetchall()}
            except Exception:
                materias_vinculadas = set()
            finally:
                cur.close()
                conn.close()

        self._on_cambio_semestre_grupo(materias_preseleccionadas=materias_vinculadas)

    def evento_grupos(self):
        self.master.update_idletasks()
        g = self.entry_grupo_id.get().strip().upper()
        n = self.entry_grupo_nivel.get().strip()
        if not g or len(g) > 20:
            messagebox.showwarning("Aviso", "El identificador del grupo es obligatorio y debe tener hasta 20 caracteres.")
            return
        if not n.isascii() or not n.isdigit() or len(n) > 2:
            messagebox.showwarning("Aviso", "El semestre debe ser un número entero de hasta 2 dígitos.")
            return

        seleccionadas = [(m_id, nom) for m_id, (var, nom) in self.materias_grupo_vars.items() if var.get()]
        if not seleccionadas:
            messagebox.showwarning("Aviso", "Debes seleccionar al menos una materia para vincular al grupo.")
            return

        lista_txt = "\n".join(f"- {nom} ({m_id})" for m_id, nom in seleccionadas)
        mensaje = (
            f"El grupo {g} tiene estas materias seleccionadas:\n\n"
            f"{lista_txt}\n\n"
            "¿Desea guardar esta configuración?"
        )
        if not messagebox.askyesno("Confirmar Configuración", mensaje):
            # No - modificar configuración
            return

        registro = grupo(g, n, materias=[m[0] for m in seleccionadas])
        if registro.exito:
            self.limpiar_campos_grupo()
            self._refresh_all()

    def limpiar_campos_grupo(self):
        self.entry_grupo_id.delete(0, tk.END)
        self.entry_grupo_nivel.delete(0, tk.END)
        self.materias_grupo_vars.clear()
        for w in self.frame_mat_grp_checks.winfo_children():
            w.destroy()
        ttk.Label(
            self.frame_mat_grp_checks,
            text="Ingresa un semestre para seleccionar materias",
            style='fondo.TLabel',
            foreground='#7E8B9B',
            font=self._fuente_sub
        ).pack(padx=10, pady=10)

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
                    cur.execute("DELETE FROM grupo_materias WHERE grupo_id = %s", (grupo_id,))
                    cur.execute("DELETE FROM grupos WHERE grupo_id = %s", (grupo_id,))
                    exito = True
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
            if exito:
                self.limpiar_campos_grupo()
                self._refresh_all()
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

    def iniciar_preasignacion(self):
        """
        Ejecuta la preasignación automática de aulas y horarios para los grupos registrados (Paso 4).
        """
        if not messagebox.askyesno(
            "Confirmar Preasignación",
            "¿Desea iniciar la preasignación automática de aulas y horarios?\n\n"
            "Esto asignará salones y horarios a las materias de cada grupo (sin profesor asignado) "
            "optimizando el uso de aulas (2 grupos por aula estándar o hasta 3 si son reducidos).\n\n"
            "¿Continuar?"
        ):
            return

        from src.motor_preasignacion import GeneradorPreasignacion
        generador = GeneradorPreasignacion()
        resultado = generador.ejecutar()

        if not resultado.get("exito"):
            messagebox.showerror("Error en Preasignación", resultado.get("mensaje", "Ocurrió un error desconocido."))
            return

        self._refresh_all()

        total_grupos = resultado.get("total_grupos", 0)
        total_materias = resultado.get("materias_asignadas", 0)
        total_horarios = resultado.get("horarios_generados", 0)
        salones = resultado.get("salones_utilizados", [])
        alertas = resultado.get("alertas", [])
        resumen_grupos = resultado.get("resumen_grupos", [])

        detalles = "\n".join(resumen_grupos[:10])
        if len(resumen_grupos) > 10:
            detalles += f"\n... y {len(resumen_grupos) - 10} grupos más."

        msg = (
            f"Preasignación completada exitosamente.\n\n"
            f"• Grupos procesados: {total_grupos}\n"
            f"• Materias preasignadas: {total_materias}\n"
            f"• Bloques de horario: {total_horarios}\n"
            f"• Aulas utilizadas: {', '.join(salones) if salones else 'Ninguna'}\n\n"
            f"Distribución:\n{detalles}"
        )
        if alertas:
            msg += f"\n\nObservaciones ({len(alertas)}):\n" + "\n".join(f"- {a}" for a in alertas[:5])

        messagebox.showinfo("Preasignación Exitosa", msg)

    # =================== REFRESCO BATCHEADO ===================

    def _refresh_all(self):
        self.master.update_idletasks()
        self.mostrar_datos_profesor()
        self.mostrar_datos_materias()
        self.mostrar_datos_salones()
        self.mostrar_datos_grupos()
        self.master.after(10, self._gestion_control.cargar_combos_bd)

    def _confirmar_cierre(self):
        resp = messagebox.askyesnocancel(
            "Cerrar aplicación",
            "¿Desea guardar la configuración en JSON antes de cerrar?"
        )
        if resp is None:
            return
        if resp:
            if hasattr(self, '_gestion_control') and self._gestion_control:
                ok = self._gestion_control._guardar_configuracion()
                if not ok:
                    return
        self.master.destroy()

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
