import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import mysql.connector
from src.conexion import get_conexion
from src.motor_horarios import GeneradorHorarios

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
        
        # Diccionario estático de grupos (Se podría mover a BD en el futuro)
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

        # 4. Construcción de la Interfaz Gráfica
        self.construir_interfaz()

        # 5. Carga de datos iniciales
        self.cargar_combos_bd()
        self.ventana.wait_window()

    def construir_interfaz(self):
        """Método dedicado exclusivamente a crear los widgets."""
        
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
        
        #----------boton modificado
        boton_asignar = ttk.Button(self.frame_izq_gp, text="Empezar asignación automática", 
                           command=self.iniciar_asignacion_automatica) # <--- CAMBIO AQUÍ
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

        # Botón Limpiar Filtros
        boton_limpiar = ttk.Button(self.frame_der, text="Ver Todas las Asignaciones", command=self.limpiar_filtros)
        boton_limpiar.pack(pady=10, side='bottom', fill='x', padx=20)

    # --- UTILIDADES ---
    
    def _obtener_id_valido(self, texto_combo, es_grupo=False):
        """
        Función auxiliar para extraer el ID de un string formato 'ID - Nombre'.
        Retorna None si el texto es vacío o contiene mensajes de error.
        """
        if not texto_combo:
            return None
            
        # Validar textos basura comunes
        textos_invalidos = ["sin grupos", "cargando", "seleccione", "sin materias", "no asignado"]
        if any(txt in texto_combo.lower() for txt in textos_invalidos):
            return None
            
        if ' - ' in texto_combo:
            return texto_combo.split(' - ')[0]
        
        # Si no tiene guion y es un grupo, asumimos que es un ID directo (ej. S1A)
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
        #confirmacion
        respuesta =messagebox.askyesno("Confirmar","esto generara horarios automaticos y borrara los anteriores")
        
        if not respuesta: return
        
        conexion =get_conexion()
        if not conexion:
            messagebox.showerror("error","mp hay conexion a la base de datos")
            return
        try:
            generador=GeneradorHorarios(conexion)
            cantidad=generador.ejecutar()
            
            messagebox.showinfo("exito",f"se generaron {cantidad}horarios correctamente")
            #---------aplicar cuando se desarrolle la interfaz de los horarios
            #self.notebook.select(self.pes1)
        except Exception as e:
            messagebox.showerror("error critico",f"fallo la generacion de horarios ")
            print(e)
        finally:
            conexion.close()
            
            
    def cargar_grupos_por_semestre(self, semestre_id):
        semestre_id = str(semestre_id)
        grupos = self.grupos_por_semestre.get(semestre_id, [])
        self.combo_grupos['values'] = grupos
        if grupos:
            self.combo_grupos.set(grupos[0])
        else:
            self.combo_grupos.set("")
            self.combo_grupos.set("sin grupos cargados")

    def cargar_combos_bd(self):
        conexion = get_conexion()
        if not conexion:
            messagebox.showerror("Error", "Sin conexión a BD")
            return

        cursor = conexion.cursor()
        try:
            # Profesores
            cursor.execute("SELECT profesor_id, nombre FROM profesores ORDER BY nombre")
            profesores = cursor.fetchall()
            self.profesores_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in profesores}
            lista_prof = list(self.profesores_map.values())
            self.combo_profesores['values'] = lista_prof
            if lista_prof: self.combo_profesores.set(lista_prof[0])

            # Semestres
            cursor.execute("SELECT id_semestre, nombre FROM semestres ORDER BY id_semestre")
            semestres = cursor.fetchall()
            self.semestres_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in semestres}
            self.lista_maestra_semestres = [{"texto": f"{row[0]} - {row[1]}", "id": int(row[0])} for row in semestres]
            lista_sem = list(self.semestres_map.values())
            self.combo_semestre['values'] = lista_sem
            if lista_sem: self.combo_semestre.set(lista_sem[0])

            # Materias
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

        # Filtrar Materias
        mat_filtradas = [m["texto"] for m in self.lista_maestra_materias if m["semestre"] in semestres_validos]
        self.combo_materias['values'] = mat_filtradas
        
        # Filtrar Semestres
        sem_filtrados = [s["texto"] for s in self.lista_maestra_semestres if s["id"] in semestres_validos]
        self.combo_semestre['values'] = sem_filtrados

        # Resetear selecciones
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
            
            self.cargar_grupos_por_semestre(id_sem)
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
            self.cargar_grupos_por_semestre(semestre_id)
        else:
            self.combo_semestre.set("No Asignado")

    def obtener_o_crear_grupo(self, grupo_texto):
        grupo_texto = grupo_texto.strip().upper()
        if not grupo_texto:
            messagebox.showerror("Error", "Campo Grupo vacío")
            return None

        # Verificar si ya es un formato "ID - Nombre" o un ID puro
        grupo_id = self._obtener_id_valido(grupo_texto, es_grupo=True)
        
        # Conexión DB
        conexion = get_conexion()
        if not conexion: return None
        cursor = conexion.cursor()

        try:
            # 1. Verificar si existe
            cursor.execute("SELECT grupo_id FROM grupos WHERE grupo_id = %s", (grupo_id,))
            if cursor.fetchone():
                return grupo_id

            # 2. Si no existe, crear
            cursor.execute("INSERT INTO grupos (grupo_id, nombre) VALUES (%s, %s)", (grupo_id, grupo_id))
            conexion.commit()
            
            self.cargar_combos_bd() # Recargar para que aparezca
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
            # Verificar duplicados
            sql_check = "SELECT COUNT(*) FROM asignaciones WHERE profesor_id=%s AND materia_id=%s AND grupo_id=%s"
            cursor.execute(sql_check, (prof_id, mat_id, grupo_id))
            if cursor.fetchone()[0] > 0:
                messagebox.showwarning("Aviso", "Esta asignación ya existe")
                return

            # Insertar
            sql_ins = "INSERT INTO asignaciones (profesor_id, materia_id, grupo_id) VALUES (%s, %s, %s)"
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
        # Usamos la función auxiliar para limpiar IDs y evitar errores con "sin grupos..."
        prof_id = self._obtener_id_valido(self.combo_profesores.get())
        mat_id = self._obtener_id_valido(self.combo_materias.get())
        grup_id = self._obtener_id_valido(self.combo_grupos.get(), es_grupo=True)

        # Limpiar tabla
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

            if resultados:
                for row in resultados:
                    p_str = f"{row[0]} - {row[1]}"
                    m_str = f"{row[2]} - {row[3]} ({row[5]})"
                    self.tabla_profesores.insert('', 'end', values=(p_str, m_str))
            else:
                self.tabla_profesores.insert('', 'end', values=("(No hay resultados)", ""))

        except mysql.connector.Error as err:
            self.tabla_profesores.insert('', 'end', values=(f"Error BD: {err}", ""))
        finally:
            cursor.close()
            conexion.close()