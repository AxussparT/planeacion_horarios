import tkinter as tk
from tkinter import ttk, font, messagebox
from PIL import Image, ImageTk
import mysql.connector
import datetime
import textwrap
import os
import sys
import threading
import queue

from src.conexion import get_conexion, obtener_cursor, obtener_cursor_dict
from src.motor_horarios_nuevo import GeneradorHorarios
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
        self._profesor_id_seleccionado = None
        self._periodo_seleccionado = None
        self._semestres_filtrados = []
        
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
                    nivel = str(row[1]) if row[1] is not None else "0"
                    if nivel not in grupos:
                        grupos[nivel] = []
                    grupos[nivel].append(gid)
        except Exception as e:
            print(f"Error cargando grupos desde BD: {e}")
        return grupos

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

    def _cargar_tensor_diferido(self):
        if self._tensor_cargado:
            return
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
        if hasattr(self, 'combo_vista_horarios') and self.notebook.index(self.notebook.select()) == 1:
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

        def _on_mousewheel_izq(event):
            self.canvas_izq.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        def _on_mousewheel_izq_linux(event):
            self.canvas_izq.yview_scroll(-1 if event.num == 4 else 1, 'units')

        self.canvas_izq.bind('<MouseWheel>', _on_mousewheel_izq)
        self.canvas_izq.bind('<Button-4>', _on_mousewheel_izq_linux)
        self.canvas_izq.bind('<Button-5>', _on_mousewheel_izq_linux)
        self.canvas_izq.bind('<Enter>', lambda e: self.canvas_izq.focus_set())

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

        def _on_mousewheel(event):
            self.canvas_der.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        def _on_mousewheel_linux(event):
            self.canvas_der.yview_scroll(-1 if event.num == 4 else 1, 'units')

        self.canvas_der.bind('<MouseWheel>', _on_mousewheel)
        self.canvas_der.bind('<Button-4>', _on_mousewheel_linux)
        self.canvas_der.bind('<Button-5>', _on_mousewheel_linux)
        self.canvas_der.bind('<Enter>', lambda e: self.canvas_der.focus_set())

        self.canvas_der.configure(yscrollcommand=self.sb_der.set)
        self.canvas_der.pack(side='left', fill='both', expand=True, padx=(5, 0))
        self.sb_der.pack(side='left', fill='y', padx=(0, 10))

        # --- Tabla de Profesores (seleccionable) ---
        lbl_prof = ttk.Label(self.frame_der, text="Profesores", background='#0A0F1E', foreground='white', font=self._fuente_sub)
        lbl_prof.pack(anchor='w', padx=6, pady=(4, 2))

        f_busca_prof = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_busca_prof.pack(fill='x', padx=6)
        self.sv_busca_prof_tabla = tk.StringVar()
        self.sv_busca_prof_tabla.trace_add("write", lambda *a: self._filtrar_tabla_profesores())
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
        self.sv_busqueda_asignaciones.trace_add("write", lambda *a: self.actualizar_vista_previa())
        entry_busqueda = ttk.Entry(f_busqueda, textvariable=self.sv_busqueda_asignaciones, font=self._fuente_label)
        entry_busqueda.pack(side='left', fill='x', expand=True, padx=(0, 5))

        # --- Filtros de semestre y grupo ---
        f_filtros_vp = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_filtros_vp.pack(fill='x', pady=(2, 2))
        ttk.Label(f_filtros_vp, text="Semestre:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(5, 2))
        self._sv_filtro_semestre_vp = tk.StringVar()
        self._sv_filtro_semestre_vp.trace_add("write", lambda *a: self._on_filtro_semestre_vp())
        self.combo_filtro_semestre_vp = ttk.Combobox(f_filtros_vp, textvariable=self._sv_filtro_semestre_vp, state="readonly", width=12, font=self._fuente_label)
        self.combo_filtro_semestre_vp.pack(side='left', padx=(0, 10))
        self.combo_filtro_semestre_vp['values'] = ["Todos"]

        ttk.Label(f_filtros_vp, text="Grupo:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=(0, 2))
        self._sv_filtro_grupo_vp = tk.StringVar()
        self._sv_filtro_grupo_vp.trace_add("write", lambda *a: self.actualizar_vista_previa())
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

        self.ventana.after(100, self.actualizar_vista_previa)

    # --- UTILIDADES ---

    def _filtrar_tabla_profesores(self):
        texto = self.sv_busca_prof_tabla.get().strip().lower()
        for item in self.tabla_profesores.get_children():
            self.tabla_profesores.delete(item)
        if not texto:
            self._poblar_tabla_profesores(self._lista_completa_profesores)
        else:
            filtrados = [p for p in self._lista_completa_profesores if texto in p[1].lower() or texto in p[2].lower()]
            self._poblar_tabla_profesores(filtrados)

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

    def _on_filtro_semestre_vp(self):
        sel = self._sv_filtro_semestre_vp.get()
        grupos = ["Todos"]
        if sel and sel != "Todos" and ' - ' in sel:
            try:
                sid = sel.split(' - ')[0].strip()
                grupos_sem = self.grupos_por_semestre.get(sid, [])
                if grupos_sem:
                    grupos.extend(grupos_sem)
            except (ValueError, IndexError):
                pass
        self.combo_filtro_grupo_vp['values'] = grupos
        self._sv_filtro_grupo_vp.set("Todos")
        self.actualizar_vista_previa()

    def _materias_filtradas_actual(self):
        semestre_txt = self.combo_filtro_semestre.get()
        periodo_txt = self.combo_periodos.get()
        materias = self.lista_maestra_materias
        if periodo_txt:
            semestres_validos = [1, 3, 5, 7, 9] if periodo_txt == "A" else [2, 4, 6, 8, 10]
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
        grupos_filtrados = self._grupos_filtrados_actual()
        for pd in self._periodos_asignacion:
            for cm, cg in pd.get("filas_asignacion", []):
                cm['values'] = filtradas
                if cm.get() and cm.get() not in filtradas:
                    cm.set('')
                cg['values'] = grupos_filtrados
                if cg.get() and cg.get() not in grupos_filtrados:
                    cg.set('')

    def _grupos_filtrados_actual(self):
        semestre_txt = self.combo_filtro_semestre.get()
        if semestre_txt and semestre_txt != "Todos" and ' - ' in semestre_txt:
            try:
                sid = semestre_txt.split(' - ')[0].strip()
                return self.grupos_por_semestre.get(sid, [])
            except (ValueError, IndexError):
                pass
        todos = []
        for sem in sorted(self.grupos_por_semestre.keys(), key=int):
            for g in self.grupos_por_semestre[sem]:
                if g not in todos:
                    todos.append(g)
        return todos

    MAPA_DIAS = {"0": "Lunes", "1": "Martes", "2": "Miércoles", "3": "Jueves", "4": "Viernes", "5": "Sábado"}
    NOMBRES_DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

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
                if not filas:
                    self._agregar_periodo_vacio(horas_pre=(disponibles, asignadas), grupos_pre=todos_grupos, materias_pre=mat_ids)
        except Exception as e:
            print(f"Error cargando disponibilidad: {e}")
            self._agregar_periodo_vacio()

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
        for wd in self._periodos_asignacion:
            baseline_minutos += wd.get('db_minutos', 0)
            entry_i = wd.get('entry_i')
            entry_f = wd.get('entry_f')
            vars_dias = wd.get('vars_dias', {})
            if entry_i and entry_f:
                hi_str = entry_i.get().strip()
                hf_str = entry_f.get().strip()
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
        if not self._profesor_id_seleccionado:
            return
        for wd in self._periodos_asignacion:
            for cm, cg in wd['filas_asignacion']:
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
        entry_i = ttk.Entry(f_h, width=10, font=self._fuente_label)
        entry_i.pack(side='left', padx=2)
        ttk.Label(f_h, text="-", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=2)
        entry_f = ttk.Entry(f_h, width=10, font=self._fuente_label)
        entry_f.pack(side='left', padx=2)

        if datos:
            entry_i.insert(0, datos.get('hora_i', ''))
            entry_f.insert(0, datos.get('hora_f', ''))

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

        btn_agregar_mat = ttk.Button(f_asig, text="+ Agregar Materia", command=lambda: None)
        btn_agregar_mat.grid(row=1, column=0, columnspan=4, pady=2)

        def agregar_fila_asignacion(mat_inicial=None, grp_inicial=None):
            row = len(filas_asignacion)
            ttk.Label(f_asig, text="Materia:", background='#0A0F1E', foreground='white', font=self._fuente_label).grid(row=row, column=0, sticky='w', padx=2)
            if mat_inicial and mat_inicial not in mat_ids:
                mat_ids.append(mat_inicial)
            cm = ttk.Combobox(f_asig, values=mat_ids, width=28, font=self._fuente_label, state='readonly')
            cm.grid(row=row, column=1, padx=4, pady=1)
            cm.bind("<<ComboboxSelected>>", lambda e, c=cm, lb=label_restante: self._actualizar_horas_periodo(c, lb))

            ttk.Label(f_asig, text="Grupo:", background='#0A0F1E', foreground='white', font=self._fuente_label).grid(row=row, column=2, sticky='w', padx=(10, 2))
            cg = ttk.Combobox(f_asig, values=todos_grupos, width=10, font=self._fuente_label, state='normal')
            cg.grid(row=row, column=3, padx=4, pady=1)

            if mat_inicial:
                cm.set(mat_inicial)
            if grp_inicial:
                cg.set(grp_inicial)

            filas_asignacion.append((cm, cg))
            btn_agregar_mat.grid(row=len(filas_asignacion), column=0, columnspan=4, pady=2)

        btn_agregar_mat.config(command=agregar_fila_asignacion)

        asignaciones_existentes = datos.get('asignaciones', []) if datos else []
        if asignaciones_existentes:
            for mat_id, grp_id in asignaciones_existentes:
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
                disponibles2, asignadas2 = self._calcular_horas_con_ui(self._profesor_id_seleccionado)
                restantes2 = max(0, disponibles2 - asignadas2)
                if hrs_mat > restantes2:
                    if not messagebox.askyesno(
                        "Sobrecarga de horas",
                        f"'{materia_txt}' requiere {hrs_mat:.1f}h pero solo restan {restantes2:.1f}h.\n¿Asignar de todas formas?"
                    ):
                        continue

                self._guardar_disponibilidad_periodo(self._profesor_id_seleccionado, hora_i, hora_f, dias_sel, modalidad_var.get(), wd.get('db_hora_i', ''), wd.get('db_hora_f', ''))
                self._asignar_periodo(self._profesor_id_seleccionado, mat_id, grupo_id, periodo or "A", hora_i, hora_f, modalidad_var.get())
                alguna_guardada = True

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
            "btn_agregar_mat": btn_agregar_mat,
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
                mapa_dias = {"Lunes": "0", "Martes": "1", "Miércoles": "2", "Miercoles": "2", "Jueves": "3", "Viernes": "4", "Sábado": "5", "Sabado": "5", "Domingo": "6"}
                for dia in dias_sel:
                    dia_num = mapa_dias.get(dia, dia)
                    cur.execute(
                        "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin, modalidad) VALUES (%s, %s, %s, %s, %s)",
                        (profesor_id, dia_num, hora_i, hora_f, modalidad)
                    )
        except Exception as e:
            print(f"Error guardando disponibilidad: {e}")

    def _actualizar_horas_periodo(self, combo_mat, label_restante):
        materia_txt = combo_mat.get()
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
                    generador = GeneradorHorarios(conexion)
                    generador.separacion_online_activa = False
                    resultado = generador.ejecutar(modo=modo_seleccionado)
                    if isinstance(resultado, tuple):
                        cantidad, alertas = resultado
                    else:
                        cantidad = resultado
                        alertas = []
                    result_queue.put(("ok", cantidad, alertas))
                finally:
                    conexion.close()
            except Exception as e:
                result_queue.put(("error", str(e)))

            def procesar_resultado():
                self._en_operacion = False
                loading.destroy()
                try:
                    tipo, *datos = result_queue.get_nowait()
                except queue.Empty:
                    messagebox.showerror("Error", "No se recibió respuesta del proceso.")
                    return

                if tipo == "error":
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

                self.notebook.select(self.pes1)
                self._cargar_tensor_diferido()

            self.ventana.after(0, procesar_resultado)

        hilo = threading.Thread(target=tarea, daemon=True)
        hilo.start()

    def cargar_grupos_por_semestre(self, semestre_id, materia_id=None):
        semestre_id = str(semestre_id)
        grupos_base = self.grupos_por_semestre.get(semestre_id, [])
        grupos_filtrados = grupos_base.copy()

        if materia_id:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    if self.asignacion_seleccionada_id:
                        cur.execute("SELECT grupo_id FROM asignaciones WHERE materia_id = %s AND asignacion_id != %s", (materia_id, self.asignacion_seleccionada_id))
                    else:
                        cur.execute("SELECT grupo_id FROM asignaciones WHERE materia_id = %s", (materia_id,))
                    
                    grupos_ocupados = [row[0] for row in cur.fetchall()]
                    grupos_filtrados = [g for g in grupos_base if g not in grupos_ocupados]
                except mysql.connector.Error as err:
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

                self.actualizar_vista_previa()

                lista_sem = list(self.semestres_map.values())
                self.combo_filtro_semestre['values'] = lista_sem
                if lista_sem and not self.combo_filtro_semestre.get():
                    self.combo_filtro_semestre.set(lista_sem[0])

                if hasattr(self, 'combo_filtro_semestre_vp'):
                    self.combo_filtro_semestre_vp['values'] = ["Todos"] + lista_sem
            except mysql.connector.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error cargando combos: {err}")

    def _poblar_tabla_profesores(self, lista_prof):
        if not hasattr(self, 'tabla_profesores'):
            return

        disp_por_profesor = {}
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                cur.execute("SELECT profesor_id, dia, hora_inicio, hora_fin FROM profesor_disponibilidad ORDER BY profesor_id")
                filas = cur.fetchall()
                dias = {"0": "Lu", "1": "Ma", "2": "Mi", "3": "Ju", "4": "Vi", "5": "Sa", "6": "Do"}
                for pid, d, hi, hf in filas:
                    if pid not in disp_por_profesor:
                        disp_por_profesor[pid] = []
                    dia_str = dias.get(str(d), f"D{d}")
                    disp_por_profesor[pid].append(f"{dia_str} {hi}-{hf}")
        except Exception:
            pass

        for item in self.tabla_profesores.get_children():
            self.tabla_profesores.delete(item)
        for pid, no_cuenta, nombre in lista_prof:
            partes = disp_por_profesor.get(pid, [])
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
        self.tabla_alertas = ttk.Treeview(f_contenido, columns=cols, show='headings', height=12)
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

        self.texto_detalle_alerta = tk.Text(f_contenido, height=14, wrap='word',
                                            font=("Consolas", 10),
                                            bg='#1a1a1a', fg='#e0e0e0',
                                            relief='flat', bd=2)
        self.texto_detalle_alerta.pack(fill='both', expand=True)

        ttk.Button(f_superior, text="Limpiar Alertas",
                   command=self._limpiar_alertas).pack(pady=5)

    def _mostrar_alertas_en_tabla(self):
        if not hasattr(self, 'tabla_alertas'):
            return
        for item in self.tabla_alertas.get_children():
            self.tabla_alertas.delete(item)
        self.texto_detalle_alerta.delete('1.0', tk.END)
        for a in self._ultimas_alertas:
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
        texto = f"MATERIA: {a.get('materia', '?')}  |  GRUPO: {a.get('grupo', '?')}\n"
        texto += f"PROFESOR: {a.get('profesor', '?')}  |  ID: {a.get('profesor_id', '?')}\n"
        texto += "-"*70 + "\n"
        texto += "CAUSAS:\n"
        for i, c in enumerate(a.get('causas', []), 1):
            texto += f"  {i}. {c}\n"
        texto += "\nSUGERENCIAS:\n"
        for i, s in enumerate(a.get('sugerencias', []), 1):
            texto += f"  {i}. {s}\n"
        extras = a.get('detalles_extra', [])
        if extras:
            texto += "\nDETALLES TÉCNICOS:\n"
            for e in extras:
                texto += f"  {e}\n"
        self.texto_detalle_alerta.insert('1.0', texto)
        self.texto_detalle_alerta.see('1.0')

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
        semestres_validos = [1, 3, 5, 7, 9] if periodo == "A" else [2, 4, 6, 8, 10]
        self._semestres_filtrados = semestres_validos
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
                    return grupo_id
                if nivel is None:
                    nivel = 0
                cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, %s)", (grupo_id, nivel))
                self.cargar_combos_bd() 
                messagebox.showinfo("Éxito", f"Grupo '{grupo_id}' creado.")
                return grupo_id
            except mysql.connector.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error gestionando grupo: {err}")
                return None

    def _asignar_periodo(self, profesor_id, materia_id, grupo_id, periodo, hora_i, hora_f, modalidad="Presencial"):
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
                            "UPDATE asignaciones SET periodo=%s, hora_inicio=%s, hora_fin=%s WHERE asignacion_id=%s",
                            (periodo, hora_i, hora_f, existente[0])
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
                                "UPDATE asignaciones SET profesor_id=%s, hora_inicio=%s, hora_fin=%s WHERE asignacion_id=%s",
                                (profesor_id, hora_i, hora_f, old_asig_id)
                            )
                            conn.commit()
                            messagebox.showinfo("Sustituido", "Asignación transferida al nuevo profesor")
                            exito = True
                        else:
                            conn.rollback()
                            return False
                    else:
                        cur.execute(
                            "INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, estado, periodo, hora_inicio, hora_fin, modalidad) VALUES (%s, %s, %s, 'pendiente', %s, %s, %s, %s)",
                            (profesor_id, materia_id, grupo_id, periodo, hora_i, hora_f, modalidad)
                        )
                        conn.commit()
                        messagebox.showinfo("Éxito", f"Asignación guardada para el periodo {periodo}")
                        exito = True
            except mysql.connector.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error al asignar: {err}")
                return False

        if exito:
            self.actualizar_vista_previa()
            return True
        return False

    def actualizar_vista_previa(self, event=None, mostrar_todo=False):
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
            for item in tabla.get_children():
                tabla.delete(item)

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

            except mysql.connector.Error as err:
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