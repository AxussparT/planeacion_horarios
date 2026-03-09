import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import mysql.connector
import datetime
import textwrap

from src.conexion import get_conexion
from src.motor_horarios import GeneradorHorarios
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages
import src.clases.memoria_Horario_Grafico as mem_grafico

class VentanaGestion:
    def __init__(self, master_window):
        # 1. Configuración inicial de la ventana
        self.ventana = tk.Toplevel(master_window)
        self.ventana.title("Ventana de Gestión")
        self.ventana.state('zoomed')
        self.ventana.grab_set()
        self.ventana.transient(master_window)

        # 2. Estilos
        estilo = ttk.Style()
        estilo.configure('blue.TFrame', background='#0A0F1E')

        # 3. Inicialización de variables de datos
        self.profesores_map = {}
        self.materias_map = {}
        self.semestres_map = {}
        self.lista_maestra_semestres = []
        self.lista_maestra_materias = []
        
        self.grupos_por_semestre = {
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

        # MANDATORIO: Llenar el tensor con datos reales antes de crear los widgets
        try:
            mem_grafico.inicializar_y_llenar_tensor("Salón")
        except Exception as e:
            print(f"Error al precargar el tensor: {e}")

        # 4. Construcción de la Interfaz Gráfica
        self.construir_interfaz()

        # 5. Carga de datos iniciales
        self.cargar_combos_bd()
        self.ventana.wait_window()

    def construir_interfaz(self):
        # --- Fondo ---
        try:
            image = Image.open(r"assets/fondo.png")
            self.original_image = image
            self.background_label = tk.Label(self.ventana)
            self.background_label.place(x=0, y=0, relwidth=1, relheight=1)
            self.ventana.bind("<Configure>", self.redimensionar_fondo)
        except Exception as e:
            print(f"Error al cargar fondo: {e}")
            self.ventana.config(bg="grey")

        # --- Frame Principal ---
        self.frame_principal = ttk.Frame(self.ventana, style='blue.TFrame')
        self.frame_principal.place(relx=0.5, rely=0.5, anchor='center', width=1100, height=700)

        ttk.Button(self.frame_principal, text="Cerrar", command=self.ventana.destroy).pack(pady=2)

        # --- Notebook (Pestañas) ---
        self.notebook = ttk.Notebook(self.frame_principal)
        self.notebook.pack(fill='both', expand='yes')
        
        self.pes0 = ttk.Frame(self.notebook, style='blue.TFrame')
        self.pes1 = ttk.Frame(self.notebook, style='blue.TFrame')
        
        self.notebook.add(self.pes0, text='Gestionar')
        self.notebook.add(self.pes1, text='Ver Horarios')

        self.Construccion_Ver_Horarios(self.pes1)

        # --- Contenedor Superior (Gestión) ---
        frame_contenedor = ttk.Frame(self.pes0, style='blue.TFrame')
        frame_contenedor.pack(fill='x', pady=10)

        # Lado Izquierdo (Periodo)
        self.frame_izq = ttk.Frame(frame_contenedor, style='blue.TFrame')
        self.frame_izq.pack(side='left', padx=10, anchor='n')
        
        ttk.Label(self.frame_izq, text="Gestión", background='#0A0F1E', foreground='white', font=("Roboto", 10)).pack(pady=3)
        ttk.Label(self.frame_izq, text="Seleccione el periodo", background='#0A0F1E', foreground='white', font=("Roboto", 10)).pack()
        
        self.combo_periodos = ttk.Combobox(self.frame_izq, width=30, font=("Roboto", 9), state='readonly')
        self.combo_periodos['values'] = ("A (Septiembre-Octubre)", "B (Febrero - Junio)")
        self.combo_periodos.pack(pady=2, padx=10)
        self.combo_periodos.bind("<<ComboboxSelected>>", self.filtrar_materias_por_periodo)

        # Lado Derecho (Título Vista Previa)
        self.frame_der = ttk.Frame(frame_contenedor, style='blue.TFrame')
        self.frame_der.pack(side='left', padx=10, anchor='n')
        ttk.Label(self.frame_der, text="Vista Previa", background='#0A0F1E', foreground='white', font=("Roboto", 10)).pack(pady=3)

        # --- Contenedor Medio (Profesor y Materia) ---
        frame_contenedor2 = ttk.Frame(self.frame_izq, style='blue.TFrame')
        frame_contenedor2.pack(fill='x', pady=10)

        # Profesor
        self.frame_izq_pf = ttk.Frame(frame_contenedor2, style='blue.TFrame')
        self.frame_izq_pf.pack(side='left', padx=10, anchor='n')
        ttk.Label(self.frame_izq_pf, text="Profesor", background='#0A0F1E', foreground='white', font=("Roboto", 10)).pack(pady=3)
        
        self.combo_profesores = ttk.Combobox(self.frame_izq_pf, width=30, font=("Roboto", 9), state='readonly')
        self.combo_profesores.pack(pady=3)
        self.combo_profesores.bind("<<ComboboxSelected>>", self.actualizar_vista_previa)
        
        ttk.Button(self.frame_izq_pf, text="Asignar Manualmente", command=self.asignar_profesor_materia).pack(pady=2)

        # Materia
        self.frame_der_pf = ttk.Frame(frame_contenedor2, style='blue.TFrame')
        self.frame_der_pf.pack(side='left', padx=10, anchor='n')
        ttk.Label(self.frame_der_pf, text="Materia", background='#0A0F1E', foreground='white', font=("Roboto", 10)).pack(pady=3)
        
        self.combo_materias = ttk.Combobox(self.frame_der_pf, width=30, font=("Roboto", 9), state='readonly')
        self.combo_materias.pack(pady=3)
        self.combo_materias.bind("<<ComboboxSelected>>", lambda e: (self.mostrar_semestre_de_materia(e), self.actualizar_vista_previa(e)))

        # --- Contenedor Inferior (Grupo y Semestre) ---
        frame_contenedor3 = ttk.Frame(self.frame_izq, style='blue.TFrame')
        frame_contenedor3.pack(fill='x', pady=10)

        # Grupo
        self.frame_izq_gp = ttk.Frame(frame_contenedor3, style='blue.TFrame')
        self.frame_izq_gp.pack(side='left', padx=10, anchor='n')
        ttk.Label(self.frame_izq_gp, text="Grupo", background='#0A0F1E', foreground='white', font=("Roboto", 10)).pack(pady=3)
        
        self.combo_grupos = ttk.Combobox(self.frame_izq_gp, width=20, font=("Roboto", 9), state='normal')
        self.combo_grupos.pack(pady=3)
        
        boton_asignar = ttk.Button(self.frame_izq_gp, text="Empezar asignación automática", command=self.iniciar_asignacion_automatica) 
        boton_asignar.pack(pady=2)

        # Semestre
        self.frame_der_gp = ttk.Frame(frame_contenedor3, style='blue.TFrame')
        self.frame_der_gp.pack(side='left', padx=10, anchor='n')
        ttk.Label(self.frame_der_gp, text="Semestre", background='#0A0F1E', foreground='white', font=("Roboto", 10)).pack(pady=3)
        
        self.combo_semestre = ttk.Combobox(self.frame_der_gp, width=30, font=("Roboto", 10), state='readonly')
        self.combo_semestre.pack(pady=3)
        self.combo_semestre.bind("<<ComboboxSelected>>", self.filtrar_materias_semestre_seleccionado)

        # --- Tabla Vista Previa ---
        self.frame_tablas = ttk.Frame(self.frame_der, style='blue.TFrame')
        self.frame_tablas.pack(padx=10, anchor='n', fill='both', expand=True)

        columnas = ('Profesor', 'materia')
        self.tabla_profesores = ttk.Treeview(self.frame_tablas, columns=columnas, show='headings', height=20)
        self.tabla_profesores.column('Profesor', anchor='w', width=200)
        self.tabla_profesores.column('materia', anchor='w', width=250)
        
        self.tabla_profesores.heading('Profesor', text='Profesor')
        self.tabla_profesores.heading('materia', text='Materia (Grupo)')

        # Scrollbars
        sb_v = ttk.Scrollbar(self.frame_tablas, orient='vertical', command=self.tabla_profesores.yview)
        self.tabla_profesores.configure(yscroll=sb_v.set)
        sb_v.pack(side='right', fill='y')

        sb_h = ttk.Scrollbar(self.frame_tablas, orient='horizontal', command=self.tabla_profesores.xview)
        self.tabla_profesores.configure(xscroll=sb_h.set)
        sb_h.pack(side='bottom', fill='x')

        self.tabla_profesores.pack(fill='both', expand=True)

        boton_limpiar = ttk.Button(self.frame_der, text="Ver Todas las Asignaciones", command=self.limpiar_filtros)
        boton_limpiar.pack(pady=10, side='bottom', fill='x', padx=20)

    # --- UTILIDADES ---
    def _obtener_id_valido(self, texto_combo, es_grupo=False):
        if not texto_combo:
            return None
        textos_invalidos = ["sin grupos", "cargando", "seleccione", "sin materias", "no asignado", "grupos llenos"]
        if any(txt in texto_combo.lower() for txt in textos_invalidos):
            return None
        if ' - ' in texto_combo:
            return texto_combo.split(' - ')[0]
        if es_grupo:
            return texto_combo.upper()
        return None

    def redimensionar_fondo(self, event):
        try:
            if event.width > 0 and event.height > 0 and hasattr(self, 'original_image'):
                resized = self.original_image.resize((event.width, event.height), Image.LANCZOS)
                self.background_image = ImageTk.PhotoImage(resized)
                self.background_label.config(image=self.background_image)
        except Exception as e:
            print(f"Error resize: {e}")

    # --- LÓGICA DE NEGOCIO ---
    def iniciar_asignacion_automatica(self):
        respuesta = messagebox.askyesnocancel(
            "Tipo de Asignación", 
            "¿Deseas resetear todos los horarios y empezar desde cero?\n\n"
            "• SÍ: Borra todo y asigna desde cero.\n"
            "• NO: Mantiene los horarios actuales y SOLO asigna los pendientes.\n"
            "• CANCELAR: Abortar operación."
        )
        
        if respuesta is None: return
            
        modo_seleccionado = "completo" if respuesta else "parcial"
        
        conexion = get_conexion()
        if not conexion:
            messagebox.showerror("Error", "No hay conexión a la base de datos")
            return
            
        try:
            generador = GeneradorHorarios(conexion)
            cantidad = generador.ejecutar(modo=modo_seleccionado)
            messagebox.showinfo("Éxito", f"Se generaron {cantidad} horarios correctamente en modo '{modo_seleccionado}'.")
            
            self.notebook.select(self.pes1)
            modo_actual = self.combo_vista_horarios.get() if hasattr(self, 'combo_vista_horarios') else "Salón"
            mem_grafico.inicializar_y_llenar_tensor(modo_actual)
            self.actualizar_vista_previa()
            self.s_idx = 0
            self.actualizar_tabla_grafica()
            
        except Exception as e:
            messagebox.showerror("Error Crítico", f"Falló la generación de horarios: {e}")
            print(e)
        finally:
            conexion.close()

    def cargar_grupos_por_semestre(self, semestre_id, materia_id=None):
        semestre_id = str(semestre_id)
        grupos_base = self.grupos_por_semestre.get(semestre_id, [])
        grupos_filtrados = grupos_base.copy()

        if materia_id:
            conexion = get_conexion()
            if conexion:
                try:
                    cursor = conexion.cursor()
                    cursor.execute("SELECT grupo_id FROM asignaciones WHERE materia_id = %s", (materia_id,))
                    grupos_ocupados = [row[0] for row in cursor.fetchall()]
                    grupos_filtrados = [g for g in grupos_base if g not in grupos_ocupados]
                except mysql.connector.Error as err:
                    print(f"Error filtrando grupos: {err}")
                finally:
                    cursor.close()
                    conexion.close()

        self.combo_grupos['values'] = grupos_filtrados
        if grupos_filtrados:
            self.combo_grupos.set(grupos_filtrados[0])
        else:
            self.combo_grupos.set("")
            if grupos_base:
                self.combo_grupos.set("Grupos llenos para esta materia")
            else:
                self.combo_grupos.set("sin grupos cargados")

    def cargar_combos_bd(self):
        conexion = get_conexion()
        if not conexion: return

        cursor = conexion.cursor()
        try:
            cursor.execute("SELECT profesor_id, nombre FROM profesores ORDER BY nombre")
            profesores = cursor.fetchall()
            self.profesores_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in profesores}
            lista_prof = list(self.profesores_map.values())
            self.combo_profesores['values'] = lista_prof
            if lista_prof: self.combo_profesores.set(lista_prof[0])

            cursor.execute("SELECT id_semestre, nombre FROM semestres ORDER BY id_semestre")
            semestres = cursor.fetchall()
            self.semestres_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in semestres}
            self.lista_maestra_semestres = [{"texto": f"{row[0]} - {row[1]}", "id": int(row[0])} for row in semestres]
            lista_sem = list(self.semestres_map.values())
            self.combo_semestre['values'] = lista_sem
            if lista_sem: self.combo_semestre.set(lista_sem[0])

            cursor.execute("SELECT materia_id, nombre, semestre_id FROM materias ORDER BY semestre_id")
            materias = cursor.fetchall()
            self.materias_map = {}
            self.lista_maestra_materias = []
            lista_mat = []
            
            for row in materias:
                m_id, nombre, s_id = row
                texto = f"{m_id} - {nombre}"
                self.materias_map[str(m_id)] = s_id
                self.lista_maestra_materias.append({"texto": texto, "semestre": int(s_id)})
                lista_mat.append(texto)

            self.combo_materias['values'] = lista_mat
            if lista_mat:
                self.combo_materias.set(lista_mat[0])
                self.mostrar_semestre_de_materia()

            self.actualizar_vista_previa()
        except mysql.connector.Error as err:
            messagebox.showerror("Error BD", f"Error cargando combos: {err}")
        finally:
            cursor.close()
            conexion.close()

    def limpiar_filtros(self):
        self.combo_profesores.set('')
        self.combo_materias.set('')
        self.combo_grupos.set('')
        self.combo_periodos.set('')
        self.combo_semestre.set('')
        self.actualizar_vista_previa()

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
        conexion = get_conexion()
        if not conexion: return None
        cursor = conexion.cursor()
        try:
            cursor.execute("SELECT grupo_id FROM grupos WHERE grupo_id = %s", (grupo_id,))
            if cursor.fetchone(): return grupo_id
            cursor.execute("INSERT INTO grupos (grupo_id, nombre) VALUES (%s, %s)", (grupo_id, grupo_id))
            conexion.commit()
            self.cargar_combos_bd() 
            messagebox.showinfo("Éxito", f"Grupo '{grupo_id}' creado.")
            return grupo_id
        except mysql.connector.Error as err:
            conexion.rollback()
            messagebox.showerror("Error BD", f"Error gestionando grupo: {err}")
            return None
        finally:
            cursor.close()
            conexion.close()

    def asignar_profesor_materia(self):
        prof_id = self._obtener_id_valido(self.combo_profesores.get())
        mat_id = self._obtener_id_valido(self.combo_materias.get())
        if not prof_id or not mat_id:
            messagebox.showerror("Error", "Seleccione Profesor y Materia válidos")
            return
        grupo_id = self.obtener_o_crear_grupo(self.combo_grupos.get())
        if not grupo_id: return
        conexion = get_conexion()
        if not conexion: return
        cursor = conexion.cursor()
        try:
            sql_check = "SELECT COUNT(*) FROM asignaciones WHERE profesor_id=%s AND materia_id=%s AND grupo_id=%s"
            cursor.execute(sql_check, (prof_id, mat_id, grupo_id))
            if cursor.fetchone()[0] > 0:
                messagebox.showwarning("Aviso", "Esta asignación ya existe")
                return
            sql_ins = "INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, estado) VALUES (%s, %s, %s, 'pendiente')"
            cursor.execute(sql_ins, (prof_id, mat_id, grupo_id))
            conexion.commit()
            messagebox.showinfo("Éxito", "Asignación guardada correctamente")
            self.actualizar_vista_previa()
        except mysql.connector.Error as err:
            conexion.rollback()
            messagebox.showerror("Error BD", f"Error al asignar: {err}")
        finally:
            cursor.close()
            conexion.close()

    def actualizar_vista_previa(self, event=None):
        prof_id = self._obtener_id_valido(self.combo_profesores.get()) if hasattr(self, 'combo_profesores') else None
        mat_id = self._obtener_id_valido(self.combo_materias.get()) if hasattr(self, 'combo_materias') else None
        grup_id = self._obtener_id_valido(self.combo_grupos.get(), es_grupo=True) if hasattr(self, 'combo_grupos') else None

        if hasattr(self, 'tabla_profesores'):
            for item in self.tabla_profesores.get_children():
                self.tabla_profesores.delete(item)

        conexion = get_conexion()
        if not conexion: return
        cursor = conexion.cursor()

        try:
            sql = """
                SELECT 
                    a.profesor_id, IFNULL(p.nombre, 'Sin Profesor'), 
                    a.materia_id, IFNULL(m.nombre, 'Materia Desconocida'),
                    a.grupo_id, IFNULL(g.nombre, 'Sin Grupo')
                FROM asignaciones a
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN grupos g ON a.grupo_id = g.grupo_id 
                WHERE 1=1 
            """
            params = []
            if prof_id:
                sql += " AND a.profesor_id = %s"
                params.append(prof_id)
            if mat_id:
                sql += " AND a.materia_id = %s"
                params.append(mat_id)
            if grup_id:
                sql += " AND a.grupo_id = %s"
                params.append(grup_id)

            sql += " LIMIT 50"
            cursor.execute(sql, params)
            resultados = cursor.fetchall()

            if resultados and hasattr(self, 'tabla_profesores'):
                for row in resultados:
                    p_str = f"{row[0]} - {row[1]}"
                    m_str = f"{row[2]} - {row[3]} ({row[4]})"
                    self.tabla_profesores.insert('', 'end', values=(p_str, m_str))
            elif hasattr(self, 'tabla_profesores'):
                self.tabla_profesores.insert('', 'end', values=("(No hay resultados)", ""))

        except mysql.connector.Error as err:
            if hasattr(self, 'tabla_profesores'):
                self.tabla_profesores.insert('', 'end', values=(f"Error BD: {err}", ""))
        finally:
            cursor.close()
            conexion.close()

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

        ttk.Button(frame_controles, text="◀ Anterior", command=self.anterior_salon).pack(side='left', padx=10)
        ttk.Button(frame_controles, text="Siguiente ▶", command=self.siguiente_salon).pack(side='left', padx=10)
        
        ttk.Label(frame_controles, text="Ver por:", background='#0A0F1E', foreground='white', font=("Roboto", 10, "bold")).pack(side='left', padx=(30, 5))
        self.combo_vista_horarios = ttk.Combobox(frame_controles, values=["Salón", "Profesor", "Grupo"], state="readonly", width=12, font=("Roboto", 10))
        self.combo_vista_horarios.set("Salón")
        self.combo_vista_horarios.pack(side='left')
        self.combo_vista_horarios.bind("<<ComboboxSelected>>", self.cambiar_modo_vista)

        ttk.Button(frame_controles, text="Descargar PDF Completo", command=self.exportar_pdf_completo).pack(side='right', padx=10)
        ttk.Button(frame_controles, text="Descargar PNG", command=self.guardar_captura).pack(side='right', padx=10)

        self.actualizar_tabla_grafica()

    def siguiente_salon(self):
        max_idx = len(mem_grafico.entidades_actuales)
        if max_idx > 0:
            self.s_idx = (self.s_idx + 1) % max_idx
            self.actualizar_tabla_grafica()

    def anterior_salon(self):
        max_idx = len(mem_grafico.entidades_actuales)
        if max_idx > 0:
            self.s_idx = (self.s_idx - 1) % max_idx
            self.actualizar_tabla_grafica()

    def cambiar_modo_vista(self, event=None):
        modo = self.combo_vista_horarios.get()
        mem_grafico.inicializar_y_llenar_tensor(modo)
        self.s_idx = 0
        self.actualizar_tabla_grafica()

    def exportar_pdf_completo(self):
        modo = self.combo_vista_horarios.get()
        nombre_archivo = f"Horarios_Plasem_{modo}_{datetime.datetime.now().strftime('%H%M%S')}.pdf"
        
        if not mem_grafico.entidades_actuales:
            messagebox.showwarning("Aviso", "No hay datos para exportar.")
            return

        respuesta = messagebox.askyesno("Confirmar", f"¿Deseas generar un PDF de múltiples páginas con todos los horarios por {modo}?\nEsto tardará unos segundos.")
        if not respuesta: return

        try:
            indice_respaldo = self.s_idx
            with PdfPages(nombre_archivo) as pdf:
                for s in mem_grafico.entidades_actuales:
                    self.s_idx = s[1]
                    self.actualizar_tabla_grafica() 
                    pdf.savefig(self.fig, bbox_inches='tight')
                    
            self.s_idx = indice_respaldo
            self.actualizar_tabla_grafica()
            messagebox.showinfo("Éxito", f"Reporte PDF guardado exitosamente:\n{nombre_archivo}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el PDF:\n{e}")

    def guardar_captura(self):
        if not hasattr(mem_grafico, 'entidades_actuales') or not mem_grafico.entidades_actuales:
            messagebox.showwarning("Aviso", "No hay un horario generado para capturar.")
            return

        try:
            nombre_real = next(e[0] for e in mem_grafico.entidades_actuales if e[1] == self.s_idx)
            modo = mem_grafico.modo_actual
            nombre_seguro = "".join([c if c.isalnum() else "_" for c in nombre_real])
            nombre_archivo = f"Horario_{modo}_{nombre_seguro}_{datetime.datetime.now().strftime('%H%M%S')}.png"
            
            self.fig.savefig(nombre_archivo, bbox_inches='tight', dpi=200)
            messagebox.showinfo("Captura Guardada", f"Se ha guardado la imagen exitosamente como:\n{nombre_archivo}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar la captura:\n{e}")

    def actualizar_tabla_grafica(self):
        self.ax.clear()
        self.ax.axis('off')

        time_col_w = 0.15 
        day_col_w = (1.0 - time_col_w) / 6 
        col_widths = [time_col_w] + [day_col_w] * 6

        num_horarios = mem_grafico.intervalos - 1 
        header_h = 0.08 
        grid_area_h = 1.0 - header_h
        interval_h = grid_area_h / num_horarios 
        
        titulo_texto = "HORARIO" 
        if mem_grafico.entidades_actuales:
            try:
                nombre_real = next(e[0] for e in mem_grafico.entidades_actuales if e[1] == self.s_idx)
                modo_up = mem_grafico.modo_actual.upper()
                titulo_texto = f"HORARIO {modo_up} - {nombre_real}"
            except StopIteration:
                pass
        
        self.ax.set_title(titulo_texto, color="white", pad=10, fontsize=12, fontweight='bold')

        day_names = ['Hora', 'Lunes', 'Martes', 'Miér', 'Juev', 'Vier', 'Sáb']
        x_curr = 0.0
        for i, name in enumerate(day_names):
            self.ax.add_patch(Rectangle((x_curr, 1.0 - header_h), col_widths[i], header_h, 
                                      facecolor='#2f4a23', edgecolor='white', linewidth=1, zorder=5))
            self.ax.text(x_curr + col_widths[i]/2, 1.0 - header_h/2, name,
                        ha='center', va='center', fontweight='bold', color='white', fontsize=10, zorder=6)
            x_curr += col_widths[i]

        x_grid = 0.0
        for col_idx in range(7):
            y_grid = 1.0 - header_h
            for row_idx in range(1, mem_grafico.intervalos):
                y_pos = y_grid - interval_h
                bg_color = '#1a1a1a' if col_idx == 0 else 'white'
                self.ax.add_patch(Rectangle((x_grid, y_pos), col_widths[col_idx], interval_h, 
                                          facecolor=bg_color, edgecolor='black', linewidth=0.5, zorder=1))
                
                if col_idx == 0 and mem_grafico.tensor_actual is not None:
                    try:
                        texto_hora = mem_grafico.tensor_actual[self.s_idx, row_idx, 0]
                        self.ax.text(x_grid + col_widths[col_idx]/2, y_pos + interval_h/2, 
                                    texto_hora, ha='center', va='center', color='white', fontsize=8, zorder=2)
                    except IndexError: pass
                y_grid -= interval_h
            x_grid += col_widths[col_idx]

        x_materia = col_widths[0] 
        
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
                                              facecolor='white', edgecolor='black', linewidth=1.2, zorder=3))
                    
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