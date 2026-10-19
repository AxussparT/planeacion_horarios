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

        estilo = ttk.Style()
        estilo.configure('blue.TFrame', background='#0A0F1E')
        estilo.configure('TNotebook', background='#0A0F1E', borderwidth=0)
        estilo.configure('TNotebook.Tab', background='#1a1f3e', foreground='#ffffff', padding=[10, 2])
        estilo.map('TNotebook.Tab', background=[('selected', '#0A0F1E')], foreground=[('selected', '#6D583A')])


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
        
        self._fuente_titulo = font.Font(family="Roboto", size=18, weight="bold")
        self._fuente_sub = font.Font(family="Roboto", size=12)
        self._fuente_label = font.Font(family="Roboto", size=10)
        self._fuente_btn = font.Font(family="Roboto", size=10, weight="bold")
        
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
        btn_asignar = ttk.Button(frame_filtros, text="Iniciar Asignaciones de Aula", command=self.iniciar_asignacion_automatica)
        btn_asignar.pack(side='left', padx=5)
        ttk.Separator(frame_filtros, orient='vertical').pack(side='left', fill='y', padx=8)
        ttk.Button(frame_filtros, text="Guardar Config", command=self._guardar_configuracion).pack(side='left', padx=2)
        ttk.Button(frame_filtros, text="Actualizar Config", command=self._actualizar_configuracion).pack(side='left', padx=2)
        ttk.Button(frame_filtros, text="Cargar Config", command=self._cargar_configuracion).pack(side='left', padx=2)
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

        # --- Profesor info (read-only when loaded) ---
        f_prof_info = ttk.LabelFrame(self.frame_izq, text="Profesor", style='blue.TFrame')
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

        btn_limpiar = ttk.Button(f_prof_info, text="Limpiar", command=self._limpiar_profesor_seleccionado)
        btn_limpiar.pack(pady=(2, 4))

        # --- Horas info ---
        self._label_horas = ttk.Label(self.frame_izq, text="", background='#0A0F1E', foreground='#FFD700', font=self._fuente_label)
        self._label_horas.pack(fill='x', padx=10, pady=(2, 0))

        # --- Periodos de Asignacion (con disponibilidad) ---
        f_periodos = ttk.LabelFrame(self.frame_izq, text="Periodos del Profesor", style='blue.TFrame')
        f_periodos.pack(fill='both', expand=True, padx=8, pady=4)

        self._periodos_asignacion = []
        self._periodos_frame = ttk.Frame(f_periodos, style='blue.TFrame')
        self._periodos_frame.pack(fill='both', expand=True, padx=4, pady=4)

        self._btn_agregar_periodo = ttk.Button(f_periodos, text="+ Agregar Periodo", command=self._agregar_periodo_vacio)
        self._btn_agregar_periodo.pack(pady=4)

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

        self.frame_previa_horario = ttk.LabelFrame(
            self.frame_der, text="Horario del grupo", style='blue.TFrame'
        )
        self.frame_previa_horario.pack(fill='x', padx=6, pady=(4, 8))
        ttk.Button(
            self.frame_previa_horario,
            text="Ajustar vista",
            command=self._abrir_previa_horario_ajustada
        ).pack(anchor='e', padx=4, pady=(4, 0))
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
        for pid, info in self.profesores_map.items():
            if info["no_cuenta"] == no_cuenta:
                self._profesor_id_seleccionado = pid
                break
        self._actualizar_horas_info()
        for item in self._periodos_frame.winfo_children():
            item.destroy()
        self._periodos_asignacion.clear()
        self._cargar_periodos_desde_bd()

    def _cambiar_filtro_semestre(self, event=None):
        self._actualizar_materias_en_periodos()

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
        self._profesor_id_seleccionado = None
        self._label_horas.config(text="")
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

    def _crear_spinner_hora(self, parent, valor_inicial="07:00"):
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
            if self._debounce_after_id:
                self.ventana.after_cancel(self._debounce_after_id)
            self._debounce_after_id = self.ventana.after(1000, self._actualizar_todas_periodos)

        btn_menos = ttk.Button(f, text="-", width=3, command=lambda: ajustar(-30))
        btn_menos.pack(side='left')

        entry = ttk.Entry(f, textvariable=var, width=7, font=self._fuente_label, justify='center')
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
        s = str(h)
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
                title="Guardar Configuración de Periodos"
            )
            if not filepath:
                return False

        self._progress_config.pack(side='left', padx=5)
        self._progress_config["value"] = 0
        self.ventana.update_idletasks()

        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return False
                cur, conn = ctx

                # Clean ALL corrupt dia values before saving
                print("[DEBUG GUARDAR] Limpiando datos corruptos en profesor_disponibilidad...")
                cur.execute("DELETE FROM profesor_disponibilidad WHERE dia NOT IN ('0','1','2','3','4','5','6')")
                deleted = cur.rowcount
                if deleted:
                    print(f"[DEBUG GUARDAR] Eliminadas {deleted} filas corruptas de disponibilidad")

                cur.execute("SELECT profesor_id, no_cuenta, nombre FROM profesores ORDER BY nombre")
                prof_rows = cur.fetchall()
                total = len(prof_rows)

                cur.execute("SELECT materia_id, nombre, horas_semana, semestre_id, tipo FROM materias")
                mat_rows = cur.fetchall()
                materias_catalog = []
                for m_id, m_nombre, m_hs, m_sem, m_tipo in mat_rows:
                    materias_catalog.append({
                        "materia_id": m_id,
                        "nombre": m_nombre,
                        "horas_semana": str(m_hs) if m_hs else "4",
                        "semestre_id": m_sem,
                        "tipo": m_tipo or "Normal"
                    })

                cur.execute("SELECT salon_id, capacidad, tipo FROM salones")
                sal_rows = cur.fetchall()
                salones_catalog = []
                for s_id, s_cap, s_tipo in sal_rows:
                    salones_catalog.append({
                        "salon_id": s_id,
                        "capacidad": s_cap,
                        "tipo": s_tipo or "Normal"
                    })

                config = {"version": 1, "materias": materias_catalog, "salones": salones_catalog, "profesores": []}

                for i, (prof_id, no_cuenta, nombre) in enumerate(prof_rows):
                    cur.execute(
                        "SELECT dia, hora_inicio, hora_fin, modalidad FROM profesor_disponibilidad WHERE profesor_id = %s AND dia != '6' ORDER BY dia",
                        (prof_id,)
                    )
                    disp_rows = cur.fetchall()

                    periods_map = {}
                    for dia, hi, hf, modal in disp_rows:
                        hi_str = self._hora_db_a_str(hi)
                        hf_str = self._hora_db_a_str(hf)
                        modal_str = modal or "Presencial"
                        clave = f"{hi_str}-{hf_str}-{modal_str}"
                        if clave not in periods_map:
                            periods_map[clave] = {
                                "hora_i": hi_str,
                                "hora_f": hf_str,
                                "modalidad": modal_str,
                                "dias": [],
                                "asignaciones": []
                            }
                        dia_num = self._normalizar_dia(dia)
                        dia_nombre = self.MAPA_DIAS.get(dia_num, dia_num)
                        if dia_num not in ('0','1','2','3','4','5'):
                            print(f"[DEBUG GUARDAR] *** DIA ANORMAL: raw={dia!r} -> dia_num={dia_num!r} -> dia_nombre={dia_nombre!r} (prof {prof_id})")
                        if dia_nombre not in periods_map[clave]["dias"]:
                            periods_map[clave]["dias"].append(dia_nombre)

                    cur.execute(
                        "SELECT a.asignacion_id, a.materia_id, a.grupo_id, a.hora_inicio, a.hora_fin, a.modalidad, a.periodo, a.estado FROM asignaciones a WHERE a.profesor_id = %s AND a.estado != 'cancelada' AND a.hora_inicio IS NOT NULL",
                        (prof_id,)
                    )
                    for row in cur.fetchall():
                        asig_id, m_id, g_id, hi, hf, modal, periodo, estado = row
                        hi_str = self._hora_db_a_str(hi)
                        hf_str = self._hora_db_a_str(hf)
                        modal_str = modal or "Presencial"
                        clave = f"{hi_str}-{hf_str}-{modal_str}"
                        if clave in periods_map:
                            asignacion_data = {
                                "materia_id": m_id,
                                "grupo_id": str(g_id),
                                "periodo": periodo or "A",
                                "estado": estado or "pendiente"
                            }
                            if estado == 'asignado':
                                cur.execute(
                                    "SELECT salon_id, dia, hora_inicio, hora_fin FROM horarios WHERE asignacion_id = %s",
                                    (asig_id,)
                                )
                                horarios_list = []
                                for h in cur.fetchall():
                                    horarios_list.append({
                                        "salon_id": h[0],
                                        "dia": h[1],
                                        "hora_inicio": self._hora_db_a_str(h[2]),
                                        "hora_fin": self._hora_db_a_str(h[3])
                                    })
                                if horarios_list:
                                    asignacion_data["horarios"] = horarios_list
                            periods_map[clave]["asignaciones"].append(asignacion_data)

                    # Solo guardar periodos que tengan al menos una asignacion
                    periods_con_asignaciones = {k: v for k, v in periods_map.items() if v["asignaciones"]}

                    config["profesores"].append({
                        "profesor_id": prof_id,
                        "no_cuenta": no_cuenta,
                        "nombre": nombre,
                        "periodos": list(periods_con_asignaciones.values())
                    })

                    self._progress_config["value"] = ((i + 1) / total) * 100
                    self.ventana.update_idletasks()

                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)

                # Formatear BD: limpiar horarios, asignaciones y disponibilidad
                print("[DEBUG GUARDAR] Formateando BD tras guardar config...")
                cur.execute("TRUNCATE TABLE horarios")
                cur.execute("DELETE FROM asignaciones")
                cur.execute("DELETE FROM profesor_disponibilidad")
                conn.commit()
                print("[DEBUG GUARDAR] BD formateada correctamente")

                self._ultimo_config_path = filepath
                if self._profesor_id_seleccionado:
                    self._cargar_periodos_desde_bd()
                self.actualizar_vista_previa()
                self._cargar_previa_horario_grupo()
                messagebox.showinfo("Configuración", f"Configuración guardada para {total} profesor(es) en:\n{filepath}\n\nBD formateada. Lista para nuevas asignaciones.")
                return True
        except Exception as e:
            messagebox.showerror("Error", f"Error al guardar configuración: {e}")
            return False
        finally:
            self._progress_config.pack_forget()

    def _actualizar_configuracion(self):
        if not self._ultimo_config_path or not os.path.exists(self._ultimo_config_path):
            if not messagebox.askyesno("Sin archivo",
                    "No hay un archivo de configuración previo.\n¿Deseas elegir una ubicación para guardar?"):
                return
            self._guardar_configuracion()
            return
        self._escribir_config_en(self._ultimo_config_path)

    def _escribir_config_en(self, filepath):
        self._progress_config.pack(side='left', padx=5)
        self._progress_config["value"] = 0
        self.ventana.update_idletasks()
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                cur.execute("DELETE FROM profesor_disponibilidad WHERE dia NOT IN ('0','1','2','3','4','5','6')")
                cur.execute("SELECT profesor_id, no_cuenta, nombre FROM profesores ORDER BY nombre")
                prof_rows = cur.fetchall()
                total = len(prof_rows)

                cur.execute("SELECT materia_id, nombre, horas_semana, semestre_id, tipo FROM materias")
                mat_rows = cur.fetchall()
                materias_catalog = []
                for m_id, m_nombre, m_hs, m_sem, m_tipo in mat_rows:
                    materias_catalog.append({
                        "materia_id": m_id,
                        "nombre": m_nombre,
                        "horas_semana": str(m_hs) if m_hs else "4",
                        "semestre_id": m_sem,
                        "tipo": m_tipo or "Normal"
                    })

                cur.execute("SELECT salon_id, capacidad, tipo FROM salones")
                sal_rows = cur.fetchall()
                salones_catalog = []
                for s_id, s_cap, s_tipo in sal_rows:
                    salones_catalog.append({
                        "salon_id": s_id,
                        "capacidad": s_cap,
                        "tipo": s_tipo or "Normal"
                    })

                config = {"version": 1, "materias": materias_catalog, "salones": salones_catalog, "profesores": []}
                for i, (prof_id, no_cuenta, nombre) in enumerate(prof_rows):
                    cur.execute(
                        "SELECT dia, hora_inicio, hora_fin, modalidad FROM profesor_disponibilidad WHERE profesor_id = %s AND dia != '6' ORDER BY dia",
                        (prof_id,)
                    )
                    disp_rows = cur.fetchall()
                    periods_map = {}
                    for dia, hi, hf, modal in disp_rows:
                        hi_str = self._hora_db_a_str(hi)
                        hf_str = self._hora_db_a_str(hf)
                        modal_str = modal or "Presencial"
                        clave = f"{hi_str}-{hf_str}-{modal_str}"
                        if clave not in periods_map:
                            periods_map[clave] = {
                                "hora_i": hi_str, "hora_f": hf_str, "modalidad": modal_str,
                                "dias": [], "asignaciones": []
                            }
                        dia_num = self._normalizar_dia(dia)
                        dia_nombre = self.MAPA_DIAS.get(dia_num, dia_num)
                        if dia_nombre not in periods_map[clave]["dias"]:
                            periods_map[clave]["dias"].append(dia_nombre)
                    cur.execute(
                        "SELECT a.asignacion_id, a.materia_id, a.grupo_id, a.hora_inicio, a.hora_fin, a.modalidad, a.periodo, a.estado FROM asignaciones a WHERE a.profesor_id = %s AND a.estado != 'cancelada' AND a.hora_inicio IS NOT NULL",
                        (prof_id,)
                    )
                    for row in cur.fetchall():
                        asig_id, m_id, g_id, hi, hf, modal, periodo, estado = row
                        hi_str = self._hora_db_a_str(hi)
                        hf_str = self._hora_db_a_str(hf)
                        modal_str = modal or "Presencial"
                        clave = f"{hi_str}-{hf_str}-{modal_str}"
                        if clave in periods_map:
                            asignacion_data = {
                                "materia_id": m_id, "grupo_id": str(g_id),
                                "periodo": periodo or "A", "estado": estado or "pendiente"
                            }
                            if estado == 'asignado':
                                cur.execute(
                                    "SELECT salon_id, dia, hora_inicio, hora_fin FROM horarios WHERE asignacion_id = %s",
                                    (asig_id,)
                                )
                                horarios_list = []
                                for h in cur.fetchall():
                                    horarios_list.append({
                                        "salon_id": h[0], "dia": h[1],
                                        "hora_inicio": self._hora_db_a_str(h[2]),
                                        "hora_fin": self._hora_db_a_str(h[3])
                                    })
                                if horarios_list:
                                    asignacion_data["horarios"] = horarios_list
                            periods_map[clave]["asignaciones"].append(asignacion_data)
                    periods_con_asignaciones = {k: v for k, v in periods_map.items() if v["asignaciones"]}
                    config["profesores"].append({
                        "profesor_id": prof_id, "no_cuenta": no_cuenta, "nombre": nombre,
                        "periodos": list(periods_con_asignaciones.values())
                    })
                    self._progress_config["value"] = ((i + 1) / total) * 100
                    self.ventana.update_idletasks()
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
            self._ultimo_config_path = filepath
            messagebox.showinfo("Configuración", f"Configuración actualizada en:\n{filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Error al actualizar configuración: {e}")
        finally:
            self._progress_config.pack_forget()

    def _sincronizar_profesor_desde_json(self, cur, prof):
        """Inserta o reutiliza un profesor en la BD al cargar una configuración.

        Busca coincidencias por no_cuenta o por nombre. Si encuentra alguna,
        pregunta al usuario si es el mismo registro:
          - Sí  → reutiliza el registro existente de la BD (sin modificar su
                  no_cuenta ni su nombre); solo se sobreescribirá su disponibilidad.
          - No  → crea un nuevo registro para el profesor del JSON.
        Si no hay coincidencias, crea un nuevo registro directamente.

        Devuelve el profesor_id a usar, o None si el profesor debe omitirse.
        """
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
                print(f"[DEBUG CARGAR] Coincidencia aceptada para {nombre_json!r} -> usa {candidatos[0][0]}")
                return candidatos[0][0]
            print(f"[DEBUG CARGAR] Coincidencia rechazada para {nombre_json!r} -> se creará un nuevo registro")

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
        print(f"[DEBUG CARGAR] Nuevo profesor creado: {nuevo_id} ({nombre_json})")
        return nuevo_id

    def _cargar_configuracion(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")],
            title="Cargar Configuración de Periodos"
        )
        if not filepath:
            return

        if self._ultimo_config_path and os.path.exists(self._ultimo_config_path):
            if messagebox.askyesno("Guardar cambios",
                    "¿Desea guardar los cambios actuales en la configuración antes de cargar otro archivo?\n\nLos datos actuales se perderán si no los guarda."):
                self._escribir_config_en(self._ultimo_config_path)

        if not messagebox.askyesno("Cargar Configuración",
                "Se resetearán los periodos y asignaciones de todos los profesores.\nLos profesores no se eliminarán.\n¿Desea continuar?"):
            return

        self._progress_config.pack(side='left', padx=5)
        self._progress_config["value"] = 0
        self.ventana.update_idletasks()

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                config = json.load(f)

            profesores = config.get("profesores", [])
            total = len(profesores)

            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx

                print(f"[DEBUG CARGAR] ===== FORMATEANDO BD ({total} profesores) =====")

                cur.execute("TRUNCATE TABLE horarios")
                cur.execute("DELETE FROM asignaciones")
                cur.execute("DELETE FROM profesor_disponibilidad")
                conn.commit()
                print("[DEBUG CARGAR] BD formateada, cargando config...")

                materias_catalog = config.get("materias", [])
                if materias_catalog:
                    insertadas = 0
                    for mat in materias_catalog:
                        m_id = mat.get("materia_id")
                        m_nombre = mat.get("nombre", "")
                        m_hs = mat.get("horas_semana", "4")
                        m_sem = mat.get("semestre_id")
                        m_tipo = mat.get("tipo", "Normal")
                        if not m_id:
                            continue
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
                            insertadas += 1
                    print(f"[DEBUG CARGAR] Materias importadas: {insertadas} nuevas de {len(materias_catalog)} en JSON")
                else:
                    print("[DEBUG CARGAR] JSON sin catálogo de materias (formato antiguo)")

                salones_catalog = config.get("salones", [])
                if salones_catalog:
                    insertados = 0
                    for sal in salones_catalog:
                        s_id = sal.get("salon_id")
                        s_cap = sal.get("capacidad", 0)
                        s_tipo = sal.get("tipo", "Normal")
                        if not s_id:
                            continue
                        cur.execute("SELECT 1 FROM salones WHERE salon_id = %s", (s_id,))
                        if not cur.fetchone():
                            cur.execute(
                                "INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, %s, %s)",
                                (s_id, s_cap, s_tipo)
                            )
                            insertados += 1
                    print(f"[DEBUG CARGAR] Salones importados: {insertados} nuevos de {len(salones_catalog)} en JSON")
                else:
                    print("[DEBUG CARGAR] JSON sin catálogo de salones (formato antiguo)")

                conn.commit()

                for i, prof in enumerate(profesores):
                    prof_id = self._sincronizar_profesor_desde_json(cur, prof)
                    if not prof_id:
                        continue
                    print(f"[DEBUG CARGAR] Procesando profesor {prof_id} ({prof.get('nombre','?')})")

                    for periodo in prof.get("periodos", []):
                        hora_i = periodo["hora_i"]
                        hora_f = periodo["hora_f"]
                        modalidad = periodo.get("modalidad", "Presencial")
                        dias = periodo.get("dias", [])
                        print(f"[DEBUG CARGAR]   periodo {hora_i}-{hora_f} [{modalidad}], dias JSON: {dias!r}")

                        for dia_nombre in dias:
                            dia_num = self._normalizar_dia(dia_nombre)
                            print(f"[DEBUG CARGAR]     dia_nombre={dia_nombre!r} -> dia_num={dia_num!r}")
                            cur.execute(
                                "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin, modalidad) VALUES (%s, %s, %s, %s, %s)",
                                (prof_id, dia_num, hora_i, hora_f, modalidad)
                            )

                        for asig in periodo.get("asignaciones", []):
                            mat_id = asig["materia_id"]
                            grupo_texto = asig["grupo_id"]
                            periodo_letra = asig.get("periodo", "A")
                            estado = asig.get("estado", "pendiente")
                            grupo_id = self._obtener_id_valido(grupo_texto, es_grupo=True)
                            if not grupo_id:
                                continue
                            cur.execute(
                                "SELECT semestre_id FROM materias WHERE materia_id = %s",
                                (mat_id,)
                            )
                            materia = cur.fetchone()
                            if not materia:
                                print(f"[DEBUG CARGAR] *** MATERIA NO ENCONTRADA: {mat_id} - se omite asignación para {grupo_id}")
                                continue

                            nivel_grupo = materia[0] if materia[0] is not None else 0
                            cur.execute("SELECT grupo_id FROM grupos WHERE grupo_id = %s", (grupo_id,))
                            if not cur.fetchone():
                                cur.execute(
                                    "INSERT INTO grupos (grupo_id, nivel) VALUES (%s, %s)",
                                    (grupo_id, nivel_grupo)
                                )
                            else:
                                cur.execute(
                                    "UPDATE grupos SET nivel = %s "
                                    "WHERE grupo_id = %s AND (nivel IS NULL OR nivel = 0)",
                                    (nivel_grupo, grupo_id)
                                )
                            dias_str = ", ".join(dias)
                            cur.execute(
                                "INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, estado, periodo, hora_inicio, hora_fin, dias, modalidad) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                (prof_id, mat_id, grupo_id, estado, periodo_letra, hora_i, hora_f, dias_str, modalidad)
                            )
                            if estado == 'asignado':
                                horarios_data = asig.get("horarios", [])
                                if horarios_data:
                                    nueva_asignacion_id = cur.lastrowid
                                    for h in horarios_data:
                                        dia_num = self._normalizar_dia(h["dia"])
                                        dia_nombre = self.MAPA_DIAS.get(dia_num, "Lunes")
                                        salon_id = h["salon_id"]
                                        cur.execute("SELECT 1 FROM salones WHERE salon_id = %s", (salon_id,))
                                        if not cur.fetchone():
                                            print(f"[DEBUG CARGAR] *** SALON NO ENCONTRADO: {salon_id} - se omite horario")
                                            continue
                                        cur.execute(
                                            "INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin) VALUES (%s, %s, %s, %s, %s)",
                                            (nueva_asignacion_id, salon_id, dia_nombre, h["hora_inicio"], h["hora_fin"])
                                        )

                    conn.commit()

                    self._progress_config["value"] = ((i + 1) / total) * 100
                    self.ventana.update_idletasks()

            if self._profesor_id_seleccionado:
                self._cargar_periodos_desde_bd()
            self.grupos_por_semestre = self._cargar_grupos_desde_bd()
            if hasattr(self, 'combo_filtro_semestre_vp'):
                self.combo_filtro_semestre_vp['values'] = ["Todos"] + list(self.semestres_map.values())
                self._sv_filtro_semestre_vp.set("Todos")
                self._on_filtro_semestre_vp()
            with obtener_cursor() as ctx:
                if ctx is not None:
                    cur, conn = ctx
                    cur.execute(
                        "SELECT grupo_id FROM asignaciones "
                        "WHERE estado IS NULL OR estado != 'cancelada' "
                        "ORDER BY grupo_id LIMIT 1"
                    )
                    primer_grupo = cur.fetchone()
                else:
                    primer_grupo = None
            if primer_grupo:
                self._seleccionar_grupo_previa(primer_grupo[0])
            self.actualizar_vista_previa()
            self._cargar_previa_horario_grupo()
            self._ultimo_config_path = filepath
            messagebox.showinfo("Configuración", f"Configuración cargada para {total} profesor(es).\nBD formateada y datos cargados.")
        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar configuración: {e}")
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
        if not self.asignacion_seleccionada_id:
            messagebox.showwarning("Aviso", "Primero selecciona una asignación de la tabla de la derecha.")
            return

        if messagebox.askyesno("Confirmar", "¿Estás seguro de eliminar esta asignación?\n\nSe liberará el espacio del salón para que otra asignación pendiente pueda usarlo."):
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (self.asignacion_seleccionada_id,))
                    cur.execute("DELETE FROM asignaciones WHERE asignacion_id = %s", (self.asignacion_seleccionada_id,))
                    messagebox.showinfo("Éxito", "Asignación eliminada correctamente.")
                    self.asignacion_seleccionada_id = None 
                    self.actualizar_vista_previa()
                    self._cargar_previa_horario_grupo()
                    self._cargar_tensor_diferido()
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error", f"No se pudo borrar: {e}")

    def formatear_asignaciones(self):
        if messagebox.askyesno("¡ADVERTENCIA CRÍTICA!", "¿Estás ABSOLUTAMENTE SEGURO de querer borrar TODAS las asignaciones guardadas?\n\nEsto vaciará por completo la base de datos de horarios. No se puede deshacer."):
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM horarios")
                    cur.execute("DELETE FROM asignaciones")
                    try: cur.execute("ALTER TABLE horarios AUTO_INCREMENT = 1")
                    except: pass
                    try: cur.execute("ALTER TABLE asignaciones AUTO_INCREMENT = 1")
                    except: pass
                    messagebox.showinfo("Éxito", "La base de datos de asignaciones ha sido limpiada.")
                    self.asignacion_seleccionada_id = None
                    self.actualizar_vista_previa()
                    self._cargar_previa_horario_grupo()
                    if self._profesor_id_seleccionado:
                        for item in self._periodos_frame.winfo_children():
                            item.destroy()
                        self._periodos_asignacion.clear()
                        self._cargar_periodos_desde_bd()
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error", f"Ocurrió un error al formatear: {e}")

    def cargar_asignacion_seleccionada(self, event):
        item = self.tabla_asignaciones.focus()
        if not item or item == "no_results": return
        
        self.asignacion_seleccionada_id = item

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
                        a.profesor_id, IFNULL(p.nombre, 'Sin Profesor'), 
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
                        p_str = f"{row[1]} - {row[2]}"
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
        self, profesor_id, materia_id, grupo_id, modalidad, dias, hora_i, hora_f
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

    def _detectar_choques_grupo(self, grupo_id, materia_id, dias, hora_i, hora_f):
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
            cur.execute(
                """
                SELECT a.asignacion_id, a.dias, a.hora_inicio AS asignacion_inicio,
                       a.hora_fin AS asignacion_fin, m.nombre AS materia,
                       h.dia AS horario_dia, h.hora_inicio AS horario_inicio,
                       h.hora_fin AS horario_fin
                FROM asignaciones a
                LEFT JOIN materias m ON m.materia_id = a.materia_id
                LEFT JOIN horarios h ON h.asignacion_id = a.asignacion_id
                WHERE a.grupo_id = %s
                  AND a.materia_id <> %s
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
                """,
                (grupo_id, materia_id)
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
                    
                    self.ax.add_patch(Rectangle((x_materia, y_pos_materia), col_widths[col_idx], h_bloque,
                                              facecolor='white', edgecolor=edge_color, linewidth=1.2, zorder=3))
                    
                    lineas_originales = str(materia).split('\n')
                    lineas_ajustadas = []
                    for linea in lineas_originales:
                        lineas_ajustadas.append(textwrap.fill(linea, width=20))
                        
                    texto_final = '\n'.join(lineas_ajustadas)
                    
                    self.ax.text(x_materia + col_widths[col_idx]/2, y_pos_materia + h_bloque/2, texto_final,
                               ha='center', va='center', fontsize=6.5, fontweight='bold',
                               color='black', zorder=4)
                    
                r_ptr += 1
            x_materia += col_widths[col_idx]

        self.fig.tight_layout(pad=0)
        self.canvas_horario.draw()