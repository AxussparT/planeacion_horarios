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
from src.motor_horarios import GeneradorHorarios
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
        
        self.asignacion_seleccionada_id = None
        self.entidades_filtradas = []
        self._tensor_cargado = False
        self._last_width = 0
        self._last_height = 0
        self._scale_factor = 1.0
        self._en_operacion = False
        
        self._fuente_titulo = font.Font(family="Roboto", size=18, weight="bold")
        self._fuente_sub = font.Font(family="Roboto", size=12)
        self._fuente_label = font.Font(family="Roboto", size=10)
        self._fuente_btn = font.Font(family="Roboto", size=10, weight="bold")
        
        self.grupos_por_semestre = self._cargar_grupos_desde_bd()

        if not self._is_embedded:
            self.ventana.protocol("WM_DELETE_WINDOW", self._confirmar_cierre)
        self.construir_interfaz()
        self.ventana.after(100, self._post_init)
        if not self._is_embedded:
            self.ventana.wait_window()

    def _cargar_grupos_desde_bd(self):
        grupos = {}
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return self._grupos_fallback()
                cur, conn = ctx
                cur.execute("SELECT grupo_id FROM grupos ORDER BY grupo_id")
                filas = cur.fetchall()
                for row in filas:
                    gid = row[0]
                    import re
                    m = re.match(r'S(\d)', str(gid))
                    sem = m.group(1) if m else "0"
                    if sem not in grupos:
                        grupos[sem] = []
                    grupos[sem].append(gid)
        except Exception as e:
            print(f"Error cargando grupos desde BD: {e}")
        return grupos if grupos else self._grupos_fallback()
    
    def _grupos_fallback(self):
        return {
            "1": ["S1A", "S1B", "S1C", "S1D", "S1E", "S1F"],
            "2": ["S2A", "S2B", "S2C", "S2D", "S2E", "S2F"],
            "3": ["S3A", "S3B", "S3C", "S3D", "S3E"],
            "4": ["S4A", "S4B", "S4C", "S4D", "S4E"],
            "5": ["S5A", "S5B", "S5C", "S5D", "S5E"],
            "6": ["S6A", "S6B", "S6C", "S6D"],
            "7": ["S7A", "S7B", "S7C", "S7D"],
            "8": ["S8A", "S8B", "S8C"],
            "9": ["S9A", "S9B", "S9C"]
        }

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
        
        self.notebook.add(self.pes0, text='Gestionar')
        self.notebook.add(self.pes1, text='Ver Horarios')

        self.Construccion_Ver_Horarios(self.pes1)

        frame_contenedor = ttk.Frame(self.pes0, style='blue.TFrame')
        frame_contenedor.pack(fill='x', pady=10)

        self.frame_izq = ttk.Frame(frame_contenedor, style='blue.TFrame')
        self.frame_izq.pack(side='left', padx=10, anchor='n')
        
        ttk.Label(self.frame_izq, text="Gestión", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(pady=3)
        ttk.Label(self.frame_izq, text="Seleccione el periodo", background='#0A0F1E', foreground='white', font=self._fuente_label).pack()
        
        self.combo_periodos = ttk.Combobox(self.frame_izq, width=30, font=self._fuente_label, state='readonly')
        self.combo_periodos['values'] = ("A (Septiembre-Octubre)", "B (Febrero - Junio)")
        self.combo_periodos.pack(pady=2, padx=10)
        self.combo_periodos.bind("<<ComboboxSelected>>", self.filtrar_materias_por_periodo)

        self.frame_der = ttk.Frame(frame_contenedor, style='blue.TFrame')
        self.frame_der.pack(side='left', padx=10, anchor='n', fill='both', expand=True)
        ttk.Label(self.frame_der, text="Vista Previa", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(pady=3)

        f_filtro_estado = ttk.Frame(self.frame_der, style='blue.TFrame')
        f_filtro_estado.pack(fill='x', pady=2)
        ttk.Label(f_filtro_estado, text="Filtrar por Estado:", background='#0A0F1E', foreground='white', font=self._fuente_label).pack(side='left', padx=5)
        self.combo_estado_filtro = ttk.Combobox(f_filtro_estado, values=["Todos", "pendiente", "asignado"], state="readonly", width=15, font=self._fuente_label)
        self.combo_estado_filtro.set("Todos")
        self.combo_estado_filtro.pack(side='left')
        self.combo_estado_filtro.bind("<<ComboboxSelected>>", lambda e: self.actualizar_vista_previa())

        frame_contenedor2 = ttk.Frame(self.frame_izq, style='blue.TFrame')
        frame_contenedor2.pack(fill='x', pady=10)

        self.frame_izq_pf = ttk.Frame(frame_contenedor2, style='blue.TFrame')
        self.frame_izq_pf.pack(side='left', padx=10, anchor='n')
        ttk.Label(self.frame_izq_pf, text="Profesor", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(pady=3)
        
        self.combo_profesores = ttk.Combobox(self.frame_izq_pf, width=30, font=self._fuente_label, state='readonly')
        self.combo_profesores.pack(pady=3)
        self.combo_profesores.bind("<<ComboboxSelected>>", lambda e: self.actualizar_vista_previa())
        
        ttk.Button(self.frame_izq_pf, text="Asignar Manualmente", command=self.asignar_profesor_materia).pack(pady=2)

        self.frame_der_pf = ttk.Frame(frame_contenedor2, style='blue.TFrame')
        self.frame_der_pf.pack(side='left', padx=10, anchor='n')
        ttk.Label(self.frame_der_pf, text="Materia", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(pady=3)
        
        self.combo_materias = ttk.Combobox(self.frame_der_pf, width=30, font=self._fuente_label, state='readonly')
        self.combo_materias.pack(pady=3)
        self.combo_materias.bind("<<ComboboxSelected>>", lambda e: (self.mostrar_semestre_de_materia(e), self.actualizar_vista_previa()))

        frame_contenedor3 = ttk.Frame(self.frame_izq, style='blue.TFrame')
        frame_contenedor3.pack(fill='x', pady=10)

        self.frame_izq_gp = ttk.Frame(frame_contenedor3, style='blue.TFrame')
        self.frame_izq_gp.pack(side='left', padx=10, anchor='n')
        ttk.Label(self.frame_izq_gp, text="Grupo", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(pady=3)
        
        self.combo_grupos = ttk.Combobox(self.frame_izq_gp, width=20, font=self._fuente_label, state='normal')
        self.combo_grupos.pack(pady=3)
        
        boton_asignar = ttk.Button(self.frame_izq_gp, text="Empezar asignación automática", command=self.iniciar_asignacion_automatica) 
        boton_asignar.pack(pady=2)
        
        boton_formatear_asignaciones=ttk.Button(self.frame_izq_gp,text="Borrar asignaciones almacenadas", command=self.formatear_asignaciones)
        boton_formatear_asignaciones.pack(pady=2)
        
        boton_borrar_asignacion=ttk.Button(self.frame_izq_gp,text="Borrar asignacion", command=self.borrar_asignacion_seleccionada)
        boton_borrar_asignacion.pack(pady=2)

        self.frame_der_gp = ttk.Frame(frame_contenedor3, style='blue.TFrame')
        self.frame_der_gp.pack(side='left', padx=10, anchor='n')
        ttk.Label(self.frame_der_gp, text="Semestre", background='#0A0F1E', foreground='white', font=self._fuente_sub).pack(pady=3)
        
        self.combo_semestre = ttk.Combobox(self.frame_der_gp, width=30, font=self._fuente_sub, state='readonly')
        self.combo_semestre.pack(pady=3)
        self.combo_semestre.bind("<<ComboboxSelected>>", self.filtrar_materias_semestre_seleccionado)

        self.frame_tablas = ttk.Frame(self.frame_der, style='blue.TFrame')
        self.frame_tablas.pack(padx=10, anchor='n', fill='both', expand=True)

        columnas = ('Profesor', 'materia', 'Estado')
        self.tabla_profesores = ttk.Treeview(self.frame_tablas, columns=columnas, show='headings', height=20)
        self.tabla_profesores.column('Profesor', anchor='w', width=180)
        self.tabla_profesores.column('materia', anchor='w', width=200)
        self.tabla_profesores.column('Estado', anchor='center', width=80)
        
        self.tabla_profesores.heading('Profesor', text='Profesor')
        self.tabla_profesores.heading('materia', text='Materia (Grupo)')
        self.tabla_profesores.heading('Estado', text='Estado')

        self.tabla_profesores.bind("<<TreeviewSelect>>", self.cargar_asignacion_seleccionada)

        sb_v = ttk.Scrollbar(self.frame_tablas, orient='vertical', command=self.tabla_profesores.yview)
        self.tabla_profesores.configure(yscroll=sb_v.set)
        sb_v.pack(side='right', fill='y')

        sb_h = ttk.Scrollbar(self.frame_tablas, orient='horizontal', command=self.tabla_profesores.xview)
        self.tabla_profesores.configure(xscroll=sb_h.set)
        sb_h.pack(side='bottom', fill='x')

        self.tabla_profesores.pack(fill='both', expand=True)
        
        boton_limpiar = ttk.Button(self.frame_der, text="Ver Todas las Asignaciones / Limpiar Selección", command=self.limpiar_filtros)
        boton_limpiar.pack(pady=10, side='bottom', fill='x', padx=20)

    # --- UTILIDADES ---
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
                    cur.execute("UPDATE asignaciones SET estado = 'pendiente' WHERE asignacion_id = %s", (self.asignacion_seleccionada_id,))
                    messagebox.showinfo("Éxito", "Asignación liberada correctamente.\nEl espacio del salón queda disponible para nuevas asignaciones.")
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
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error", f"Ocurrió un error al formatear: {e}")

    def cargar_asignacion_seleccionada(self, event):
        item = self.tabla_profesores.focus()
        if not item: return
        
        v = self.tabla_profesores.item(item, "values")
        if len(v) < 4: return
        
        self.asignacion_seleccionada_id = v[3] 
        p_str = v[0] 
        m_g_str = v[1] 
        
        g_str = ""
        m_str = m_g_str
        if "(" in m_g_str and m_g_str.endswith(")"):
            m_str = m_g_str[:m_g_str.rfind("(")].strip()
            g_str = m_g_str[m_g_str.rfind("(")+1:-1].strip()

        for val in self.combo_profesores['values']:
            if val.startswith(p_str.split(" - ")[0]):
                self.combo_profesores.set(val)
                break
                
        for val in self.combo_materias['values']:
            if val.startswith(m_str.split(" - ")[0]):
                self.combo_materias.set(val)
                break
        
        self.mostrar_semestre_de_materia()
        self.combo_grupos.set(g_str)

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
                if alertas:
                    partes = []
                    for a in alertas[:6]:
                        partes.append(f"▸ {a}\n")
                    if len(alertas) > 6:
                        partes.append(f"... y {len(alertas) - 6} asignaciones más.\n")
                    mensaje = (
                        f"Se asignaron {cantidad} horarios.\n\n"
                        f"Hubo conflictos con {len(alertas)} materia(s):\n\n"
                        + "".join(partes)
                    )
                    messagebox.showwarning("Asignación con Conflictos", mensaje)
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

        self.combo_grupos['values'] = grupos_filtrados
        if grupos_filtrados and not self.combo_grupos.get():
            self.combo_grupos.set(grupos_filtrados[0])

    def cargar_combos_bd(self):
        with obtener_cursor() as ctx:
            if ctx is None:
                return
            cur, conn = ctx
            try:
                cur.execute("SELECT profesor_id, nombre FROM profesores ORDER BY nombre")
                profesores = cur.fetchall()
                self.profesores_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in profesores}
                lista_prof = list(self.profesores_map.values())
                self.combo_profesores['values'] = lista_prof
                if lista_prof: self.combo_profesores.set(lista_prof[0])

                cur.execute("SELECT id_semestre, nombre FROM semestres ORDER BY id_semestre")
                semestres = cur.fetchall()
                self.semestres_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in semestres}
                self.lista_maestra_semestres = [{"texto": f"{row[0]} - {row[1]}", "id": int(row[0])} for row in semestres]
                lista_sem = list(self.semestres_map.values())
                self.combo_semestre['values'] = lista_sem
                if lista_sem: self.combo_semestre.set(lista_sem[0])

                cur.execute("SELECT materia_id, nombre, semestre_id FROM materias ORDER BY semestre_id")
                materias = cur.fetchall()
                self.materias_map = {}
                self.lista_maestra_materias = []
                lista_mat = []
                
                for row in materias:
                    m_id, nombre, s_id = row
                    texto = f"{m_id} - {nombre}"
                    self.materias_map[str(m_id)] = s_id
                    sem_val = int(s_id) if s_id is not None else 0
                    self.lista_maestra_materias.append({"texto": texto, "semestre": sem_val})
                    lista_mat.append(texto)

                self.combo_materias['values'] = lista_mat
                if lista_mat:
                    self.combo_materias.set(lista_mat[0])
                    self.mostrar_semestre_de_materia()

                self.actualizar_vista_previa()
            except mysql.connector.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error cargando combos: {err}")

    def limpiar_filtros(self):
        self.asignacion_seleccionada_id = None 
        self.actualizar_vista_previa(mostrar_todo=True)

    def filtrar_materias_por_periodo(self, event=None):
        periodo = self.combo_periodos.get()
        if not periodo: return
        semestres_validos = [1, 3, 5, 7, 9] if "A (" in periodo else [2, 4, 6, 8, 10]
        mat_filtradas = [m["texto"] for m in self.lista_maestra_materias if m["semestre"] in semestres_validos]
        self.combo_materias['values'] = mat_filtradas
        sem_filtrados = [s["texto"] for s in self.lista_maestra_semestres if s["id"] in semestres_validos]
        self.combo_semestre['values'] = sem_filtrados

        self.combo_materias.set(mat_filtradas[0] if mat_filtradas else 'sin materias para este periodo')
        self.combo_semestre.set(sem_filtrados[0] if sem_filtrados else '')
        self.combo_grupos.set('')
        if mat_filtradas: self.mostrar_semestre_de_materia()

    def filtrar_materias_semestre_seleccionado(self, event=None):
        id_sem = self._obtener_id_valido(self.combo_semestre.get())
        if not id_sem: return
        try:
            id_sem = int(id_sem)
            mat_filtradas = [m["texto"] for m in self.lista_maestra_materias if m["semestre"] == id_sem]
            self.combo_materias['values'] = mat_filtradas
            self.combo_materias.set(mat_filtradas[0] if mat_filtradas else "sin materias cargadas")
            materia_id = self._obtener_id_valido(self.combo_materias.get())
            self.cargar_grupos_por_semestre(id_sem, materia_id)
        except ValueError:
            pass

    def mostrar_semestre_de_materia(self, event=None):
        materia_id = self._obtener_id_valido(self.combo_materias.get())
        if not materia_id:
            self.combo_semestre.set("")
            self.combo_grupos.set("")
            return
        semestre_id = self.materias_map.get(materia_id)
        if semestre_id:
            texto_sem = self.semestres_map.get(str(semestre_id))
            self.combo_semestre.set(texto_sem if texto_sem else "Desconocido")
            self.cargar_grupos_por_semestre(semestre_id, materia_id)
        else:
            self.combo_semestre.set("No Asignado")
            self.combo_grupos.set("")

    def obtener_o_crear_grupo(self, grupo_texto):
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
                    return grupo_id
                cur.execute("INSERT INTO grupos (grupo_id, nombre) VALUES (%s, %s)", (grupo_id, grupo_id))
                self.cargar_combos_bd() 
                messagebox.showinfo("Éxito", f"Grupo '{grupo_id}' creado.")
                return grupo_id
            except mysql.connector.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error gestionando grupo: {err}")
                return None

    def asignar_profesor_materia(self):
        prof_id = self._obtener_id_valido(self.combo_profesores.get())
        mat_id = self._obtener_id_valido(self.combo_materias.get())
        if not prof_id or not mat_id:
            messagebox.showerror("Error", "Seleccione Profesor y Materia válidos")
            return
            
        grupo_id = self.obtener_o_crear_grupo(self.combo_grupos.get())
        if not grupo_id:
            return
        
        with obtener_cursor() as ctx:
            if ctx is None:
                return
            cur, conn = ctx
            try:
                if self.asignacion_seleccionada_id:
                    cur.execute("SELECT COUNT(*) FROM asignaciones WHERE profesor_id=%s AND materia_id=%s AND grupo_id=%s AND asignacion_id != %s",
                                (prof_id, mat_id, grupo_id, self.asignacion_seleccionada_id))
                    if cur.fetchone()[0] > 0:
                        messagebox.showwarning("Aviso", "Otra asignación ya utiliza estos mismos datos.")
                        return
                    
                    sql_upd = "UPDATE asignaciones SET profesor_id=%s, materia_id=%s, grupo_id=%s, estado='pendiente' WHERE asignacion_id=%s"
                    cur.execute(sql_upd, (prof_id, mat_id, grupo_id, self.asignacion_seleccionada_id))
                    cur.execute("DELETE FROM horarios WHERE asignacion_id=%s", (self.asignacion_seleccionada_id,))
                    
                    messagebox.showinfo("Éxito", "Asignación modificada correctamente. Su horario anterior fue borrado para ser reasignado.")
                    self.asignacion_seleccionada_id = None 
                else:
                    cur.execute("SELECT COUNT(*) FROM asignaciones WHERE profesor_id=%s AND materia_id=%s AND grupo_id=%s",
                                (prof_id, mat_id, grupo_id))
                    if cur.fetchone()[0] > 0:
                        messagebox.showwarning("Aviso", "Esta asignación ya existe")
                        return
                        
                    sql_ins = "INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, estado) VALUES (%s, %s, %s, 'pendiente')"
                    cur.execute(sql_ins, (prof_id, mat_id, grupo_id))
                    messagebox.showinfo("Éxito", "Asignación nueva guardada correctamente")
                    
                self.actualizar_vista_previa()
            except mysql.connector.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error al guardar asignación: {err}")

    def actualizar_vista_previa(self, event=None, mostrar_todo=False):
        if mostrar_todo:
            prof_id = None
            mat_id = None
            grup_id = None
            estado_filtro = "Todos"
        else:
            prof_id = self._obtener_id_valido(self.combo_profesores.get()) if hasattr(self, 'combo_profesores') else None
            mat_id = self._obtener_id_valido(self.combo_materias.get()) if hasattr(self, 'combo_materias') else None
            grup_id = self._obtener_id_valido(self.combo_grupos.get(), es_grupo=True) if hasattr(self, 'combo_grupos') else None
            estado_filtro = self.combo_estado_filtro.get() if hasattr(self, 'combo_estado_filtro') else "Todos"

        if hasattr(self, 'tabla_profesores'):
            for item in self.tabla_profesores.get_children():
                self.tabla_profesores.delete(item)

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
                        a.grupo_id, IFNULL(g.nombre, 'Sin Grupo'),
                        IFNULL(a.estado, 'pendiente') AS estado
                    FROM asignaciones a
                    LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                    LEFT JOIN materias m ON a.materia_id = m.materia_id
                    LEFT JOIN grupos g ON a.grupo_id = g.grupo_id 
                    WHERE 1=1 
                """
                params = []
                
                if prof_id and not self.asignacion_seleccionada_id:
                    sql += " AND a.profesor_id = %s"
                    params.append(prof_id)
                if mat_id and not self.asignacion_seleccionada_id:
                    sql += " AND a.materia_id = %s"
                    params.append(mat_id)
                if grup_id and not self.asignacion_seleccionada_id:
                    sql += " AND a.grupo_id = %s"
                    params.append(grup_id)
                    
                if estado_filtro != "Todos":
                    sql += " AND a.estado = %s"
                    params.append(estado_filtro)

                sql += " LIMIT 50"
                cur.execute(sql, params)
                resultados = cur.fetchall()

                if resultados and hasattr(self, 'tabla_profesores'):
                    for row in resultados:
                        asig_id = row[0]
                        p_str = f"{row[1]} - {row[2]}"
                        m_str = f"{row[3]} - {row[4]} ({row[5]})"
                        estado_str = str(row[6]).upper()
                        self.tabla_profesores.insert('', 'end', values=(p_str, m_str, estado_str, asig_id))
                elif hasattr(self, 'tabla_profesores'):
                    self.tabla_profesores.insert('', 'end', values=("(No hay resultados)", "", "", ""))

            except mysql.connector.Error as err:
                if hasattr(self, 'tabla_profesores'):
                    self.tabla_profesores.insert('', 'end', values=(f"Error BD: {err}", "", "", ""))

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
                        lineas_ajustadas.append(textwrap.fill(linea, width=16))
                        
                    texto_final = '\n'.join(lineas_ajustadas)
                    
                    self.ax.text(x_materia + col_widths[col_idx]/2, y_pos_materia + h_bloque/2, texto_final,
                               ha='center', va='center', fontsize=6.5, fontweight='bold',
                               color='black', zorder=4)
                    
                r_ptr += 1
            x_materia += col_widths[col_idx]

        self.fig.tight_layout(pad=0)
        self.canvas_horario.draw()