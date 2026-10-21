import tkinter as tk
from tkinter import ttk, font, messagebox, filedialog, simpledialog
from PIL import Image, ImageTk
import sqlite3
import datetime
import textwrap
import os
import sys
import threading
import queue
import json
import unicodedata

from src.conexion import get_conexion, obtener_cursor, obtener_cursor_dict
from src.motor_horarios_nuevo import GeneradorHorarios
from src.clases.validacion_bd import _generar_profesor_id
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages
import src.clases.memoria_Horario_Grafico as mem_grafico

def ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base_path, relative_path)

def _migrar_bd():
    conn = None
    cursor = None
    try:
        conn = get_conexion()
        if conn is None:
            return
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(asignaciones)")
        columnas = {fila[1] for fila in cursor.fetchall()}
        if "dias" not in columnas:
            cursor.execute("ALTER TABLE asignaciones ADD COLUMN dias TEXT DEFAULT NULL")
            conn.commit()
    except sqlite3.Error as err:
        if conn:
            conn.rollback()
        print(f"Error migrando el esquema SQLite: {err}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def _backfill_dias():
    conn = None
    try:
        conn = get_conexion()
        if conn is None:
            return
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT asignacion_id, profesor_id, hora_inicio, hora_fin FROM asignaciones WHERE dias IS NULL AND hora_inicio IS NOT NULL AND hora_fin IS NOT NULL")
        pendientes = cur.fetchall()

        mapa_num_dia = {"0": "Lunes", "1": "Martes", "2": "Miércoles", "3": "Jueves", "4": "Viernes", "5": "Sábado"}

        for a in pendientes:
            cur.execute(
                "SELECT DISTINCT dia FROM profesor_disponibilidad WHERE profesor_id=%s AND hora_inicio=%s AND hora_fin=%s",
                (a['profesor_id'], a['hora_inicio'], a['hora_fin'])
            )
            dias_raw = [row['dia'] for row in cur.fetchall()]
            if dias_raw:
                dias_str = ", ".join(mapa_num_dia.get(str(d), str(d)) for d in sorted(dias_raw, key=lambda x: int(x) if str(x).isdigit() else 0))
                cur.execute("UPDATE asignaciones SET dias=%s WHERE asignacion_id=%s", (dias_str, a['asignacion_id']))
        conn.commit()
        if pendientes:
            print(f"[MIGRACIÓN] días asignados a {len(pendientes)} asignaciones existentes")
    except Exception as e:
        print(f"[MIGRACIÓN] Error backfill: {e}")
        conn.rollback() if conn else None
    finally:
        if conn and conn.is_connected():
            conn.close()

class VentanaGestion:
    def __init__(self, master_window=None, parent_frame=None):
        if parent_frame is not None:
            self.ventana = parent_frame
            self._is_embedded = True
        else:
            self.ventana = tk.Toplevel(master_window)
            self.ventana.title("Ventana de Gestión")
            self.ventana.state('zoomed')
            self.ventana.transient(master_window)
            self._is_embedded = False

        _migrar_bd()
        _backfill_dias()

        self._fuente_titulo = font.Font(family="Roboto", size=18, weight="bold")
        self._fuente_sub = font.Font(family="Roboto", size=12)
        self._fuente_label = font.Font(family="Roboto", size=10)
        self._fuente_btn = font.Font(family="Roboto", size=10, weight="bold")

        estilo = ttk.Style()
        estilo.configure('blue.TFrame', background='#0A0F1E')
        estilo.configure('TNotebook', background='#0A0F1E', borderwidth=0)
        estilo.configure('TNotebook.Tab', background='#1a1f3e', foreground='#ffffff', padding=[10, 2])
        estilo.map('TNotebook.Tab', background=[('selected', '#0A0F1E')], foreground=[('selected', '#6D583A')])
        estilo.configure('Custom.TCheckbutton', font=self._fuente_label, background='#0A0F1E', foreground='#ffffff')
        estilo.map('Custom.TCheckbutton',
            background=[('active', '#ffffff'), ('focus', '#ffffff'), ('pressed', '#ffffff')],
            foreground=[('active', '#000000'), ('focus', '#000000'), ('pressed', '#000000')]
        )

        self.profesores_map = {}
        self.materias_map = {}
        self.semestres_map = {}
        self.lista_maestra_semestres = []
        self.lista_maestra_materias = []
        self._lista_completa_profesores = []
        
        self.asignacion_seleccionada_id = None
        self.entidades_filtradas = []
        self._tensor_cargado = False
        self._ultimas_alertas = []
        self._last_width = 0
        self._last_height = 0
        self._scale_factor = 1.0
        self._en_operacion = False
        self._ultimo_config_path = None
        self._profesor_id_seleccionado = None
        self._debounce_after_id = None
        self._periodo_seleccionado = None
        self._semestres_filtrados = []
        self._wheel_delta = 0
        self._wheel_bindings = []
        self._after_busqueda_profesores_id = None
        self._after_busqueda_asignaciones_id = None
        self._disponibilidad_profesores = {}
        self._materia_grupo_seleccionada_id = None
        self._materias_grupo_cache = {}
        
        self.grupos_por_semestre = self._cargar_grupos_desde_bd()

        if not self._is_embedded:
            self.ventana.protocol("WM_DELETE_WINDOW", self._confirmar_cierre)
        self.construir_interfaz()
        self._post_init()
        if not self._is_embedded:
            self.ventana.wait_window()

    def _cargar_grupos_desde_bd(self):
        grupos = {}
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return grupos
                cur, conn = ctx
                cur.execute("SELECT grupo_id, nivel FROM grupos ORDER BY nivel, grupo_id")
                filas = cur.fetchall()
                for row in filas:
                    gid = row[0]
                    nivel = self._normalizar_nivel_grupo(row[1])
                    if nivel not in grupos:
                        grupos[nivel] = []
                    grupos[nivel].append(gid)
        except Exception as e:
            print(f"Error cargando grupos desde BD: {e}")
        return grupos

    @staticmethod
    def _normalizar_nivel_grupo(nivel):
        if nivel is None:
            return "0"
        try:
            return str(int(float(nivel)))
        except (TypeError, ValueError, OverflowError):
            return str(nivel).strip()

    def _grupos_del_semestre(self, semestre_id):
        semestre_id = self._normalizar_nivel_grupo(semestre_id)
        for nivel, grupos in self.grupos_por_semestre.items():
            if self._normalizar_nivel_grupo(nivel) == semestre_id:
                return grupos
        return []

    def _confirmar_cierre(self):
        if self._en_operacion:
            messagebox.showwarning("Operación en curso", "Espera a que termine la operación actual antes de cerrar.")
            return
        if messagebox.askyesno("Confirmar cierre", "¿Estás seguro de cerrar la ventana de gestión?"):
            self.ventana.destroy()

    def _post_init(self):
        self._inicializar_fuentes()
        self.cargar_combos_bd()
        self.ventana.after(50, self._cargar_tensor_diferido)

    def _inicializar_fuentes(self):
        estilo = ttk.Style()
        estilo.configure('Treeview', rowheight=22)
        self._rescale_ui()

    def _cargar_tensor_diferido(self, forzar=False):
        if self._tensor_cargado and not forzar:
            return
        self._tensor_cargado = False
        def tarea():
            try:
                mem_grafico.inicializar_y_llenar_tensor("Salón")
                self.ventana.after(0, self._on_tensor_listo)
            except Exception as e:
                print(f"Error al cargar tensor: {e}")
        hilo = threading.Thread(target=tarea, daemon=True)
        hilo.start()

    def _on_tensor_listo(self):
        self._tensor_cargado = True
        if hasattr(self, 'combo_vista_horarios'):
            self.cambiar_modo_vista()

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
        self.pes_alertas = ttk.Frame(self.notebook, style='blue.TFrame')
        
        self.notebook.add(self.pes0, text='Gestionar')
        self.notebook.add(self.pes_alertas, text='Alertas')
        self.notebook.add(self.pes1, text='Ver Horarios')

        self.Construccion_Ver_Horarios(self.pes1)
        self._construir_pestana_alertas()

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

        ttk.Separator(frame_filtros, orient='vertical').pack(side='left', fill='y', padx=15)
        btn_preasig_todas = ttk.Button(frame_filtros, text="🏢 Preasignar Todas las Aulas", command=self._preasignar_todas_aulas)
        btn_preasig_todas.pack(side='left', padx=3)
        btn_asignar = ttk.Button(frame_filtros, text="👨‍🏫 Asignar Profesores Automático", command=self.iniciar_asignacion_automatica)
        btn_asignar.pack(side='left', padx=3)
        ttk.Separator(frame_filtros, orient='vertical').pack(side='left', fill='y', padx=8)
        ttk.Button(frame_filtros, text="Guardar Config", command=self._guardar_configuracion).pack(side='left', padx=2)
        ttk.Button(frame_filtros, text="Actualizar Config", command=self._actualizar_configuracion).pack(side='left', padx=2)
        ttk.Button(frame_filtros, text="Cargar Config", command=self._cargar_configuracion).pack(side='left', padx=2)
        ttk.Separator(frame_filtros, orient='vertical').pack(side='left', fill='y', padx=8)
        ttk.Button(frame_filtros, text="📸 Crear Punto", command=self._crear_punto_restauracion).pack(side='left', padx=2)
        ttk.Button(frame_filtros, text="⏪ Restaurar Punto", command=self._abrir_dialogo_restaurar_punto).pack(side='left', padx=2)
        ttk.Separator(frame_filtros, orient='vertical').pack(side='left', fill='y', padx=8)
        ttk.Button(frame_filtros, text="📊 Sábana General", command=self._abrir_dialogo_sabana_horarios).pack(side='left', padx=2)
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

        ttk.Button(f_grupo_linea, text="Refrescar", command=self._cargar_materias_grupo_gestion).pack(side='left', padx=4)
        ttk.Button(f_grupo_linea, text="🔄 Volver a preasignar", command=self._confirmar_volver_a_preasignar_grupo).pack(side='left', padx=4)

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
            text="Vincular / Asignar Docente",
            command=self._ejecutar_vinculacion_docente,
            state='disabled'
        )
        self._btn_vincular_profesor.pack(side='left', padx=2)

        self._btn_desvincular_profesor = ttk.Button(
            f_doc_sel,
            text="Desvincular (Sin Profesor)",
            command=self._desvincular_docente_materia,
            state='disabled'
        )
        self._btn_desvincular_profesor.pack(side='left', padx=2)

        # Fila 2: Modalidad y Toggle de Horario Manual
        f_modo_linea = ttk.Frame(f_docente_vinculo, style='blue.TFrame')
        f_modo_linea.pack(fill='x', padx=6, pady=3)

        ttk.Label(f_modo_linea, text="Modalidad:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(0, 4))
        self.combo_modalidad_vinculo = ttk.Combobox(
            f_modo_linea,
            values=["Presencial", "Mediación Tecnológica"],
            state="readonly",
            width=20,
            font=self._fuente_label
        )
        self.combo_modalidad_vinculo.set("Presencial")
        self.combo_modalidad_vinculo.pack(side='left', padx=(0, 10))

        self._horario_manual_visible = False
        self._btn_toggle_horario_manual = ttk.Button(
            f_modo_linea,
            text="⚙ Horario y Días Manual ▼",
            command=self._toggle_horario_manual
        )
        self._btn_toggle_horario_manual.pack(side='left', padx=4)

        # Fila 3: Subpanel Desplegable de Horario y Días Manual (inicialmente no empaquetado)
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
            text="💾 Aplicar Horario Manual",
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

        # --- Profesor info y Periodos legacy (colapsable / secundario) ---
        f_prof_info = ttk.LabelFrame(self.frame_izq, text="Detalle del Profesor Seleccionado", style='blue.TFrame')
        f_prof_info.pack(fill='x', padx=8, pady=4)

        f_cuenta = ttk.Frame(f_prof_info, style='blue.TFrame')
        f_cuenta.pack(fill='x', padx=6, pady=2)
        ttk.Label(f_cuenta, text="No. Cuenta:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left')
        self.entry_no_cuenta = ttk.Entry(f_cuenta, font=self._fuente_label, state='readonly')
        self.entry_no_cuenta.pack(side='left', fill='x', expand=True, padx=(6, 0))

        f_nombre = ttk.Frame(f_prof_info, style='blue.TFrame')
        f_nombre.pack(fill='x', padx=6, pady=2)
        ttk.Label(f_nombre, text="Nombre:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left')
        self.entry_nombre_prof = ttk.Entry(f_nombre, font=self._fuente_label, state='readonly')
        self.entry_nombre_prof.pack(side='left', fill='x', expand=True, padx=(6, 0))

        btn_limpiar = ttk.Button(f_prof_info, text="Limpiar Profesor", command=self._limpiar_profesor_seleccionado)
        btn_limpiar.pack(pady=(2, 4))

        self._label_horas = ttk.Label(self.frame_izq, text="", background='#0A0F1E', foreground='#FFD700', font=self._fuente_label)
        self._label_horas.pack(fill='x', padx=10, pady=(2, 0))

        # Contenedor para periodos de disponibilidad manual si se requiere
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

        f_busqueda = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_busqueda.pack(fill='x', pady=(2, 2))
        ttk.Label(f_busqueda, text="Buscar:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=5)
        self.sv_busqueda_asignaciones = tk.StringVar()
        self.sv_busqueda_asignaciones.trace_add("write", lambda *a: self._programar_actualizacion_vista_previa())
        entry_busqueda = ttk.Entry(f_busqueda, textvariable=self.sv_busqueda_asignaciones, font=self._fuente_label)
        entry_busqueda.pack(side='left', fill='x', expand=True, padx=(0, 5))

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

        # --- Acciones ---
        f_acciones = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_acciones.pack(fill='x', padx=6, pady=4)
        ttk.Button(f_acciones, text="Liberar", command=self.borrar_asignacion_seleccionada).pack(side='left', padx=4)
        ttk.Button(f_acciones, text="Borrar Todas", command=self.formatear_asignaciones).pack(side='left', padx=4)
        ttk.Separator(f_acciones, orient='vertical').pack(side='left', fill='y', padx=8)
        ttk.Button(f_acciones, text="📸 Snapshot", command=self._crear_punto_restauracion).pack(side='left', padx=4)
        ttk.Button(f_acciones, text="⏪ Deshacer / Restaurar", command=self._abrir_dialogo_restaurar_punto).pack(side='left', padx=4)

        self.frame_previa_horario = ttk.LabelFrame(
            self.frame_der, text="Horario del grupo", style='blue.TFrame'
        )
        self.frame_previa_horario.pack(fill='x', padx=6, pady=(4, 8))
        f_top_previa = ttk.Frame(self.frame_previa_horario, style='blue.TFrame')
        f_top_previa.pack(fill='x', padx=4, pady=(2, 2))
        ttk.Button(
            f_top_previa,
            text="🔄 Volver a preasignar grupo",
            command=self._confirmar_volver_a_preasignar_grupo
        ).pack(side='left', padx=4)
        ttk.Button(
            f_top_previa,
            text="Ajustar vista",
            command=self._abrir_previa_horario_ajustada
        ).pack(side='right', padx=4)
        self.canvas_previa_horario = tk.Canvas(
            self.frame_previa_horario, height=566, background='white',
            highlightthickness=0
        )
        self.canvas_previa_horario.pack(fill='x', expand=True, padx=4, pady=4)
        self.canvas_previa_horario.bind(
            '<Configure>', lambda event: self._dibujar_previa_horario_grupo(
                self.canvas_previa_horario
            )
        )

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

    # --- UTILIDADES ---

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

    def _on_cambio_grupo_gestion(self, event=None):
        self._materia_grupo_seleccionada_id = None
        self._cargar_materias_grupo_gestion()
        self._actualizar_estado_boton_vinculo()
        if hasattr(self, '_sv_filtro_grupo_vp'):
            g = self._sv_grupo_gestion.get().strip()
            if g:
                self._seleccionar_grupo_previa(g)

    def _cargar_materias_grupo_gestion(self):
        if not hasattr(self, 'tabla_materias_grupo'):
            return
        for item in self.tabla_materias_grupo.get_children():
            self.tabla_materias_grupo.delete(item)

        grupo_id = self._sv_grupo_gestion.get().strip()
        if not grupo_id:
            self._lbl_info_grupo_gestion.config(text="Selecciona un grupo para ver sus materias preasignadas.")
            return

        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            cur.execute("""
                SELECT 
                    a.asignacion_id,
                    a.materia_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(a.dias, '') AS dias,
                    a.hora_inicio,
                    a.hora_fin,
                    a.profesor_id,
                    IFNULL(p.nombre, 'Sin profesor') AS prof_nombre,
                    IFNULL(a.estado, 'no asignado') AS estado,
                    GROUP_CONCAT(DISTINCT h.salon_id) AS salones,
                    IFNULL(a.modalidad, 'Presencial') AS modalidad
                FROM asignaciones a
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                LEFT JOIN horarios h ON a.asignacion_id = h.asignacion_id
                WHERE a.grupo_id = %s AND (a.estado IS NULL OR a.estado != 'cancelada')
                GROUP BY a.asignacion_id
                ORDER BY a.materia_id
            """, (grupo_id,))
            filas = cur.fetchall()

        if not filas:
            # Si no hay registros en 'asignaciones', consultar si el grupo tiene materias en 'grupo_materias'
            filas_gm = []
            with obtener_cursor() as ctx:
                if ctx:
                    cur, conn = ctx
                    cur.execute("""
                        SELECT gm.materia_id, m.nombre
                        FROM grupo_materias gm
                        JOIN materias m ON gm.materia_id = m.materia_id
                        WHERE gm.grupo_id = %s
                        ORDER BY m.materia_id
                    """, (grupo_id,))
                    filas_gm = cur.fetchall()

            if filas_gm:
                self._materias_grupo_cache = {}
                for fgm in filas_gm:
                    m_id, m_nom = fgm
                    item_id = f"gm_{m_id}"
                    self.tabla_materias_grupo.insert(
                        '', 'end', iid=item_id,
                        values=(f"{m_id} - {m_nom}", "Sin preasignar", "Presencial", "Pendiente", "Pendiente", "Sin profesor", "NO PREASIGNADO")
                    )
                self._lbl_info_grupo_gestion.config(
                    text=f"Grupo: {grupo_id} | {len(filas_gm)} materias sin preasignar. Presiona '⚡ Volver a preasignar' para asignar aula y horarios."
                )
                self._actualizar_estado_boton_vinculo()
                return

        self._materias_grupo_cache = {}
        total_asignadas = 0
        for f in filas:
            asig_id, m_id, m_nom, dias, hi, hf, prof_id, prof_nom, estado, salones, modalidad = f
            hi_str = self._hora_db_a_str(hi) if hi else ""
            hf_str = self._hora_db_a_str(hf) if hf else ""
            horario_str = f"{hi_str} - {hf_str}" if hi_str and hf_str else "Sin horario"
            aula_str = salones if salones else "Sin aula"
            p_display = "Sin profesor" if (not prof_id or prof_id == 'SIN_ASIGNAR') else prof_nom
            if p_display != "Sin profesor":
                total_asignadas += 1

            info_asig = {
                "asignacion_id": asig_id,
                "materia_id": m_id,
                "materia_nombre": m_nom,
                "dias": dias,
                "hora_inicio": hi_str,
                "hora_fin": hf_str,
                "profesor_id": prof_id,
                "profesor_nombre": p_display,
                "estado": estado,
                "salon_id": aula_str,
                "modalidad": modalidad
            }
            self._materias_grupo_cache[str(asig_id)] = info_asig

            self.tabla_materias_grupo.insert(
                '', 'end', iid=str(asig_id),
                values=(f"{m_id} - {m_nom}", aula_str, modalidad, dias, horario_str, p_display, estado.upper())
            )

        self._lbl_info_grupo_gestion.config(
            text=f"Grupo: {grupo_id} | Total Materias: {len(filas)} | Con Profesor: {total_asignadas} / {len(filas)}"
        )
        self._actualizar_estado_boton_vinculo()

    def _toggle_horario_manual(self):
        if getattr(self, '_horario_manual_visible', False):
            self._frame_horario_manual.pack_forget()
            self._horario_manual_visible = False
            self._btn_toggle_horario_manual.config(text="⚙ Horario y Días Manual ▼")
        else:
            self._frame_horario_manual.pack(fill='x', padx=6, pady=4, before=self._lbl_estado_vinculo)
            self._horario_manual_visible = True
            self._btn_toggle_horario_manual.config(text="⚙ Ocultar Horario Manual ▲")

    def _cargar_salones_para_manual(self):
        try:
            with obtener_cursor() as ctx:
                if ctx:
                    cur, conn = ctx
                    cur.execute("SELECT DISTINCT salon_id FROM salones WHERE salon_id NOT LIKE 'MEDIACION%' ORDER BY salon_id")
                    salones = [r[0] for r in cur.fetchall()]
                    if hasattr(self, 'combo_manual_aula'):
                        self.combo_manual_aula['values'] = salones
                        if salones and not self.combo_manual_aula.get():
                            self.combo_manual_aula.set(salones[0])
        except Exception as e:
            print(f"Error cargando salones manuales: {e}")

    def _on_select_materia_grupo_gestion(self, event=None):
        sel = self.tabla_materias_grupo.selection()
        if not sel:
            self._materia_grupo_seleccionada_id = None
        else:
            self._materia_grupo_seleccionada_id = sel[0]
            asig_info = self._materias_grupo_cache.get(str(sel[0]))
            if asig_info:
                if hasattr(self, 'combo_modalidad_vinculo'):
                    self.combo_modalidad_vinculo.set(asig_info.get('modalidad') or 'Presencial')
                if hasattr(self, 'combo_manual_hora_i') and asig_info.get('hora_inicio'):
                    self.combo_manual_hora_i.set(self._hora_db_a_str(asig_info['hora_inicio']))
                if hasattr(self, 'combo_manual_hora_f') and asig_info.get('hora_fin'):
                    self.combo_manual_hora_f.set(self._hora_db_a_str(asig_info['hora_fin']))
                if hasattr(self, 'combo_manual_aula') and asig_info.get('salon_id'):
                    aula = asig_info['salon_id'].split(',')[0].strip()
                    if aula and aula != "Sin aula":
                        self.combo_manual_aula.set(aula)
                if hasattr(self, '_vars_dias_manual'):
                    dias_act = [d.strip() for d in (asig_info.get('dias') or '').split(',') if d.strip()]
                    for d_nom, var in self._vars_dias_manual.items():
                        var.set(d_nom in dias_act)
        self._actualizar_estado_boton_vinculo()

    def _actualizar_estado_boton_vinculo(self):
        asig_id = self._materia_grupo_seleccionada_id
        prof_id = self._profesor_id_seleccionado

        asig_info = self._materias_grupo_cache.get(str(asig_id)) if asig_id else None

        if hasattr(self, '_btn_guardar_manual'):
            self._btn_guardar_manual.config(state='normal' if asig_info else 'disabled')

        if asig_info:
            p_actual = asig_info.get("profesor_nombre", "Sin profesor")
            tiene_prof = (asig_info.get("profesor_id") and asig_info.get("profesor_id") != 'SIN_ASIGNAR')
            if hasattr(self, '_btn_desvincular_profesor'):
                self._btn_desvincular_profesor.config(state='normal' if tiene_prof else 'disabled')

            if prof_id:
                prof_info = self.profesores_map.get(str(prof_id), {})
                p_nombre_sel = prof_info.get("nombre", prof_id)
                self._lbl_estado_vinculo.config(
                    text=f"Materia: {asig_info['materia_nombre']} | Horario: {asig_info['hora_inicio']}-{asig_info['hora_fin']} [{asig_info['dias']}] (Aula: {asig_info['salon_id']}) [{asig_info.get('modalidad', 'Presencial')}]\n"
                         f"Docente a vincular: {p_nombre_sel}",
                    foreground='#98FB98'
                )
                if hasattr(self, '_btn_vincular_profesor'):
                    self._btn_vincular_profesor.config(state='normal')
            else:
                self._lbl_estado_vinculo.config(
                    text=f"Materia seleccionada: {asig_info['materia_nombre']} ({p_actual}) [{asig_info.get('modalidad', 'Presencial')}]. Selecciona un profesor de la tabla derecha.",
                    foreground='#FFD700'
                )
                if hasattr(self, '_btn_vincular_profesor'):
                    self._btn_vincular_profesor.config(state='disabled')
        else:
            if hasattr(self, '_btn_vincular_profesor'):
                self._btn_vincular_profesor.config(state='disabled')
            if hasattr(self, '_btn_desvincular_profesor'):
                self._btn_desvincular_profesor.config(state='disabled')
            self._lbl_estado_vinculo.config(
                text="Selecciona una materia preasignada arriba y un profesor a la derecha para vincular.",
                foreground='#7E8B9B'
            )

    def _validar_disponibilidad_profesor(self, prof_id, dias_lista, hora_i, hora_f):
        if not prof_id or prof_id == 'SIN_ASIGNAR':
            return False, ""
        disp_choque = False
        disp_detalle = ""
        with obtener_cursor() as ctx:
            if ctx:
                cur, conn = ctx
                cur.execute(
                    "SELECT dia, hora_inicio, hora_fin FROM profesor_disponibilidad WHERE profesor_id = %s",
                    (prof_id,)
                )
                disp_rows = cur.fetchall()
                if disp_rows:
                    ini_min = self._minutos_hora_previa(hora_i)
                    fin_min = self._minutos_hora_previa(hora_f)
                    dias_indices = [self._dia_a_indice_previa(d) for d in dias_lista if self._dia_a_indice_previa(d) is not None]

                    cubiertos = set()
                    for d_idx in dias_indices:
                        for row_dia, row_hi, row_hf in disp_rows:
                            r_d_idx = self._dia_a_indice_previa(row_dia)
                            r_ini = self._minutos_hora_previa(row_hi)
                            r_fin = self._minutos_hora_previa(row_hf)
                            if r_d_idx == d_idx and r_ini is not None and r_fin is not None:
                                if r_ini <= ini_min and fin_min <= r_fin:
                                    cubiertos.add(d_idx)
                                    break
                    if len(cubiertos) < len(dias_indices):
                        disp_choque = True
                        disp_detalle = f"El horario ({hora_i} - {hora_f} en {', '.join(dias_lista)}) excede o no coincide con los periodos de disponibilidad registrados del profesor."
        return disp_choque, disp_detalle

    def _detectar_choques_aula(self, salon_id, asignacion_id, dias, hora_i, hora_f):
        if not salon_id or salon_id in ("Sin aula", "") or str(salon_id).upper().startswith("MEDIACION"):
            return []
        inicio = self._minutos_hora_previa(hora_i)
        fin = self._minutos_hora_previa(hora_f)
        dias_propuestos = {
            indice for indice in (self._dia_a_indice_previa(dia) for dia in dias)
            if indice is not None
        }
        if inicio is None or fin is None or fin <= inicio or not dias_propuestos:
            return []

        choques = []
        with obtener_cursor_dict() as ctx:
            if ctx is None:
                return []
            cur, conn = ctx
            cur.execute("""
                SELECT h.dia, h.hora_inicio, h.hora_fin, a.grupo_id, IFNULL(m.nombre, a.materia_id) AS materia,
                       a.asignacion_id, a.profesor_id, IFNULL(p.nombre, 'Sin profesor') AS profesor_nombre
                FROM horarios h
                JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                WHERE LOWER(h.salon_id) = LOWER(%s)
                  AND h.asignacion_id <> %s
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
            """, (salon_id, asignacion_id or -1))
            filas = cur.fetchall()
            for f in filas:
                indice_dia = self._dia_a_indice_previa(f['dia'])
                if indice_dia in dias_propuestos:
                    ini_ex = self._minutos_hora_previa(f['hora_inicio'])
                    fin_ex = self._minutos_hora_previa(f['hora_fin'])
                    if ini_ex is not None and fin_ex is not None:
                        if inicio < fin_ex and fin > ini_ex:
                            choques.append({
                                "dia": self.NOMBRES_DIAS[indice_dia] if indice_dia < len(self.NOMBRES_DIAS) else str(f['dia']),
                                "inicio": f['hora_inicio'],
                                "fin": f['hora_fin'],
                                "grupo_id": f['grupo_id'],
                                "materia": f['materia'],
                                "asignacion_id": f.get('asignacion_id'),
                                "profesor_id": f.get('profesor_id'),
                                "profesor_nombre": f.get('profesor_nombre')
                            })
        return choques

    def _aplicar_horario_manual_seleccionada(self):
        asig_id = self._materia_grupo_seleccionada_id
        if not asig_id:
            messagebox.showwarning("Aviso", "Selecciona primero una materia de la tabla de materias preasignadas.")
            return

        asig_info = self._materias_grupo_cache.get(str(asig_id))
        if not asig_info:
            messagebox.showerror("Error", "No se encontró la información de la materia seleccionada.")
            return

        hora_i = self.combo_manual_hora_i.get().strip()
        hora_f = self.combo_manual_hora_f.get().strip()
        aula_sel = self.combo_manual_aula.get().strip()
        modalidad_sel = self.combo_modalidad_vinculo.get().strip() or "Presencial"
        dias_sel = [d for d, var in self._vars_dias_manual.items() if var.get()]

        # 1. Validar horas
        ini_min = self._minutos_hora_previa(hora_i)
        fin_min = self._minutos_hora_previa(hora_f)
        if ini_min is None or fin_min is None or fin_min <= ini_min:
            messagebox.showerror("Horario Inválido", "La hora de fin debe ser posterior a la hora de inicio.")
            return

        # 2. Validar días
        if not dias_sel:
            messagebox.showwarning("Días Requeridos", "Debes seleccionar al menos un día para el horario manual.")
            return

        # 3. Límite vespertino (17:00 hrs = 1020 min)
        if fin_min > 17 * 60:
            if not messagebox.askyesno(
                "Horario Vespertino",
                f"La hora de fin ({hora_f}) excede las 17:00 hrs.\n"
                f"La normativa institucional establece las 17:00 hrs como límite para las asignaciones.\n\n"
                f"¿Desea continuar de todos modos?"
            ):
                return

        # 4. Validar horas semanales de la materia
        duracion_sesion_horas = (fin_min - ini_min) / 60.0
        total_horas_manual = duracion_sesion_horas * len(dias_sel)
        horas_requeridas = self._get_horas_materia(asig_info['materia_id'])
        if horas_requeridas > 0 and abs(total_horas_manual - horas_requeridas) > 0.01:
            if not messagebox.askyesno(
                "Discrepancia de Horas Semanales",
                f"La materia '{asig_info['materia_nombre']}' requiere {int(horas_requeridas)} hrs/semana según plan de estudios.\n\n"
                f"La configuración manual suma {total_horas_manual:.1f} hrs/semana ({len(dias_sel)} días x {duracion_sesion_horas:.1f} hrs/día).\n\n"
                f"¿Desea aplicar este horario de todos modos?"
            ):
                return

        # 5. Choque de Grupo
        grupo_id = self._sv_grupo_gestion.get().strip()
        choques_grupo = self._detectar_choques_grupo(grupo_id, asig_info['materia_id'], dias_sel, hora_i, hora_f, excluir_asignacion_id=asig_id)
        if choques_grupo:
            detalles = "\n".join([f"• {c['dia']} {c['inicio']}-{c['fin']}: {c['materia']}" for c in choques_grupo])
            messagebox.showerror(
                "Conflicto de Horario del Grupo",
                f"El grupo '{grupo_id}' ya tiene materias asignadas en ese horario:\n\n{detalles}\n\nNo es posible sobreponer materias para el mismo grupo."
            )
            return

        # 6. Choque de Aula (si es presencial)
        if modalidad_sel == "Mediación Tecnológica":
            if not aula_sel or aula_sel == "Sin aula":
                aula_sel = "MEDIACION_TECNOLOGICA"
        else:
            if not aula_sel or aula_sel == "Sin aula":
                messagebox.showwarning("Aula requerida", "Para la modalidad presencial debes seleccionar un aula válida.")
                return
            choques_aula = self._detectar_choques_aula(aula_sel, asig_id, dias_sel, hora_i, hora_f)
            if choques_aula:
                detalles = "\n".join([f"• {c['dia']} {c['inicio']}-{c['fin']}: Grupo {c['grupo_id']} ({c['materia']})" for c in choques_aula])
                messagebox.showerror(
                    "Conflicto de Aula",
                    f"El aula '{aula_sel}' ya está ocupada en ese horario:\n\n{detalles}\n\nSeleccione otra aula u otro horario."
                )
                return

        # 7. Choque de Profesor (si ya tiene profesor asignado)
        prof_id = asig_info.get('profesor_id')
        if prof_id and prof_id != 'SIN_ASIGNAR':
            choques_profesor = []
            try:
                choques_profesor = self._detectar_choques_profesor(
                    prof_id, asig_info['materia_id'], grupo_id, modalidad_sel, dias_sel, hora_i, hora_f, excluir_asignacion_id=asig_id
                )
            except Exception as e:
                print(f"Error comprobando choques de profesor: {e}")
            disp_choque, disp_detalle = self._validar_disponibilidad_profesor(prof_id, dias_sel, hora_i, hora_f)

            if choques_profesor or disp_choque:
                self._mostrar_modal_resolucion_conflicto(
                    asig_info=asig_info,
                    prof_id=prof_id,
                    prof_nombre=asig_info.get('profesor_nombre', prof_id),
                    choques=choques_profesor,
                    motivo_disp=disp_detalle
                )
                return

        # 8. Persistir en la base de datos
        dias_str = ", ".join(dias_sel)
        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            try:
                cur.execute("""
                    UPDATE asignaciones
                    SET hora_inicio = %s, hora_fin = %s, dias = %s, modalidad = %s
                    WHERE asignacion_id = %s
                """, (hora_i, hora_f, dias_str, modalidad_sel, asig_id))

                cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (asig_id,))
                for d in dias_sel:
                    cur.execute("""
                        INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (asig_id, aula_sel, d, f"{hora_i}:00" if len(hora_i) == 5 else hora_i, f"{hora_f}:00" if len(hora_f) == 5 else hora_f))

                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error actualizando horario manual: {err}")
                return

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo("Éxito", f"Horario manual asignado correctamente a '{asig_info['materia_nombre']}':\n{dias_str} de {hora_i} a {hora_f} en {aula_sel} ({modalidad_sel}).")

    def _desvincular_docente_materia(self):
        asig_id = self._materia_grupo_seleccionada_id
        if not asig_id:
            return
        asig_info = self._materias_grupo_cache.get(str(asig_id))
        if not asig_info:
            return

        if not messagebox.askyesno(
            "Confirmar Desvinculación",
            f"¿Desea desvincular al docente de la materia '{asig_info['materia_nombre']}'?\n"
            f"La materia conservará su aula y horario preasignados y volverá al estado 'Sin profesor'."
        ):
            return

        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            try:
                cur.execute("""
                    UPDATE asignaciones
                    SET profesor_id = 'SIN_ASIGNAR', estado = 'no asignado'
                    WHERE asignacion_id = %s
                """, (asig_id,))
                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"No se pudo desvincular: {err}")
                return

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo("Éxito", "Docente desvinculado. La materia ahora se muestra como 'Sin profesor'.")

    def _detectar_compactacion_docente(self, prof_id, asig_id, materia_id, grupo_id, modalidad, aula_actual):
        """
        Detecta si el docente ya tiene otras clases asignadas y busca acomodar la nueva materia
        en los MISMOS días que sus clases existentes, en horario corrido (contiguo),
        para compactar su jornada a la menor cantidad de días posibles (ej. concentrar en 2 días).
        """
        if not prof_id or prof_id == 'SIN_ASIGNAR':
            return None

        # 1. Consultar asignaciones activas existentes del profesor
        with obtener_cursor_dict() as ctx:
            if not ctx:
                return None
            cur, conn = ctx
            cur.execute("""
                SELECT a.asignacion_id, a.materia_id, IFNULL(m.nombre, a.materia_id) as materia_nombre,
                       a.grupo_id, h.dia, h.hora_inicio, h.hora_fin, h.salon_id
                FROM asignaciones a
                JOIN materias m ON a.materia_id = m.materia_id
                JOIN horarios h ON a.asignacion_id = h.asignacion_id
                WHERE a.profesor_id = %s
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
                  AND a.asignacion_id != %s
                ORDER BY h.dia, h.hora_inicio
            """, (prof_id, asig_id or -1))
            clases_existentes = cur.fetchall()

        if not clases_existentes:
            return None

        # 2. Extraer los días en los que el profesor ya imparte clase
        dias_prof = {}
        for c in clases_existentes:
            d_norm = self._normalizar_dia(c['dia'])
            d_nombre = getattr(self, 'MAPA_DIAS', {}).get(d_norm, c['dia'])
            if d_nombre not in dias_prof:
                dias_prof[d_nombre] = []
            ini_m = self._minutos_hora_previa(c['hora_inicio'])
            fin_m = self._minutos_hora_previa(c['hora_fin'])
            if ini_m is not None and fin_m is not None:
                dias_prof[d_nombre].append({
                    "ini": ini_m,
                    "fin": fin_m,
                    "hi": self._hora_db_a_str(c['hora_inicio']),
                    "hf": self._hora_db_a_str(c['hora_fin']),
                    "materia": c['materia_nombre'],
                    "grupo": c['grupo_id'],
                    "aula": c['salon_id']
                })

        dias_unicos = list(dias_prof.keys())
        parejas_posibles = [
            ["Lunes", "Miércoles"],
            ["Martes", "Jueves"],
            ["Miércoles", "Viernes"],
            ["Viernes", "Sábado"],
            ["Lunes", "Viernes"]
        ]

        dias_objetivo = None
        for p in parejas_posibles:
            if any(d in dias_prof for d in p):
                dias_objetivo = p
                break
        if not dias_objetivo:
            dias_objetivo = dias_unicos[:2] if len(dias_unicos) >= 2 else dias_unicos

        min_hora = 24 * 60
        max_hora = 0
        horas_ocupadas_prof = []
        for d in dias_objetivo:
            for c in dias_prof.get(d, []):
                min_hora = min(min_hora, c['ini'])
                max_hora = max(max_hora, c['fin'])
                horas_ocupadas_prof.append((c['ini'], c['fin']))

        if not horas_ocupadas_prof:
            return None

        h_req = self._get_horas_materia(materia_id)
        if h_req and len(dias_objetivo) > 0:
            duracion_min = int((h_req / len(dias_objetivo)) * 60)
        else:
            duracion_min = 120

        franjas_candidatas = []
        # Prioridad 1: Corrida posterior a la última clase del profesor
        if max_hora + duracion_min <= 17 * 60:
            franjas_candidatas.append((max_hora, max_hora + duracion_min, True))

        # Prioridad 2: Corrida anterior a la primera clase del profesor
        if min_hora - duracion_min >= 7 * 60:
            franjas_candidatas.append((min_hora - duracion_min, min_hora, True))

# Solo evaluar franjas continuas (clases corridas contiguas)

        if not aula_actual or aula_actual in ("Sin aula", ""):
            return None
        aula_objetivo = aula_actual

        resumen_existentes = []
        for d in dias_objetivo:
            for c in dias_prof.get(d, []):
                resumen_existentes.append(f"• {d} {c['hi']}-{c['hf']}: {c['materia']} (Grupo {c['grupo']}) en Aula {c['aula']}")

        docentes_en_conflicto = set()

        # Datos de la asignación original para evaluar swap si hay materia sin profesor
        orig_hi = ""
        orig_hf = ""
        orig_dias_str = ""
        orig_dias = []
        asig_info_act = getattr(self, '_materias_grupo_cache', {}).get(str(asig_id), {})
        if asig_info_act:
            orig_hi = self._hora_db_a_str(asig_info_act.get('hora_inicio')) if asig_info_act.get('hora_inicio') else ""
            orig_hf = self._hora_db_a_str(asig_info_act.get('hora_fin')) if asig_info_act.get('hora_fin') else ""
            orig_dias_str = asig_info_act.get('dias') or ""
            orig_dias = [d.strip() for d in orig_dias_str.split(',') if d.strip()]

        for h_ini, h_fin, es_continua in franjas_candidatas:
            hi_str = f"{h_ini // 60:02d}:{h_ini % 60:02d}"
            hf_str = f"{h_fin // 60:02d}:{h_fin % 60:02d}"

            ch_prof = self._detectar_choques_profesor(
                prof_id, materia_id, grupo_id, modalidad, dias_objetivo, hi_str, hf_str, excluir_asignacion_id=asig_id
            )
            if ch_prof:
                continue

            disp_ch, _ = self._validar_disponibilidad_profesor(prof_id, dias_objetivo, hi_str, hf_str)
            if disp_ch:
                continue

            ch_grupo = self._detectar_choques_grupo(
                grupo_id, materia_id, dias_objetivo, hi_str, hf_str, excluir_asignacion_id=asig_id
            )
            if ch_grupo:
                continue

            # Revisar choques en el aula_objetivo (exclusivamente en aula_actual, sin cambiar de salón)
            ch_aula = self._detectar_choques_aula(aula_objetivo, asig_id, dias_objetivo, hi_str, hf_str)
            if not ch_aula:
                # El aula está completamente libre en este horario corrido
                return {
                    "encontrado": True,
                    "dias": dias_objetivo,
                    "dias_str": ", ".join(dias_objetivo),
                    "hora_i": hi_str,
                    "hora_f": hf_str,
                    "salon": aula_objetivo,
                    "es_continua": es_continua,
                    "clases_actuales": resumen_existentes,
                    "desplazamiento": None
                }
            else:
                # El aula está ocupada. Comprobar si los ocupantes tienen profesor asignado
                tiene_otro_prof = False
                ocupantes_sin_prof = []
                for c in ch_aula:
                    p_id = c.get('profesor_id')
                    p_nom = c.get('profesor_nombre', 'Sin profesor')
                    if p_id and str(p_id).strip() != 'SIN_ASIGNAR' and str(p_id).strip() != str(prof_id):
                        tiene_otro_prof = True
                        if p_nom and p_nom != 'Sin profesor':
                            docentes_en_conflicto.add(p_nom)
                    else:
                        ocupantes_sin_prof.append(c)

                if tiene_otro_prof:
                    # Ocupado por otro profesor con clase asignada: NO desplazar para no afectarlo
                    continue

                if ocupantes_sin_prof and orig_hi and orig_hf and orig_dias:
                    # Desplazar la materia sin profesor al horario vacante en el mismo salón
                    asig_disp = ocupantes_sin_prof[0]
                    ch_grp_disp = self._detectar_choques_grupo(
                        asig_disp['grupo_id'], asig_disp.get('materia', ''), orig_dias, orig_hi, orig_hf,
                        excluir_asignacion_id=asig_id
                    )
                    if not ch_grp_disp:
                        return {
                            "encontrado": True,
                            "dias": dias_objetivo,
                            "dias_str": ", ".join(dias_objetivo),
                            "hora_i": hi_str,
                            "hora_f": hf_str,
                            "salon": aula_objetivo,
                            "es_continua": es_continua,
                            "clases_actuales": resumen_existentes,
                            "desplazamiento": {
                                "asignacion_id": asig_disp.get('asignacion_id'),
                                "materia_nombre": asig_disp.get('materia', 'Materia sin profesor'),
                                "grupo_id": asig_disp['grupo_id'],
                                "nuevo_hora_i": orig_hi,
                                "nuevo_hora_f": orig_hf,
                                "nuevos_dias": orig_dias,
                                "nuevos_dias_str": orig_dias_str,
                                "salon": aula_objetivo
                            }
                        }

        # No fue posible el acomodo en el salón sin afectar a otros profesores
        txt_prof = f" (horario ocupado por: {', '.join(sorted(docentes_en_conflicto))})" if docentes_en_conflicto else ""
        return {
            "encontrado": False,
            "motivo": "sin_lugar_en_aula",
            "salon": aula_objetivo,
            "mensaje": f"No fue posible compactar la jornada en horario contiguo en el aula '{aula_objetivo}' sin afectar los horarios de otros profesores asignados{txt_prof}."
        }

    def _mostrar_dialogo_sugerencia_compactacion(self, asig_info, prof_nombre, compactacion):
        """
        Diálogo interactivo para sugerir la compactación de la carga del docente en la menor
        cantidad de días posible con clases corridas (contiguas).
        Retorna True si el usuario acepta, False si prefiere mantener el original, None si cancela.
        """
        resultado = [False]

        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Optimización de Jornada Docente")
        dialogo.transient(self.ventana)
        dialogo.grab_set()
        dialogo.configure(background='#0A0F1E')

        ancho_dlg = 760
        alto_dlg = 640

        try:
            self.ventana.update_idletasks()
            px = self.ventana.winfo_rootx() + (self.ventana.winfo_width() // 2) - (ancho_dlg // 2)
            py = self.ventana.winfo_rooty() + (self.ventana.winfo_height() // 2) - (alto_dlg // 2)
            if px < 20: px = 20
            if py < 20: py = 20
            dialogo.geometry(f"{ancho_dlg}x{alto_dlg}+{px}+{py}")
        except Exception:
            dialogo.geometry(f"{ancho_dlg}x{alto_dlg}")

        dialogo.minsize(680, 500)
        dialogo.resizable(True, True)

        # 1. PIE DE PÁGINA (Botones SIEMPRE visibles y anclados al fondo)
        f_btns = ttk.Frame(dialogo, style='blue.TFrame')
        f_btns.pack(side='bottom', fill='x', padx=20, pady=(10, 16))

        def _aceptar():
            resultado[0] = True
            dialogo.destroy()

        def _conservar():
            resultado[0] = False
            dialogo.destroy()

        def _cancelar():
            resultado[0] = None
            dialogo.destroy()

        btn_cancelar = ttk.Button(f_btns, text="Cancelar", command=_cancelar)
        btn_cancelar.pack(side='right', padx=6)

        btn_conservar = ttk.Button(f_btns, text="Mantener Horario Original", command=_conservar)
        btn_conservar.pack(side='right', padx=6)

        btn_compactar = ttk.Button(f_btns, text="⚡ Sí, Compactar Horario", command=_aceptar)
        btn_compactar.pack(side='right', padx=6)

        sep = ttk.Separator(dialogo, orient='horizontal')
        sep.pack(side='bottom', fill='x', padx=16, pady=(4, 0))

        # 2. ÁREA CENTRAL DESPLAZABLE (Canvas con Scrollbar para garantizar visualización total)
        f_scroll_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_scroll_cont.pack(side='top', fill='both', expand=True, padx=16, pady=(14, 4))

        canvas = tk.Canvas(f_scroll_cont, background='#0A0F1E', highlightthickness=0, bd=0)
        sb_v = ttk.Scrollbar(f_scroll_cont, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=sb_v.set)

        sb_v.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        f_cont = ttk.Frame(canvas, style='blue.TFrame')
        canvas_window = canvas.create_window((0, 0), window=f_cont, anchor='nw')

        def _on_canvas_configure(evt):
            canvas.itemconfig(canvas_window, width=evt.width)
        canvas.bind('<Configure>', _on_canvas_configure)

        def _on_frame_configure(evt):
            canvas.configure(scrollregion=canvas.bbox("all"))
        f_cont.bind('<Configure>', _on_frame_configure)

        def _on_mousewheel(evt):
            try:
                delta = -1 if evt.delta < 0 else 1
                canvas.yview_scroll(delta * -1, "units")
            except Exception:
                pass

        def _bind_mousewheel(evt=None):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_mousewheel(evt=None):
            try:
                canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass

        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)
        dialogo.bind("<Destroy>", _unbind_mousewheel)

        # 3. CONTENIDO DEL DIÁLOGO
        ttk.Label(
            f_cont,
            text="⚡ Sugerencia: Compactación Continua de Jornada",
            background='#0A0F1E',
            foreground='#FFD700',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 6))

        ttk.Label(
            f_cont,
            text=f"El profesor {prof_nombre} ya cuenta con clases asignadas. El motor detectó una oportunidad para concentrar su asistencia en 2 días con clases corridas (sin tiempos muertos):",
            background='#0A0F1E',
            foreground='#CFD8DC',
            font=self._fuente_label,
            wraplength=670,
            justify='left'
        ).pack(anchor='w', pady=(0, 10))

        # Bloque 1: Clases asignadas actualmente
        f_exist = ttk.LabelFrame(f_cont, text=" Clases ya asignadas a este profesor ", style='blue.TFrame')
        f_exist.pack(fill='x', pady=4)
        txt_exist = "\n".join(compactacion['clases_actuales'][:6])
        ttk.Label(
            f_exist,
            text=txt_exist,
            background='#0A0F1E',
            foreground='#90CAF9',
            font=self._fuente_label,
            justify='left'
        ).pack(anchor='w', padx=12, pady=8)

        # Bloque 2: Comparativa de Horarios
        f_prop = ttk.LabelFrame(f_cont, text=" Comparativa de Asignación ", style='blue.TFrame')
        f_prop.pack(fill='x', pady=6)

        h_act = f"{asig_info.get('hora_inicio')} a {asig_info.get('hora_fin')} [{asig_info.get('dias')}] en Aula {asig_info.get('salon_id')}"
        tipo_continua = " (Clase corrida contigua)" if compactacion.get('es_continua') else " (Mismos días)"
        h_sug = f"{compactacion['hora_i']} a {compactacion['hora_f']} [{compactacion['dias_str']}] en Aula {compactacion['salon']}{tipo_continua}"

        f_grid = ttk.Frame(f_prop, style='blue.TFrame')
        f_grid.pack(fill='x', padx=10, pady=8)

        ttk.Label(f_grid, text="Horario Preasignado:", background='#0A0F1E', foreground='#B0BEC5', font=self._fuente_sub).grid(row=0, column=0, sticky='w', pady=3)
        ttk.Label(f_grid, text=h_act, background='#0A0F1E', foreground='#FFAB91', font=self._fuente_label, wraplength=490, justify='left').grid(row=0, column=1, sticky='w', padx=10, pady=3)

        ttk.Label(f_grid, text="Propuesta Compactada:", background='#0A0F1E', foreground='#B0BEC5', font=self._fuente_sub).grid(row=1, column=0, sticky='w', pady=3)
        ttk.Label(f_grid, text=h_sug, background='#0A0F1E', foreground='#A5D6A7', font=self._fuente_btn, wraplength=490, justify='left').grid(row=1, column=1, sticky='w', padx=10, pady=3)

        # Bloque 3: Reacomodo en el mismo salón (si aplica)
        desp = compactacion.get('desplazamiento')
        if desp:
            f_desp = ttk.LabelFrame(f_cont, text=" Reacomodo Interno (Mismo Salón) ", style='blue.TFrame')
            f_desp.pack(fill='x', pady=6)
            txt_desp = (
                f"• Para habilitar este horario corrido, la materia '{desp['materia_nombre']}' (Grupo {desp['grupo_id']}),\n"
                f"  que no tiene profesor asignado, se reubicará al horario {desp['nuevo_hora_i']} a {desp['nuevo_hora_f']} [{desp['nuevos_dias_str']}]\n"
                f"  dentro del mismo salón {desp['salon']}."
            )
            ttk.Label(
                f_desp,
                text=txt_desp,
                background='#0A0F1E',
                foreground='#FFE082',
                font=self._fuente_sub,
                wraplength=670,
                justify='left'
            ).pack(anchor='w', padx=12, pady=6)

        # Bloque 4: Lista de verificación de ventajas
        ttk.Label(
            f_cont,
            text=f"✔ Concentra la asistencia del profesor en 2 días.\n✔ Clases corridas sin horas libres intermedias.\n✔ Aula conservada: {compactacion['salon']}.\n✔ Sin afectar a ningún otro profesor.",
            background='#0A0F1E',
            foreground='#81C784',
            font=self._fuente_label,
            justify='left'
        ).pack(anchor='w', pady=(6, 12))

        dialogo.wait_window()
        return resultado[0]

    def _ejecutar_vinculacion_docente(self):
        asig_id = self._materia_grupo_seleccionada_id
        prof_id = self._profesor_id_seleccionado

        if not asig_id or not prof_id:
            messagebox.showwarning("Aviso", "Selecciona una materia del grupo y un profesor para vincular.")
            return

        asig_info = self._materias_grupo_cache.get(str(asig_id))
        if not asig_info:
            messagebox.showerror("Error", "No se encontró la información de la materia preasignada.")
            return

        prof_info = self.profesores_map.get(str(prof_id), {})
        prof_nombre = prof_info.get("nombre", prof_id)
        materia_id = asig_info['materia_id']
        materia_nombre = asig_info['materia_nombre']
        grupo_id = self._sv_grupo_gestion.get().strip()

        modalidad = self.combo_modalidad_vinculo.get().strip() or "Presencial"

        if getattr(self, '_horario_manual_visible', False):
            # Usar valores del panel manual
            hora_i = self.combo_manual_hora_i.get().strip()
            hora_f = self.combo_manual_hora_f.get().strip()
            aula_sel = self.combo_manual_aula.get().strip()
            dias_lista = [d for d, var in self._vars_dias_manual.items() if var.get()]
            dias_str = ", ".join(dias_lista)

            # Validar horas
            ini_min = self._minutos_hora_previa(hora_i)
            fin_min = self._minutos_hora_previa(hora_f)
            if ini_min is None or fin_min is None or fin_min <= ini_min:
                messagebox.showerror("Horario Inválido", "La hora de fin debe ser posterior a la hora de inicio.")
                return
            if not dias_lista:
                messagebox.showwarning("Días Requeridos", "Debes seleccionar al menos un día para el horario manual.")
                return
            if fin_min > 17 * 60:
                if not messagebox.askyesno("Horario Vespertino", f"La hora de fin ({hora_f}) excede las 17:00 hrs.\n¿Desea continuar de todos modos?"):
                    return
            dur_h = (fin_min - ini_min) / 60.0
            tot_h = dur_h * len(dias_lista)
            h_req = self._get_horas_materia(materia_id)
            if h_req > 0 and abs(tot_h - h_req) > 0.01:
                if not messagebox.askyesno("Discrepancia de Horas", f"La materia requiere {int(h_req)} hrs/sem y la selección manual suma {tot_h:.1f} hrs/sem.\n¿Desea continuar de todos modos?"):
                    return
            # Choque grupo
            choques_grupo = self._detectar_choques_grupo(grupo_id, materia_id, dias_lista, hora_i, hora_f, excluir_asignacion_id=asig_id)
            if choques_grupo:
                det = "\n".join([f"• {c['dia']} {c['inicio']}-{c['fin']}: {c['materia']}" for c in choques_grupo])
                messagebox.showerror("Conflicto de Grupo", f"El grupo '{grupo_id}' ya tiene clases en ese horario:\n\n{det}")
                return
            # Choque aula
            if modalidad == "Mediación Tecnológica":
                if not aula_sel or aula_sel == "Sin aula":
                    aula_sel = "MEDIACION_TECNOLOGICA"
            else:
                if not aula_sel or aula_sel == "Sin aula":
                    messagebox.showwarning("Aula requerida", "Para la modalidad presencial debes seleccionar un aula válida.")
                    return
                choques_aula = self._detectar_choques_aula(aula_sel, asig_id, dias_lista, hora_i, hora_f)
                if choques_aula:
                    det = "\n".join([f"• {c['dia']} {c['inicio']}-{c['fin']}: Grupo {c['grupo_id']} ({c['materia']})" for c in choques_aula])
                    messagebox.showerror("Conflicto de Aula", f"El aula '{aula_sel}' ya está ocupada en ese horario:\n\n{det}")
                    return
        else:
            hora_i = asig_info['hora_inicio']
            hora_f = asig_info['hora_fin']
            dias_str = asig_info['dias']
            dias_lista = [d.strip() for d in dias_str.split(',') if d.strip()]
            aula_sel = asig_info.get('salon_id', 'Sin aula')

            # --- Detección y Sugerencia de Compactación Continua Docente ---
            compactacion = self._detectar_compactacion_docente(
                prof_id=prof_id,
                asig_id=asig_id,
                materia_id=materia_id,
                grupo_id=grupo_id,
                modalidad=modalidad,
                aula_actual=aula_sel
            )
            if compactacion and compactacion.get("encontrado"):
                dias_asig_norm = [self._dia_a_indice_previa(d) for d in dias_lista]
                dias_comp_norm = [self._dia_a_indice_previa(d) for d in compactacion['dias']]
                mismo_horario = (
                    dias_asig_norm == dias_comp_norm and
                    compactacion['hora_i'] == self._hora_db_a_str(hora_i) and
                    compactacion['hora_f'] == self._hora_db_a_str(hora_f)
                )
                if not mismo_horario:
                    resp_comp = self._mostrar_dialogo_sugerencia_compactacion(
                        asig_info=asig_info,
                        prof_nombre=prof_nombre,
                        compactacion=compactacion
                    )
                    if resp_comp is None:
                        # Cancelar vinculación
                        return
                    elif resp_comp is True:
                        # Aplicar compactación sugerida directamente (en el mismo salón)
                        hora_i = compactacion['hora_i']
                        hora_f = compactacion['hora_f']
                        dias_lista = compactacion['dias']
                        dias_str = compactacion['dias_str']
                        aula_sel = compactacion['salon']

                        # Si hubo materia desplazada sin profesor, aplicar su reubicación en BD
                        desp = compactacion.get('desplazamiento')
                        if desp and desp.get('asignacion_id'):
                            try:
                                with obtener_cursor() as ctx_desp:
                                    if ctx_desp:
                                        cur_d, conn_d = ctx_desp
                                        cur_d.execute("""
                                            UPDATE asignaciones
                                            SET hora_inicio = %s, hora_fin = %s, dias = %s
                                            WHERE asignacion_id = %s
                                        """, (desp['nuevo_hora_i'], desp['nuevo_hora_f'], desp['nuevos_dias_str'], desp['asignacion_id']))
                                        cur_d.execute("DELETE FROM horarios WHERE asignacion_id = %s", (desp['asignacion_id'],))
                                        for d_dia in desp['nuevos_dias']:
                                            cur_d.execute("""
                                                INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                                                VALUES (%s, %s, %s, %s, %s)
                                            """, (desp['asignacion_id'], desp['salon'], d_dia, desp['nuevo_hora_i'], desp['nuevo_hora_f']))
                                        conn_d.commit()
                            except Exception as e_desp:
                                print(f"Error aplicando desplazamiento de materia sin profesor: {e_desp}")

                        self._aplicar_vinculacion_docente(
                            asig_id, prof_id, estado='asignado', modalidad=modalidad,
                            hora_i=hora_i, hora_f=hora_f, dias_str=dias_str, dias_lista=dias_lista,
                            aula_sel=aula_sel
                        )
                        return
            elif compactacion and not compactacion.get("encontrado") and compactacion.get("motivo") == "sin_lugar_en_aula":
                messagebox.showinfo(
                    "Aviso de Jornada Docente",
                    f"El profesor {prof_nombre} ya cuenta con clases asignadas.\n\n"
                    f"{compactacion['mensaje']}\n\n"
                    f"Se conservará el salón '{aula_sel}' y su horario preasignado ({self._hora_db_a_str(hora_i)} a {self._hora_db_a_str(hora_f)})."
                )

        # 1. Comprobar si el profesor ya tiene esa misma asignación
        if asig_info.get('profesor_id') == prof_id and asig_info.get('modalidad') == modalidad and not getattr(self, '_horario_manual_visible', False):
            messagebox.showinfo("Información", f"El profesor '{prof_nombre}' ya está asignado a esta materia con la misma configuración.")
            return

        # 2. Comprobar choques de horario del profesor
        choques_profesor = []
        try:
            choques_profesor = self._detectar_choques_profesor(
                prof_id, materia_id, grupo_id, modalidad, dias_lista, hora_i, hora_f, excluir_asignacion_id=asig_id
            )
        except Exception as err:
            print(f"Error comprobando choques del profesor: {err}")

        # 3. Comprobar disponibilidad registrada del profesor
        disp_choque, disp_detalle = self._validar_disponibilidad_profesor(prof_id, dias_lista, hora_i, hora_f)

        # Si hay choques con otra clase o con su disponibilidad, abrir modal de 4 opciones
        if choques_profesor or disp_choque:
            self._mostrar_modal_resolucion_conflicto(
                asig_info=asig_info,
                prof_id=prof_id,
                prof_nombre=prof_nombre,
                choques=choques_profesor,
                motivo_disp=disp_detalle
            )
            return

        # Sin conflicto: proceder con la asignación directa
        self._aplicar_vinculacion_docente(
            asig_id, prof_id, estado='asignado', modalidad=modalidad,
            hora_i=hora_i if getattr(self, '_horario_manual_visible', False) else None,
            hora_f=hora_f if getattr(self, '_horario_manual_visible', False) else None,
            dias_str=dias_str if getattr(self, '_horario_manual_visible', False) else None,
            dias_lista=dias_lista if getattr(self, '_horario_manual_visible', False) else None,
            aula_sel=aula_sel if getattr(self, '_horario_manual_visible', False) else None
        )

    def _aplicar_vinculacion_docente(self, asig_id, prof_id, estado='asignado', modalidad=None,
                                    hora_i=None, hora_f=None, dias_str=None, dias_lista=None, aula_sel=None):
        if modalidad is None and hasattr(self, 'combo_modalidad_vinculo'):
            modalidad = self.combo_modalidad_vinculo.get().strip() or 'Presencial'
        with obtener_cursor() as ctx:
            if not ctx:
                return False
            cur, conn = ctx
            try:
                if hora_i and hora_f and dias_str is not None:
                    cur.execute("""
                        UPDATE asignaciones
                        SET profesor_id = %s, estado = %s, modalidad = %s, hora_inicio = %s, hora_fin = %s, dias = %s
                        WHERE asignacion_id = %s
                    """, (prof_id, estado, modalidad, hora_i, hora_f, dias_str, asig_id))
                    if aula_sel and dias_lista:
                        cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (asig_id,))
                        for d in dias_lista:
                            cur.execute("""
                                INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (asig_id, aula_sel, d, f"{hora_i}:00" if len(hora_i) == 5 else hora_i, f"{hora_f}:00" if len(hora_f) == 5 else hora_f))
                else:
                    cur.execute("""
                        UPDATE asignaciones
                        SET profesor_id = %s, estado = %s, modalidad = %s
                        WHERE asignacion_id = %s
                    """, (prof_id, estado, modalidad, asig_id))
                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error al vincular docente: {err}")
                return False

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo("Éxito", "Profesor vinculado correctamente a la materia preasignada.")
        return True

    def _mostrar_modal_resolucion_conflicto(self, asig_info, prof_id, prof_nombre, choques, motivo_disp=""):
        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Conflicto de Horario / Disponibilidad")
        dialogo.transient(self.ventana)
        dialogo.grab_set()
        dialogo.configure(background='#0A0F1E')
        dialogo.geometry("680x570")
        dialogo.minsize(620, 480)
        dialogo.resizable(True, True)

        # Botones siempre anclados abajo
        f_btns = ttk.Frame(dialogo, style='blue.TFrame')
        f_btns.pack(side='bottom', fill='x', padx=18, pady=(10, 14))

        opcion_var = tk.StringVar(value="imponer")

        def ejecutar_resolucion():
            eleccion = opcion_var.get()
            dialogo.destroy()

            if eleccion == "cancelar":
                messagebox.showinfo("Cancelado", "Asignación cancelada. No se realizaron cambios.")
                return

            elif eleccion == "imponer":
                self._aplicar_vinculacion_docente(asig_info['asignacion_id'], prof_id, estado='pendiente')

            elif eleccion == "intercambiar":
                self._ejecutar_intercambio_profesor(asig_info, prof_id, prof_nombre, choques)

            elif eleccion == "reubicar":
                self._ejecutar_reubicacion_automatica(asig_info, prof_id, prof_nombre)

        ttk.Button(f_btns, text="Cerrar", command=dialogo.destroy).pack(side='right', padx=4)
        ttk.Button(f_btns, text="Confirmar y Aplicar", command=ejecutar_resolucion).pack(side='right', padx=4)

        sep = ttk.Separator(dialogo, orient='horizontal')
        sep.pack(side='bottom', fill='x', padx=16, pady=(4, 0))

        f_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=18, pady=(14, 4))

        ttk.Label(
            f_cont,
            text="⚠ CONFLICTO DETECTADO AL ASIGNAR PROFESOR",
            background='#0A0F1E',
            foreground='#FF6B6B',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 6))

        materia_txt = f"{asig_info['materia_id']} - {asig_info['materia_nombre']}"
        horario_txt = f"{asig_info['hora_inicio']} - {asig_info['hora_fin']} [{asig_info['dias']}] en Aula {asig_info['salon_id']}"
        detalles_txt = f"• Materia a vincular: {materia_txt}\n• Horario preasignado: {horario_txt}\n• Profesor seleccionado: {prof_nombre}\n\n"

        if choques:
            detalles_txt += "Cruce con otra(s) clase(s) del profesor:\n"
            for ch in choques:
                detalles_txt += f"  - {ch['dia']} ({ch['inicio']} - {ch['fin']}): {ch['materia']} (Grupo: {ch['grupo']})\n"
        if motivo_disp:
            detalles_txt += f"\nDisponibilidad:\n  - {motivo_disp}\n"

        txt_widget = tk.Text(f_cont, height=7, font=("Consolas", 10), bg='#111827', fg='#E5E7EB', relief='flat', bd=2)
        txt_widget.insert('1.0', detalles_txt)
        txt_widget.config(state='disabled')
        txt_widget.pack(fill='x', pady=6)

        ttk.Label(
            f_cont,
            text="Selecciona una opción para resolver este conflicto:",
            background='#0A0F1E',
            foreground='#FFD700',
            font=self._fuente_sub
        ).pack(anchor='w', pady=(8, 4))

        rb1 = ttk.Radiobutton(
            f_cont,
            text="1. Intercambiar profesor (Intercambiar con el docente de la otra clase en conflicto)",
            variable=opcion_var,
            value="intercambiar"
        )
        rb1.pack(anchor='w', pady=3)

        rb2 = ttk.Radiobutton(
            f_cont,
            text="2. Cancelar asignación (No realizar cambios y mantener sin profesor)",
            variable=opcion_var,
            value="cancelar"
        )
        rb2.pack(anchor='w', pady=3)

        rb3 = ttk.Radiobutton(
            f_cont,
            text="3. Imponer como pendiente (Asignar al profesor conservando el horario y marcar 'pendiente')",
            variable=opcion_var,
            value="imponer"
        )
        rb3.pack(anchor='w', pady=3)

        rb4 = ttk.Radiobutton(
            f_cont,
            text="4. Reubicar automáticamente (Buscar un aula u horario alternativo sin conflicto)",
            variable=opcion_var,
            value="reubicar"
        )
        rb4.pack(anchor='w', pady=3)

    def _ejecutar_intercambio_profesor(self, asig_info, prof_id, prof_nombre, choques):
        """
        Intercambia profesores:
        Asigna el prof_id a la materia actual, y si la materia actual tenía otro profesor,
        se intercambia con la clase en conflicto.
        """
        asig_id_actual = asig_info['asignacion_id']
        prof_id_anterior = asig_info.get('profesor_id')

        asig_conflicto_id = None
        if choques:
            # Buscar el asignacion_id de la clase en conflicto
            with obtener_cursor() as ctx:
                if ctx:
                    cur, conn = ctx
                    ch = choques[0]
                    cur.execute("""
                        SELECT a.asignacion_id FROM asignaciones a
                        JOIN materias m ON a.materia_id = m.materia_id
                        WHERE a.profesor_id = %s AND a.grupo_id = %s AND m.nombre = %s
                        LIMIT 1
                    """, (prof_id, ch['grupo'], ch['materia']))
                    row = cur.fetchone()
                    if row:
                        asig_conflicto_id = row[0]

        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            try:
                # Asignar prof_id a la materia actual
                cur.execute("UPDATE asignaciones SET profesor_id = %s, estado = 'asignado' WHERE asignacion_id = %s",
                            (prof_id, asig_id_actual))

                if asig_conflicto_id:
                    # El profesor anterior toma la clase que tenía el profesor_id
                    nuevo_profe_para_conflicto = prof_id_anterior if (prof_id_anterior and prof_id_anterior != 'SIN_ASIGNAR') else 'SIN_ASIGNAR'
                    cur.execute("UPDATE asignaciones SET profesor_id = %s, estado = %s WHERE asignacion_id = %s",
                                (nuevo_profe_para_conflicto, 'asignado' if nuevo_profe_para_conflicto != 'SIN_ASIGNAR' else 'no asignado', asig_conflicto_id))

                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"Error realizando intercambio: {err}")
                return

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo("Intercambio Realizado", "Se ha realizado el intercambio de profesores exitosamente.")

    def _ejecutar_reubicacion_automatica(self, asig_info, prof_id, prof_nombre):
        """
        Busca otro bloque libre para esta materia y aula o profesor que no tenga choques.
        """
        asig_id = asig_info['asignacion_id']
        grupo_id = self._sv_grupo_gestion.get().strip()
        materia_id = asig_info['materia_id']
        salon_id = asig_info['salon_id'].split(',')[0].strip() if asig_info.get('salon_id') else 'Normal'

        dias_alternativos = [("Lunes", "Miércoles"), ("Martes", "Jueves"), ("Miércoles", "Viernes")]
        horas_alternativas = [
            ("07:00", "09:00"), ("09:00", "11:00"), ("11:00", "13:00"),
            ("13:00", "15:00"), ("15:00", "17:00")
        ]

        encontrado = None

        # Prioridad 1: Compactar en los mismos días del profesor con horario continuo
        comp = self._detectar_compactacion_docente(
            prof_id=prof_id,
            asig_id=asig_id,
            materia_id=materia_id,
            grupo_id=grupo_id,
            modalidad='Presencial',
            aula_actual=salon_id
        )
        if comp and comp.get("encontrado"):
            encontrado = (tuple(comp['dias']), comp['hora_i'], comp['hora_f'])
            if comp.get('salon'):
                salon_id = comp['salon']

        # Prioridad 2: Buscar en parejas estándar si no se pudo compactar
        if not encontrado:
            for pareja in dias_alternativos:
                dias_str = ", ".join(pareja)
                for hi, hf in horas_alternativas:
                    choques_g = self._detectar_choques_grupo(grupo_id, materia_id, list(pareja), hi, hf)
                    if choques_g:
                        continue
                    choques_p = self._detectar_choques_profesor(prof_id, materia_id, grupo_id, 'Presencial', list(pareja), hi, hf)
                    if choques_p:
                        continue
                    encontrado = (pareja, hi, hf)
                    break
                if encontrado:
                    break

        if not encontrado:
            # Si no encuentra espacio idéntico, asigna con estado pendiente
            self._aplicar_vinculacion_docente(asig_id, prof_id, estado='pendiente')
            messagebox.showwarning(
                "Reubicación Compleja",
                "No se encontró un bloque automático libre sin choques.\n"
                "La asignación se guardó como 'PENDIENTE' para que se ajuste manualmente."
            )
            return

        pareja, hi, hf = encontrado
        dias_str = ", ".join(pareja)

        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            try:
                # Actualizar asignación
                cur.execute("""
                    UPDATE asignaciones
                    SET profesor_id = %s, hora_inicio = %s, hora_fin = %s, dias = %s, estado = 'asignado'
                    WHERE asignacion_id = %s
                """, (prof_id, hi, hf, dias_str, asig_id))

                # Actualizar sesiones en horarios
                cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (asig_id,))
                for d in pareja:
                    cur.execute("""
                        INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (asig_id, salon_id if salon_id != "Sin aula" else "F10", d, f"{hi}:00", f"{hf}:00"))

                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"Error al reubicar: {err}")
                return

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo(
            "Reubicación Exitosa",
            f"La materia fue reubicada automáticamente sin conflictos:\n\n"
            f"• Días: {dias_str}\n"
            f"• Horario: {hi} a {hf}\n"
            f"• Profesor: {prof_nombre}"
        )

    def _cargar_profesor_desde_tabla(self, event):
        item = self.tabla_profesores.focus()
        if not item:
            return
        v = self.tabla_profesores.item(item, "values")
        if len(v) < 2:
            return
        no_cuenta, nombre = v[0], v[1]
        self.entry_no_cuenta.config(state='normal')
        self.entry_no_cuenta.delete(0, tk.END)
        self.entry_no_cuenta.insert(0, no_cuenta)
        self.entry_no_cuenta.config(state='readonly')
        self.entry_nombre_prof.config(state='normal')
        self.entry_nombre_prof.delete(0, tk.END)
        self.entry_nombre_prof.insert(0, nombre)
        self.entry_nombre_prof.config(state='readonly')

        if hasattr(self, 'entry_prof_vinculo'):
            self.entry_prof_vinculo.config(state='normal')
            self.entry_prof_vinculo.delete(0, tk.END)
            self.entry_prof_vinculo.insert(0, f"{no_cuenta} - {nombre}")
            self.entry_prof_vinculo.config(state='readonly')

        for pid, info in self.profesores_map.items():
            if info["no_cuenta"] == no_cuenta:
                self._profesor_id_seleccionado = pid
                break
        self._actualizar_horas_info()
        self._actualizar_estado_boton_vinculo()
        for item in self._periodos_frame.winfo_children():
            item.destroy()
        self._periodos_asignacion.clear()
        self._cargar_periodos_desde_bd()

    def _cambiar_filtro_semestre(self, event=None):
        self._actualizar_materias_en_periodos()
        if hasattr(self, 'combo_grupo_gestion'):
            grupos = self._grupos_filtrados_actual()
            self.combo_grupo_gestion['values'] = grupos
            if grupos:
                self.combo_grupo_gestion.set(grupos[0])
            else:
                self.combo_grupo_gestion.set('')
            self._on_cambio_grupo_gestion()

    def _on_filtro_semestre_vp(self, preservar_seleccion=False):
        sel = self._sv_filtro_semestre_vp.get()
        grupo_seleccionado = self._sv_filtro_grupo_vp.get()
        grupos = ["Todos"]
        if sel and sel != "Todos" and ' - ' in sel:
            try:
                sid = self._normalizar_nivel_grupo(sel.split(' - ')[0])
                grupos_sem = self._grupos_del_semestre(sid)
                if grupos_sem:
                    grupos.extend(grupos_sem)
            except (ValueError, IndexError):
                pass
        else:
            grupos.extend(
                grupo
                for semestre in sorted(
                    self.grupos_por_semestre,
                    key=lambda valor: (
                        not self._normalizar_nivel_grupo(valor).isdigit(),
                        int(self._normalizar_nivel_grupo(valor))
                        if self._normalizar_nivel_grupo(valor).isdigit()
                        else self._normalizar_nivel_grupo(valor)
                    )
                )
                for grupo in self.grupos_por_semestre[semestre]
                if grupo not in grupos
            )
        self.combo_filtro_grupo_vp['values'] = grupos
        if preservar_seleccion and grupo_seleccionado in grupos:
            self._sv_filtro_grupo_vp.set(grupo_seleccionado)
        else:
            self._sv_filtro_grupo_vp.set("Todos")
        self.actualizar_vista_previa()

    def _on_cambio_filtro_grupo_vp(self):
        self.actualizar_vista_previa()
        if hasattr(self, 'canvas_previa_horario'):
            self._cargar_previa_horario_grupo()

    def _actualizar_grupos_en_periodos(self):
        for periodo in self._periodos_asignacion:
            for combo_materia, combo_grupo in periodo.get("filas_asignacion", []):
                grupo_actual = combo_grupo.get().strip().upper()
                asignacion_cargada = getattr(combo_grupo, "_asignacion_cargada", None)
                materia_id = self._obtener_id_valido(combo_materia.get())
                preservar_grupo = asignacion_cargada == (materia_id, grupo_actual)
                self._actualizar_grupos_de_asignacion(
                    combo_materia,
                    combo_grupo,
                    preservar_grupo=preservar_grupo
                )

    def _materias_filtradas_actual(self):
        semestre_txt = self.combo_filtro_semestre.get()
        periodo_txt = self.combo_periodos.get()
        materias = self.lista_maestra_materias
        if periodo_txt:
            semestres_validos = [2, 4, 6, 8, 10] if periodo_txt == "A" else [1, 3, 5, 7, 9]
            materias = [m for m in materias if m["semestre"] in semestres_validos]
        if semestre_txt and ' - ' in semestre_txt:
            try:
                id_sem = int(semestre_txt.split(' - ')[0])
                materias = [m for m in materias if m["semestre"] == id_sem]
            except ValueError:
                pass
        return [m["texto"] for m in materias]

    def _actualizar_materias_en_periodos(self):
        filtradas = self._materias_filtradas_actual()
        for pd in self._periodos_asignacion:
            for cm, cg in pd.get("filas_asignacion", []):
                cm['values'] = filtradas
                if cm.get() and cm.get() not in filtradas:
                    cm.set('')
                materia_id = self._obtener_id_valido(cm.get())
                grupo_actual = cg.get().strip().upper()
                asignacion_cargada = getattr(cg, "_asignacion_cargada", None)
                preservar_grupo = asignacion_cargada == (materia_id, grupo_actual)
                self._actualizar_grupos_de_asignacion(
                    cm, cg, preservar_grupo=preservar_grupo
                )

    def _grupos_para_materia(self, materia_texto):
        materia_id = self._obtener_id_valido(materia_texto)
        if not materia_id:
            return self._grupos_filtrados_actual()
        nivel = self.materias_map.get(str(materia_id))
        if nivel is None:
            return self._grupos_filtrados_actual()
        return self.cargar_grupos_por_semestre(nivel, materia_id)

    def _actualizar_grupos_de_asignacion(self, combo_materia, combo_grupo, preservar_grupo=False):
        grupos = self._grupos_para_materia(combo_materia.get())
        grupo_actual = combo_grupo.get().strip().upper()
        if preservar_grupo and grupo_actual and grupo_actual not in grupos:
            grupos.append(grupo_actual)
        combo_grupo['values'] = grupos
        if grupo_actual and grupo_actual not in grupos:
            combo_grupo.set('')

    def _on_cambio_materia_asignacion(self, combo_materia, combo_grupo, label_restante):
        self._actualizar_horas_periodo(combo_materia, label_restante)
        combo_grupo.set('')
        self._actualizar_grupos_de_asignacion(combo_materia, combo_grupo)

    def _grupos_filtrados_actual(self):
        semestre_txt = self.combo_filtro_semestre.get()
        if semestre_txt and semestre_txt != "Todos" and ' - ' in semestre_txt:
            try:
                sid = self._normalizar_nivel_grupo(semestre_txt.split(' - ')[0])
                return self._grupos_del_semestre(sid)
            except (ValueError, IndexError):
                pass
        todos = []
        for sem in sorted(
            self.grupos_por_semestre,
            key=lambda nivel: (
                not self._normalizar_nivel_grupo(nivel).isdigit(),
                int(self._normalizar_nivel_grupo(nivel))
                if self._normalizar_nivel_grupo(nivel).isdigit()
                else self._normalizar_nivel_grupo(nivel)
            )
        ):
            for g in self.grupos_por_semestre[sem]:
                if g not in todos:
                    todos.append(g)
        return todos

    MAPA_DIAS = {"0": "Lunes", "1": "Martes", "2": "Miércoles", "3": "Jueves", "4": "Viernes", "5": "Sábado"}
    NOMBRES_DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    _DIA_SIN_ACENTOS = {"lunes": "0", "martes": "1", "miercoles": "2", "jueves": "3", "viernes": "4", "sabado": "5", "domingo": "6"}

    @staticmethod
    def _normalizar_dia(valor):
        s = unicodedata.normalize('NFKD', str(valor)).encode('ascii', 'ignore').decode('ascii').strip().lower()
        return VentanaGestion._DIA_SIN_ACENTOS.get(s, str(valor).strip())

    def _cargar_periodos_desde_bd(self):
        if not self._profesor_id_seleccionado:
            return
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                # Clean up dummy 07:00-07:30 period from old Personal tab saves
                cur.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id=%s AND hora_inicio='07:00' AND hora_fin='07:30' AND dia='0' AND NOT EXISTS (SELECT 1 FROM asignaciones WHERE profesor_id=%s AND hora_inicio='07:00' AND hora_fin='07:30')",
                            (self._profesor_id_seleccionado, self._profesor_id_seleccionado))
                # Clean up corrupted dia values (non-numeric)
                cur.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id=%s AND dia NOT IN ('0','1','2','3','4','5','6')",
                            (self._profesor_id_seleccionado,))

                cur.execute(
                    "SELECT dia, hora_inicio, hora_fin, modalidad FROM profesor_disponibilidad WHERE profesor_id = %s ORDER BY dia",
                    (self._profesor_id_seleccionado,)
                )
                filas = cur.fetchall()

                # Fetch assignments with materia names in a single query
                cur.execute(
                    "SELECT a.materia_id, a.grupo_id, a.hora_inicio, a.hora_fin, a.modalidad, m.nombre "
                    "FROM asignaciones a LEFT JOIN materias m ON a.materia_id = m.materia_id "
                    "WHERE a.profesor_id=%s AND a.hora_inicio IS NOT NULL",
                    (self._profesor_id_seleccionado,)
                )
                asig_por_clave = {}
                for m_id, g_id, hi, hf, modal, m_nombre in cur.fetchall():
                    m_texto = f"{m_id} - {m_nombre}" if m_nombre else m_id
                    clave = f"{hi}-{hf}"
                    asig_por_clave.setdefault(clave, []).append((m_texto, g_id))

                # Calculate horas once using the same cursor
                total_minutos = 0
                for d, hi, hf, modal in filas:
                    if str(d) == "6":
                        continue
                    parts_i = str(hi).split(':')
                    parts_f = str(hf).split(':')
                    ini = int(parts_i[0]) * 60 + int(parts_i[1])
                    fin = int(parts_f[0]) * 60 + int(parts_f[1])
                    if fin > ini:
                        total_minutos += (fin - ini)
                disponibles = total_minutos / 60.0
                cur.execute(
                    "SELECT COALESCE(SUM(m.horas_semana), 0) FROM asignaciones a "
                    "JOIN materias m ON a.materia_id = m.materia_id "
                    "WHERE a.profesor_id = %s AND a.estado != 'cancelada'",
                    (self._profesor_id_seleccionado,)
                )
                asignadas = float(cur.fetchone()[0])

                # Build shared lists once
                todos_grupos = self._grupos_filtrados_actual()
                mat_ids = self._materias_filtradas_actual()

                agrupado = {}
                for d, hi, hf, modal in filas:
                    dia_str = str(d)
                    if dia_str == "6":
                        continue
                    if str(hi) == str(hf):
                        continue
                    clave = f"{hi}-{hf}"
                    if clave not in agrupado:
                        agrupado[clave] = {"hora_i": str(hi), "hora_f": str(hf), "dias": set(), "modalidad": modal or "Presencial"}
                    agrupado[clave]["dias"].add(self.MAPA_DIAS.get(dia_str, dia_str))
                for info in agrupado.values():
                    clave = f"{info['hora_i']}-{info['hora_f']}"
                    info['asignaciones'] = asig_por_clave.get(clave, [])
                    # Compute original DB minutes for this card
                    parts_i = str(info['hora_i']).split(':')
                    parts_f = str(info['hora_f']).split(':')
                    ini = int(parts_i[0]) * 60 + int(parts_i[1])
                    fin = int(parts_f[0]) * 60 + int(parts_f[1])
                    mins = (fin - ini) if fin > ini else 0
                    info['db_minutos'] = mins * len(info['dias'])
                    self._agregar_periodo_asignacion(datos=info, horas_pre=(disponibles, asignadas), grupos_pre=todos_grupos, materias_pre=mat_ids)
        except Exception as e:
            print(f"Error cargando disponibilidad: {e}")

    def _actualizar_horas_info(self):
        if not self._profesor_id_seleccionado:
            self._label_horas.config(text="")
            return
        disponibles, asignadas = self._calcular_horas_con_ui(self._profesor_id_seleccionado)
        restantes = max(0, disponibles - asignadas)
        color = '#FF6B6B' if restantes <= 0 else '#98FB98'
        self._label_horas.config(
            text=f"Horas: {asignadas:.1f}h asignadas / {disponibles:.1f}h disponibles ({restantes:.1f}h restantes)",
            foreground=color
        )

    def _limpiar_profesor_seleccionado(self):
        self.entry_no_cuenta.config(state='normal')
        self.entry_no_cuenta.delete(0, tk.END)
        self.entry_no_cuenta.config(state='readonly')
        self.entry_nombre_prof.config(state='normal')
        self.entry_nombre_prof.delete(0, tk.END)
        self.entry_nombre_prof.config(state='readonly')
        if hasattr(self, 'entry_prof_vinculo'):
            self.entry_prof_vinculo.config(state='normal')
            self.entry_prof_vinculo.delete(0, tk.END)
            self.entry_prof_vinculo.config(state='readonly')
        self._profesor_id_seleccionado = None
        self._label_horas.config(text="")
        self._actualizar_estado_boton_vinculo()
        for item in self._periodos_frame.winfo_children():
            item.destroy()
        self._periodos_asignacion.clear()

    def _calcular_horas_profesor(self, profesor_id):
        disponibilidad = 0
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return 0, 0
                cur, conn = ctx
                cur.execute(
                    "SELECT hora_inicio, hora_fin FROM profesor_disponibilidad WHERE profesor_id = %s",
                    (profesor_id,)
                )
                filas = cur.fetchall()
                total_minutos = 0
                for hi, hf in filas:
                    parts_i = str(hi).split(':')
                    parts_f = str(hf).split(':')
                    ini = int(parts_i[0]) * 60 + int(parts_i[1])
                    fin = int(parts_f[0]) * 60 + int(parts_f[1])
                    if fin > ini:
                        total_minutos += (fin - ini)
                disponibilidad = total_minutos / 60.0

                cur.execute(
                    "SELECT COALESCE(SUM(m.horas_semana), 0) FROM asignaciones a "
                    "JOIN materias m ON a.materia_id = m.materia_id "
                    "WHERE a.profesor_id = %s AND a.estado != 'cancelada'",
                    (profesor_id,)
                )
                asignadas = float(cur.fetchone()[0])
                return disponibilidad, asignadas
        except Exception as e:
            print(f"Error calculando horas del profesor: {e}")
            return 0, 0

    def _calcular_horas_con_ui(self, profesor_id):
        db_disponibles, asignadas = self._calcular_horas_profesor(profesor_id)
        baseline_minutos = 0
        ui_minutos = 0
        for wd in list(self._periodos_asignacion):
            baseline_minutos += wd.get('db_minutos', 0)
            entry_i = wd.get('entry_i')
            entry_f = wd.get('entry_f')
            vars_dias = wd.get('vars_dias', {})
            if entry_i and entry_f:
                try:
                    hi_str = entry_i.get().strip()
                except Exception:
                    continue
                try:
                    hf_str = entry_f.get().strip()
                except Exception:
                    continue
                if hi_str and hf_str:
                    try:
                        parts_i = hi_str.split(':')
                        parts_f = hf_str.split(':')
                        ini = int(parts_i[0]) * 60 + int(parts_i[1])
                        fin = int(parts_f[0]) * 60 + int(parts_f[1])
                        if fin > ini:
                            dias_sel = sum(1 for d, v in vars_dias.items() if v.get() == 1 and d != 'Domingo')
                            ui_minutos += (fin - ini) * dias_sel
                    except (ValueError, IndexError):
                        pass
        delta = ui_minutos - baseline_minutos
        disponibles = max(0, db_disponibles + delta / 60.0)
        return disponibles, asignadas

    def _actualizar_todas_periodos(self):
        self._debounce_after_id = None
        if not self._profesor_id_seleccionado:
            return
        for wd in list(self._periodos_asignacion):
            for cm, cg in list(wd.get('filas_asignacion', [])):
                try:
                    cm.get()
                except Exception:
                    continue
                self._actualizar_horas_periodo(cm, wd['label_restante'])

    def _get_horas_materia(self, materia_id):
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return 0
                cur, conn = ctx
                if '-' in str(materia_id):
                    materia_id = str(materia_id).split(' - ')[0]
                cur.execute("SELECT horas_semana FROM materias WHERE materia_id = %s", (materia_id,))
                row = cur.fetchone()
                return float(row[0]) if row else 0
        except Exception as e:
            print(f"Error obteniendo horas de materia: {e}")
            return 0

    def _nombre_de_materia(self, materia_id):
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return None
                cur, conn = ctx
                cur.execute("SELECT nombre FROM materias WHERE materia_id = %s", (materia_id,))
                row = cur.fetchone()
                return str(row[0]) if row else None
        except Exception as e:
            print(f"Error obteniendo nombre de materia: {e}")
            return None

    def _crear_spinner_hora(self, parent, valor_inicial="07:00", actualizar_periodos=True):
        f = ttk.Frame(parent, style='blue.TFrame')
        var = tk.StringVar(value=valor_inicial)

        def ajustar(delta):
            try:
                partes = var.get().strip().split(':')
                h = int(partes[0])
                m = int(partes[1])
            except (ValueError, IndexError):
                h, m = 7, 0
            total_min = h * 60 + m + delta
            total_min = max(7 * 60, min(total_min, 22 * 60))
            var.set(f"{total_min // 60:02d}:{total_min % 60:02d}")
            if actualizar_periodos and hasattr(self, '_actualizar_todas_periodos'):
                if self._debounce_after_id:
                    self.ventana.after_cancel(self._debounce_after_id)
                self._debounce_after_id = self.ventana.after(1000, self._actualizar_todas_periodos)

        btn_menos = ttk.Button(f, text="-", width=3, command=lambda: ajustar(-30))
        btn_menos.pack(side='left')

        entry = ttk.Entry(f, textvariable=var, width=8, font=self._fuente_label, justify='center')
        entry.pack(side='left', padx=1)

        def on_key(event):
            if event.keysym == 'Left':
                ajustar(-30)
                return 'break'
            elif event.keysym == 'Right':
                ajustar(30)
                return 'break'

        entry.bind("<Left>", on_key)
        entry.bind("<Right>", on_key)

        btn_mas = ttk.Button(f, text="+", width=3, command=lambda: ajustar(30))
        btn_mas.pack(side='left')

        return f, entry, var

    def _agregar_periodo_vacio(self, horas_pre=None, grupos_pre=None, materias_pre=None):
        self._agregar_periodo_asignacion(datos=None, horas_pre=horas_pre, grupos_pre=grupos_pre, materias_pre=materias_pre)

    def _agregar_periodo_asignacion(self, datos=None, horas_pre=None, grupos_pre=None, materias_pre=None):
        if not self._profesor_id_seleccionado and datos is None:
            return
        idx = len(self._periodos_asignacion)
        periodo = self.combo_periodos.get()
        if not periodo:
            if self.combo_periodos['values']:
                periodo = self.combo_periodos['values'][0]
                self.combo_periodos.set(periodo)

        f_periodo = ttk.LabelFrame(self._periodos_frame, text=f"Periodo {idx+1}", style='blue.TFrame')
        f_periodo.pack(fill='x', pady=4)

        # --- Horario ---
        f_h = ttk.Frame(f_periodo, style='blue.TFrame')
        f_h.pack(fill='x', padx=6, pady=2)
        ttk.Label(f_h, text="Horario:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=2)
        f_i, entry_i, var_hora_i = self._crear_spinner_hora(f_h, "07:00")
        f_i.pack(side='left', padx=1)
        ttk.Label(f_h, text="-", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=1)
        f_f, entry_f, var_hora_f = self._crear_spinner_hora(f_h, "07:00")
        f_f.pack(side='left', padx=1)

        if datos:
            var_hora_i.set(datos.get('hora_i', '07:00'))
            var_hora_f.set(datos.get('hora_f', '07:00'))

        def _on_horario_change(*args):
            self._actualizar_todas_periodos()

        entry_i.bind("<KeyRelease>", _on_horario_change)
        entry_f.bind("<KeyRelease>", _on_horario_change)

        # --- Modalidad ---
        modalidad_inicial = datos.get('modalidad', 'Presencial') if datos else 'Presencial'
        modalidad_var = tk.StringVar(value=modalidad_inicial)
        ttk.Label(f_h, text="  Modalidad:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(15, 2))
        combo_modal = ttk.Combobox(f_h, values=["Presencial", "Mediacion Tecnologica"], textvariable=modalidad_var, width=22, font=self._fuente_label, state='readonly')
        combo_modal.pack(side='left', padx=2)

        # --- Materias y Grupos (multiples filas) ---
        if horas_pre:
            disponibles, asignadas = horas_pre
        else:
            disponibles, asignadas = self._calcular_horas_profesor(self._profesor_id_seleccionado) if self._profesor_id_seleccionado else (0, 0)
        restantes = max(0, disponibles - asignadas)
        label_restante = ttk.Label(
            f_periodo,
            text=f"Disponible: {restantes:.1f}h restantes",
            background='#0A0F1E',
            foreground='#98FB98',
            font=self._fuente_label
        )
        label_restante.pack(anchor='w', padx=8)

        f_asig = ttk.Frame(f_periodo, style='blue.TFrame')
        f_asig.pack(fill='x', padx=6, pady=2)

        filas_asignacion = []
        if grupos_pre is not None:
            todos_grupos = grupos_pre
        else:
            todos_grupos = self._grupos_filtrados_actual() if self._profesor_id_seleccionado else []
        if materias_pre is not None:
            mat_ids = materias_pre
        else:
            mat_ids = self._materias_filtradas_actual() if self._profesor_id_seleccionado else []

        def agregar_fila_asignacion(mat_inicial=None, grp_inicial=None):
            row = len(filas_asignacion)
            ttk.Label(f_asig, text="Materia:", background='#0A0F1E', foreground='white', font=self._fuente_label).grid(row=row, column=0, sticky='w', padx=2)
            if mat_inicial and mat_inicial not in mat_ids:
                mat_ids.append(mat_inicial)
            cm = ttk.Combobox(f_asig, values=mat_ids, width=28, font=self._fuente_label, state='readonly')
            cm.grid(row=row, column=1, padx=4, pady=1)

            ttk.Label(f_asig, text="Grupo:", background='#0A0F1E', foreground='white', font=self._fuente_label).grid(row=row, column=2, sticky='w', padx=(10, 2))
            cg = ttk.Combobox(f_asig, values=todos_grupos, width=10, font=self._fuente_label, state='normal')
            cg.grid(row=row, column=3, padx=4, pady=1)

            if mat_inicial:
                cm.set(mat_inicial)
            if grp_inicial:
                cg.set(grp_inicial)
                cg._asignacion_cargada = (
                    self._obtener_id_valido(mat_inicial),
                    str(grp_inicial).strip().upper()
                )
            self._actualizar_grupos_de_asignacion(
                cm, cg, preservar_grupo=bool(grp_inicial)
            )
            cm.bind(
                "<<ComboboxSelected>>",
                lambda e, materia=cm, grupo=cg, lb=label_restante:
                    self._on_cambio_materia_asignacion(materia, grupo, lb)
            )

            filas_asignacion.append((cm, cg))

        asignaciones_existentes = datos.get('asignaciones', []) if datos else []
        if asignaciones_existentes:
            for mat_id, grp_id in asignaciones_existentes[:1]:
                agregar_fila_asignacion(mat_inicial=mat_id, grp_inicial=grp_id)
        else:
            agregar_fila_asignacion()

        # --- Días ---
        f_dias = ttk.Frame(f_periodo, style='blue.TFrame')
        f_dias.pack(fill='x', padx=6, pady=2)
        vars_dias = {}
        dias_disponibles = set(datos.get('dias', [])) if datos else set()
        for i, dia in enumerate(self.NOMBRES_DIAS):
            var = tk.IntVar(value=1 if dia in dias_disponibles else 0)
            vars_dias[dia] = var
            cb = ttk.Checkbutton(f_dias, text=dia, variable=var, style='Custom.TCheckbutton')
            cb.grid(row=i // 3, column=i % 3, sticky='w', padx=5, pady=1)
            cb.configure(command=self._actualizar_todas_periodos)
        for c in range(3):
            f_dias.grid_columnconfigure(c, weight=1)

        label_alerta = ttk.Label(f_periodo, text="", background='#0A0F1E', foreground='#FF6B6B', font=self._fuente_label, wraplength=350)
        label_alerta.pack(fill='x', padx=8)

        btn_guardar = ttk.Button(f_periodo, text="Guardar Asignaciones", command=lambda: None)
        btn_guardar.pack(side='left', padx=(8, 2), pady=(2, 4))

        btn_quitar = ttk.Button(f_periodo, text="Quitar Periodo", command=lambda f=f_periodo, i=idx: self._quitar_periodo_card(f, i))
        btn_quitar.pack(side='left', padx=(2, 8), pady=(2, 4))

        # --- Separador ---
        ttk.Separator(f_periodo, orient='horizontal').pack(fill='x', pady=3)

        def guardar():
            if not self._profesor_id_seleccionado:
                messagebox.showwarning("Aviso", "Selecciona un profesor primero.")
                return
            hora_i = entry_i.get().strip()
            hora_f = entry_f.get().strip()
            if not hora_i or not hora_f:
                messagebox.showwarning("Aviso", "Completa el horario del periodo")
                return
            dias_sel = [d for d, v in vars_dias.items() if v.get() == 1]
            if not dias_sel:
                messagebox.showwarning("Aviso", "Selecciona al menos un día")
                return

            alguna_guardada = False
            for cm, cg in filas_asignacion:
                materia_txt = cm.get()
                grupo_txt = cg.get()
                if not materia_txt or not grupo_txt:
                    continue
                mat_id = self._obtener_id_valido(materia_txt)
                grupo_id = grupo_txt.strip().upper()
                if not mat_id or not grupo_id:
                    continue

                hrs_mat = self._get_horas_materia(mat_id)
                try:
                    parts_i = hora_i.split(':')
                    parts_f = hora_f.split(':')
                    ini = int(parts_i[0]) * 60 + int(parts_i[1])
                    fin = int(parts_f[0]) * 60 + int(parts_f[1])
                    if fin > ini:
                        minutos_por_dia = fin - ini
                    else:
                        minutos_por_dia = 0
                except (ValueError, IndexError):
                    minutos_por_dia = 0
                dias_sin_domingo = sum(1 for d in dias_sel if d != 'Domingo')
                horas_cubiertas = dias_sin_domingo * minutos_por_dia / 60.0
                accion = "normal"
                dias_extra = []
                if horas_cubiertas < hrs_mat:
                    faltantes = hrs_mat - horas_cubiertas
                    opcion = messagebox.askyesnocancel(
                        "Horas insuficientes",
                        f"'{materia_txt}' requiere {hrs_mat:.1f}h pero el periodo actual cubre "
                        f"{horas_cubiertas:.1f}h ({len(dias_sel)} día(s)"
                        f" × {minutos_por_dia/60:.1f}h/día).\n\n"
                        f"Faltan {faltantes:.1f}h.\n\n"
                        "• Sí: Agregar días adicionales para completar las horas\n"
                        "• No: No asignar nada\n"
                        "• Cancelar: Asignar de todas formas (sin completar horas)"
                    )
                    if opcion is False:
                        continue
                    elif opcion is True:
                        dias_extra_str = simpledialog.askstring(
                            "Completar horas",
                            f"Faltan {faltantes:.1f}h. Ingresa días adicionales (separados por coma).\n"
                            f"Ejemplo: Miércoles, Viernes\n"
                            f"Horario: {hora_i} - {hora_f}"
                        )
                        if not dias_extra_str:
                            continue
                        dias_extra = [d.strip() for d in dias_extra_str.split(',') if d.strip()]
                        if not dias_extra:
                            continue
                        accion = "completar"

                disponibles2, asignadas2 = self._calcular_horas_con_ui(self._profesor_id_seleccionado)
                restantes2 = max(0, disponibles2 - asignadas2)
                if hrs_mat > restantes2:
                    if not messagebox.askyesno(
                        "Sobrecarga de horas",
                        f"'{materia_txt}' requiere {hrs_mat:.1f}h pero solo restan {restantes2:.1f}h.\n¿Asignar de todas formas?"
                    ):
                        continue

                todos_dias = dias_sel + dias_extra
                try:
                    choques = self._detectar_choques_grupo(
                        grupo_id, mat_id, todos_dias, hora_i, hora_f
                    )
                    choques_profesor = self._detectar_choques_profesor(
                        self._profesor_id_seleccionado,
                        mat_id,
                        grupo_id,
                        modalidad_var.get(),
                        todos_dias,
                        hora_i,
                        hora_f
                    )
                except (sqlite3.Error, RuntimeError) as err:
                    messagebox.showerror(
                        "Error al validar horario",
                        f"No se pudo comprobar si el grupo o el profesor tienen un choque:\n{err}"
                    )
                    continue
                if choques:
                    detalles = []
                    for choque in choques:
                        inicio_choque = self._minutos_hora_previa(choque['inicio'])
                        fin_choque = self._minutos_hora_previa(choque['fin'])
                        if inicio_choque is None or fin_choque is None:
                            rango = f"{choque['inicio']} - {choque['fin']}"
                        else:
                            rango = (
                                f"{inicio_choque // 60:02d}:{inicio_choque % 60:02d} - "
                                f"{fin_choque // 60:02d}:{fin_choque % 60:02d}"
                            )
                        detalles.append(
                            f"{choque['dia']}, {rango}: {choque['materia']}"
                        )
                    messagebox.showwarning(
                        "Choque de horario",
                        f"No se guardó la asignación de {materia_txt} para el grupo "
                        f"{grupo_id} porque se cruza con otra clase del grupo:\n\n"
                        + "\n".join(detalles)
                    )
                    continue
                if choques_profesor:
                    detalles = []
                    for choque in choques_profesor:
                        inicio_choque = self._minutos_hora_previa(choque['inicio'])
                        fin_choque = self._minutos_hora_previa(choque['fin'])
                        if inicio_choque is None or fin_choque is None:
                            rango = f"{choque['inicio']} - {choque['fin']}"
                        else:
                            rango = (
                                f"{inicio_choque // 60:02d}:{inicio_choque % 60:02d} - "
                                f"{fin_choque // 60:02d}:{fin_choque % 60:02d}"
                            )
                        detalles.append(
                            f"{choque['dia']}, {rango}: {choque['materia']} "
                            f"(grupo {choque['grupo']})"
                        )
                    messagebox.showwarning(
                        "Choque de horario del profesor",
                        f"No se guardó la asignación de {materia_txt} para el grupo "
                        f"{grupo_id} porque el profesor ya tiene otra clase en ese horario:\n\n"
                        + "\n".join(detalles)
                    )
                    continue

                guardada = self._asignar_periodo(
                    self._profesor_id_seleccionado, mat_id, grupo_id,
                    periodo or "A", hora_i, hora_f, modalidad_var.get(),
                    ", ".join(dias_sel)
                )
                if not guardada:
                    continue

                self._actualizar_materias_en_periodos()
                self._guardar_disponibilidad_periodo(
                    self._profesor_id_seleccionado, hora_i, hora_f,
                    todos_dias, modalidad_var.get(),
                    wd.get('db_hora_i', ''), wd.get('db_hora_f', '')
                )
                if accion == "completar":
                    dias_str_extra = ", ".join(dias_extra)
                    with obtener_cursor() as ctx2:
                        if ctx2:
                            cur2, conn2 = ctx2
                            grupo_id2 = self.obtener_o_crear_grupo(
                                grupo_txt.strip().upper(),
                                nivel=self.materias_map.get(mat_id)
                            )
                            if grupo_id2:
                                cur2.execute(
                                    "INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, estado, periodo, hora_inicio, hora_fin, dias, modalidad) VALUES (%s, %s, %s, 'pendiente', %s, %s, %s, %s, %s)",
                                    (self._profesor_id_seleccionado, mat_id, grupo_id2, periodo or "A", hora_i, hora_f, dias_str_extra, modalidad_var.get())
                                )
                                conn2.commit()
                alguna_guardada = True
                self._seleccionar_grupo_previa(grupo_id)
                self._cargar_previa_horario_grupo()

            if alguna_guardada:
                btn_guardar.config(text="Guardado")
                label_alerta.config(text="Asignación(es) guardada(s)", foreground='#98FB98')
                self._actualizar_horas_info()
            else:
                label_alerta.config(text="No se guardó ninguna asignación", foreground='#FF6B6B')

        btn_guardar.config(command=guardar)

        wd = {
            "frame": f_periodo,
            "entry_i": entry_i,
            "entry_f": entry_f,
            "vars_dias": vars_dias,
            "filas_asignacion": filas_asignacion,
            "modalidad_var": modalidad_var,
            "label_restante": label_restante,
            "db_minutos": datos.get('db_minutos', 0) if datos else 0,
            "db_hora_i": datos.get('hora_i', '') if datos else '',
            "db_hora_f": datos.get('hora_f', '') if datos else ''
        }
        self._periodos_asignacion.append(wd)

    def _quitar_periodo_card(self, frame, idx):
        if 0 <= idx < len(self._periodos_asignacion):
            self._periodos_asignacion.pop(idx)
        frame.destroy()

    def _hora_db_a_str(self, h):
        if h is None:
            return ""
        s = str(h).strip()
        if not s or s.lower() == "none":
            return ""
        parts = s.split(':')
        try:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        except (ValueError, IndexError):
            return s

    def _guardar_configuracion(self, filepath=None):
        if not filepath:
            filepath = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json")],
                title="Guardar Configuración de Periodos y Asignaciones"
            )
            if not filepath:
                return False

        exito, total_asigs = self._escribir_config_en(filepath)
        if exito:
            messagebox.showinfo(
                "Configuración Guardada",
                f"Configuración guardada exitosamente en:\n{filepath}\n\n"
                f"Total de asignaciones respaldadas: {total_asigs}\n"
                f"Los datos activos en la base de datos se conservan intactos."
            )
            return True
        return False

    def _actualizar_configuracion(self):
        if not self._ultimo_config_path or not os.path.exists(self._ultimo_config_path):
            if not messagebox.askyesno("Sin archivo",
                    "No hay un archivo de configuración previo.\n¿Deseas elegir una ubicación para guardar?"):
                return
            self._guardar_configuracion()
            return
        exito, total_asigs = self._escribir_config_en(self._ultimo_config_path)
        if exito:
            messagebox.showinfo(
                "Configuración Actualizada",
                f"Configuración actualizada correctamente en:\n{self._ultimo_config_path}\n\n"
                f"Total de asignaciones respaldadas: {total_asigs}"
            )

    def _escribir_config_en(self, filepath):
        self._progress_config.pack(side='left', padx=5)
        self._progress_config["value"] = 0
        self.ventana.update_idletasks()
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return False, 0
                cur, conn = ctx

                # 1. Limpiar registros de disponibilidad inválidos
                cur.execute("DELETE FROM profesor_disponibilidad WHERE dia NOT IN ('0','1','2','3','4','5','6')")
                conn.commit()

                # 2. Catálogo de Materias
                cur.execute("SELECT materia_id, nombre, horas_semana, semestre_id, tipo FROM materias ORDER BY materia_id")
                materias_catalog = []
                for m_id, m_nombre, m_hs, m_sem, m_tipo in cur.fetchall():
                    materias_catalog.append({
                        "materia_id": m_id,
                        "nombre": m_nombre,
                        "horas_semana": str(m_hs) if m_hs else "4",
                        "semestre_id": m_sem,
                        "tipo": m_tipo or "Normal"
                    })

                # 3. Catálogo de Salones
                cur.execute("SELECT salon_id, capacidad, tipo FROM salones ORDER BY salon_id")
                salones_catalog = []
                for s_id, s_cap, s_tipo in cur.fetchall():
                    salones_catalog.append({
                        "salon_id": s_id,
                        "capacidad": s_cap,
                        "tipo": s_tipo or "Normal"
                    })

                # 4. Catálogo de Grupos
                cur.execute("SELECT grupo_id, nivel FROM grupos ORDER BY nivel, grupo_id")
                grupos_catalog = []
                for g_id, g_nivel in cur.fetchall():
                    grupos_catalog.append({
                        "grupo_id": g_id,
                        "nivel": g_nivel
                    })

                # 5. Grupo-Materias (vínculos curriculares)
                cur.execute("SELECT grupo_id, materia_id FROM grupo_materias ORDER BY grupo_id, materia_id")
                grupo_materias_catalog = []
                for g_id, m_id in cur.fetchall():
                    grupo_materias_catalog.append({
                        "grupo_id": g_id,
                        "materia_id": m_id
                    })

                # 6. Catálogo de Profesores
                cur.execute("""
                    SELECT profesor_id, no_cuenta, nombre, correo_institucional,
                           disponible_inicio, disponible_fin, dias_disponibles, en_linea
                    FROM profesores ORDER BY nombre
                """)
                profesores_catalog = []
                for row in cur.fetchall():
                    pid, ncta, nom, correo, di, df, dd, enl = row
                    profesores_catalog.append({
                        "profesor_id": pid,
                        "no_cuenta": ncta or "",
                        "nombre": nom,
                        "correo_institucional": correo or "",
                        "disponible_inicio": self._hora_db_a_str(di) if di else None,
                        "disponible_fin": self._hora_db_a_str(df) if df else None,
                        "dias_disponibles": dd or "",
                        "en_linea": enl or "NO"
                    })

                # 7. Disponibilidad de Profesores
                cur.execute("""
                    SELECT profesor_id, dia, hora_inicio, hora_fin, modalidad
                    FROM profesor_disponibilidad
                    WHERE dia != '6'
                    ORDER BY profesor_id, dia, hora_inicio
                """)
                disp_catalog = []
                for pid, dia, hi, hf, modal in cur.fetchall():
                    disp_catalog.append({
                        "profesor_id": pid,
                        "dia": dia,
                        "hora_inicio": self._hora_db_a_str(hi),
                        "hora_fin": self._hora_db_a_str(hf),
                        "modalidad": modal or "Presencial"
                    })

                # 8. Todas las Asignaciones activas con sus Horarios
                cur.execute("""
                    SELECT asignacion_id, profesor_id, materia_id, grupo_id,
                           periodo, hora_inicio, hora_fin, dias, modalidad, estado
                    FROM asignaciones
                    WHERE estado IS NULL OR estado != 'cancelada'
                    ORDER BY grupo_id, materia_id
                """)
                asig_rows = cur.fetchall()
                asignaciones_catalog = []
                total_asigs = len(asig_rows)

                for idx, row in enumerate(asig_rows):
                    asig_id, p_id, m_id, g_id, per, hi, hf, dias, modal, est = row
                    cur.execute("""
                        SELECT salon_id, dia, hora_inicio, hora_fin
                        FROM horarios
                        WHERE asignacion_id = %s
                        ORDER BY dia, hora_inicio
                    """, (asig_id,))
                    horarios_list = []
                    for s_id, h_dia, h_hi, h_hf in cur.fetchall():
                        horarios_list.append({
                            "salon_id": s_id,
                            "dia": h_dia,
                            "hora_inicio": self._hora_db_a_str(h_hi),
                            "hora_fin": self._hora_db_a_str(h_hf)
                        })

                    asignaciones_catalog.append({
                        "asignacion_id": asig_id,
                        "profesor_id": p_id if p_id else "SIN_ASIGNAR",
                        "materia_id": m_id,
                        "grupo_id": str(g_id),
                        "periodo": per or "A",
                        "hora_inicio": self._hora_db_a_str(hi),
                        "hora_fin": self._hora_db_a_str(hf),
                        "dias": dias or "",
                        "modalidad": modal or "Presencial",
                        "estado": est or "pendiente",
                        "horarios": horarios_list
                    })

                    if total_asigs > 0:
                        self._progress_config["value"] = ((idx + 1) / total_asigs) * 90
                        if idx % 10 == 0:
                            self.ventana.update_idletasks()

                # Profesores formato v1 para retrocompatibilidad
                profesores_v1 = []
                for p_info in profesores_catalog:
                    pid = p_info["profesor_id"]
                    p_disps = [d for d in disp_catalog if d["profesor_id"] == pid]
                    periods_map = {}
                    for d in p_disps:
                        clave = f"{d['hora_inicio']}-{d['hora_fin']}-{d['modalidad']}"
                        if clave not in periods_map:
                            periods_map[clave] = {
                                "hora_i": d["hora_inicio"],
                                "hora_f": d["hora_fin"],
                                "modalidad": d["modalidad"],
                                "dias": [],
                                "asignaciones": []
                            }
                        dia_num = self._normalizar_dia(d["dia"])
                        dia_nombre = self.MAPA_DIAS.get(dia_num, dia_num)
                        if dia_nombre not in periods_map[clave]["dias"]:
                            periods_map[clave]["dias"].append(dia_nombre)

                    p_asigs = [a for a in asignaciones_catalog if str(a["profesor_id"]) == str(pid)]
                    for a in p_asigs:
                        asig_sub = {
                            "materia_id": a["materia_id"],
                            "grupo_id": a["grupo_id"],
                            "periodo": a["periodo"],
                            "estado": a["estado"],
                            "hora_inicio": a["hora_inicio"],
                            "hora_fin": a["hora_fin"],
                            "dias": a["dias"],
                            "modalidad": a["modalidad"],
                            "horarios": a["horarios"]
                        }
                        clave_asig = f"{a['hora_inicio']}-{a['hora_fin']}-{a['modalidad']}"
                        if clave_asig in periods_map:
                            periods_map[clave_asig]["asignaciones"].append(asig_sub)
                        else:
                            dias_p = [d.strip() for d in a["dias"].split(",") if d.strip()]
                            periods_map[clave_asig] = {
                                "hora_i": a["hora_inicio"],
                                "hora_f": a["hora_fin"],
                                "modalidad": a["modalidad"],
                                "dias": dias_p,
                                "asignaciones": [asig_sub]
                            }

                    profesores_v1.append({
                        "profesor_id": pid,
                        "no_cuenta": p_info["no_cuenta"],
                        "nombre": p_info["nombre"],
                        "periodos": list(periods_map.values())
                    })

                config = {
                    "version": 2,
                    "materias": materias_catalog,
                    "salones": salones_catalog,
                    "grupos": grupos_catalog,
                    "grupo_materias": grupo_materias_catalog,
                    "profesores_catalogo": profesores_catalog,
                    "profesor_disponibilidad": disp_catalog,
                    "asignaciones": asignaciones_catalog,
                    "profesores": profesores_v1
                }

                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)

                self._ultimo_config_path = filepath
                self._progress_config["value"] = 100
                self.ventana.update_idletasks()
                return True, len(asignaciones_catalog)
        except Exception as e:
            messagebox.showerror("Error al guardar", f"No se pudo guardar la configuración:\n{e}")
            return False, 0
        finally:
            self._progress_config.pack_forget()

    def _sincronizar_profesor_desde_json(self, cur, prof):
        """Inserta o reutiliza un profesor en la BD al cargar una configuración."""
        prof_id_json = (prof.get("profesor_id") or "").strip()
        no_cuenta_json = (prof.get("no_cuenta") or "").strip()
        nombre_json = (prof.get("nombre") or "").strip()

        candidatos = []
        if no_cuenta_json:
            cur.execute("SELECT profesor_id, no_cuenta, nombre FROM profesores WHERE no_cuenta = %s", (no_cuenta_json,))
            for row in cur.fetchall():
                if row not in candidatos:
                    candidatos.append(row)
        if nombre_json:
            cur.execute("SELECT profesor_id, no_cuenta, nombre FROM profesores WHERE nombre = %s", (nombre_json,))
            for row in cur.fetchall():
                if row not in candidatos:
                    candidatos.append(row)

        if candidatos:
            detalle_bd = "\n".join(
                f"    {pid}  |  Cuenta: {nc or '(vacía)'}  |  Nombre: {nm}"
                for pid, nc, nm in candidatos
            )
            mismo = messagebox.askyesno(
                "Profesor existente",
                f"El profesor del archivo JSON:\n"
                f"    {prof_id_json or '(sin ID)'}  |  Cuenta: {no_cuenta_json or '(vacía)'}  |  Nombre: {nombre_json}\n\n"
                f"Coincide con el(los) registro(s) en la base de datos:\n{detalle_bd}\n\n"
                f"¿Son el MISMO profesor?\n\n"
                f"[Sí]  Conservar el registro de la BD y solo actualizar su disponibilidad.\n"
                f"[No]  Crear un nuevo registro para este profesor."
            )
            if mismo:
                return candidatos[0][0]

        nuevo_id = None
        if prof_id_json:
            cur.execute("SELECT 1 FROM profesores WHERE profesor_id = %s", (prof_id_json,))
            if not cur.fetchone():
                nuevo_id = prof_id_json
        if not nuevo_id:
            nuevo_id = _generar_profesor_id(cur)

        cur.execute(
            "INSERT INTO profesores (profesor_id, no_cuenta, nombre, disponible_inicio, disponible_fin, dias_disponibles, en_linea) "
            "VALUES (%s, %s, %s, '00:00:00', '00:00:00', '', 'NO')",
            (nuevo_id, no_cuenta_json or None, nombre_json)
        )
        return nuevo_id

    def _cargar_configuracion(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")],
            title="Cargar Configuración de Periodos y Asignaciones"
        )
        if not filepath:
            return

        if not messagebox.askyesno("Cargar Configuración",
                "Se restaurará la configuración completa desde el archivo seleccionado.\n\n"
                "• Se actualizarán los catálogos (materias, salones, grupos y profesores).\n"
                "• Se reemplazarán las asignaciones, disponibilidad y horarios actuales con los del archivo.\n\n"
                "¿Desea continuar?"):
            return

        self._progress_config.pack(side='left', padx=5)
        self._progress_config["value"] = 0
        self.ventana.update_idletasks()

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                config = json.load(f)

            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx

                # 1. Catálogo de Materias
                materias_catalog = config.get("materias", [])
                for mat in materias_catalog:
                    m_id = mat.get("materia_id")
                    if not m_id:
                        continue
                    m_nombre = mat.get("nombre", "")
                    m_hs = mat.get("horas_semana", "4")
                    m_sem = mat.get("semestre_id")
                    m_tipo = mat.get("tipo", "Normal")
                    cur.execute("SELECT 1 FROM materias WHERE materia_id = %s", (m_id,))
                    if cur.fetchone():
                        cur.execute(
                            "UPDATE materias SET nombre=%s, horas_semana=%s, semestre_id=%s, tipo=%s WHERE materia_id=%s",
                            (m_nombre, m_hs, m_sem, m_tipo, m_id)
                        )
                    else:
                        cur.execute(
                            "INSERT INTO materias (materia_id, nombre, horas_semana, semestre_id, tipo) VALUES (%s, %s, %s, %s, %s)",
                            (m_id, m_nombre, m_hs, m_sem, m_tipo)
                        )

                # 2. Catálogo de Salones
                salones_catalog = config.get("salones", [])
                for sal in salones_catalog:
                    s_id = sal.get("salon_id")
                    if not s_id:
                        continue
                    s_cap = sal.get("capacidad", 0)
                    s_tipo = sal.get("tipo", "Normal")
                    cur.execute("SELECT 1 FROM salones WHERE salon_id = %s", (s_id,))
                    if cur.fetchone():
                        cur.execute(
                            "UPDATE salones SET capacidad=%s, tipo=%s WHERE salon_id=%s",
                            (s_cap, s_tipo, s_id)
                        )
                    else:
                        cur.execute(
                            "INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, %s, %s)",
                            (s_id, s_cap, s_tipo)
                        )

                # 3. Catálogo de Grupos
                grupos_catalog = config.get("grupos", [])
                for grp in grupos_catalog:
                    g_id = grp.get("grupo_id")
                    if not g_id:
                        continue
                    g_niv = grp.get("nivel")
                    cur.execute("SELECT 1 FROM grupos WHERE grupo_id = %s", (g_id,))
                    if cur.fetchone():
                        if g_niv is not None:
                            cur.execute("UPDATE grupos SET nivel=%s WHERE grupo_id=%s", (g_niv, g_id))
                    else:
                        cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, %s)", (g_id, g_niv if g_niv is not None else 0))

                # 4. Grupo-Materias (vínculos curriculares)
                grupo_mat_catalog = config.get("grupo_materias", [])
                for gm in grupo_mat_catalog:
                    g_id = gm.get("grupo_id")
                    m_id = gm.get("materia_id")
                    if g_id and m_id:
                        cur.execute("SELECT 1 FROM grupos WHERE grupo_id = %s", (g_id,))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, 0)", (g_id,))
                        cur.execute("SELECT 1 FROM grupo_materias WHERE grupo_id = %s AND materia_id = %s", (g_id, m_id))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO grupo_materias (grupo_id, materia_id) VALUES (%s, %s)", (g_id, m_id))

                # 5. Profesores
                prof_id_map = {}
                profesores_cat = config.get("profesores_catalogo")
                if profesores_cat:
                    for p in profesores_cat:
                        p_id = (p.get("profesor_id") or "").strip()
                        ncta = (p.get("no_cuenta") or "").strip() or None
                        nom = (p.get("nombre") or "").strip()
                        correo = p.get("correo_institucional") or None
                        di = p.get("disponible_inicio")
                        df = p.get("disponible_fin")
                        dd = p.get("dias_disponibles")
                        enl = p.get("en_linea") or "NO"

                        if not nom and not p_id:
                            continue

                        cur.execute("SELECT profesor_id FROM profesores WHERE profesor_id = %s", (p_id,))
                        row = cur.fetchone()
                        if not row and ncta:
                            cur.execute("SELECT profesor_id FROM profesores WHERE no_cuenta = %s", (ncta,))
                            row = cur.fetchone()
                        if not row and nom:
                            cur.execute("SELECT profesor_id FROM profesores WHERE nombre = %s", (nom,))
                            row = cur.fetchone()

                        if row:
                            bd_pid = row[0]
                            prof_id_map[p_id] = bd_pid
                            cur.execute("""
                                UPDATE profesores
                                SET no_cuenta=COALESCE(%s, no_cuenta),
                                    nombre=%s,
                                    correo_institucional=COALESCE(%s, correo_institucional),
                                    disponible_inicio=COALESCE(%s, disponible_inicio),
                                    disponible_fin=COALESCE(%s, disponible_fin),
                                    dias_disponibles=COALESCE(%s, dias_disponibles),
                                    en_linea=%s
                                WHERE profesor_id = %s
                            """, (ncta, nom, correo, di, df, dd, enl, bd_pid))
                        else:
                            nuevo_pid = p_id if p_id else _generar_profesor_id(cur)
                            cur.execute("""
                                INSERT INTO profesores (profesor_id, no_cuenta, nombre, correo_institucional,
                                                       disponible_inicio, disponible_fin, dias_disponibles, en_linea)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (nuevo_pid, ncta, nom, correo, di, df, dd, enl))
                            prof_id_map[p_id] = nuevo_pid
                else:
                    for prof in config.get("profesores", []):
                        pid_orig = (prof.get("profesor_id") or "").strip()
                        pid_nuevo = self._sincronizar_profesor_desde_json(cur, prof)
                        if pid_orig:
                            prof_id_map[pid_orig] = pid_nuevo

                # 6. Limpiar tablas transaccionales antes de recargar disponibilidad, asignaciones y horarios
                cur.execute("TRUNCATE TABLE horarios")
                cur.execute("DELETE FROM asignaciones")
                cur.execute("DELETE FROM profesor_disponibilidad")

                # 7. Disponibilidad de Profesores
                disponibilidad_cat = config.get("profesor_disponibilidad")
                if disponibilidad_cat:
                    for d in disponibilidad_cat:
                        raw_pid = d.get("profesor_id")
                        real_pid = prof_id_map.get(raw_pid, raw_pid)
                        dia_num = self._normalizar_dia(d.get("dia", "0"))
                        hi = d.get("hora_inicio")
                        hf = d.get("hora_fin")
                        modal = d.get("modalidad", "Presencial")
                        if real_pid and hi and hf and dia_num in ('0','1','2','3','4','5'):
                            cur.execute(
                                "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin, modalidad) VALUES (%s, %s, %s, %s, %s)",
                                (real_pid, dia_num, hi, hf, modal)
                            )
                elif "profesores" in config:
                    for prof in config.get("profesores", []):
                        raw_pid = prof.get("profesor_id")
                        real_pid = prof_id_map.get(raw_pid, raw_pid)
                        if not real_pid:
                            continue
                        for per in prof.get("periodos", []):
                            hi = per.get("hora_i")
                            hf = per.get("hora_f")
                            modal = per.get("modalidad", "Presencial")
                            for dia_nom in per.get("dias", []):
                                dia_num = self._normalizar_dia(dia_nom)
                                if dia_num in ('0','1','2','3','4','5'):
                                    cur.execute(
                                        "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin, modalidad) VALUES (%s, %s, %s, %s, %s)",
                                        (real_pid, dia_num, hi, hf, modal)
                                    )

                # 8. Asignaciones y Horarios
                asignaciones_cat = config.get("asignaciones")
                total_cargadas = 0

                if asignaciones_cat is not None:
                    # Formato v2
                    total_total = len(asignaciones_cat)
                    for idx, asig in enumerate(asignaciones_cat):
                        raw_pid = asig.get("profesor_id")
                        if raw_pid and raw_pid != 'SIN_ASIGNAR':
                            real_pid = prof_id_map.get(raw_pid, raw_pid)
                        else:
                            real_pid = 'SIN_ASIGNAR'

                        m_id = asig.get("materia_id")
                        g_id = asig.get("grupo_id")
                        per = asig.get("periodo", "A")
                        hi = asig.get("hora_inicio") or None
                        hf = asig.get("hora_fin") or None
                        dias = asig.get("dias") or ""
                        modal = asig.get("modalidad", "Presencial")
                        est = asig.get("estado", "pendiente")

                        if not m_id or not g_id:
                            continue

                        cur.execute("SELECT 1 FROM grupos WHERE grupo_id = %s", (g_id,))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, 0)", (g_id,))
                        cur.execute("SELECT 1 FROM grupo_materias WHERE grupo_id = %s AND materia_id = %s", (g_id, m_id))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO grupo_materias (grupo_id, materia_id) VALUES (%s, %s)", (g_id, m_id))

                        cur.execute("""
                            INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, periodo, hora_inicio, hora_fin, dias, modalidad, estado)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (real_pid, m_id, g_id, per, hi, hf, dias, modal, est))
                        nueva_asig_id = cur.lastrowid
                        total_cargadas += 1

                        for h in asig.get("horarios", []):
                            s_id = h.get("salon_id")
                            h_dia = h.get("dia")
                            h_hi = h.get("hora_inicio")
                            h_hf = h.get("hora_fin")
                            if s_id and h_dia and h_hi and h_hf:
                                cur.execute("SELECT 1 FROM salones WHERE salon_id = %s", (s_id,))
                                if not cur.fetchone():
                                    cur.execute("INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, 30, 'Normal')", (s_id,))
                                dia_num = self._normalizar_dia(h_dia)
                                dia_nombre = self.MAPA_DIAS.get(dia_num, h_dia)
                                cur.execute("""
                                    INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                                    VALUES (%s, %s, %s, %s, %s)
                                """, (nueva_asig_id, s_id, dia_nombre, h_hi, h_hf))

                        if total_total > 0:
                            self._progress_config["value"] = ((idx + 1) / total_total) * 100
                            if idx % 10 == 0:
                                self.ventana.update_idletasks()
                else:
                    # Formato v1 legacy
                    profesores_list = config.get("profesores", [])
                    total_total = len(profesores_list)
                    for idx, prof in enumerate(profesores_list):
                        raw_pid = prof.get("profesor_id")
                        real_pid = prof_id_map.get(raw_pid, raw_pid)
                        for periodo in prof.get("periodos", []):
                            hora_i = periodo.get("hora_i")
                            hora_f = periodo.get("hora_f")
                            modalidad = periodo.get("modalidad", "Presencial")
                            dias_list = periodo.get("dias", [])
                            dias_str = ", ".join(dias_list)

                            for asig in periodo.get("asignaciones", []):
                                mat_id = asig.get("materia_id")
                                grupo_texto = asig.get("grupo_id")
                                periodo_letra = asig.get("periodo", "A")
                                estado = asig.get("estado", "pendiente")
                                grupo_id = self._obtener_id_valido(grupo_texto, es_grupo=True)
                                if not grupo_id or not mat_id:
                                    continue

                                cur.execute("SELECT 1 FROM grupos WHERE grupo_id = %s", (grupo_id,))
                                if not cur.fetchone():
                                    cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, 0)", (grupo_id,))
                                cur.execute("SELECT 1 FROM grupo_materias WHERE grupo_id = %s AND materia_id = %s", (grupo_id, mat_id))
                                if not cur.fetchone():
                                    cur.execute("INSERT INTO grupo_materias (grupo_id, materia_id) VALUES (%s, %s)", (grupo_id, mat_id))

                                cur.execute("""
                                    INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, estado, periodo, hora_inicio, hora_fin, dias, modalidad)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """, (real_pid, mat_id, grupo_id, estado, periodo_letra, hora_i, hora_f, dias_str, modalidad))
                                nueva_asig_id = cur.lastrowid
                                total_cargadas += 1

                                for h in asig.get("horarios", []):
                                    dia_num = self._normalizar_dia(h["dia"])
                                    dia_nombre = self.MAPA_DIAS.get(dia_num, "Lunes")
                                    salon_id = h["salon_id"]
                                    cur.execute("SELECT 1 FROM salones WHERE salon_id = %s", (salon_id,))
                                    if not cur.fetchone():
                                        cur.execute("INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, 30, 'Normal')", (salon_id,))
                                    cur.execute("""
                                        INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                                        VALUES (%s, %s, %s, %s, %s)
                                    """, (nueva_asig_id, salon_id, dia_nombre, h["hora_inicio"], h["hora_fin"]))

                        if total_total > 0:
                            self._progress_config["value"] = ((idx + 1) / total_total) * 100
                            self.ventana.update_idletasks()

                conn.commit()

            # Refrescar toda la interfaz gráfica
            self.grupos_por_semestre = self._cargar_grupos_desde_bd()
            self.cargar_combos_bd()

            if hasattr(self, 'combo_filtro_semestre'):
                self.combo_filtro_semestre['values'] = ["Todos"] + list(self.semestres_map.values())
                self.combo_filtro_semestre.set("Todos")

            if hasattr(self, 'combo_filtro_semestre_vp'):
                self.combo_filtro_semestre_vp['values'] = ["Todos"] + list(self.semestres_map.values())
                self._sv_filtro_semestre_vp.set("Todos")
                self._on_filtro_semestre_vp()

            grupos = self._grupos_filtrados_actual()
            if hasattr(self, 'combo_grupo_gestion'):
                self.combo_grupo_gestion['values'] = grupos
                if grupos:
                    self.combo_grupo_gestion.set(grupos[0])
                    self._on_cambio_grupo_gestion()
                    self._seleccionar_grupo_previa(grupos[0])
                else:
                    self.combo_grupo_gestion.set('')
                    self._cargar_materias_grupo_gestion()

            if self._profesor_id_seleccionado:
                self._cargar_periodos_desde_bd()

            self.actualizar_vista_previa()
            self._cargar_previa_horario_grupo()
            self._ultimo_config_path = filepath
            messagebox.showinfo(
                "Configuración Cargada",
                f"Configuración cargada exitosamente desde:\n{filepath}\n\n"
                f"Total de asignaciones restauradas: {total_cargadas}"
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Error al cargar configuración", f"Ocurrió un error al cargar el archivo:\n{e}")
        finally:
            self._progress_config.pack_forget()

    def _guardar_disponibilidad_periodo(self, profesor_id, hora_i, hora_f, dias_sel, modalidad="Presencial", db_hora_i="", db_hora_f=""):
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                # Delete old rows (both original and current horas, in case they changed)
                if db_hora_i and db_hora_f and (db_hora_i != hora_i or db_hora_f != hora_f):
                    cur.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id = %s AND hora_inicio = %s AND hora_fin = %s",
                                (profesor_id, db_hora_i, db_hora_f))
                cur.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id = %s AND hora_inicio = %s AND hora_fin = %s",
                            (profesor_id, hora_i, hora_f))
                for dia in dias_sel:
                    dia_num = self._normalizar_dia(dia)
                    cur.execute(
                        "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin, modalidad) VALUES (%s, %s, %s, %s, %s)",
                        (profesor_id, dia_num, hora_i, hora_f, modalidad)
                    )
        except Exception as e:
            print(f"Error guardando disponibilidad: {e}")

    def _actualizar_horas_periodo(self, combo_mat, label_restante):
        try:
            materia_txt = combo_mat.get()
        except Exception:
            return
        if not materia_txt:
            return
        mat_id = self._obtener_id_valido(materia_txt)
        if not mat_id:
            return
        hrs_mat = self._get_horas_materia(mat_id)
        disponibles, asignadas = self._calcular_horas_con_ui(self._profesor_id_seleccionado) if self._profesor_id_seleccionado else (0, 0)
        restantes = max(0, disponibles - asignadas)
        despues = restantes - hrs_mat
        if despues < 0:
            label_restante.config(
                text=f"Disponible: {restantes:.1f}h — Esta materia excede por {abs(despues):.1f}h",
                foreground='#FF6B6B'
            )
        else:
            label_restante.config(
                text=f"Disponible: {restantes:.1f}h — Después quedarían {despues:.1f}h",
                foreground='#98FB98'
            )

    def _obtener_id_valido(self, texto_combo, es_grupo=False):
        if not texto_combo: return None
        textos_invalidos = ["sin grupos", "cargando", "seleccione", "sin materias", "no asignado", "grupos llenos"]
        if any(txt in texto_combo.lower() for txt in textos_invalidos): return None
        if ' - ' in texto_combo: return texto_combo.split(' - ')[0]
        if es_grupo: return texto_combo.upper()
        return None

    def _rescale_ui(self):
        w = self.ventana.winfo_width()
        h = self.ventana.winfo_height()
        if w < 100 or h < 100:
            return
        escala = min(w / 1920, h / 1080)
        escala = max(0.5, min(escala, 2.0))
        if abs(escala - self._scale_factor) < 0.05:
            return
        self._scale_factor = escala
        if hasattr(self, '_fuente_titulo'):
            self._fuente_titulo.configure(size=max(12, int(18 * escala)))
        if hasattr(self, '_fuente_sub'):
            self._fuente_sub.configure(size=max(9, int(12 * escala)))
        if hasattr(self, '_fuente_label'):
            self._fuente_label.configure(size=max(8, int(10 * escala)))
        if hasattr(self, '_fuente_btn'):
            self._fuente_btn.configure(size=max(8, int(10 * escala)))
        estilo = ttk.Style()
        estilo.configure('Treeview', rowheight=max(18, int(22 * escala)))

    def redimensionar_fondo(self, event):
        try:
            if event.width > 0 and event.height > 0 and hasattr(self, 'original_image'):
                self._rescale_ui()
                if event.width != self._last_width or event.height != self._last_height:
                    self._last_width, self._last_height = event.width, event.height
                    resized = self.original_image.resize((event.width, event.height), Image.LANCZOS)
                    self.background_image = ImageTk.PhotoImage(resized)
                    self.background_label.config(image=self.background_image)
        except Exception as e: print(f"Error resize: {e}")

    # --- LÓGICA DE NEGOCIO ---
    
    def borrar_asignacion_seleccionada(self):
        """
        Elimina la(s) asignación(es) seleccionada(s) en la tabla de vista previa.
        Permite selección única o múltiple de filas.
        """
        seleccionados = self.tabla_asignaciones.selection()
        if not seleccionados:
            if self.asignacion_seleccionada_id and self.asignacion_seleccionada_id not in ("no_results", "error_bd"):
                seleccionados = [self.asignacion_seleccionada_id]
            else:
                messagebox.showwarning("Aviso", "Primero selecciona una o más asignaciones de la tabla.")
                return

        ids_a_borrar = [s for s in seleccionados if s not in ("no_results", "error_bd")]
        if not ids_a_borrar:
            return

        total = len(ids_a_borrar)
        texto_pregunta = f"¿Estás seguro de eliminar {total} asignación(es)?\n\nSe liberarán sus horarios y espacios de aula." if total > 1 else "¿Estás seguro de eliminar esta asignación?\n\nSe liberará su horario y espacio de aula."

        if not messagebox.askyesno("Confirmar Eliminación", texto_pregunta):
            return

        self._ejecutar_eliminacion_en_hilo(
            titulo="Liberando asignación(es)...",
            mensaje=f"Eliminando {total} asignación(es) seleccionada(s)...",
            es_total=False,
            ids=ids_a_borrar
        )

    def formatear_asignaciones(self):
        """
        Borra todas las asignaciones y horarios guardados en la base de datos de manera
        asíncrona con barra de progreso, evitando congelar la interfaz.
        """
        if not messagebox.askyesno(
            "¡ADVERTENCIA CRÍTICA!",
            "¿Estás ABSOLUTAMENTE SEGURO de querer borrar TODAS las asignaciones guardadas?\n\n"
            "Esto vaciará por completo la base de datos de horarios y asignaciones. "
            "No se puede deshacer."
        ):
            return

        # Crear respaldo automático previo por seguridad
        try:
            from src.gestor_restauracion import GestorRestauracion
            GestorRestauracion.crear_punto(
                nombre="Auto-respaldo antes de borrar todo",
                descripcion="Creado automáticamente antes de vaciar las asignaciones"
            )
        except Exception as e:
            print(f"Error creando auto-respaldo previo: {e}")

        self._ejecutar_eliminacion_en_hilo(
            titulo="Borrando todas las asignaciones...",
            mensaje="Vaciando la base de datos de horarios y asignaciones...",
            es_total=True
        )

    def _ejecutar_eliminacion_en_hilo(self, titulo, mensaje, es_total=False, ids=None):
        """
        Ejecuta la eliminación en segundo plano (hilo) con ventana modal y barra de progreso.
        """
        self._en_operacion = True
        loading = tk.Toplevel(self.ventana)
        loading.title(titulo)
        loading.geometry("380x130")
        loading.transient(self.ventana)
        loading.grab_set()
        loading.resizable(False, False)

        ttk.Label(loading, text=mensaje, font=("Roboto", 11), wraplength=340).pack(pady=(15, 8))
        progress = ttk.Progressbar(loading, mode='indeterminate', length=320)
        progress.pack(pady=6)
        progress.start(10)
        loading.update()

        def tarea():
            result_queue = queue.Queue()
            try:
                with obtener_cursor() as ctx:
                    if not ctx:
                        result_queue.put(("error", "No hay conexión a la base de datos"))
                        return
                    cur, conn = ctx
                    if es_total:
                        cur.execute("DELETE FROM horarios")
                        cur.execute("DELETE FROM asignaciones")
                        try: cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('horarios', 'asignaciones')")
                        except Exception: pass
                    else:
                        for chunk_start in range(0, len(ids), 200):
                            chunk = ids[chunk_start:chunk_start + 200]
                            placeholders = ', '.join(['%s'] * len(chunk))
                            cur.execute(f"DELETE FROM horarios WHERE asignacion_id IN ({placeholders})", chunk)
                            cur.execute(f"DELETE FROM asignaciones WHERE asignacion_id IN ({placeholders})", chunk)

                    conn.commit()
                result_queue.put(("ok", None))
            except Exception as e:
                result_queue.put(("error", str(e)))

            def procesar_resultado():
                self._en_operacion = False
                try:
                    loading.destroy()
                except Exception:
                    pass

                try:
                    tipo, err = result_queue.get_nowait()
                except queue.Empty:
                    tipo, err = "error", "No se recibió respuesta."

                if tipo == "error":
                    messagebox.showerror("Error", f"Ocurrió un error al eliminar: {err}")
                    return

                self.asignacion_seleccionada_id = None
                self._materia_grupo_seleccionada_id = None

                # Actualizar todos los componentes visuales
                self.actualizar_vista_previa(mostrar_todo=True)
                if hasattr(self, '_cargar_materias_grupo_gestion'):
                    self._cargar_materias_grupo_gestion()
                self._cargar_previa_horario_grupo()
                self._cargar_tensor_diferido(forzar=True)

                if es_total:
                    if self._profesor_id_seleccionado:
                        for item in self._periodos_frame.winfo_children():
                            item.destroy()
                        self._periodos_asignacion.clear()
                        self._cargar_periodos_desde_bd()
                    messagebox.showinfo("Éxito", "Todas las asignaciones y horarios han sido eliminados correctamente.")
                else:
                    messagebox.showinfo("Éxito", f"Se eliminaron {len(ids)} asignación(es) correctamente.")

            self.ventana.after(0, procesar_resultado)

        hilo = threading.Thread(target=tarea, daemon=True)
        hilo.start()

    def cargar_asignacion_seleccionada(self, event):
        item = self.tabla_asignaciones.focus()
        if not item or item == "no_results": return
        
        self.asignacion_seleccionada_id = item

    def _mostrar_dialogo_modo_preasignacion(self):
        """
        Muestra un diálogo de confirmación para elegir si se preasignan
        todos los grupos o solo los grupos que aún no tienen aula asignada.
        Retorna 'sin_aula', 'todos', o None (cancelar).
        """
        seleccion = [None]

        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Preasignación de Aulas y Horarios")
        dialogo.transient(self.ventana)
        dialogo.grab_set()
        dialogo.configure(background='#0A0F1E')
        dialogo.geometry("540x360")
        dialogo.resizable(False, False)

        f_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=20, pady=16)

        ttk.Label(
            f_cont,
            text="🏢 Preasignación de Aulas y Horarios",
            background='#0A0F1E',
            foreground='#38BDF8',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 6))

        ttk.Label(
            f_cont,
            text="¿Qué grupos desea preasignar?",
            background='#0A0F1E',
            foreground='#FFFFFF',
            font=self._fuente_sub
        ).pack(anchor='w', pady=(0, 10))

        # Opción 1: Solo grupos sin aula (Recomendado)
        f_op1 = ttk.LabelFrame(f_cont, text="Opción Recomendada", style='blue.TFrame')
        f_op1.pack(fill='x', pady=6)

        def _sel_sin_aula():
            seleccion[0] = "sin_aula"
            dialogo.destroy()

        ttk.Button(
            f_op1,
            text="⚡ Solo grupos que no tienen aula aún",
            command=_sel_sin_aula
        ).pack(anchor='w', padx=10, pady=(6, 2))

        ttk.Label(
            f_op1,
            text="• Conserva intactos los grupos y materias ya asignadas a profesores.\n• Solo asigna salón y horarios a los grupos pendientes.",
            background='#0A0F1E',
            foreground='#81C784',
            font=self._fuente_label,
            justify='left'
        ).pack(anchor='w', padx=10, pady=(0, 6))

        # Opción 2: Todos los grupos
        f_op2 = ttk.LabelFrame(f_cont, text="Reasignación Total", style='blue.TFrame')
        f_op2.pack(fill='x', pady=6)

        def _sel_todos():
            if messagebox.askyesno(
                "Confirmar Reasignación Total",
                "¿Estás seguro de querer preasignar TODOS los grupos registrados?\n\n"
                "Se reorganizarán los salones y horarios para toda la institución.\n\n"
                "¿Deseas continuar?"
            ):
                seleccion[0] = "todos"
                dialogo.destroy()

        ttk.Button(
            f_op2,
            text="🔄 Todos los grupos registrados",
            command=_sel_todos
        ).pack(anchor='w', padx=10, pady=(6, 2))

        ttk.Label(
            f_op2,
            text="• Vuelve a distribuir las aulas y horarios de todos los grupos desde cero.\n• Mantendrá las vinculaciones docentes siempre que sea compatible.",
            background='#0A0F1E',
            foreground='#FFB74D',
            font=self._fuente_label,
            justify='left'
        ).pack(anchor='w', padx=10, pady=(0, 6))

        # Botón cancelar
        f_btn = ttk.Frame(f_cont, style='blue.TFrame')
        f_btn.pack(fill='x', side='bottom', pady=(10, 0))

        def _cancelar():
            seleccion[0] = None
            dialogo.destroy()

        ttk.Button(f_btn, text="Cancelar", command=_cancelar).pack(side='right', padx=4)

        dialogo.wait_window()
        return seleccion[0]

    def _preasignar_todas_aulas(self):
        """
        Ejecuta la preasignación de aulas y horarios según la selección del usuario.
        """
        modo = self._mostrar_dialogo_modo_preasignacion()
        if not modo:
            return

        solo_sin_aula = (modo == "sin_aula")

        from src.motor_preasignacion import GeneradorPreasignacion
        motor = GeneradorPreasignacion()
        res = motor.ejecutar(solo_sin_aula=solo_sin_aula)
        if res.get("exito"):
            messagebox.showinfo(
                "Preasignación Exitosa",
                res.get("mensaje", f"Se preasignaron exitosamente {res.get('materias_asignadas', 0)} materias.")
            )
            self.actualizar_vista_previa()
            self._cargar_materias_grupo_gestion()
        else:
            messagebox.showerror(
                "Error en Preasignación",
                res.get("mensaje", "Ocurrió un error en la preasignación.")
            )

    def iniciar_asignacion_automatica(self):
        respuesta = messagebox.askyesnocancel(
            "Tipo de Asignación", 
            "¿Deseas resetear todos los horarios y empezar desde cero?\n\n"
            "• SÍ: Borra todo y asigna desde cero.\n"
            "• NO: Mantiene los horarios actuales y SOLO asigna los pendientes.\n"
            "• CANCELAR: Abortar operación."
        )
        if respuesta is None:
            return
        modo_seleccionado = "completo" if respuesta else "parcial"

        # Crear respaldo automático previo por seguridad
        try:
            from src.gestor_restauracion import GestorRestauracion
            GestorRestauracion.crear_punto(
                nombre=f"Auto-respaldo antes de asignación ({modo_seleccionado})",
                descripcion=f"Generado automáticamente antes de asignación automática ({modo_seleccionado})"
            )
        except Exception as e:
            print(f"Error creando auto-respaldo previo: {e}")

        self._en_operacion = True
        loading = tk.Toplevel(self.ventana)
        loading.title("Asignando horarios...")
        loading.geometry("350x120")
        loading.transient(self.ventana)
        loading.grab_set()
        ttk.Label(loading, text="Generando horarios...", font=("Roboto", 12)).pack(pady=10)
        progress = ttk.Progressbar(loading, mode='indeterminate', length=300)
        progress.pack(pady=10)
        progress.start()
        ttk.Label(loading, text="Esto puede tomar unos segundos", font=("Roboto", 9)).pack()
        loading.update()

        def tarea():
            result_queue = queue.Queue()
            try:
                conexion = get_conexion()
                if not conexion:
                    result_queue.put(("error", "No hay conexión a la base de datos"))
                    return
                try:
                    print("[DEBUG ASIGNACION] ===== INICIANDO ASIGNACION AUTOMATICA =====")
                    # Clean ALL corrupt dia values before running
                    with obtener_cursor() as ctx2:
                        if ctx2:
                            cur2, conn2 = ctx2
                            cur2.execute("DELETE FROM profesor_disponibilidad WHERE dia NOT IN ('0','1','2','3','4','5','6')")
                            n2 = cur2.rowcount
                            if n2:
                                print(f"[DEBUG ASIGNACION] Limpiadas {n2} filas corruptas de disponibilidad")
                            conn2.commit()
                    print(f"[DEBUG ASIGNACION] Modo: {modo_seleccionado}")
                    generador = GeneradorHorarios(conexion)
                    generador.separacion_online_activa = False
                    resultado = generador.ejecutar(modo=modo_seleccionado)
                    if isinstance(resultado, tuple):
                        cantidad, alertas = resultado
                    else:
                        cantidad = resultado
                        alertas = []
                    result_queue.put(("ok", cantidad, alertas))
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    result_queue.put(("error", f"{type(e).__name__}: {e}"))
                finally:
                    conexion.close()
            except Exception as e:
                import traceback
                traceback.print_exc()
                result_queue.put(("error", f"{type(e).__name__}: {e}"))

            def procesar_resultado():
                self._en_operacion = False
                loading.destroy()
                try:
                    tipo, *datos = result_queue.get_nowait()
                except queue.Empty:
                    messagebox.showerror("Error", "No se recibió respuesta del proceso.")
                    return

                if tipo == "error":
                    print(f"[DEBUG ASIGNACION] ERROR CAPTURADO: {datos[0]}")
                    messagebox.showerror("Error", f"Falló la generación de horarios: {datos[0]}")
                    return

                cantidad, alertas = datos
                self._ultimas_alertas = alertas
                self._mostrar_alertas_en_tabla()
                if alertas:
                    messagebox.showwarning(
                        "Asignación con Conflictos",
                        f"Se asignaron {cantidad} horarios.\n"
                        f"Hubo conflictos con {len(alertas)} materia(s).\n\n"
                        f"Revisa los detalles en la pestaña 'Alertas'."
                    )
                else:
                    messagebox.showinfo("Éxito",
                        f"¡Perfecto! Se generaron {cantidad} horarios sin conflictos en modo '{modo_seleccionado}'.")

                self._cargar_tensor_diferido(forzar=True)
                self._cargar_previa_horario_grupo()
                self.notebook.select(self.pes1)

            self.ventana.after(0, procesar_resultado)

        hilo = threading.Thread(target=tarea, daemon=True)
        hilo.start()

    def cargar_grupos_por_semestre(self, semestre_id, materia_id=None):
        grupos_base = self._grupos_del_semestre(semestre_id)
        grupos_filtrados = grupos_base.copy()
        if materia_id:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return []
                cur, conn = ctx
                try:
                    if self.asignacion_seleccionada_id:
                        cur.execute(
                            "SELECT grupo_id FROM asignaciones "
                            "WHERE materia_id = %s AND asignacion_id != %s "
                            "AND (estado IS NULL OR estado != 'cancelada')",
                            (materia_id, self.asignacion_seleccionada_id)
                        )
                    else:
                        cur.execute(
                            "SELECT grupo_id FROM asignaciones "
                            "WHERE materia_id = %s "
                            "AND (estado IS NULL OR estado != 'cancelada')",
                            (materia_id,)
                        )
                    
                    grupos_ocupados = [row[0] for row in cur.fetchall()]
                    grupos_filtrados = [g for g in grupos_base if g not in grupos_ocupados]
                except sqlite3.Error as err:
                    print(f"Error filtrando grupos: {err}")

        return grupos_filtrados

    def cargar_combos_bd(self):
        with obtener_cursor() as ctx:
            if ctx is None:
                return
            cur, conn = ctx
            try:
                cur.execute("SELECT profesor_id, nombre, no_cuenta FROM profesores ORDER BY nombre")
                profesores = cur.fetchall()
                self.profesores_map = {}
                self._lista_completa_profesores = []
                for row in profesores:
                    pid = str(row[0])
                    nombre = row[1]
                    no_cuenta = row[2] if row[2] else ''
                    self.profesores_map[pid] = {"nombre": nombre, "no_cuenta": no_cuenta}
                    self._lista_completa_profesores.append((pid, no_cuenta, nombre))

                cur.execute(
                    "SELECT profesor_id, dia, hora_inicio, hora_fin "
                    "FROM profesor_disponibilidad ORDER BY profesor_id"
                )
                filas_disponibilidad = cur.fetchall()
                dias = {"0": "Lu", "1": "Ma", "2": "Mi", "3": "Ju", "4": "Vi", "5": "Sa", "6": "Do"}
                self._disponibilidad_profesores = {}
                for pid, dia, hora_inicio, hora_fin in filas_disponibilidad:
                    key = str(pid)
                    dia_str = dias.get(str(dia), f"D{dia}")
                    self._disponibilidad_profesores.setdefault(key, []).append(
                        f"{dia_str} {hora_inicio}-{hora_fin}"
                    )

                self._poblar_tabla_profesores(self._lista_completa_profesores)

                cur.execute("SELECT id_semestre, nombre FROM semestres ORDER BY id_semestre")
                semestres = cur.fetchall()
                self.semestres_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in semestres}
                self.lista_maestra_semestres = [{"texto": f"{row[0]} - {row[1]}", "id": int(row[0])} for row in semestres]

                cur.execute("SELECT materia_id, nombre, semestre_id FROM materias ORDER BY semestre_id")
                materias = cur.fetchall()
                self.materias_map = {}
                self.lista_maestra_materias = []
                for row in materias:
                    m_id, nombre, s_id = row
                    self.materias_map[str(m_id)] = s_id
                    sem_val = int(s_id) if s_id is not None else 0
                    self.lista_maestra_materias.append({"texto": f"{m_id} - {nombre}", "semestre": sem_val})

                cur.execute("SELECT grupo_id, nivel FROM grupos ORDER BY nivel, grupo_id")
                self.grupos_por_semestre = {}
                for grupo_id, nivel in cur.fetchall():
                    nivel = self._normalizar_nivel_grupo(nivel)
                    self.grupos_por_semestre.setdefault(nivel, []).append(grupo_id)

                self.actualizar_vista_previa()

                if self._semestres_filtrados:
                    lista_sem = [v for k, v in self.semestres_map.items() if int(k) in self._semestres_filtrados]
                else:
                    lista_sem = list(self.semestres_map.values())
                self.combo_filtro_semestre['values'] = lista_sem
                if lista_sem and not self.combo_filtro_semestre.get():
                    self.combo_filtro_semestre.set(lista_sem[0])

                if hasattr(self, 'combo_filtro_semestre_vp'):
                    self.combo_filtro_semestre_vp['values'] = ["Todos"] + lista_sem
                    self._on_filtro_semestre_vp(preservar_seleccion=True)

                if not self.combo_periodos.get() and self.combo_periodos['values']:
                    self.combo_periodos.set(self.combo_periodos['values'][0])
                    self._cambiar_filtro_periodo()
                else:
                    self._cambiar_filtro_semestre()
                self._cargar_salones_para_manual()

                self._actualizar_grupos_en_periodos()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error cargando combos: {err}")

    def _poblar_tabla_profesores(self, lista_prof):
        if not hasattr(self, 'tabla_profesores'):
            return

        children = self.tabla_profesores.get_children()
        if children:
            self.tabla_profesores.delete(*children)
        for pid, no_cuenta, nombre in lista_prof:
            partes = self._disponibilidad_profesores.get(str(pid), [])
            disponibilidad = ", ".join(partes[:3]) + ("..." if len(partes) > 3 else "") if partes else "Sin disponibilidad"
            self.tabla_profesores.insert('', 'end', values=(no_cuenta, nombre, disponibilidad))

    def limpiar_filtros(self):
        self.asignacion_seleccionada_id = None
        if hasattr(self, 'sv_busqueda_asignaciones'):
            self.sv_busqueda_asignaciones.set("")
        self.actualizar_vista_previa(mostrar_todo=True)

    # --- PESTAÑA DE ALERTAS ---
    def _construir_pestana_alertas(self):
        f_superior = ttk.Frame(self.pes_alertas, style='blue.TFrame')
        f_superior.pack(fill='both', expand=True, padx=10, pady=10)

        ttk.Label(f_superior, text="ALERTAS DE ASIGNACIÓN",
                  background='#0A0F1E', foreground='white',
                  font=self._fuente_titulo).pack(pady=(5, 10))

        f_contenido = ttk.Frame(f_superior, style='blue.TFrame')
        f_contenido.pack(fill='both', expand=True)

        cols = ('Materia', 'Grupo', 'Profesor', 'Causa')
        self.tabla_alertas = ttk.Treeview(f_contenido, columns=cols, show='headings', height=8)
        for c in cols:
            self.tabla_alertas.heading(c, text=c)
        self.tabla_alertas.column('Materia', width=200)
        self.tabla_alertas.column('Grupo', width=80)
        self.tabla_alertas.column('Profesor', width=250)
        self.tabla_alertas.column('Causa', width=350)
        self.tabla_alertas.pack(side='top', fill='x', pady=(0, 5))
        self.tabla_alertas.bind("<<TreeviewSelect>>", self._mostrar_detalle_alerta)

        sb_a = ttk.Scrollbar(f_contenido, orient='vertical', command=self.tabla_alertas.yview)
        self.tabla_alertas.configure(yscroll=sb_a.set)
        sb_a.pack(side='right', fill='y')

        ttk.Label(f_contenido, text="Detalle completo:",
                  background='#0A0F1E', foreground='white',
                  font=self._fuente_sub).pack(anchor='w', pady=(5, 2))

        self.texto_detalle_alerta = tk.Text(f_contenido, height=6, wrap='word',
                                            font=("Consolas", 10),
                                            bg='#1a1a1a', fg='#e0e0e0',
                                            relief='flat', bd=2)
        self.texto_detalle_alerta.pack(fill='both', expand=True)

        # --- Frame de resolución de conflictos (oculto por defecto) ---
        self._frame_resolucion = ttk.LabelFrame(f_contenido, text="Resolución de Conflicto", style='blue.TFrame')
        self._frame_resolucion.pack(fill='x', pady=(5, 0))

        self._resolucion_inner = ttk.Frame(self._frame_resolucion, style='blue.TFrame')
        self._resolucion_inner.pack(fill='x', padx=6, pady=4)

        self._resolucion_label = ttk.Label(self._resolucion_inner, text="Selecciona qué asignación conservar en este horario:",
                                           background='#0A0F1E', foreground='#FFD700', font=self._fuente_label)
        self._resolucion_label.pack(anchor='w')

        self._radio_var = tk.StringVar(value="")
        self._radio_frame = ttk.Frame(self._resolucion_inner, style='blue.TFrame')
        self._radio_frame.pack(fill='x', pady=4)

        self._btn_resolver = ttk.Button(self._resolucion_inner, text="Asignar Seleccionada y Buscar Alternativas",
                                        command=self._resolver_conflicto, state='disabled')
        self._btn_resolver.pack(pady=4)

        self._frame_resolucion_alternativas = ttk.Frame(self._resolucion_inner, style='blue.TFrame')
        self._frame_resolucion_alternativas.pack(fill='x', pady=4)

        self._ocultar_frame_resolucion()

        ttk.Button(f_superior, text="Limpiar Alertas",
                   command=self._limpiar_alertas).pack(pady=5)

    def _ocultar_frame_resolucion(self):
        self._frame_resolucion.pack_forget()

    def _mostrar_frame_resolucion(self):
        self._frame_resolucion.pack(fill='x', pady=(5, 0))

    def _limpiar_resolucion(self):
        for w in self._radio_frame.winfo_children():
            w.destroy()
        for w in self._frame_resolucion_alternativas.winfo_children():
            w.destroy()
        self._radio_var.set("")
        self._btn_resolver.config(state='disabled')

    def _mostrar_alertas_en_tabla(self):
        if not hasattr(self, 'tabla_alertas'):
            return
        for item in self.tabla_alertas.get_children():
            self.tabla_alertas.delete(item)
        self.texto_detalle_alerta.delete('1.0', tk.END)
        self._ocultar_frame_resolucion()
        for a in self._ultimas_alertas:
            if a.get('tipo') == 'conflicto':
                conflictos = a.get('conflictos', [])
                materia_text = conflictos[0]['materia'] if conflictos else '?'
                if len(conflictos) > 1:
                    materia_text += f" (+{len(conflictos)-1} más)"
                grupo_text = conflictos[0]['grupo'] if conflictos else '?'
                if len(conflictos) > 1:
                    grupo_text += f" (+{len(conflictos)-1})"
                causa = f"CONFLICTO: {len(conflictos)} materias chocan en horario"
                self.tabla_alertas.insert('', 'end', values=(
                    materia_text,
                    grupo_text,
                    a.get('profesor', '?'),
                    causa
                ))
            else:
                causa = a['causas'][0] if a.get('causas') else 'Sin causa identificada'
                self.tabla_alertas.insert('', 'end', values=(
                    a.get('materia', '?'),
                    a.get('grupo', '?'),
                    a.get('profesor', '?'),
                    causa
                ))

    def _mostrar_detalle_alerta(self, event=None):
        sel = self.tabla_alertas.selection()
        if not sel:
            return
        idx = self.tabla_alertas.index(sel[0])
        if idx >= len(self._ultimas_alertas):
            return
        a = self._ultimas_alertas[idx]
        self.texto_detalle_alerta.delete('1.0', tk.END)
        self._ocultar_frame_resolucion()

        if a.get('tipo') == 'conflicto':
            self._mostrar_detalle_conflicto(a)
        else:
            self._mostrar_detalle_normal(a)

    def _mostrar_detalle_normal(self, a):
        texto = f"MATERIA: {a.get('materia', '?')}  |  GRUPO: {a.get('grupo', '?')}\n"
        texto += f"PROFESOR: {a.get('profesor', '?')}  |  ID: {a.get('profesor_id', '?')}\n"
        texto += "-"*70 + "\n"
        texto += "CAUSAS:\n"
        for i, c in enumerate(a.get('causas', []), 1):
            texto += f"  {i}. {c}\n"
        texto += "\nSUGERENCIAS:\n"
        for i, s in enumerate(a.get('sugerencias', []), 1):
            texto += f"  {i}. {s}\n"
        alternativas = a.get('alternativas', [])
        if alternativas:
            texto += "\nHORARIOS ALTERNATIVOS SUGERIDOS:\n"
            for i, alt in enumerate(alternativas[:5], 1):
                texto += f"  {i}. {alt['dia']} {alt['hora_inicio']}-{alt['hora_fin']} (Salón: {alt['salon']})\n"
        extras = a.get('detalles_extra', [])
        if extras:
            texto += "\nDETALLES TÉCNICOS:\n"
            for e in extras:
                texto += f"  {e}\n"
        self.texto_detalle_alerta.insert('1.0', texto)
        self.texto_detalle_alerta.see('1.0')

    def _mostrar_detalle_conflicto(self, a):
        conflictos = a.get('conflictos', [])
        alternativas = a.get('alternativas', {})

        texto = f"⚠ CONFLICTO DE HORARIO ⚠\n"
        texto += f"PROFESOR: {a.get('profesor', '?')}  |  ID: {a.get('profesor_id', '?')}\n"
        texto += "="*70 + "\n"
        texto += f"CAUSA: {a['causas'][0] if a.get('causas') else 'Conflicto detectado'}\n"
        texto += "\nASIGNACIONES EN CONFLICTO:\n"
        for i, c in enumerate(conflictos, 1):
            texto += f"  {i}. {c['materia']} - Grupo: {c['grupo']}  ({c['hora_inicio']}-{c['hora_fin']})  [{c['dias']}]\n"
        if alternativas:
            texto += "\n" + "~"*70 + "\n"
            texto += "HORARIOS ALTERNATIVOS SUGERIDOS:\n"
            for asig_id, alts in alternativas.items():
                c_info = next((cc for cc in conflictos if cc['asignacion_id'] == asig_id), None)
                mat_name = c_info['materia'] if c_info else f"ID {asig_id}"
                texto += f"\n  Para {mat_name}:\n"
                for alt in alts[:3]:
                    texto += f"    → {alt['dia']} {alt['hora_inicio']}-{alt['hora_fin']}\n"
        texto += "\n" + "="*70 + "\n"
        texto += "Usa los controles de abajo para resolver el conflicto."

        self.texto_detalle_alerta.insert('1.0', texto)
        self.texto_detalle_alerta.see('1.0')

        # Build resolution radio buttons
        self._limpiar_resolucion()
        if len(conflictos) > 1:
            for i, c in enumerate(conflictos):
                label = f"{c['materia']} - {c['grupo']}  ({c['hora_inicio']}-{c['hora_fin']}) [{c['dias']}]"
                rb = ttk.Radiobutton(self._radio_frame, text=label, variable=self._radio_var,
                                     value=str(c['asignacion_id']),
                                     command=lambda: self._btn_resolver.config(state='normal'))
                rb.pack(anchor='w', padx=10, pady=2)
            self._radio_var.set(str(conflictos[0]['asignacion_id']))
            self._btn_resolver.config(state='normal')
            self._mostrar_frame_resolucion()

            # Show alternatives for non-selected (when user picks)
            self._mostrar_alternativas_en_frame(conflictos, alternativas)

    def _mostrar_alternativas_en_frame(self, conflictos, alternativas):
        for w in self._frame_resolucion_alternativas.winfo_children():
            w.destroy()

        if not alternativas:
            ttk.Label(self._frame_resolucion_alternativas,
                      text="No se encontraron horarios alternativos automáticos.",
                      background='#0A0F1E', foreground='#FF6B6B',
                      font=self._fuente_label).pack(anchor='w', padx=10)
            return

        ttk.Label(self._frame_resolucion_alternativas,
                  text="Alternativas disponibles (se aplicarán al resolver):",
                  background='#0A0F1E', foreground='#98FB98',
                  font=self._fuente_label).pack(anchor='w', padx=10, pady=(4, 2))

        for asig_id, alts in alternativas.items():
            c_info = next((cc for cc in conflictos if cc['asignacion_id'] == asig_id), None)
            if not c_info:
                continue
            mat_name = c_info['materia']
            f_alt = ttk.Frame(self._frame_resolucion_alternativas, style='blue.TFrame')
            f_alt.pack(fill='x', padx=15, pady=2)
            alt_text = f"{mat_name} ({c_info['grupo']}): "
            alt_opts = []
            for alt in alts[:3]:
                alt_opts.append(f"{alt['dia']} {alt['hora_inicio']}-{alt['hora_fin']}")
            alt_text += " | ".join(alt_opts) if alt_opts else "Sin alternativas"
            ttk.Label(f_alt, text=alt_text, background='#0A0F1E',
                      foreground='#e0e0e0', font=self._fuente_label).pack(anchor='w')

    def _resolver_conflicto(self):
        selected_id = self._radio_var.get()
        if not selected_id:
            return

        alerta = None
        for a in self._ultimas_alertas:
            if a.get('tipo') == 'conflicto':
                if any(str(c['asignacion_id']) == selected_id for c in a.get('conflictos', [])):
                    alerta = a
                    break

        if not alerta:
            messagebox.showerror("Error", "No se encontró el conflicto seleccionado.")
            return

        conflictos = alerta.get('conflictos', [])
        alternativas = alerta.get('alternativas', {})

        with obtener_cursor() as ctx:
            if ctx is None:
                return
            cur, conn = ctx
            try:
                selected_data = next(c for c in conflictos if str(c['asignacion_id']) == selected_id)

                # obtener_cursor() returns tuples, not dicts
                cur.execute(
                    "SELECT hora_inicio, hora_fin, dias, modalidad, profesor_id, materia_id FROM asignaciones WHERE asignacion_id = %s",
                    (selected_id,)
                )
                row = cur.fetchone()
                if not row:
                    messagebox.showerror("Error", "No se encontró la asignación en BD.")
                    return
                # row: (hora_inicio, hora_fin, dias, modalidad, profesor_id, materia_id)
                hora_inicio = row[0]
                hora_fin = row[1]
                dias_bd = row[2]
                modalidad = row[3]
                profesor_id = row[4]
                materia_id = row[5]

                cur.execute(
                    "SELECT tipo FROM materias WHERE materia_id = %s",
                    (materia_id,)
                )
                tipo_row = cur.fetchone()
                tipo_materia = (tipo_row[0] or 'Normal').lower() if tipo_row else 'normal'

                es_mediacion = str(modalidad or 'Presencial') == 'Mediacion Tecnologica'

                if es_mediacion:
                    cur.execute("SELECT salon_id FROM salones WHERE salon_id LIKE 'MEDIACION_TECNOLOGICA%' LIMIT 1")
                elif tipo_materia == 'auditorio':
                    cur.execute("SELECT salon_id FROM salones WHERE tipo = 'Auditorio' LIMIT 1")
                elif tipo_materia == 'laboratorio':
                    cur.execute("SELECT salon_id FROM salones WHERE tipo = 'Laboratorio' OR tipo = 'Normal' LIMIT 1")
                elif tipo_materia in ('tecnologica', 'tecnológica', 'laboratorio de computacion', 'laboratorio de computación'):
                    cur.execute("SELECT salon_id FROM salones WHERE tipo IN ('Tecnologica', 'TECNOLOGICA', 'TECNOLÓGICA', 'Laboratorio de Computacion', 'Laboratorio de computación') LIMIT 1")
                elif tipo_materia == 'normal':
                    cur.execute("SELECT salon_id FROM salones WHERE tipo = 'Normal' LIMIT 1")
                else:
                    cur.execute("SELECT salon_id FROM salones WHERE salon_id NOT LIKE 'MEDIACION_TECNOLOGICA%' LIMIT 1")

                salon_row = cur.fetchone()
                if not salon_row:
                    messagebox.showerror("Error", "No hay salones compatibles disponibles.")
                    return
                salon_id = salon_row[0]

                def _formatear_hora_valor(h):
                    if isinstance(h, datetime.timedelta):
                        total_seconds = int(h.total_seconds())
                        hh = total_seconds // 3600
                        mm = (total_seconds % 3600) // 60
                        return f"{hh:02d}:{mm:02d}:00"
                    elif isinstance(h, datetime.time):
                        return f"{h.hour:02d}:{h.minute:02d}:00"
                    return str(h)[:5] + ':00'

                dias_list = [d.strip() for d in dias_bd.split(',')] if dias_bd else ['Lunes']
                hora_i = _formatear_hora_valor(hora_inicio)
                hora_f = _formatear_hora_valor(hora_fin)

                for dia in dias_list:
                    cur.execute(
                        "INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin) VALUES (%s, %s, %s, %s, %s)",
                        (selected_id, salon_id, dia, hora_i, hora_f)
                    )

                cur.execute("UPDATE asignaciones SET estado = 'asignado' WHERE asignacion_id = %s", (selected_id,))

                for c in conflictos:
                    if str(c['asignacion_id']) != selected_id:
                        alt_list = alternativas.get(c['asignacion_id'], [])
                        if alt_list:
                            alt = alt_list[0]
                            new_dias = alt['dia']
                            new_hi = alt['hora_inicio'] + ':00'
                            new_hf = alt['hora_fin'] + ':00'

                            cur.execute(
                                "UPDATE asignaciones SET hora_inicio = %s, hora_fin = %s, dias = %s, estado = 'pendiente' WHERE asignacion_id = %s",
                                (new_hi, new_hf, new_dias, c['asignacion_id'])
                            )

                            cur.execute(
                                "SELECT profesor_id FROM asignaciones WHERE asignacion_id = %s",
                                (c['asignacion_id'],)
                            )
                            prof_row = cur.fetchone()
                            if prof_row:
                                mapa_dias_inv = {"Lunes": "0", "Martes": "1", "Miércoles": "2", "Jueves": "3", "Viernes": "4", "Sábado": "5"}
                                dia_num = mapa_dias_inv.get(alt['dia'], "0")
                                cur.execute(
                                    "DELETE FROM profesor_disponibilidad WHERE profesor_id = %s AND hora_inicio = %s AND hora_fin = %s",
                                    (prof_row[0], new_hi, new_hf)
                                )
                                cur.execute(
                                    "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin, modalidad) VALUES (%s, %s, %s, %s, 'Presencial')",
                                    (prof_row[0], dia_num, new_hi, new_hf)
                                )

                conn.commit()

                messagebox.showinfo(
                    "Conflicto Resuelto",
                    f"✓ ASIGNADA: {selected_data['materia']} ({selected_data['grupo']})\n"
                    f"  Horario: {selected_data['hora_inicio']}-{selected_data['hora_fin']} [{selected_data['dias']}]\n"
                    f"  Salón: {salon_id}\n\n"
                    f"Las demás asignaciones recibieron horarios alternativos sugeridos.\n"
                    f"Revisa la Vista Previa para ver los cambios."
                )

                self._limpiar_resolucion()
                self._ocultar_frame_resolucion()

                self._ultimas_alertas = [a for a in self._ultimas_alertas if a is not alerta]
                self._mostrar_alertas_en_tabla()

                self.actualizar_vista_previa()
                self._cargar_previa_horario_grupo()

            except Exception as e:
                conn.rollback()
                messagebox.showerror("Error", f"Error al resolver conflicto: {e}")

    def _limpiar_alertas(self):
        self._ultimas_alertas = []
        if hasattr(self, 'tabla_alertas'):
            for item in self.tabla_alertas.get_children():
                self.tabla_alertas.delete(item)
        if hasattr(self, 'texto_detalle_alerta'):
            self.texto_detalle_alerta.delete('1.0', tk.END)

    def _cambiar_filtro_periodo(self, event=None):
        periodo = self.combo_periodos.get()
        if not periodo: return
        self._periodo_seleccionado = periodo
        semestres_validos = [2, 4, 6, 8, 10] if periodo == "A" else [1, 3, 5, 7, 9]
        self._semestres_filtrados = semestres_validos
        lista_sem = [v for k, v in self.semestres_map.items() if int(k) in semestres_validos]
        if lista_sem:
            self.combo_filtro_semestre['values'] = lista_sem
            if self.combo_filtro_semestre.get() not in lista_sem:
                self.combo_filtro_semestre.set(lista_sem[0])
        if hasattr(self, 'combo_filtro_semestre_vp'):
            self.combo_filtro_semestre_vp['values'] = ["Todos"] + lista_sem
        self._cambiar_filtro_semestre()
        self.actualizar_vista_previa()

    def _materias_para_semestre(self, id_sem):
        if isinstance(id_sem, str) and '-' in id_sem:
            id_sem = int(id_sem.split(' - ')[0])
        return [m for m in self.lista_maestra_materias if m["semestre"] == int(id_sem)]

    def _obtener_semestre_de_materia(self, materia_id):
        if materia_id and '-' in str(materia_id):
            materia_id = str(materia_id).split(' - ')[0]
        return self.materias_map.get(str(materia_id))

    def obtener_o_crear_grupo(self, grupo_texto, nivel=None):
        grupo_texto = grupo_texto.strip().upper()
        if not grupo_texto:
            messagebox.showerror("Error", "Campo Grupo vacío")
            return None
        grupo_id = self._obtener_id_valido(grupo_texto, es_grupo=True)
        with obtener_cursor() as ctx:
            if ctx is None:
                return None
            cur, conn = ctx
            try:
                cur.execute("SELECT grupo_id FROM grupos WHERE grupo_id = %s", (grupo_id,))
                if cur.fetchone():
                    if nivel is not None:
                        cur.execute("UPDATE grupos SET nivel = %s WHERE grupo_id = %s", (nivel, grupo_id))
                        conn.commit()
                        self.grupos_por_semestre = self._cargar_grupos_desde_bd()
                        self._actualizar_materias_en_periodos()
                    return grupo_id
                if nivel is None:
                    nivel = 0
                cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, %s)", (grupo_id, nivel))
                self.grupos_por_semestre = self._cargar_grupos_desde_bd()
                self._actualizar_materias_en_periodos()
                self.cargar_combos_bd() 
                messagebox.showinfo("Éxito", f"Grupo '{grupo_id}' creado.")
                return grupo_id
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error gestionando grupo: {err}")
                return None

    def _asignar_periodo(self, profesor_id, materia_id, grupo_id, periodo, hora_i, hora_f, modalidad="Presencial", dias_str=""):
        if not profesor_id or not materia_id or not grupo_id:
            messagebox.showerror("Error", "Complete todos los campos del periodo")
            return False
        nivel = self.materias_map.get(materia_id)
        grupo_id = self.obtener_o_crear_grupo(grupo_id, nivel=nivel)
        if not grupo_id:
            return False

        exito = False
        with obtener_cursor() as ctx:
            if ctx is None:
                return False
            cur, conn = ctx
            try:
                # Check same materia+grupo for this professor (update path)
                cur.execute(
                    "SELECT asignacion_id FROM asignaciones WHERE profesor_id=%s AND materia_id=%s AND grupo_id=%s AND modalidad=%s",
                    (profesor_id, materia_id, grupo_id, modalidad)
                )
                existente = cur.fetchone()
                if existente:
                    if messagebox.askyesno("Asignación existente",
                        "Esta asignación ya existe. ¿Desea modificar sus datos (periodo/horario)?"):
                        cur.execute(
                            "DELETE FROM horarios WHERE asignacion_id=%s",
                            (existente[0],)
                        )
                        cur.execute(
                            "UPDATE asignaciones SET periodo=%s, hora_inicio=%s, hora_fin=%s, dias=%s, estado='pendiente' WHERE asignacion_id=%s",
                            (periodo, hora_i, hora_f, dias_str, existente[0])
                        )
                        conn.commit()
                        messagebox.showinfo("Actualizado", "Asignación actualizada correctamente")
                        exito = True
                    else:
                        conn.rollback()
                        return False
                else:
                    # Check same materia+grupo across different professors
                    cur.execute(
                        "SELECT a.asignacion_id, p.nombre, p.profesor_id FROM asignaciones a JOIN profesores p ON a.profesor_id=p.profesor_id WHERE a.materia_id=%s AND a.grupo_id=%s AND a.periodo=%s AND a.modalidad=%s AND a.profesor_id!=%s AND a.estado!='cancelada' LIMIT 1",
                        (materia_id, grupo_id, periodo, modalidad, profesor_id)
                    )
                    otro = cur.fetchone()
                    if otro:
                        old_asig_id, old_nombre, old_prof_id = otro
                        if messagebox.askyesno("Conflicto",
                            f"'{old_nombre}' ya tiene asignada esta materia y grupo en el periodo {periodo} ({modalidad}).\n¿Desea sustituirlo por el profesor actual?"):
                            cur.execute(
                                "DELETE FROM horarios WHERE asignacion_id=%s",
                                (old_asig_id,)
                            )
                            cur.execute(
                                "UPDATE asignaciones SET profesor_id=%s, hora_inicio=%s, hora_fin=%s, dias=%s, estado='pendiente' WHERE asignacion_id=%s",
                                (profesor_id, hora_i, hora_f, dias_str, old_asig_id)
                            )
                            conn.commit()
                            messagebox.showinfo("Sustituido", "Asignación transferida al nuevo profesor")
                            exito = True
                        else:
                            conn.rollback()
                            return False
                    else:
                        cur.execute(
                            "INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, estado, periodo, hora_inicio, hora_fin, dias, modalidad) VALUES (%s, %s, %s, 'pendiente', %s, %s, %s, %s, %s)",
                            (profesor_id, materia_id, grupo_id, periodo, hora_i, hora_f, dias_str, modalidad)
                        )
                        conn.commit()
                        messagebox.showinfo("Éxito", f"Asignación guardada para el periodo {periodo}")
                        exito = True
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error al asignar: {err}")
                return False

        if exito:
            self.actualizar_vista_previa()
            return True
        return False

    def actualizar_vista_previa(self, event=None, mostrar_todo=False):
        if self._after_busqueda_asignaciones_id is not None:
            self.ventana.after_cancel(self._after_busqueda_asignaciones_id)
            self._after_busqueda_asignaciones_id = None

        if mostrar_todo:
            estado_filtro = "Todos"
            texto_busqueda = ""
            if hasattr(self, 'sv_busqueda_asignaciones'):
                self.sv_busqueda_asignaciones.set("")
        else:
            estado_filtro = self.combo_estado_filtro.get() if hasattr(self, 'combo_estado_filtro') else "Todos"
            texto_busqueda = self.sv_busqueda_asignaciones.get().strip() if hasattr(self, 'sv_busqueda_asignaciones') else ""

        tabla = self.tabla_asignaciones if hasattr(self, 'tabla_asignaciones') else None
        if tabla:
            children = tabla.get_children()
            if children:
                tabla.delete(*children)

        with obtener_cursor() as ctx:
            if ctx is None:
                return
            cur, conn = ctx
            try:
                sql = """
                    SELECT 
                        a.asignacion_id,
                        a.profesor_id,
                        CASE 
                            WHEN a.profesor_id IS NULL OR a.profesor_id = 'SIN_ASIGNAR' THEN 'Sin profesor asignado'
                            ELSE IFNULL(p.nombre, 'Sin profesor asignado')
                        END AS profesor_nombre,
                        a.materia_id, IFNULL(m.nombre, 'Materia Desconocida'),
                        a.grupo_id, IFNULL(g.grupo_id, 'Sin Grupo'),
                        IFNULL(a.estado, 'pendiente') AS estado
                    FROM asignaciones a
                    LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                    LEFT JOIN materias m ON a.materia_id = m.materia_id
                    LEFT JOIN grupos g ON a.grupo_id = g.grupo_id 
                    WHERE 1=1 
                """
                params = []

                if estado_filtro != "Todos":
                    if estado_filtro == "pendiente":
                        sql += " AND (a.estado = 'pendiente' OR a.estado = 'no asignado' OR a.profesor_id = 'SIN_ASIGNAR' OR a.profesor_id IS NULL)"
                    elif estado_filtro == "asignado":
                        sql += " AND a.estado = 'asignado' AND a.profesor_id != 'SIN_ASIGNAR' AND a.profesor_id IS NOT NULL"
                    else:
                        sql += " AND a.estado = %s"
                        params.append(estado_filtro)

                if texto_busqueda:
                    sql += " AND (p.nombre LIKE %s OR m.nombre LIKE %s OR a.profesor_id LIKE %s OR a.materia_id LIKE %s)"
                    like = f"%{texto_busqueda}%"
                    params.extend([like, like, like, like])

                if hasattr(self, '_sv_filtro_semestre_vp'):
                    sem_sel = self._sv_filtro_semestre_vp.get()
                    if sem_sel and sem_sel != "Todos" and ' - ' in sem_sel:
                        try:
                            sid = sem_sel.split(' - ')[0].strip()
                            sql += " AND m.semestre_id = %s"
                            params.append(sid)
                        except (ValueError, IndexError):
                            pass

                if hasattr(self, '_sv_filtro_grupo_vp'):
                    grp_sel = self._sv_filtro_grupo_vp.get()
                    if grp_sel and grp_sel != "Todos":
                        sql += " AND a.grupo_id = %s"
                        params.append(grp_sel)

                sql += " ORDER BY a.asignacion_id"
                cur.execute(sql, params)
                resultados = cur.fetchall()

                if resultados and tabla:
                    for row in resultados:
                        asig_id = row[0]
                        prof_id_val = row[1]
                        prof_nom_val = row[2]
                        if not prof_id_val or prof_id_val == 'SIN_ASIGNAR':
                            p_str = "Sin profesor asignado"
                        else:
                            p_str = f"{prof_id_val} - {prof_nom_val}"
                        m_str = f"{row[3]} - {row[4]} ({row[5]})"
                        estado_str = str(row[7]).upper()
                        tabla.insert('', 'end', iid=str(asig_id), values=(p_str, m_str, estado_str))
                elif tabla:
                    tabla.insert('', 'end', iid="no_results", values=("(No hay resultados)", "", ""))

            except sqlite3.Error as err:
                if tabla:
                    tabla.insert('', 'end', iid="error_bd", values=(f"Error BD: {err}", "", ""))

    # --- VISUALIZACIÓN GRÁFICA ---
    def Construccion_Ver_Horarios(self, contenedor):
        self.s_idx = 0 
        self.frame_grafico_display = ttk.Frame(contenedor)
        self.frame_grafico_display.pack(fill='both', expand=True)

        self.fig = Figure(dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.fig.patch.set_facecolor('#0A0F1E') 
        
        self.canvas_horario = FigureCanvasTkAgg(self.fig, master=self.frame_grafico_display)
        widget_canvas = self.canvas_horario.get_tk_widget()
        widget_canvas.pack(fill='both', expand=True)

        frame_controles = ttk.Frame(contenedor, style='blue.TFrame')
        frame_controles.pack(fill='x', side='bottom', pady=5)

        ttk.Button(frame_controles, text="◀ Ant.", command=self.anterior_salon, width=6).pack(side='left', padx=2)
        ttk.Button(frame_controles, text="Sig. ▶", command=self.siguiente_salon, width=6).pack(side='left', padx=2)
        
        ttk.Label(frame_controles, text="Ver por:", background='#0A0F1E', foreground='white', font=self._fuente_btn).pack(side='left', padx=(10, 2))
        self.combo_vista_horarios = ttk.Combobox(frame_controles, values=["Salón", "Profesor", "Grupo"], state="readonly", width=8, font=self._fuente_label)
        self.combo_vista_horarios.set("Salón")
        self.combo_vista_horarios.pack(side='left')
        self.combo_vista_horarios.bind("<<ComboboxSelected>>", self.cambiar_modo_vista)

        self.lbl_sem_filtro = ttk.Label(frame_controles, text="Semestre:", background='#0A0F1E', foreground='white', font=self._fuente_btn)
        self.lbl_sem_filtro.pack(side='left', padx=(10, 2))
        
        self.combo_semestre_filtro = ttk.Combobox(frame_controles, values=["Todos", "1", "2", "3", "4", "5", "6", "7", "8", "9"], state="readonly", width=6, font=self._fuente_label)
        self.combo_semestre_filtro.set("Todos")
        self.combo_semestre_filtro.pack(side='left')
        self.combo_semestre_filtro.bind("<<ComboboxSelected>>", self.actualizar_combo_ir_a)

        ttk.Label(frame_controles, text="Seleccionar:", background='#0A0F1E', foreground='white', font=self._fuente_btn).pack(side='left', padx=(10, 2))
        self.combo_ir_a = ttk.Combobox(frame_controles, state="readonly", width=15, font=self._fuente_label)
        self.combo_ir_a.pack(side='left')
        self.combo_ir_a.bind("<<ComboboxSelected>>", self.saltar_a_entidad)

        ttk.Button(frame_controles, text="📊 Sábana General", command=self._abrir_dialogo_sabana_horarios).pack(side='right', padx=4)
        ttk.Button(frame_controles, text="PDF", command=self.exportar_pdf_completo, width=6).pack(side='right', padx=2)
        ttk.Button(frame_controles, text="PNG", command=self.guardar_captura, width=6).pack(side='right', padx=2)
        ttk.Button(frame_controles, text="Excel", command=self.exportar_excel, width=6).pack(side='right', padx=2)

        self.ax.text(0.5, 0.5, "Cargando horarios...", ha='center', va='center',
                    transform=self.ax.transAxes, fontsize=14, color='gray')
        self.canvas_horario.draw()

    def cambiar_modo_vista(self, event=None):
        modo = self.combo_vista_horarios.get()
        if not self._tensor_cargado:
            self.ax.clear(); self.ax.axis('off')
            self.ax.text(0.5, 0.5, "Cargando horarios...", ha='center', va='center',
                        transform=self.ax.transAxes, fontsize=14, color='gray')
            self.fig.tight_layout(pad=0)
            self.canvas_horario.draw()
            return
        try:
            mem_grafico.inicializar_y_llenar_tensor(modo)
        except Exception as e:
            print(f"Error cargando tensor: {e}")
        self.s_idx = 0
        
        if modo == "Grupo":
            self.combo_semestre_filtro.config(state="readonly")
        else:
            self.combo_semestre_filtro.set("Todos")
            self.combo_semestre_filtro.config(state="disabled")
            
        self.actualizar_combo_ir_a()

    def actualizar_combo_ir_a(self, event=None):
        modo = self.combo_vista_horarios.get()
        semestre = self.combo_semestre_filtro.get()
        
        self.entidades_filtradas = []
        if hasattr(mem_grafico, 'entidades_actuales') and mem_grafico.entidades_actuales:
            for e in mem_grafico.entidades_actuales:
                nombre = e[0]
                if modo == "Grupo" and semestre != "Todos":
                    if nombre in self.grupos_por_semestre.get(semestre, []):
                        self.entidades_filtradas.append(e)
                else:
                    self.entidades_filtradas.append(e)
                    
        nombres = [e[0] for e in self.entidades_filtradas]
        self.combo_ir_a['values'] = nombres
        
        if self.entidades_filtradas:
            if not any(e[1] == self.s_idx for e in self.entidades_filtradas):
                self.s_idx = self.entidades_filtradas[0][1]
                
            current_name = next(e[0] for e in self.entidades_filtradas if e[1] == self.s_idx)
            self.combo_ir_a.set(current_name)
        else:
            self.combo_ir_a.set("")
            
        self.actualizar_tabla_grafica()

    def saltar_a_entidad(self, event=None):
        nombre_seleccionado = self.combo_ir_a.get()
        if not nombre_seleccionado: return
        
        for e in self.entidades_filtradas:
            if e[0] == nombre_seleccionado:
                self.s_idx = e[1]
                self.actualizar_tabla_grafica()
                break

    def siguiente_salon(self):
        if not hasattr(self, 'entidades_filtradas') or not self.entidades_filtradas: return
        idx_in_filtered = next((i for i, e in enumerate(self.entidades_filtradas) if e[1] == self.s_idx), -1)
        if idx_in_filtered != -1:
            next_idx = (idx_in_filtered + 1) % len(self.entidades_filtradas)
            self.s_idx = self.entidades_filtradas[next_idx][1]
            self.combo_ir_a.set(self.entidades_filtradas[next_idx][0])
            self.actualizar_tabla_grafica()

    def anterior_salon(self):
        if not hasattr(self, 'entidades_filtradas') or not self.entidades_filtradas: return
        idx_in_filtered = next((i for i, e in enumerate(self.entidades_filtradas) if e[1] == self.s_idx), -1)
        if idx_in_filtered != -1:
            next_idx = (idx_in_filtered - 1) % len(self.entidades_filtradas)
            self.s_idx = self.entidades_filtradas[next_idx][1]
            self.combo_ir_a.set(self.entidades_filtradas[next_idx][0])
            self.actualizar_tabla_grafica()

    def exportar_pdf_completo(self):
        modo = self.combo_vista_horarios.get()
        ruta_descargas = os.path.join(os.path.expanduser('~'), 'Downloads')
        nombre_archivo = f"Horarios_Plasem_{modo}_{datetime.datetime.now().strftime('%H%M%S')}.pdf"
        ruta_completa = os.path.join(ruta_descargas, nombre_archivo)
        
        if not hasattr(self, 'entidades_filtradas') or not self.entidades_filtradas:
            messagebox.showwarning("Aviso", "No hay datos para exportar con los filtros actuales.")
            return

        respuesta = messagebox.askyesno("Confirmar", f"¿Deseas generar un PDF de los horarios mostrados actualmente?\nSe guardará en tu carpeta de Descargas en formato Blanco y Negro.")
        if not respuesta: return

        try:
            indice_respaldo = self.s_idx
            with PdfPages(ruta_completa) as pdf: 
                for s in self.entidades_filtradas:
                    self.s_idx = s[1]
                    self.actualizar_tabla_grafica(modo_impresion=True)
                    pdf.savefig(self.fig, bbox_inches='tight')
                    
            self.s_idx = indice_respaldo
            self.actualizar_tabla_grafica(modo_impresion=False)
            messagebox.showinfo("Éxito", f"Reporte PDF guardado exitosamente en:\n{ruta_completa}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el PDF:\n{e}")
            self.actualizar_tabla_grafica(modo_impresion=False)

    def guardar_captura(self):
        if not hasattr(mem_grafico, 'entidades_actuales') or not mem_grafico.entidades_actuales:
            messagebox.showwarning("Aviso", "No hay un horario generado para capturar.")
            return

        try:
            nombre_real = next(e[0] for e in mem_grafico.entidades_actuales if e[1] == self.s_idx)
            modo = mem_grafico.modo_actual
            nombre_seguro = "".join([c if c.isalnum() else "_" for c in nombre_real])
            ruta_descargas = os.path.join(os.path.expanduser('~'), 'Downloads')
            nombre_archivo = f"Horario_{modo}_{nombre_seguro}_{datetime.datetime.now().strftime('%H%M%S')}.png"
            ruta_completa = os.path.join(ruta_descargas, nombre_archivo)
            
            self.actualizar_tabla_grafica(modo_impresion=True)
            self.fig.savefig(ruta_completa, bbox_inches='tight', dpi=200) 
            self.actualizar_tabla_grafica(modo_impresion=False)
            
            messagebox.showinfo("Captura Guardada", f"Se ha guardado la imagen exitosamente en:\n{ruta_completa}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar la captura:\n{e}")
            self.actualizar_tabla_grafica(modo_impresion=False)

    # --- NUEVA FUNCIÓN EXCEL ---
    def exportar_excel(self):
        try:
            import pandas as pd
        except ImportError:
            messagebox.showerror("Error de dependencias", "Para exportar a Excel necesitas instalar pandas y openpyxl.\n\nAbre tu terminal en VS Code y ejecuta:\npip install pandas openpyxl")
            return

        modo = self.combo_vista_horarios.get()
        ruta_descargas = os.path.join(os.path.expanduser('~'), 'Downloads')
        nombre_archivo = f"Horarios_Plasem_{modo}_{datetime.datetime.now().strftime('%H%M%S')}.xlsx"
        ruta_completa = os.path.join(ruta_descargas, nombre_archivo)
        
        if not hasattr(self, 'entidades_filtradas') or not self.entidades_filtradas:
            messagebox.showwarning("Aviso", "No hay datos para exportar con los filtros actuales.")
            return

        respuesta = messagebox.askyesno("Confirmar Excel", f"¿Deseas generar un archivo Excel de los horarios mostrados?\n\nCada horario ({modo}) será una pestaña (hoja) independiente en el archivo.")
        if not respuesta: return

        try:
            columnas = ['Hora', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
            
            # Motor para escribir múltiples hojas en un solo Excel
            with pd.ExcelWriter(ruta_completa, engine='openpyxl') as writer:
                for e in self.entidades_filtradas:
                    s_idx = e[1]
                    nombre_real = str(e[0])
                    
                    # Limpiar el nombre de la hoja para que Excel no marque error (máximo 31 caracteres y sin símbolos extraños)
                    nombre_hoja = "".join([c for c in nombre_real if c not in r'\/*?:[]'])[:31]
                    if not nombre_hoja: nombre_hoja = f"Hoja_{s_idx}"
                    
                    datos = []
                    for row_idx in range(1, mem_grafico.intervalos):
                        fila = []
                        for col_idx in range(7):
                            try:
                                val = mem_grafico.tensor_actual[s_idx, row_idx, col_idx]
                                # Reemplazamos los saltos de línea (\n) con un espacio para que se acomode bien en la celda
                                val_limpio = str(val).replace('\n', ' - ') if val else ''
                                fila.append(val_limpio)
                            except IndexError:
                                fila.append('')
                        datos.append(fila)
                        
                    df = pd.DataFrame(datos, columns=columnas)
                    df.to_excel(writer, sheet_name=nombre_hoja, index=False)
                    
                    # Auto-ajustar el ancho de las columnas en la hoja
                    worksheet = writer.sheets[nombre_hoja]
                    for col in worksheet.columns:
                        max_length = 0
                        col_letter = col[0].column_letter
                        for cell in col:
                            try: 
                                if len(str(cell.value)) > max_length:
                                    max_length = len(str(cell.value))
                            except:
                                pass
                        
                        # Limitar el ancho máximo a 40 para que no sea excesivo
                        adjusted_width = min((max_length + 2), 40)
                        worksheet.column_dimensions[col_letter].width = adjusted_width

            messagebox.showinfo("Éxito", f"Reporte Excel guardado exitosamente en:\n{ruta_completa}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el Excel:\n{e}")

    def _dia_a_indice_previa(self, dia):
        dia_normalizado = self._normalizar_dia(dia)
        if dia_normalizado.isdigit():
            indice = int(dia_normalizado)
            return indice if 0 <= indice < len(self.NOMBRES_DIAS) else None
        for indice, nombre in enumerate(self.NOMBRES_DIAS):
            if self._normalizar_dia(nombre) == dia_normalizado:
                return indice
        return None

    @staticmethod
    def _minutos_hora_previa(hora):
        if isinstance(hora, datetime.timedelta):
            segundos = int(hora.total_seconds())
            return (segundos // 3600) * 60 + (segundos % 3600) // 60
        if isinstance(hora, datetime.time):
            return hora.hour * 60 + hora.minute
        partes = str(hora).split(':')
        try:
            return int(partes[0]) * 60 + int(partes[1])
        except (ValueError, IndexError):
            return None

    def _detectar_choques_profesor(
        self, profesor_id, materia_id, grupo_id, modalidad, dias, hora_i, hora_f, excluir_asignacion_id=None
    ):
        inicio = self._minutos_hora_previa(hora_i)
        fin = self._minutos_hora_previa(hora_f)
        dias_propuestos = {
            indice for indice in (self._dia_a_indice_previa(dia) for dia in dias)
            if indice is not None
        }
        if inicio is None or fin is None or fin <= inicio or not dias_propuestos:
            return []

        choques = []
        with obtener_cursor_dict() as ctx:
            if ctx is None:
                raise RuntimeError("No hay conexión a la base de datos para validar el horario.")
            cur, conn = ctx
            if excluir_asignacion_id is not None:
                excluir_id = excluir_asignacion_id
            else:
                cur.execute(
                    """
                    SELECT asignacion_id
                    FROM asignaciones
                    WHERE profesor_id = %s
                      AND materia_id = %s
                      AND grupo_id = %s
                      AND modalidad = %s
                      AND (estado IS NULL OR estado != 'cancelada')
                    ORDER BY asignacion_id
                    LIMIT 1
                    """,
                    (profesor_id, materia_id, grupo_id, modalidad)
                )
                asignacion_existente = cur.fetchone()
                excluir_id = asignacion_existente['asignacion_id'] if asignacion_existente else None

            cur.execute(
                """
                SELECT a.asignacion_id, a.dias, a.hora_inicio AS asignacion_inicio,
                       a.hora_fin AS asignacion_fin, a.grupo_id,
                       m.nombre AS materia, h.dia AS horario_dia,
                       h.hora_inicio AS horario_inicio, h.hora_fin AS horario_fin
                FROM asignaciones a
                LEFT JOIN materias m ON m.materia_id = a.materia_id
                LEFT JOIN horarios h ON h.asignacion_id = a.asignacion_id
                WHERE a.profesor_id = %s
                  AND a.asignacion_id IS NOT ?
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
                """,
                (profesor_id, excluir_id)
            )
            for fila in cur.fetchall():
                if fila['horario_dia'] is not None:
                    horarios_existentes = [{
                        "dia": fila['horario_dia'],
                        "inicio": fila['horario_inicio'],
                        "fin": fila['horario_fin']
                    }]
                else:
                    horarios_existentes = [
                        {
                            "dia": dia.strip(),
                            "inicio": fila['asignacion_inicio'],
                            "fin": fila['asignacion_fin']
                        }
                        for dia in (fila.get('dias') or "").split(',')
                        if dia.strip()
                    ]

                for horario in horarios_existentes:
                    indice_dia = self._dia_a_indice_previa(horario['dia'])
                    inicio_existente = self._minutos_hora_previa(horario['inicio'])
                    fin_existente = self._minutos_hora_previa(horario['fin'])
                    if (
                        indice_dia in dias_propuestos
                        and inicio_existente is not None
                        and fin_existente is not None
                        and inicio < fin_existente
                        and fin > inicio_existente
                    ):
                        choques.append({
                            "dia": self.NOMBRES_DIAS[indice_dia],
                            "inicio": horario['inicio'],
                            "fin": horario['fin'],
                            "materia": fila.get('materia') or "Materia sin nombre",
                            "grupo": fila['grupo_id']
                        })
        return choques

    def _detectar_choques_grupo(self, grupo_id, materia_id, dias, hora_i, hora_f, excluir_asignacion_id=None):
        inicio = self._minutos_hora_previa(hora_i)
        fin = self._minutos_hora_previa(hora_f)
        dias_propuestos = {
            indice for indice in (self._dia_a_indice_previa(dia) for dia in dias)
            if indice is not None
        }
        if inicio is None or fin is None or fin <= inicio or not dias_propuestos:
            return []

        choques = []
        with obtener_cursor_dict() as ctx:
            if ctx is None:
                raise RuntimeError("No hay conexión a la base de datos para validar el horario.")
            cur, conn = ctx
            if excluir_asignacion_id is not None:
                cond_asig = "AND a.asignacion_id <> %s"
                param_asig = excluir_asignacion_id
            else:
                cond_asig = "AND a.materia_id <> %s"
                param_asig = materia_id
            cur.execute(
                f"""
                SELECT a.asignacion_id, a.dias, a.hora_inicio AS asignacion_inicio,
                       a.hora_fin AS asignacion_fin, m.nombre AS materia,
                       h.dia AS horario_dia, h.hora_inicio AS horario_inicio,
                       h.hora_fin AS horario_fin
                FROM asignaciones a
                LEFT JOIN materias m ON m.materia_id = a.materia_id
                LEFT JOIN horarios h ON h.asignacion_id = a.asignacion_id
                WHERE a.grupo_id = %s
                  {cond_asig}
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
                """,
                (grupo_id, param_asig)
            )
            for fila in cur.fetchall():
                if fila['horario_dia'] is not None:
                    horarios_existentes = [{
                        "dia": fila['horario_dia'],
                        "inicio": fila['horario_inicio'],
                        "fin": fila['horario_fin']
                    }]
                else:
                    horarios_existentes = [
                        {
                            "dia": dia.strip(),
                            "inicio": fila['asignacion_inicio'],
                            "fin": fila['asignacion_fin']
                        }
                        for dia in (fila.get('dias') or "").split(',')
                        if dia.strip()
                    ]

                for horario in horarios_existentes:
                    indice_dia = self._dia_a_indice_previa(horario['dia'])
                    inicio_existente = self._minutos_hora_previa(horario['inicio'])
                    fin_existente = self._minutos_hora_previa(horario['fin'])
                    if (
                        indice_dia in dias_propuestos
                        and inicio_existente is not None
                        and fin_existente is not None
                        and inicio < fin_existente
                        and fin > inicio_existente
                    ):
                        choques.append({
                            "dia": self.NOMBRES_DIAS[indice_dia],
                            "inicio": horario['inicio'],
                            "fin": horario['fin'],
                            "materia": fila.get('materia') or "Materia sin nombre"
                        })
        return choques

    def _seleccionar_grupo_previa(self, grupo_id):
        if hasattr(self, '_sv_filtro_semestre_vp'):
            self._sv_filtro_semestre_vp.set("Todos")
        if hasattr(self, 'combo_estado_filtro'):
            self.combo_estado_filtro.set("Todos")
        if hasattr(self, 'sv_busqueda_asignaciones'):
            self.sv_busqueda_asignaciones.set("")
        grupos = list(self.combo_filtro_grupo_vp['values'])
        if grupo_id not in grupos:
            grupos.append(grupo_id)
            self.combo_filtro_grupo_vp['values'] = grupos
        self._sv_filtro_grupo_vp.set(grupo_id)

    def _cargar_previa_horario_grupo(self):
        if not hasattr(self, 'canvas_previa_horario'):
            return
        grupo_id = self._sv_filtro_grupo_vp.get().strip()
        self._grupo_previa_datos = []
        self._grupo_previa_error = None
        if not grupo_id or grupo_id == "Todos":
            self._actualizar_previa_horario_grupo()
            return

        try:
            with obtener_cursor_dict() as ctx:
                if ctx is None:
                    raise RuntimeError("No hay conexión a la base de datos.")
                cur, conn = ctx
                cur.execute(
                    """
                    SELECT a.asignacion_id, a.dias, a.hora_inicio, a.hora_fin,
                           a.estado, m.nombre AS materia, p.nombre AS profesor,
                           h.dia AS horario_dia, h.hora_inicio AS horario_inicio,
                           h.hora_fin AS horario_fin, h.salon_id
                    FROM asignaciones a
                    LEFT JOIN materias m ON m.materia_id = a.materia_id
                    LEFT JOIN profesores p ON p.profesor_id = a.profesor_id
                    LEFT JOIN horarios h ON h.asignacion_id = a.asignacion_id
                    WHERE a.grupo_id = %s
                      AND (a.estado IS NULL OR a.estado != 'cancelada')
                    ORDER BY a.asignacion_id
                    """,
                    (grupo_id,)
                )
                filas = cur.fetchall()

            ids_con_horario = set()
            for fila in filas:
                if fila['horario_dia'] is None:
                    continue
                indice_dia = self._dia_a_indice_previa(fila['horario_dia'])
                inicio = self._minutos_hora_previa(fila['horario_inicio'])
                fin = self._minutos_hora_previa(fila['horario_fin'])
                if indice_dia is None or inicio is None or fin is None or fin <= inicio:
                    continue
                ids_con_horario.add(fila['asignacion_id'])
                self._grupo_previa_datos.append({
                    "dia": indice_dia,
                    "inicio": inicio,
                    "fin": fin,
                    "materia": fila.get('materia') or "Materia sin nombre",
                    "profesor": fila.get('profesor') or "Profesor sin nombre",
                    "salon": fila.get('salon_id') or "Sin salón",
                    "propuesta": False
                })

            for fila in filas:
                if fila['asignacion_id'] in ids_con_horario:
                    continue
                inicio = self._minutos_hora_previa(fila['hora_inicio'])
                fin = self._minutos_hora_previa(fila['hora_fin'])
                if inicio is None or fin is None or fin <= inicio:
                    continue
                dias = [dia.strip() for dia in (fila.get('dias') or "").split(',')]
                for dia in dias:
                    indice_dia = self._dia_a_indice_previa(dia)
                    if indice_dia is None:
                        continue
                    self._grupo_previa_datos.append({
                        "dia": indice_dia,
                        "inicio": inicio,
                        "fin": fin,
                        "materia": fila.get('materia') or "Materia sin nombre",
                        "profesor": fila.get('profesor') or "Profesor sin nombre",
                        "salon": "Pendiente",
                        "propuesta": True
                    })
        except (sqlite3.Error, RuntimeError, KeyError, TypeError, ValueError) as err:
            self._grupo_previa_error = str(err)
        self._actualizar_previa_horario_grupo()

    def _actualizar_previa_horario_grupo(self):
        for canvas in (
            getattr(self, 'canvas_previa_horario', None),
            getattr(self, '_canvas_previa_ampliada', None)
        ):
            if canvas is not None and canvas.winfo_exists():
                self._dibujar_previa_horario_grupo(canvas)

    def _abrir_previa_horario_ajustada(self):
        ventana_existente = getattr(self, '_ventana_previa_ampliada', None)
        if ventana_existente is not None and ventana_existente.winfo_exists():
            ventana_existente.deiconify()
            ventana_existente.lift()
            return

        ventana = tk.Toplevel(self.ventana)
        ventana.title("Horario del grupo - Vista ajustada")
        ancho = max(640, int(ventana.winfo_screenwidth() * 0.95))
        alto = max(480, int(ventana.winfo_screenheight() * 0.88))
        x = max(0, (ventana.winfo_screenwidth() - ancho) // 2)
        y = max(0, (ventana.winfo_screenheight() - alto) // 2)
        ventana.geometry(f"{ancho}x{alto}+{x}+{y}")
        ventana.minsize(640, 480)
        canvas = tk.Canvas(ventana, background='white', highlightthickness=0)
        canvas.pack(fill='both', expand=True, padx=8, pady=8)
        self._ventana_previa_ampliada = ventana
        self._canvas_previa_ampliada = canvas
        canvas.bind(
            '<Configure>',
            lambda event: self._dibujar_previa_horario_grupo(canvas)
        )

        def cerrar():
            self._ventana_previa_ampliada = None
            self._canvas_previa_ampliada = None
            ventana.destroy()

        ventana.protocol("WM_DELETE_WINDOW", cerrar)
        self._dibujar_previa_horario_grupo(canvas)

    def _confirmar_volver_a_preasignar_grupo(self):
        grupo_id = ""
        if hasattr(self, '_sv_filtro_grupo_vp'):
            grupo_id = self._sv_filtro_grupo_vp.get().strip()
        if (not grupo_id or grupo_id == "Todos") and hasattr(self, '_sv_grupo_gestion'):
            grupo_id = self._sv_grupo_gestion.get().strip()

        if not grupo_id or grupo_id == "Todos":
            messagebox.showwarning(
                "Seleccionar Grupo",
                "Por favor selecciona un grupo específico (en la vista de gestión o en el selector de vista previa) para volver a acomodar sus materias."
            )
            return

        salon_actual = "Sin aula"
        materias_grupo = []
        with obtener_cursor() as ctx:
            if ctx:
                cur, conn = ctx
                cur.execute("""
                    SELECT DISTINCT h.salon_id
                    FROM horarios h
                    JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                    WHERE a.grupo_id = %s AND h.salon_id NOT LIKE 'MEDIACION%'
                """, (grupo_id,))
                rows = cur.fetchall()
                if rows:
                    salon_actual = ", ".join(r[0] for r in rows)

                cur.execute("""
                    SELECT a.materia_id, IFNULL(m.nombre, a.materia_id), a.profesor_id, IFNULL(p.nombre, 'Sin profesor')
                    FROM asignaciones a
                    LEFT JOIN materias m ON a.materia_id = m.materia_id
                    LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                    WHERE a.grupo_id = %s AND (a.estado IS NULL OR a.estado != 'cancelada')
                    ORDER BY a.materia_id
                """, (grupo_id,))
                materias_grupo = cur.fetchall()

        if not materias_grupo:
            # Comprobar si tiene materias en grupo_materias pendientes de preasignar
            materias_gm = []
            with obtener_cursor() as ctx:
                if ctx:
                    cur, conn = ctx
                    cur.execute("""
                        SELECT gm.materia_id, m.nombre
                        FROM grupo_materias gm
                        JOIN materias m ON gm.materia_id = m.materia_id
                        WHERE gm.grupo_id = %s
                        ORDER BY m.materia_id
                    """, (grupo_id,))
                    materias_gm = cur.fetchall()

            if materias_gm:
                if messagebox.askyesno(
                    "Preasignar Grupo",
                    f"El grupo '{grupo_id}' tiene {len(materias_gm)} materias registradas pero aún no tiene aula ni horarios preasignados.\n\n"
                    "¿Desea preasignar el aula y los horarios para este grupo ahora?"
                ):
                    from src.motor_preasignacion import GeneradorPreasignacion
                    motor = GeneradorPreasignacion()
                    res = motor.preasignar_grupo(grupo_id)
                    if res.get("exito"):
                        messagebox.showinfo("Preasignación Exitosa", res.get("mensaje", "Grupo preasignado correctamente."))
                        self.actualizar_vista_previa()
                        self._cargar_materias_grupo_gestion()
                    else:
                        messagebox.showerror("Error de Preasignación", res.get("mensaje", "No se pudo preasignar el grupo."))
                return
            else:
                messagebox.showwarning(
                    "Sin Materias",
                    f"El grupo '{grupo_id}' no tiene materias vinculadas en 'Grupos'. Registre materias para este grupo primero."
                )
                return

        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Volver a acomodar materias del grupo")
        dialogo.transient(self.ventana)
        dialogo.grab_set()
        dialogo.configure(background='#0A0F1E')
        dialogo.geometry("560x370")
        dialogo.resizable(False, False)

        f_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=20, pady=16)

        ttk.Label(
            f_cont,
            text="¿Desea volver a acomodar materias en el salón?",
            background='#0A0F1E',
            foreground='#FFD700',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 4))

        ttk.Label(
            f_cont,
            text=f"Grupo: {grupo_id}   |   Salón asignado: {salon_actual}   |   Total materias: {len(materias_grupo)}",
            background='#0A0F1E',
            foreground='white',
            font=self._fuente_sub
        ).pack(anchor='w', pady=(0, 10))

        ttk.Label(
            f_cont,
            text="Se mantendrá al grupo en el mismo salón y se buscará una nueva distribución horaria en otro orden.\nSeleccione el alcance deseado:",
            background='#0A0F1E',
            foreground='#B0BEC5',
            font=self._fuente_label,
            justify='left'
        ).pack(anchor='w', pady=(0, 14))

        def _on_opcion_todo():
            dialogo.destroy()
            self._ejecutar_reacomodo_motor(grupo_id, modo="todo")

        def _on_opcion_sin_profesor():
            dialogo.destroy()
            self._ejecutar_reacomodo_motor(grupo_id, modo="sin_profesor")

        def _on_opcion_especificar():
            dialogo.destroy()
            self._mostrar_modal_especificar_materias(grupo_id, salon_actual, materias_grupo)

        def _on_cancelar():
            dialogo.destroy()

        btn_todo = ttk.Button(
            f_cont,
            text="1. Sí (Reacomodar TODO el grupo, incluyendo con profesor)",
            command=_on_opcion_todo
        )
        btn_todo.pack(fill='x', pady=4)

        btn_sin_prof = ttk.Button(
            f_cont,
            text="2. Sí, pero SOLO a las asignaciones sin profesores",
            command=_on_opcion_sin_profesor
        )
        btn_sin_prof.pack(fill='x', pady=4)

        btn_especificar = ttk.Button(
            f_cont,
            text="3. Especificar materias con checklist...",
            command=_on_opcion_especificar
        )
        btn_especificar.pack(fill='x', pady=4)

        btn_cancelar = ttk.Button(
            f_cont,
            text="No (Cancelar)",
            command=_on_cancelar
        )
        btn_cancelar.pack(fill='x', pady=(10, 4))

    def _mostrar_modal_especificar_materias(self, grupo_id, salon_actual, materias_grupo):
        dlg_esp = tk.Toplevel(self.ventana)
        dlg_esp.title(f"Especificar Materias a Reacomodar - Grupo {grupo_id}")
        dlg_esp.transient(self.ventana)
        dlg_esp.grab_set()
        dlg_esp.configure(background='#0A0F1E')
        dlg_esp.geometry("620x480")

        f_cont = ttk.Frame(dlg_esp, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=16, pady=14)

        ttk.Label(
            f_cont,
            text="Marque las materias que desea volver a acomodar:",
            background='#0A0F1E',
            foreground='#FFD700',
            font=self._fuente_sub
        ).pack(anchor='w', pady=(0, 4))

        ttk.Label(
            f_cont,
            text=f"Grupo: {grupo_id} | Salón: {salon_actual}. Las materias no marcadas mantendrán su horario actual.",
            background='#0A0F1E',
            foreground='#B0BEC5',
            font=self._fuente_label
        ).pack(anchor='w', pady=(0, 8))

        canvas_mats = tk.Canvas(f_cont, background='#0A0F1E', highlightthickness=0)
        sb_mats = ttk.Scrollbar(f_cont, orient='vertical', command=canvas_mats.yview)
        f_lista = ttk.Frame(canvas_mats, style='blue.TFrame')

        f_lista.bind('<Configure>', lambda e: canvas_mats.configure(scrollregion=canvas_mats.bbox('all')))
        canvas_win = canvas_mats.create_window((0, 0), window=f_lista, anchor='nw')
        canvas_mats.bind('<Configure>', lambda e: canvas_mats.itemconfig(canvas_win, width=e.width))
        canvas_mats.configure(yscrollcommand=sb_mats.set)

        canvas_mats.pack(side='top', fill='both', expand=True, pady=4)
        sb_mats.pack(side='right', fill='y', before=canvas_mats)

        vars_materias = {}
        for m_id, m_nom, p_id, p_nom in materias_grupo:
            tiene_prof = bool(p_id and str(p_id).strip() != 'SIN_ASIGNAR')
            var_m = tk.BooleanVar(value=True)
            vars_materias[str(m_id)] = var_m

            f_fila_m = ttk.Frame(f_lista, style='blue.TFrame')
            f_fila_m.pack(fill='x', padx=4, pady=2)

            cb = ttk.Checkbutton(
                f_fila_m,
                text=f"{m_id} - {m_nom}",
                variable=var_m,
                style='Custom.TCheckbutton'
            )
            cb.pack(side='left', padx=4)

            info_prof = f"Profesor: {p_nom}" if tiene_prof else "(Sin profesor)"
            color_prof = '#98FB98' if tiene_prof else '#7E8B9B'
            ttk.Label(
                f_fila_m,
                text=info_prof,
                background='#0A0F1E',
                foreground=color_prof,
                font=self._fuente_label
            ).pack(side='right', padx=6)

        f_btns = ttk.Frame(f_cont, style='blue.TFrame')
        f_btns.pack(fill='x', pady=(10, 0))

        def _seleccionar_todas(val):
            for v in vars_materias.values():
                v.set(val)

        ttk.Button(f_btns, text="Marcar Todas", command=lambda: _seleccionar_todas(True)).pack(side='left', padx=3)
        ttk.Button(f_btns, text="Desmarcar Todas", command=lambda: _seleccionar_todas(False)).pack(side='left', padx=3)

        def _on_confirmar():
            seleccionadas = [m_id for m_id, v in vars_materias.items() if v.get()]
            if not seleccionadas:
                messagebox.showwarning("Aviso", "Debes seleccionar al menos una materia para reacomodar.")
                return
            dlg_esp.destroy()
            self._ejecutar_reacomodo_motor(grupo_id, modo="especificar", materias_ids=seleccionadas)

        ttk.Button(f_btns, text="No (Cancelar)", command=dlg_esp.destroy).pack(side='right', padx=3)
        ttk.Button(f_btns, text="🔄 Reacomodar Seleccionadas", command=_on_confirmar).pack(side='right', padx=3)

    def _ejecutar_reacomodo_motor(self, grupo_id, modo="todo", materias_ids=None):
        from src.motor_preasignacion import GeneradorPreasignacion
        motor = GeneradorPreasignacion()
        res = motor.reacomodar_grupo(grupo_id=grupo_id, modo=modo, materias_ids=materias_ids)

        if not res.get("exito"):
            messagebox.showerror("Reacomodo No Completado", res.get("mensaje", "Ocurrió un error al reacomodar."))
            return

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)

        messagebox.showinfo(
            "Reacomodo Exitoso",
            f"¡Grupo {grupo_id} reorganizado con éxito!\n\n"
            f"• Salón mantenido: {res['salon_base']}\n"
            f"• Materias reacomodadas: {res['total_reacomodadas']} de {res['total_solicitadas']}\n"
            f"• Se generó una nueva distribución horaria en {res.get('intentos', 1)} intento(s)."
        )

    def _crear_punto_restauracion(self, nombre_predeterminado=None):
        from src.gestor_restauracion import GestorRestauracion
        from tkinter import simpledialog
        def_name = nombre_predeterminado or f"Respaldo {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}"
        nombre = simpledialog.askstring(
            "Crear Punto de Restauración",
            "Ingrese un nombre para identificar este punto de restauración:",
            initialvalue=def_name,
            parent=self.ventana
        )
        if not nombre:
            return

        res = GestorRestauracion.crear_punto(nombre=nombre)
        if res.get("exito"):
            messagebox.showinfo(
                "Punto Creado",
                f"Punto de restauración '{nombre}' guardado con éxito.\n\n"
                f"• Asignaciones respaldadas: {res['total_asignaciones']}\n"
                f"• Horarios respaldados: {res['total_horarios']}\n"
                f"• Fecha: {res['fecha']}"
            )
        else:
            messagebox.showerror("Error", res.get("mensaje", "No se pudo crear el punto de restauración."))

    def _abrir_dialogo_restaurar_punto(self):
        from src.gestor_restauracion import GestorRestauracion
        puntos = GestorRestauracion.listar_puntos()
        if not puntos:
            messagebox.showinfo(
                "Sin Puntos de Restauración",
                "Aún no existen puntos de restauración creados.\nPuede crear uno usando el botón '📸 Crear Punto'."
            )
            return

        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Puntos de Restauración (Rollback)")
        dialogo.transient(self.ventana)
        dialogo.grab_set()
        dialogo.configure(background='#0A0F1E')
        dialogo.geometry("700x440")

        f_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=16, pady=14)

        ttk.Label(
            f_cont,
            text="⏪ Restaurar Estado Previo (Rollback)",
            background='#0A0F1E',
            foreground='#FFD700',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 4))

        ttk.Label(
            f_cont,
            text="Seleccione un punto de restauración para regresar las asignaciones y horarios a ese estado:",
            background='#0A0F1E',
            foreground='#B0BEC5',
            font=self._fuente_label
        ).pack(anchor='w', pady=(0, 8))

        f_tabla = ttk.Frame(f_cont, style='blue.TFrame')
        f_tabla.pack(fill='both', expand=True, pady=4)

        cols = ('ID', 'Fecha', 'Nombre', 'Descripción', 'Asignaciones', 'Horarios')
        tree = ttk.Treeview(f_tabla, columns=cols, show='headings', height=10)
        tree.heading('ID', text='ID')
        tree.heading('Fecha', text='Fecha / Hora')
        tree.heading('Nombre', text='Nombre del Respaldo')
        tree.heading('Descripción', text='Descripción')
        tree.heading('Asignaciones', text='Asignaciones')
        tree.heading('Horarios', text='Horarios')

        tree.column('ID', width=40, anchor='center')
        tree.column('Fecha', width=130, anchor='center')
        tree.column('Nombre', width=180, anchor='w')
        tree.column('Descripción', width=120, anchor='w')
        tree.column('Asignaciones', width=80, anchor='center')
        tree.column('Horarios', width=70, anchor='center')

        sb_v = ttk.Scrollbar(f_tabla, orient='vertical', command=tree.yview)
        tree.configure(yscroll=sb_v.set)
        sb_v.pack(side='right', fill='y')
        tree.pack(fill='both', expand=True)

        for p in puntos:
            tree.insert('', 'end', iid=str(p['punto_id']), values=(
                p['punto_id'], p['fecha_creacion'], p['nombre'],
                p.get('descripcion') or '', p['total_asignaciones'], p['total_horarios']
            ))

        f_btns = ttk.Frame(f_cont, style='blue.TFrame')
        f_btns.pack(fill='x', pady=(10, 0))

        def _ejecutar_restauracion():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Aviso", "Seleccione un punto de restauración de la lista.", parent=dialogo)
                return
            p_id = int(sel[0])
            item = tree.item(sel[0])['values']
            nom_punto = item[2]
            fecha_punto = item[1]

            if not messagebox.askyesno(
                "Confirmar Restauración",
                f"¿Está seguro de restaurar el sistema al punto '{nom_punto}' ({fecha_punto})?\n\n"
                f"⚠ Se guardará automáticamente una copia del estado actual antes de proceder, "
                f"y se restaurarán las asignaciones y horarios correspondientes a dicho punto.",
                parent=dialogo
            ):
                return

            res = GestorRestauracion.restaurar_punto(p_id)
            if res.get("exito"):
                dialogo.destroy()
                self._cargar_materias_grupo_gestion()
                self.actualizar_vista_previa()
                self._cargar_previa_horario_grupo()
                self._cargar_tensor_diferido(forzar=True)
                messagebox.showinfo(
                    "Restauración Completada",
                    f"¡El sistema ha sido restaurado con éxito al punto '{nom_punto}'!\n\n"
                    f"• Asignaciones restauradas: {res['total_asignaciones']}\n"
                    f"• Horarios restaurados: {res['total_horarios']}"
                )
            else:
                messagebox.showerror("Error al Restaurar", res.get("mensaje", "Error desconocido."), parent=dialogo)

        def _eliminar_seleccionado():
            sel = tree.selection()
            if not sel:
                return
            p_id = int(sel[0])
            if messagebox.askyesno("Eliminar Punto", "¿Desea eliminar el punto de restauración seleccionado?", parent=dialogo):
                GestorRestauracion.eliminar_punto(p_id)
                tree.delete(sel[0])

        ttk.Button(f_btns, text="🗑 Eliminar Punto", command=_eliminar_seleccionado).pack(side='left', padx=4)
        ttk.Button(f_btns, text="Cerrar", command=dialogo.destroy).pack(side='right', padx=4)
        ttk.Button(f_btns, text="⏪ Restaurar Punto Seleccionado", command=_ejecutar_restauracion).pack(side='right', padx=4)

    def _abrir_dialogo_sabana_horarios(self):
        from src.generador_sabana import GeneradorSabana

        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Sábana Matricial de Horarios (SAGA 2.0)")
        dialogo.transient(self.ventana)
        dialogo.grab_set()
        dialogo.configure(background='#0A0F1E')
        dialogo.geometry("540x420")
        dialogo.resizable(False, False)

        f_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=20, pady=16)

        ttk.Label(
            f_cont,
            text="📊 Sábana Matricial Consolidada",
            background='#0A0F1E',
            foreground='#FFD700',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 4))

        ttk.Label(
            f_cont,
            text="Genera un reporte comparativo general donde los grupos de cada semestre se visualizan en columnas paralelas lado a lado para verificar la compatibilidad y distribución docente.",
            background='#0A0F1E',
            foreground='#B0BEC5',
            font=self._fuente_label,
            wraplength=500,
            justify='left'
        ).pack(anchor='w', pady=(0, 14))

        f_form = ttk.Frame(f_cont, style='blue.TFrame')
        f_form.pack(fill='x', pady=4)

        # Filtro Semestre
        ttk.Label(f_form, text="Semestre:", background='#0A0F1E', foreground='white', font=self._fuente_sub).grid(row=0, column=0, sticky='w', pady=8, padx=(0, 12))
        combo_sem = ttk.Combobox(f_form, values=["Todos", "1", "2", "3", "4", "5", "6", "7", "8", "9"], state='readonly', width=16, font=self._fuente_label)
        val_sem_actual = getattr(self, 'combo_filtro_semestre', None)
        sem_ini = val_sem_actual.get() if val_sem_actual and val_sem_actual.get() else "Todos"
        combo_sem.set(sem_ini)
        combo_sem.grid(row=0, column=1, sticky='w', pady=8)

        # Filtro Periodo
        ttk.Label(f_form, text="Periodo:", background='#0A0F1E', foreground='white', font=self._fuente_sub).grid(row=1, column=0, sticky='w', pady=8, padx=(0, 12))
        combo_per = ttk.Combobox(f_form, values=["Todos", "A", "B"], state='readonly', width=16, font=self._fuente_label)
        per_act = getattr(self, 'combo_periodos', None)
        combo_per.set(per_act.get() if per_act and per_act.get() in ("A", "B") else "Todos")
        combo_per.grid(row=1, column=1, sticky='w', pady=8)

        # Formato de exportación
        ttk.Label(f_form, text="Formato:", background='#0A0F1E', foreground='white', font=self._fuente_sub).grid(row=2, column=0, sticky='w', pady=8, padx=(0, 12))
        formato_var = tk.StringVar(value="excel")
        f_fmt = ttk.Frame(f_form, style='blue.TFrame')
        f_fmt.grid(row=2, column=1, sticky='w', pady=8)
        rb_excel = ttk.Radiobutton(f_fmt, text="Excel (.xlsx) - Hoja por semestre", variable=formato_var, value="excel")
        rb_excel.pack(anchor='w', pady=2)
        rb_pdf = ttk.Radiobutton(f_fmt, text="PDF (.pdf) - Documento apaisado", variable=formato_var, value="pdf")
        rb_pdf.pack(anchor='w', pady=2)

        # Checkbox para abrir al terminar
        abrir_var = tk.BooleanVar(value=True)
        cb_abrir = ttk.Checkbutton(f_cont, text="Abrir archivo automáticamente al finalizar", variable=abrir_var)
        cb_abrir.pack(anchor='w', pady=(10, 10))

        # Botones de acción
        f_btns = ttk.Frame(f_cont, style='blue.TFrame')
        f_btns.pack(fill='x', side='bottom', pady=(10, 0))

        def _ejecutar_generacion():
            sem_sel = combo_sem.get().strip()
            per_sel = combo_per.get().strip()
            fmt_sel = formato_var.get()

            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            sem_nom = f"Semestre_{sem_sel}" if sem_sel != "Todos" else "Todos_Semestres"
            per_nom = f"Periodo_{per_sel}" if per_sel != "Todos" else "Ambos_Periodos"

            ruta_descargas = os.path.join(os.path.expanduser('~'), 'Downloads')
            if fmt_sel == "excel":
                ext = ".xlsx"
                tipos = [("Archivos Excel", "*.xlsx")]
                nombre_default = f"Sabana_Horarios_{sem_nom}_{per_nom}_{ts}.xlsx"
            else:
                ext = ".pdf"
                tipos = [("Documentos PDF", "*.pdf")]
                nombre_default = f"Sabana_Horarios_{sem_nom}_{per_nom}_{ts}.pdf"

            ruta_destino = filedialog.asksaveasfilename(
                title="Guardar Sábana de Horarios",
                initialdir=ruta_descargas,
                initialfile=nombre_default,
                defaultextension=ext,
                filetypes=tipos,
                parent=dialogo
            )
            if not ruta_destino:
                return

            try:
                dialogo.config(cursor="watch")
                dialogo.update_idletasks()

                if fmt_sel == "excel":
                    res = GeneradorSabana.generar_excel_sabana(
                        ruta_destino,
                        filtro_semestre=sem_sel if sem_sel != "Todos" else None,
                        filtro_periodo=per_sel if per_sel != "Todos" else None
                    )
                else:
                    res = GeneradorSabana.generar_pdf_sabana(
                        ruta_destino,
                        filtro_semestre=sem_sel if sem_sel != "Todos" else None,
                        filtro_periodo=per_sel if per_sel != "Todos" else None
                    )

                dialogo.config(cursor="")

                if not res.get("exito"):
                    messagebox.showwarning("Aviso", res.get("mensaje", "No se generó el archivo."), parent=dialogo)
                    return

                dialogo.destroy()

                msg_exito = f"¡Sábana generada exitosamente!\n\nArchivo guardado en:\n{ruta_destino}\n\n• Semestres incluidos: {res.get('total_semestres', 1)}"
                if 'total_grupos' in res:
                    msg_exito += f"\n• Total de grupos procesados: {res['total_grupos']}"

                messagebox.showinfo("Exportación Completa", msg_exito, parent=self.ventana)

                if abrir_var.get():
                    try:
                        os.startfile(ruta_destino)
                    except Exception as e_open:
                        print(f"No se pudo abrir automáticamente: {e_open}")

            except Exception as ex:
                dialogo.config(cursor="")
                messagebox.showerror("Error al generar sábana", f"Ocurrió un error inesperado:\n{ex}", parent=dialogo)

        ttk.Button(f_btns, text="Cancelar", command=dialogo.destroy).pack(side='right', padx=4)
        ttk.Button(f_btns, text="📥 Generar Reporte", command=_ejecutar_generacion).pack(side='right', padx=4)

    def _dibujar_previa_horario_grupo(self, canvas=None):
        if canvas is None:
            canvas = getattr(self, 'canvas_previa_horario', None)
        if canvas is None:
            return
        canvas.delete('all')
        width = max(canvas.winfo_width(), 360)
        height = max(canvas.winfo_height(), 320)
        label_width = min(max(width * 0.12, 70), 110)
        title_height = 24
        header_height = min(max(height * 0.045, 22), 32)
        start_minutes = 7 * 60
        end_minutes = 21 * 60 + 30
        slots = (end_minutes - start_minutes) // 30
        day_width = max(1, (width - label_width) / len(self.NOMBRES_DIAS))
        row_height = max(12, (height - title_height - header_height - 8) / slots)
        selected_group = self._sv_filtro_grupo_vp.get().strip()

        if not selected_group or selected_group == "Todos":
            canvas.create_text(
                width / 2, 18, text="Selecciona un grupo para ver su horario.",
                fill='#333333', font=('Arial', 9)
            )
            return
        if getattr(self, '_grupo_previa_error', None):
            canvas.create_text(
                8, 18, anchor='w',
                text=f"No se pudo cargar el horario: {self._grupo_previa_error}",
                fill='#9B1C1C', font=('Arial', 9)
            )
            return

        canvas.create_text(
            width / 2, title_height / 2, text=f"Grupo: {selected_group}",
            fill='#172414',
            font=('Arial', int(min(14, max(10, day_width / 7))), 'bold')
        )
        top = title_height
        canvas.create_rectangle(
            0, top, label_width, top + header_height,
            fill='#1A1A1A', outline='#111111'
        )
        canvas.create_text(
            label_width / 2, top + header_height / 2,
            text="Hora", fill='white',
            font=('Arial', int(min(10, max(7, header_height * 0.35))), 'bold')
        )
        for indice, dia in enumerate(self.NOMBRES_DIAS):
            x0 = label_width + indice * day_width
            canvas.create_rectangle(
                x0, top, x0 + day_width, top + header_height,
                fill='#2F4A23', outline='#111111'
            )
            canvas.create_text(
                x0 + day_width / 2, top + header_height / 2,
                text=dia[:3], fill='white',
                font=('Arial', int(min(10, max(7, min(day_width / 7, header_height * 0.35)))), 'bold')
            )

        grid_top = top + header_height
        for slot in range(slots):
            y0 = grid_top + slot * row_height
            hora_inicio = start_minutes + slot * 30
            hora_fin = hora_inicio + 30
            canvas.create_rectangle(
                0, y0, label_width, y0 + row_height,
                fill='#1A1A1A', outline='#333333'
            )
            canvas.create_text(
                label_width / 2, y0 + row_height / 2,
                text=f"{hora_inicio // 60:02d}:{hora_inicio % 60:02d} - "
                     f"{hora_fin // 60:02d}:{hora_fin % 60:02d}",
                fill='white', font=('Arial', int(min(8, max(5, row_height * 0.3))))
            )
            for indice in range(len(self.NOMBRES_DIAS)):
                x0 = label_width + indice * day_width
                canvas.create_rectangle(
                    x0, y0, x0 + day_width, y0 + row_height,
                    fill='white', outline='#777777', width=1
                )

        for bloque in getattr(self, '_grupo_previa_datos', []):
            inicio = max(bloque['inicio'], start_minutes)
            fin = min(bloque['fin'], end_minutes)
            if fin <= inicio:
                continue
            x0 = label_width + bloque['dia'] * day_width + 1
            x1 = label_width + (bloque['dia'] + 1) * day_width - 1
            y0 = grid_top + ((inicio - start_minutes) / 30) * row_height + 1
            y1 = grid_top + ((fin - start_minutes) / 30) * row_height - 1
            color = '#DCEBFA' if bloque['propuesta'] else '#E8F0E3'
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline='#263238', width=1)
            inicio_txt = f"{bloque['inicio'] // 60:02d}:{bloque['inicio'] % 60:02d}"
            fin_txt = f"{bloque['fin'] // 60:02d}:{bloque['fin'] % 60:02d}"
            salon_txt = "Propuesta" if bloque['propuesta'] else f"Salón: {bloque['salon']}"
            alto_bloque = y1 - y0
            tamano_fuente = int(min(8, max(5, min(day_width / 9, alto_bloque / 5))))
            caracteres_linea = max(5, int((day_width - 8) / (tamano_fuente * 0.62)))
            texto = "\n".join(
                textwrap.shorten(str(linea), width=caracteres_linea, placeholder="...")
                for linea in (bloque['materia'], bloque['profesor'], salon_txt)
            )
            if alto_bloque < 25:
                texto = textwrap.shorten(
                    str(bloque['materia']),
                    width=caracteres_linea,
                    placeholder="..."
                )
            canvas.create_text(
                (x0 + x1) / 2, y0 + alto_bloque * 0.58,
                text=texto, fill='#111111', width=max(20, x1 - x0 - 4),
                font=('Arial', tamano_fuente), justify='center'
            )
            if alto_bloque >= 25:
                canvas.create_text(
                    (x0 + x1) / 2, y0 + min(6, alto_bloque * 0.2),
                    text=f"{inicio_txt}-{fin_txt}",
                    fill='#263238', font=('Arial', max(4, tamano_fuente - 1))
                )

    def actualizar_tabla_grafica(self, modo_impresion=False):
        self.ax.clear()
        self.ax.axis('off')
        
        if mem_grafico.tensor_actual is None:
            self.ax.text(0.5, 0.5, "Cargando horarios...", ha='center', va='center',
                        transform=self.ax.transAxes, fontsize=14, color='gray')
            self.fig.tight_layout(pad=0)
            self.canvas_horario.draw()
            return

        time_col_w = 0.15 
        day_col_w = (1.0 - time_col_w) / 6 
        col_widths = [time_col_w] + [day_col_w] * 6

        num_horarios = mem_grafico.intervalos - 1 
        header_h = 0.08 
        grid_area_h = 1.0 - header_h
        interval_h = grid_area_h / num_horarios 
        
        bg_fig = 'white' if modo_impresion else '#0A0F1E'
        text_title = 'black' if modo_impresion else 'white'
        bg_header = '#e0e0e0' if modo_impresion else '#2f4a23' 
        text_header = 'black' if modo_impresion else 'white'
        bg_time_col = '#f5f5f5' if modo_impresion else '#1a1a1a' 
        text_time = 'black' if modo_impresion else 'white'
        edge_color = 'black'
        
        self.fig.patch.set_facecolor(bg_fig)
        
        titulo_texto = "HORARIO" 
        if mem_grafico.entidades_actuales:
            try:
                nombre_real = next(e[0] for e in mem_grafico.entidades_actuales if e[1] == self.s_idx)
                modo_up = mem_grafico.modo_actual.upper()
                titulo_texto = f"HORARIO {modo_up} - {nombre_real}"
            except StopIteration:
                pass
        
        self.ax.set_title(titulo_texto, color=text_title, pad=10, fontsize=12, fontweight='bold')

        day_names = ['Hora', 'Lunes', 'Martes', 'Miér', 'Juev', 'Vier', 'Sáb']
        x_curr = 0.0
        for i, name in enumerate(day_names):
            self.ax.add_patch(Rectangle((x_curr, 1.0 - header_h), col_widths[i], header_h, 
                                      facecolor=bg_header, edgecolor=edge_color, linewidth=1, zorder=5))
            self.ax.text(x_curr + col_widths[i]/2, 1.0 - header_h/2, name,
                        ha='center', va='center', fontweight='bold', color=text_header, fontsize=10, zorder=6)
            x_curr += col_widths[i]

        x_grid = 0.0
        for col_idx in range(7):
            y_grid = 1.0 - header_h
            for row_idx in range(1, mem_grafico.intervalos):
                y_pos = y_grid - interval_h
                bg_color = bg_time_col if col_idx == 0 else 'white'
                self.ax.add_patch(Rectangle((x_grid, y_pos), col_widths[col_idx], interval_h, 
                                          facecolor=bg_color, edgecolor=edge_color, linewidth=0.5, zorder=1))
                
                if col_idx == 0 and mem_grafico.tensor_actual is not None:
                    try:
                        texto_hora = mem_grafico.tensor_actual[self.s_idx, row_idx, 0]
                        self.ax.text(x_grid + col_widths[col_idx]/2, y_pos + interval_h/2, 
                                    texto_hora, ha='center', va='center', color=text_time, fontsize=8, zorder=2)
                    except IndexError: pass
                y_grid -= interval_h
            x_grid += col_widths[col_idx]

        x_materia = col_widths[0] 
        import textwrap 
        
        for col_idx in range(1, 7):
            r_ptr = 1 
            while r_ptr < mem_grafico.intervalos:
                if mem_grafico.tensor_actual is None: break
                try:
                    materia = mem_grafico.tensor_actual[self.s_idx, r_ptr, col_idx]
                except IndexError: break
                
                if materia != "" and materia is not None:
                    inicio_r = r_ptr
                    while (r_ptr + 1 < mem_grafico.intervalos and mem_grafico.tensor_actual[self.s_idx, r_ptr + 1, col_idx] == materia):
                        r_ptr += 1
                    
                    num_celdas = r_ptr - inicio_r + 1
                    h_bloque = num_celdas * interval_h
                    
                    y_base_area = 1.0 - header_h
                    y_pos_materia = y_base_area - (r_ptr) * interval_h
                    
                    es_sin_profesor = ("Sin profesor" in str(materia) or "SIN PROFESOR" in str(materia).upper())
                    if es_sin_profesor:
                        color_fondo = '#CBE5FE' if modo_impresion else '#1B4965'
                        color_texto = '#002B49' if modo_impresion else '#FFFFFF'
                    else:
                        color_fondo = '#D4EDDA' if modo_impresion else '#2D6A4F'
                        color_texto = '#155724' if modo_impresion else '#FFFFFF'

                    self.ax.add_patch(Rectangle((x_materia, y_pos_materia), col_widths[col_idx], h_bloque,
                                              facecolor=color_fondo, edgecolor=edge_color, linewidth=1.2, zorder=3))
                    
                    lineas_originales = str(materia).split('\n')
                    lineas_ajustadas = []
                    for linea in lineas_originales:
                        lineas_ajustadas.append(textwrap.fill(linea, width=20))
                        
                    texto_final = '\n'.join(lineas_ajustadas)
                    
                    self.ax.text(x_materia + col_widths[col_idx]/2, y_pos_materia + h_bloque/2, texto_final,
                               ha='center', va='center', fontsize=6.5, fontweight='bold',
                               color=color_texto, zorder=4)
                    
                r_ptr += 1
            x_materia += col_widths[col_idx]

        self.fig.tight_layout(pad=0)
        self.canvas_horario.draw()