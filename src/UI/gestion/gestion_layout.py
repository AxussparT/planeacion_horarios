# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, font, messagebox, filedialog, simpledialog
from PIL import Image, ImageTk
from src.UI.icon_manager import IconManager
import sqlite3
import datetime
import textwrap
import os
import sys
import queue
import threading
import json
import unicodedata

from src.conexion import get_conexion, obtener_cursor, obtener_cursor_dict
from src.motor_horarios import GeneradorHorarios
from src.clases.validacion_bd import _generar_profesor_id
from src.UI.gestion.gestion_base import ruta_recurso
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages
import src.clases.memoria_Horario_Grafico as mem_grafico

class GestionLayoutMixin:
    def construir_interfaz(self):
        if not self._is_embedded:
            try:
                image = Image.open(ruta_recurso("assets/fondo.png"))
                self.original_image = image
                self.background_label = tk.Label(self.ventana)
                self.background_label.place(x=0, y=0, relwidth=1, relheight=1)
                self.ventana.bind("<Configure>", self.redimensionar_fondo)
            except Exception as e:
                print(f"Error al cargar fondo: {e}")
                self.ventana.config(bg="grey")

        self.frame_principal = ttk.Frame(self.ventana, style='blue.TFrame')
        self.frame_principal.place(relx=0.5, rely=0.5, anchor='center', relwidth=0.94, relheight=0.94)

        if not self._is_embedded:
            ttk.Button(self.frame_principal, text="Cerrar", command=self.ventana.destroy).pack(pady=2)

        self.notebook = ttk.Notebook(self.frame_principal)
        self.notebook.pack(fill='both', expand='yes')
        
        self.pes0 = ttk.Frame(self.notebook, style='blue.TFrame')
        self.pes1 = ttk.Frame(self.notebook, style='blue.TFrame')
        
        self.notebook.add(self.pes0, text='Gestión de Asignaciones')
        self.notebook.add(self.pes1, text='Ver Horarios')

        self.Construccion_Ver_Horarios(self.pes1)

        # ===== FILTROS SUPERIORES =====
        frame_filtros = ttk.Frame(self.pes0, style='blue.TFrame')
        frame_filtros.pack(fill='x', pady=(8, 2), padx=10)

        ttk.Label(frame_filtros, text="Periodo", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(side='left', padx=(0, 4))
        self.combo_periodos = ttk.Combobox(frame_filtros, width=12, font=self._fuente_label, state='readonly')
        self.combo_periodos['values'] = ("A", "B")
        self.combo_periodos.pack(side='left', padx=(0, 15))
        self.combo_periodos.bind("<<ComboboxSelected>>", self._cambiar_filtro_periodo)

        ttk.Label(frame_filtros, text="Semestre", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(side='left', padx=(0, 4))
        self.combo_filtro_semestre = ttk.Combobox(frame_filtros, width=10, font=self._fuente_label, state='readonly')
        self.combo_filtro_semestre.pack(side='left')
        self.combo_filtro_semestre.bind("<<ComboboxSelected>>", self._cambiar_filtro_semestre)

        ttk.Separator(frame_filtros, orient='vertical').pack(side='left', fill='y', padx=12)

        # Acciones Principales con iconos nítidos (sin emojis)
        btn_preasig_todas = ttk.Button(
            frame_filtros,
            text=" Preasignar Aulas",
            image=IconManager.get("bolt", 16),
            compound="left",
            command=self._preasignar_todas_aulas
        )
        btn_preasig_todas.pack(side='left', padx=3)

        btn_asignar = ttk.Button(
            frame_filtros,
            text=" Asignar Docentes",
            image=IconManager.get("user-check", 16),
            compound="left",
            command=self.iniciar_asignacion_automatica
        )
        btn_asignar.pack(side='left', padx=3)

        ttk.Separator(frame_filtros, orient='vertical').pack(side='left', fill='y', padx=8)

        # Submenú Desplegable: Configuración
        self._btn_menu_config = ttk.Menubutton(
            frame_filtros,
            text=" Configuración ▾",
            image=IconManager.get("settings", 16),
            compound="left"
        )
        menu_config = tk.Menu(
            self._btn_menu_config,
            tearoff=0,
            background='#1a1f3e',
            foreground='#ffffff',
            activebackground='#38BDF8',
            activeforeground='#000000',
            font=self._fuente_label
        )
        menu_config.add_command(
            label=" Guardar Configuración",
            image=IconManager.get("save", 16),
            compound="left",
            command=self._guardar_configuracion
        )
        menu_config.add_command(
            label=" Actualizar Configuración Actual",
            image=IconManager.get("refresh", 16),
            compound="left",
            command=self._actualizar_configuracion
        )
        menu_config.add_separator()
        menu_config.add_command(
            label=" Cargar Configuración...",
            image=IconManager.get("folder", 16),
            compound="left",
            command=self._cargar_configuracion
        )
        self._btn_menu_config['menu'] = menu_config
        self._btn_menu_config.pack(side='left', padx=3)

        # Submenú Desplegable: Puntos de Respaldo
        self._btn_menu_puntos = ttk.Menubutton(
            frame_filtros,
            text=" Puntos de Respaldo ▾",
            image=IconManager.get("history", 16),
            compound="left"
        )
        menu_puntos = tk.Menu(
            self._btn_menu_puntos,
            tearoff=0,
            background='#1a1f3e',
            foreground='#ffffff',
            activebackground='#38BDF8',
            activeforeground='#000000',
            font=self._fuente_label
        )
        menu_puntos.add_command(
            label=" Deshacer Última Acción (Ctrl+Z)",
            image=IconManager.get("history", 16),
            compound="left",
            command=self._deshacer_ultimo_punto
        )
        menu_puntos.add_separator()
        menu_puntos.add_command(
            label=" Crear Punto de Restauración (Snapshot)",
            image=IconManager.get("camera", 16),
            compound="left",
            command=self._crear_punto_restauracion
        )
        menu_puntos.add_command(
            label=" Historial y Restaurar Punto...",
            image=IconManager.get("history", 16),
            compound="left",
            command=self._abrir_dialogo_restaurar_punto
        )
        self._btn_menu_puntos['menu'] = menu_puntos
        self._btn_menu_puntos.pack(side='left', padx=3)

        ttk.Separator(frame_filtros, orient='vertical').pack(side='left', fill='y', padx=8)

        # Reporte / Sábana
        ttk.Button(
            frame_filtros,
            text=" Sábana General",
            image=IconManager.get("table", 16),
            compound="left",
            command=self._abrir_dialogo_sabana_horarios
        ).pack(side='left', padx=3)

        self._progress_config = ttk.Progressbar(frame_filtros, mode='determinate', length=120)

        # ===== CONTENEDOR PRINCIPAL (izquierda / derecha) =====
        frame_contenedor = ttk.Frame(self.pes0, style='blue.TFrame')
        frame_contenedor.pack(fill='both', expand=True, pady=5)

        # ===== LADO IZQUIERDO: Asignaciones por Periodo (con scroll) =====
        self.canvas_izq = tk.Canvas(frame_contenedor, highlightthickness=0, background='#0A0F1E')
        self.sb_izq = ttk.Scrollbar(frame_contenedor, orient='vertical', command=self.canvas_izq.yview)
        self.frame_izq = ttk.Frame(self.canvas_izq, style='blue.TFrame')

        self.frame_izq.bind(
            '<Configure>', lambda e: self.canvas_izq.configure(scrollregion=self.canvas_izq.bbox('all'))
        )
        self._canvas_izq_window = self.canvas_izq.create_window((0, 0), window=self.frame_izq, anchor='nw')

        def ajustar_ancho_izq(event):
            self.canvas_izq.itemconfig(self._canvas_izq_window, width=event.width)
        self.canvas_izq.bind('<Configure>', ajustar_ancho_izq)

        self.canvas_izq.configure(yscrollcommand=self.sb_izq.set)
        self.canvas_izq.pack(side='left', fill='both', expand=True, padx=(10, 5))
        self.sb_izq.pack(side='left', fill='y')

        # --- Selector de Grupo y Detalle ---
        f_grupo_sel = ttk.LabelFrame(self.frame_izq, text="Gestión de Grupo y Materias Preasignadas", style='blue.TFrame')
        f_grupo_sel.pack(fill='x', padx=8, pady=4)

        f_grupo_linea = ttk.Frame(f_grupo_sel, style='blue.TFrame')
        f_grupo_linea.pack(fill='x', padx=6, pady=4)

        ttk.Label(f_grupo_linea, text="Grupo:", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(side='left', padx=(0, 6))
        self._sv_grupo_gestion = tk.StringVar()
        self.combo_grupo_gestion = ttk.Combobox(f_grupo_linea, textvariable=self._sv_grupo_gestion, font=self._fuente_label, state='readonly', width=16)
        self.combo_grupo_gestion.pack(side='left', padx=(0, 10))
        self.combo_grupo_gestion.bind("<<ComboboxSelected>>", self._on_cambio_grupo_gestion)

        ttk.Button(
            f_grupo_linea,
            text=" Refrescar",
            image=IconManager.get("refresh", 16),
            compound="left",
            command=self._cargar_materias_grupo_gestion
        ).pack(side='left', padx=3)

        ttk.Button(
            f_grupo_linea,
            text=" Reasignar Grupo",
            image=IconManager.get("bolt", 16),
            compound="left",
            command=self._confirmar_volver_a_preasignar_grupo
        ).pack(side='left', padx=3)

        self._lbl_info_grupo_gestion = ttk.Label(f_grupo_sel, text="", background='#0A0F1E', foreground='#FFD700', font=self._fuente_label)
        self._lbl_info_grupo_gestion.pack(fill='x', padx=8, pady=(2, 4))

        # --- Tabla de Materias Preasignadas del Grupo ---
        f_tabla_mat_grp = ttk.Frame(f_grupo_sel, style='blue.TFrame')
        f_tabla_mat_grp.pack(fill='both', expand=True, padx=6, pady=4)

        cols_mg = ('Materia', 'Aula', 'Modalidad', 'Días', 'Horario', 'Profesor', 'Estado')
        self.tabla_materias_grupo = ttk.Treeview(f_tabla_mat_grp, columns=cols_mg, show='headings', height=7)
        self.tabla_materias_grupo.heading('Materia', text='Materia')
        self.tabla_materias_grupo.heading('Aula', text='Aula')
        self.tabla_materias_grupo.heading('Modalidad', text='Modalidad')
        self.tabla_materias_grupo.heading('Días', text='Días')
        self.tabla_materias_grupo.heading('Horario', text='Horario')
        self.tabla_materias_grupo.heading('Profesor', text='Profesor Asignado')
        self.tabla_materias_grupo.heading('Estado', text='Estado')

        self.tabla_materias_grupo.column('Materia', width=130, anchor='w')
        self.tabla_materias_grupo.column('Aula', width=50, anchor='center')
        self.tabla_materias_grupo.column('Modalidad', width=80, anchor='center')
        self.tabla_materias_grupo.column('Días', width=90, anchor='center')
        self.tabla_materias_grupo.column('Horario', width=85, anchor='center')
        self.tabla_materias_grupo.column('Profesor', width=130, anchor='w')
        self.tabla_materias_grupo.column('Estado', width=65, anchor='center')

        sb_mg_v = ttk.Scrollbar(f_tabla_mat_grp, orient='vertical', command=self.tabla_materias_grupo.yview)
        self.tabla_materias_grupo.configure(yscroll=sb_mg_v.set)
        sb_mg_v.pack(side='right', fill='y')
        self.tabla_materias_grupo.pack(fill='both', expand=True)
        self.tabla_materias_grupo.bind("<<TreeviewSelect>>", self._on_select_materia_grupo_gestion)

        # --- Panel de Asignación de Docente a la Materia Preasignada ---
        f_docente_vinculo = ttk.LabelFrame(self.frame_izq, text="Vincular Profesor a Materia Seleccionada", style='blue.TFrame')
        f_docente_vinculo.pack(fill='x', padx=8, pady=6)

        # Fila 1: Profesor Entry + Botones de Vinculación
        f_doc_sel = ttk.Frame(f_docente_vinculo, style='blue.TFrame')
        f_doc_sel.pack(fill='x', padx=6, pady=4)

        ttk.Label(f_doc_sel, text="Profesor:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(0, 4))
        self.entry_prof_vinculo = ttk.Entry(f_doc_sel, font=self._fuente_label, state='readonly', width=28)
        self.entry_prof_vinculo.pack(side='left', fill='x', expand=True, padx=(0, 6))

        self._btn_vincular_profesor = ttk.Button(
            f_doc_sel,
            text=" Vincular Docente",
            image=IconManager.get("user-plus", 16),
            compound="left",
            command=self._ejecutar_vinculacion_docente,
            state='disabled'
        )
        self._btn_vincular_profesor.pack(side='left', padx=2)

        self._btn_desvincular_profesor = ttk.Button(
            f_doc_sel,
            text=" Desvincular",
            image=IconManager.get("user-x", 16),
            compound="left",
            command=self._desvincular_docente_materia,
            state='disabled'
        )
        self._btn_desvincular_profesor.pack(side='left', padx=2)

        ttk.Button(
            f_doc_sel,
            text=" Limpiar",
            image=IconManager.get("eraser", 16),
            compound="left",
            command=self._limpiar_profesor_seleccionado
        ).pack(side='left', padx=2)

        # Fila 2: Modalidad y Toggle de Horario Manual
        f_modo_linea = ttk.Frame(f_docente_vinculo, style='blue.TFrame')
        f_modo_linea.pack(fill='x', padx=6, pady=3)

        ttk.Label(f_modo_linea, text="Modalidad:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(0, 4))
        self.combo_modalidad_vinculo = ttk.Combobox(
            f_modo_linea,
            values=["Presencial", "En Línea (Mediación Tecnológica)", "Mediación Tecnológica"],
            state="readonly",
            width=20,
            font=self._fuente_label
        )
        self.combo_modalidad_vinculo.set("Presencial")
        self.combo_modalidad_vinculo.pack(side='left', padx=(0, 10))

        self._horario_manual_visible = False
        self._btn_toggle_horario_manual = ttk.Button(
            f_modo_linea,
            text="⚙ Horario Manual ▼",
            command=self._toggle_horario_manual
        )
        self._btn_toggle_horario_manual.pack(side='left', padx=2)

        self._btn_reubicacion_asistida = ttk.Button(
            f_modo_linea,
            text="🎯 Reubicación Asistida",
            command=self._abrir_reubicacion_asistida
        )
        self._btn_reubicacion_asistida.pack(side='left', padx=4)

        # Fila 3: Subpanel Desplegable de Horario y Días Manual
        self._frame_horario_manual = ttk.LabelFrame(f_docente_vinculo, text="Definir Horario y Días Manualmente", style='blue.TFrame')

        f_hm_horas = ttk.Frame(self._frame_horario_manual, style='blue.TFrame')
        f_hm_horas.pack(fill='x', padx=6, pady=3)

        ttk.Label(f_hm_horas, text="Horario:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(0, 2))
        f_i, self.entry_manual_hora_i, self.var_manual_hora_i = self._crear_spinner_hora(f_hm_horas, "07:00", actualizar_periodos=False)
        f_i.pack(side='left', padx=1)
        self.combo_manual_hora_i = self.var_manual_hora_i

        ttk.Label(f_hm_horas, text=" - ", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=1)
        f_f, self.entry_manual_hora_f, self.var_manual_hora_f = self._crear_spinner_hora(f_hm_horas, "09:00", actualizar_periodos=False)
        f_f.pack(side='left', padx=1)
        self.combo_manual_hora_f = self.var_manual_hora_f

        ttk.Label(f_hm_horas, text="Aula:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(8, 2))
        self.combo_manual_aula = ttk.Combobox(
            f_hm_horas,
            values=[],
            state="readonly",
            width=8,
            font=self._fuente_label
        )
        self.combo_manual_aula.pack(side='left', padx=(0, 8))

        self._btn_guardar_manual = ttk.Button(
            f_hm_horas,
            text=" Aplicar Horario Manual",
            image=IconManager.get("save", 16),
            compound="left",
            command=self._aplicar_horario_manual_seleccionada,
            state='disabled'
        )
        self._btn_guardar_manual.pack(side='left', padx=4)

        f_hm_dias = ttk.Frame(self._frame_horario_manual, style='blue.TFrame')
        f_hm_dias.pack(fill='x', padx=6, pady=3)

        ttk.Label(f_hm_dias, text="Días:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(0, 6))
        self._vars_dias_manual = {}
        for d_nom in ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]:
            var_d = tk.BooleanVar(value=False)
            self._vars_dias_manual[d_nom] = var_d
            cb = ttk.Checkbutton(f_hm_dias, text=d_nom, variable=var_d, style='Custom.TCheckbutton')
            cb.pack(side='left', padx=3)

        self._lbl_estado_vinculo = ttk.Label(
            f_docente_vinculo,
            text="Selecciona una materia arriba y un profesor a la derecha.",
            background='#0A0F1E',
            foreground='#7E8B9B',
            font=self._fuente_label
        )
        self._lbl_estado_vinculo.pack(fill='x', padx=8, pady=(2, 6))

        self._label_horas = ttk.Label(self.frame_izq, text="", background='#0A0F1E', foreground='#FFD700', font=self._fuente_label)
        self._label_horas.pack(fill='x', padx=10, pady=(4, 0))

        self._periodos_asignacion = []
        self._periodos_frame = ttk.Frame(self.frame_izq, style='blue.TFrame')

        # ===== Lado derecho: Profesores y Vista Previa (con scroll) =====
        self.canvas_der = tk.Canvas(frame_contenedor, highlightthickness=0, background='#0A0F1E')
        self.sb_der = ttk.Scrollbar(frame_contenedor, orient='vertical', command=self.canvas_der.yview)
        self.frame_der = ttk.Frame(self.canvas_der, style='blue.TFrame')

        self.frame_der.bind(
            '<Configure>', lambda e: self.canvas_der.configure(scrollregion=self.canvas_der.bbox('all'))
        )
        self._canvas_der_window = self.canvas_der.create_window((0, 0), window=self.frame_der, anchor='nw')

        def ajustar_ancho_der(event):
            self.canvas_der.itemconfig(self._canvas_der_window, width=event.width)
        self.canvas_der.bind('<Configure>', ajustar_ancho_der)

        self.canvas_der.configure(yscrollcommand=self.sb_der.set)
        self.canvas_der.pack(side='left', fill='both', expand=True, padx=(5, 0))
        self.sb_der.pack(side='left', fill='y', padx=(0, 10))
        self._vincular_rueda_del_ratón()

        # --- Tabla de Profesores (seleccionable) ---
        lbl_prof = ttk.Label(self.frame_der, text="Profesores", background='#0A0F1E', foreground='white', font=self._fuente_sub)
        lbl_prof.pack(anchor='w', padx=6, pady=(4, 2))

        f_busca_prof = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_busca_prof.pack(fill='x', padx=6)
        self.sv_busca_prof_tabla = tk.StringVar()
        self.sv_busca_prof_tabla.trace_add("write", lambda *a: self._programar_filtro_tabla_profesores())
        ttk.Entry(f_busca_prof, textvariable=self.sv_busca_prof_tabla, font=self._fuente_label).pack(fill='x')

        cols_prof = ('No. Cuenta', 'Profesor', 'Disponibilidad')
        self._frame_tabla_prof = ttk.Frame(self.frame_der, style='blue.TFrame')
        self._frame_tabla_prof.pack(fill='x', padx=6, pady=2)

        self.tabla_profesores = ttk.Treeview(self._frame_tabla_prof, columns=cols_prof, show='headings', height=8)
        for c in cols_prof:
            self.tabla_profesores.heading(c, text=c)
        self.tabla_profesores.column('No. Cuenta', width=80)
        self.tabla_profesores.column('Profesor', width=220)
        self.tabla_profesores.column('Disponibilidad', width=120)
        self.tabla_profesores.bind("<<TreeviewSelect>>", self._cargar_profesor_desde_tabla)

        sb_prof_v = ttk.Scrollbar(self._frame_tabla_prof, orient='vertical', command=self.tabla_profesores.yview)
        self.tabla_profesores.configure(yscroll=sb_prof_v.set)
        sb_prof_v.pack(side='right', fill='y')
        self.tabla_profesores.pack(fill='x')

        ttk.Separator(self.frame_der, orient='horizontal').pack(fill='x', pady=6)

        # --- Vista Previa de Asignaciones ---
        f_filtro_estado = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_filtro_estado.pack(fill='x', pady=(2, 2))
        ttk.Label(f_filtro_estado, text="Vista Previa -", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(side='left', padx=5)
        ttk.Label(f_filtro_estado, text="Filtrar:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(20, 4))
        self.combo_estado_filtro = ttk.Combobox(f_filtro_estado, values=["Todos", "pendiente", "asignado"], state="readonly", width=10, font=self._fuente_label)
        self.combo_estado_filtro.set("Todos")
        self.combo_estado_filtro.pack(side='left', padx=2)
        self.combo_estado_filtro.bind("<<ComboboxSelected>>", lambda e: self.actualizar_vista_previa())

        ttk.Button(f_filtro_estado, text="Limpiar", command=self.limpiar_filtros).pack(side='right', padx=5)

        # Buscador Rápido Global (Ctrl+F)
        f_busqueda = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_busqueda.pack(fill='x', pady=(4, 2))
        ttk.Label(f_busqueda, text="Buscar (Ctrl+F):", background='#0A0F1E', foreground='#38BDF8', font=self._fuente_sub).pack(side='left', padx=5)
        self.sv_busqueda_asignaciones = tk.StringVar()
        self.sv_busqueda_asignaciones.trace_add("write", lambda *a: self._programar_actualizacion_vista_previa())
        self.entry_busqueda_asignaciones = ttk.Entry(f_busqueda, textvariable=self.sv_busqueda_asignaciones, font=self._fuente_label)
        self.entry_busqueda_asignaciones.pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.entry_busqueda_asignaciones.bind("<Escape>", lambda e: self.sv_busqueda_asignaciones.set(""))
        
        btn_clear_search = ttk.Button(
            f_busqueda,
            text="✕",
            width=3,
            command=lambda: self.sv_busqueda_asignaciones.set("")
        )
        btn_clear_search.pack(side='left', padx=(0, 5))

        # --- Filtros de semestre y grupo ---
        f_filtros_vp = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_filtros_vp.pack(fill='x', pady=(2, 2))
        ttk.Label(f_filtros_vp, text="Semestre:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(5, 2))
        self._sv_filtro_semestre_vp = tk.StringVar(value="Todos")
        self._sv_filtro_semestre_vp.trace_add("write", lambda *a: self._on_filtro_semestre_vp())
        self.combo_filtro_semestre_vp = ttk.Combobox(f_filtros_vp, textvariable=self._sv_filtro_semestre_vp, state="readonly", width=12, font=self._fuente_label)
        self.combo_filtro_semestre_vp.pack(side='left', padx=(0, 10))
        self.combo_filtro_semestre_vp['values'] = ["Todos"]

        ttk.Label(f_filtros_vp, text="Grupo:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(0, 2))
        self._sv_filtro_grupo_vp = tk.StringVar()
        self._sv_filtro_grupo_vp.trace_add("write", lambda *a: self._on_cambio_filtro_grupo_vp())
        self.combo_filtro_grupo_vp = ttk.Combobox(f_filtros_vp, textvariable=self._sv_filtro_grupo_vp, state="readonly", width=14, font=self._fuente_label)
        self.combo_filtro_grupo_vp.pack(side='left')
        self.combo_filtro_grupo_vp['values'] = ["Todos"]

        self.frame_tablas = ttk.Frame(self.frame_der, style='blue.TFrame')
        self.frame_tablas.pack(fill='both', expand=True, pady=5)

        columnas = ('Profesor', 'materia', 'Estado')
        self.tabla_asignaciones = ttk.Treeview(self.frame_tablas, columns=columnas, show='headings', height=12)
        self.tabla_asignaciones.column('Profesor', anchor='w', width=180)
        self.tabla_asignaciones.column('materia', anchor='w', width=200)
        self.tabla_asignaciones.column('Estado', anchor='center', width=80)

        self.tabla_asignaciones.heading('Profesor', text='Profesor')
        self.tabla_asignaciones.heading('materia', text='Materia (Grupo)')
        self.tabla_asignaciones.heading('Estado', text='Estado')

        self.tabla_asignaciones.bind("<<TreeviewSelect>>", self.cargar_asignacion_seleccionada)

        sb_v = ttk.Scrollbar(self.frame_tablas, orient='vertical', command=self.tabla_asignaciones.yview)
        self.tabla_asignaciones.configure(yscroll=sb_v.set)
        sb_v.pack(side='right', fill='y')

        sb_h = ttk.Scrollbar(self.frame_tablas, orient='horizontal', command=self.tabla_asignaciones.xview)
        self.tabla_asignaciones.configure(xscroll=sb_h.set)
        sb_h.pack(side='bottom', fill='x')

        self.tabla_asignaciones.pack(fill='both', expand=True)

        # --- Barra de Acciones de Vista Previa (Submenús ordenados) ---
        f_acciones = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_acciones.pack(fill='x', padx=6, pady=4)

        # Menubutton: Acciones de Asignación
        self._btn_menu_acc_asig = ttk.Menubutton(
            f_acciones,
            text=" Acciones de Asignación ▾",
            image=IconManager.get("adjustments", 16),
            compound="left"
        )
        menu_acc_asig = tk.Menu(
            self._btn_menu_acc_asig,
            tearoff=0,
            background='#1a1f3e',
            foreground='#ffffff',
            activebackground='#38BDF8',
            activeforeground='#000000',
            font=self._fuente_label
        )
        menu_acc_asig.add_command(
            label=" Liberar Materia Seleccionada",
            image=IconManager.get("eraser", 16),
            compound="left",
            command=self.borrar_asignacion_seleccionada
        )
        menu_acc_asig.add_command(
            label=" Volver a Preasignar Este Grupo",
            image=IconManager.get("bolt", 16),
            compound="left",
            command=self._confirmar_volver_a_preasignar_grupo
        )
        menu_acc_asig.add_separator()
        menu_acc_asig.add_command(
            label=" Borrar Todas las Asignaciones",
            image=IconManager.get("trash", 16),
            compound="left",
            command=self.formatear_asignaciones
        )
        self._btn_menu_acc_asig['menu'] = menu_acc_asig
        self._btn_menu_acc_asig.pack(side='left', padx=3)

        # Menubutton: Puntos de Respaldo
        self._btn_menu_snap = ttk.Menubutton(
            f_acciones,
            text=" Puntos de Respaldo ▾",
            image=IconManager.get("history", 16),
            compound="left"
        )
        menu_snap = tk.Menu(
            self._btn_menu_snap,
            tearoff=0,
            background='#1a1f3e',
            foreground='#ffffff',
            activebackground='#38BDF8',
            activeforeground='#000000',
            font=self._fuente_label
        )
        menu_snap.add_command(
            label=" Deshacer Última Acción (Ctrl+Z)",
            image=IconManager.get("history", 16),
            compound="left",
            command=self._deshacer_ultimo_punto
        )
        menu_snap.add_separator()
        menu_snap.add_command(
            label=" Crear Snapshot Rápido",
            image=IconManager.get("camera", 16),
            compound="left",
            command=self._crear_punto_restauracion
        )
        menu_snap.add_command(
            label=" Historial y Restaurar Punto...",
            image=IconManager.get("history", 16),
            compound="left",
            command=self._abrir_dialogo_restaurar_punto
        )
        self._btn_menu_snap['menu'] = menu_snap
        self._btn_menu_snap.pack(side='left', padx=3)

        # Botón para abrir el horario en ventana completa
        ttk.Button(
            f_acciones,
            text=" Horario Ampliado",
            image=IconManager.get("table", 16),
            compound="left",
            command=self._abrir_previa_horario_ajustada
        ).pack(side='right', padx=4)

        # Botón para alternar la visualización de la cuadrícula mini
        def _toggle_previa_mini():
            if self.frame_previa_horario.winfo_ismapped():
                self.frame_previa_horario.pack_forget()
                self._btn_toggle_mini.config(text=" Mostrar Cuadrícula Mini")
            else:
                self.frame_previa_horario.pack(fill='x', padx=6, pady=(4, 8))
                self._btn_toggle_mini.config(text=" Ocultar Cuadrícula Mini")
                self._cargar_previa_horario_grupo()

        self._btn_toggle_mini = ttk.Button(
            f_acciones,
            text=" Mostrar Cuadrícula Mini",
            image=IconManager.get("calendar", 16),
            compound="left",
            command=_toggle_previa_mini
        )
        self._btn_toggle_mini.pack(side='right', padx=4)

        self.frame_previa_horario = ttk.LabelFrame(
            self.frame_der, text="Horario del grupo", style='blue.TFrame'
        )
        # Oculto por defecto para maximizar el espacio de las tablas de datos
        self.canvas_previa_horario = tk.Canvas(
            self.frame_previa_horario, height=360, background='white',
            highlightthickness=0
        )
        self.canvas_previa_horario.pack(fill='x', expand=True, padx=4, pady=4)
        self.canvas_previa_horario.bind(
            '<Configure>', lambda event: self._dibujar_previa_horario_grupo(
                self.canvas_previa_horario
            )
        )

        try:
            self.ventana.bind_all("<Control-z>", self._deshacer_ultimo_punto)
            self.ventana.bind_all("<Control-Z>", self._deshacer_ultimo_punto)
            def _enfocar_busqueda(event=None):
                if hasattr(self, 'entry_busqueda_asignaciones'):
                    self.entry_busqueda_asignaciones.focus_set()
                    self.entry_busqueda_asignaciones.select_range(0, 'end')
                return "break"
            self.ventana.bind_all("<Control-f>", _enfocar_busqueda)
            self.ventana.bind_all("<Control-F>", _enfocar_busqueda)
        except Exception:
            pass

        self.ventana.after(100, self.actualizar_vista_previa)
        self.ventana.after(150, self._cargar_previa_horario_grupo)

    def _vincular_rueda_del_ratón(self):
        self._wheel_toplevel = self.ventana.winfo_toplevel()
        for secuencia in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            funcid = self._wheel_toplevel.bind(
                secuencia, self._desplazar_panel_con_rueda, add='+'
            )
            self._wheel_bindings.append((secuencia, funcid))
        self.ventana.bind('<Destroy>', self._limpiar_vinculos_rueda, add='+')

    def _limpiar_vinculos_rueda(self, event):
        if event.widget is not self.ventana:
            return
        for secuencia, funcid in self._wheel_bindings:
            self._wheel_toplevel.unbind(secuencia, funcid)
        self._wheel_bindings.clear()

    def _desplazar_panel_con_rueda(self, event):
        try:
            widget = self._wheel_toplevel.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return
        if widget is None:
            return

        canvas = None
        cursor = widget
        while cursor is not None:
            if cursor.winfo_class() == 'Treeview':
                return
            if cursor is self.canvas_izq or cursor is self.canvas_der:
                canvas = cursor
                break
            cursor = cursor.master
        if canvas is None:
            return

        if event.num == 4:
            unidades = -1
        elif event.num == 5:
            unidades = 1
        else:
            self._wheel_delta += event.delta
            unidades = -int(self._wheel_delta / 120)
            self._wheel_delta -= int(self._wheel_delta / 120) * 120
            if unidades == 0:
                return 'break'

        canvas.yview_scroll(unidades, 'units')
        return 'break'

    def _filtrar_tabla_profesores(self):
        texto = self.sv_busca_prof_tabla.get().strip().lower()
        if not texto:
            self._poblar_tabla_profesores(self._lista_completa_profesores)
        else:
            filtrados = [p for p in self._lista_completa_profesores if texto in p[1].lower() or texto in p[2].lower()]
            self._poblar_tabla_profesores(filtrados)

    def _programar_filtro_tabla_profesores(self):
        if self._after_busqueda_profesores_id is not None:
            self.ventana.after_cancel(self._after_busqueda_profesores_id)
        self._after_busqueda_profesores_id = self.ventana.after(
            200, self._filtrar_tabla_profesores_diferido
        )

    def _filtrar_tabla_profesores_diferido(self):
        self._after_busqueda_profesores_id = None
        self._filtrar_tabla_profesores()

    def _programar_actualizacion_vista_previa(self):
        if self._after_busqueda_asignaciones_id is not None:
            self.ventana.after_cancel(self._after_busqueda_asignaciones_id)
        self._after_busqueda_asignaciones_id = self.ventana.after(
            250, self._actualizar_vista_previa_diferido
        )

    def _actualizar_vista_previa_diferido(self):
        self._after_busqueda_asignaciones_id = None
        self.actualizar_vista_previa()
