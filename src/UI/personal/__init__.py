# -*- coding: utf-8 -*-
import os
import sys
import json
import sqlite3
import unicodedata
import datetime
import tkinter as tk
from tkinter import ttk, font, messagebox, filedialog, simpledialog
from PIL import Image, ImageTk

from src.conexion import get_conexion, obtener_cursor
from src.clases.materia import materia
from src.clases.profesor import profesor
from src.clases.salon import salon
from src.clases.grupo import grupo
from src.UI.icon_manager import IconManager

from src.UI.ventana_gestion import VentanaGestion
from src.UI.personal.personal_base import PersonalBaseMixin, ruta_recurso
from src.UI.personal.panel_profesores import PanelProfesoresMixin
from src.UI.personal.panel_materias import PanelMateriasMixin
from src.UI.personal.panel_salones import PanelSalonesMixin
from src.UI.personal.panel_grupos import PanelGruposMixin
from src.UI.personal.importador_datos import ImportadorDatosMixin

class VentanaPrincipal(
    PersonalBaseMixin,
    PanelProfesoresMixin,
    PanelMateriasMixin,
    PanelSalonesMixin,
    PanelGruposMixin,
    ImportadorDatosMixin
):
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
        estilo.map('Custom.TCheckbutton',
            background=[('active', '#ffffff'), ('focus', '#ffffff'), ('pressed', '#ffffff')],
            foreground=[('active', '#000000'), ('focus', '#000000'), ('pressed', '#000000')],
            indicatorcolor=[('selected', '#2f4a23'), ('active', '#2f4a23')]
        )
        estilo.configure('Custom.TRadiobutton', font=self._fuente_label, background='#0A0F1E', foreground='#ffffff')
        estilo.map('Custom.TRadiobutton',
            background=[('active', '#0A0F1E'), ('focus', '#0A0F1E'), ('pressed', '#0A0F1E')],
            foreground=[('active', '#D68910'), ('focus', '#ffffff'), ('pressed', '#ffffff')],
            indicatorcolor=[('selected', '#2f4a23'), ('active', '#2f4a23')]
        )
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

        lbl_semana = ttk.Label(pf_frame, text="¿Acude toda la semana?:", style='fondo.TLabel', font=self._fuente_label)
        lbl_semana.grid(row=3, column=0, sticky='nw', pady=(8, 2))

        f_rb_semana = ttk.Frame(pf_frame, style='blue.TFrame')
        f_rb_semana.grid(row=3, column=1, sticky='w', pady=(8, 2), padx=(12, 0))

        self.var_acude_semana = tk.StringVar(value='SI')
        self.rb_semana_si = ttk.Radiobutton(
            f_rb_semana,
            text="Sí (Distribuir L-J primordial / L-V)",
            value='SI',
            variable=self.var_acude_semana,
            style='Custom.TRadiobutton'
        )
        self.rb_semana_si.pack(anchor='w', pady=2)

        self.rb_semana_no = ttk.Radiobutton(
            f_rb_semana,
            text="No (Compactar en 2 días)",
            value='NO',
            variable=self.var_acude_semana,
            style='Custom.TRadiobutton'
        )
        self.rb_semana_no.pack(anchor='w', pady=2)

        pf_frame.columnconfigure(1, weight=1)

        # --- Botones Profesor ---
        f_btns = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        f_btns.pack(fill='x', padx=25, pady=15)
        f_btns.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(f_btns, text=" Guardar", image=IconManager.get("save", 16), compound="left", command=self.evento_boton_profesores, style='Danger.TButton').grid(row=0, column=0, padx=4)
        ttk.Button(f_btns, text=" Eliminar", image=IconManager.get("trash", 16), compound="left", command=self.eliminar_profesor, style='Danger.TButton').grid(row=0, column=1, padx=4)
        ttk.Button(f_btns, text=" Limpiar", image=IconManager.get("eraser", 16), compound="left", command=self.limpiar_campos_profesor, style='Danger.TButton').grid(row=0, column=2, padx=4)

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
        ttk.Button(f_btns_materia, text=" Agregar Materia", image=IconManager.get("plus", 16), compound="left", command=self.evento_materias, style='Danger.TButton').grid(row=0, column=0, padx=4)
        ttk.Button(f_btns_materia, text=" Eliminar", image=IconManager.get("trash", 16), compound="left", command=self.eliminar_materia, style='Danger.TButton').grid(row=0, column=1, padx=4)

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
        ttk.Button(f_btns_salon, text=" Agregar Salón", image=IconManager.get("plus", 16), compound="left", command=self.evento_Salones, style='Danger.TButton').grid(row=0, column=0, padx=4)
        ttk.Button(f_btns_salon, text=" Eliminar", image=IconManager.get("trash", 16), compound="left", command=self.eliminar_salon, style='Danger.TButton').grid(row=0, column=1, padx=4)

        # ===== SECCIÓN GRUPOS =====
        ttk.Separator(self.frame_izquierdo_principal, orient='horizontal').pack(fill='x', pady=10)
        lbl_grp = ttk.Label(self.frame_izquierdo_principal, text="GRUPOS", style='fondo.TLabel', font=self._fuente_titulo)
        lbl_grp.pack(pady=(10, 10))

        gf_frame = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        gf_frame.pack(fill='x', padx=25, pady=(0, 5))

        self._crear_campo(gf_frame, "Grupo", "entry_grupo_id", 0)
        self._crear_campo(gf_frame, "Semestre", "entry_grupo_nivel", 1)
        self._crear_campo(gf_frame, "Cupo (Alumnos)", "entry_grupo_cupo", 2)
        self._limitar_entrada(self.entry_grupo_id, 20)
        self._limitar_entrada(self.entry_grupo_nivel, 2, solo_digitos=True)
        self._limitar_entrada(self.entry_grupo_cupo, 3, solo_digitos=True)
        self.entry_grupo_cupo.insert(0, "30")
        gf_frame.columnconfigure(1, weight=1)

        self.entry_grupo_nivel.bind("<KeyRelease>", lambda e: self._on_cambio_semestre_grupo())
        self.entry_grupo_nivel.bind("<FocusOut>", lambda e: self._on_cambio_semestre_grupo())

        lbl_mat_grp = ttk.Label(self.frame_izquierdo_principal, text="Materias del semestre:", style='fondo.TLabel', font=self._fuente_sub)
        lbl_mat_grp.pack(anchor='w', padx=25, pady=(8, 2))

        self.frame_contenedor_mat_grp = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        self.frame_contenedor_mat_grp.pack(fill='x', padx=25, pady=(0, 5))

        self.frame_mat_grp_checks = tk.Frame(self.frame_contenedor_mat_grp, background='#0D152A', highlightthickness=1, highlightbackground='#2A3656')
        self.frame_mat_grp_checks.pack(fill='x', expand=True)

        self.materias_grupo_vars = {}
        self._lbl_hint_mat_grp = ttk.Label(self.frame_mat_grp_checks, text="Ingresa un semestre para seleccionar materias", style='fondo.TLabel', foreground='#7E8B9B', font=self._fuente_sub)
        self._lbl_hint_mat_grp.pack(padx=10, pady=10)

        f_btns_grupo = ttk.Frame(self.frame_izquierdo_principal, style='blue.TFrame')
        f_btns_grupo.pack(fill='x', padx=25, pady=15)
        f_btns_grupo.columnconfigure((0, 1), weight=1)
        ttk.Button(f_btns_grupo, text=" Agregar Grupo", image=IconManager.get("plus", 16), compound="left", command=self.evento_grupos, style='Danger.TButton').grid(row=0, column=0, padx=4)
        ttk.Button(f_btns_grupo, text=" Eliminar", image=IconManager.get("trash", 16), compound="left", command=self.eliminar_grupo, style='Danger.TButton').grid(row=0, column=1, padx=4)
        ttk.Button(f_btns_grupo, text=" Iniciar Preasignación", image=IconManager.get("bolt", 16), compound="left", command=self.iniciar_preasignacion, style='Danger.TButton').grid(row=1, column=0, columnspan=2, padx=4, pady=(8, 0), sticky='ew')

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
            text=" Exportar datos",
            image=IconManager.get("table", 16),
            compound="left",
            command=self.exportar_datos_personal
        ).pack(side='right', padx=3)
        ttk.Button(
            f_acciones_catalogo,
            text=" Importar datos",
            image=IconManager.get("folder", 16),
            compound="left",
            command=self.importar_datos_personal
        ).pack(side='right', padx=3)
        self.crear_seccion_tabla("Profesores Registrados", "sv_busqueda", "tabla_profesores", ('No. Cuenta', 'Profesor', 'Correo institucional'))
        self.tabla_profesores.column('Correo institucional', width=240, anchor='w')
        self.tabla_profesores.bind("<<TreeviewSelect>>", self.cargar_profesor_seleccionado)

        self.sv_busqueda_mat = tk.StringVar()
        self.sv_busqueda_mat.trace_add("write", lambda *a: self.filtrar_materias())
        self.sv_filtro_semestre = tk.StringVar(value="Todos")
        self.sv_filtro_semestre.trace_add("write", lambda *a: self.filtrar_materias())
        self.crear_seccion_tabla("Materias Registradas", "sv_busqueda_mat", "tabla_materias", ('Clave', 'Nombre', 'Hrs/Sem', 'Semestre', 'Preferencia de Salón'), combo_semestre_var="sv_filtro_semestre")
        self.tabla_materias.bind("<<TreeviewSelect>>", self.cargar_materia_seleccionada)

        self.crear_seccion_tabla("Salones Registrados", None, "tabla_salones", ('Aula', 'Capacidad', 'Tipo'))
        self.tabla_salones.bind("<<TreeviewSelect>>", self.cargar_salon_seleccionado)

        self.sv_busqueda_grupo = tk.StringVar()
        self.sv_busqueda_grupo.trace_add("write", lambda *a: self.filtrar_grupos())
        self.sv_filtro_semestre_grupo = tk.StringVar(value="Todos")
        self.sv_filtro_semestre_grupo.trace_add("write", lambda *a: self.filtrar_grupos())
        self.crear_seccion_tabla("Grupos Registrados", "sv_busqueda_grupo", "tabla_grupos", ('Grupo', 'Semestre', 'Cupo'), combo_semestre_var="sv_filtro_semestre_grupo")
        self.tabla_grupos.bind("<<TreeviewSelect>>", self.cargar_grupo_seleccionado)


__all__ = ['VentanaPrincipal']
