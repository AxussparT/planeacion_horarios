import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from PIL import Image, ImageTk
import mysql.connector
from src.conexion import get_conexion # Necesario para la conexión a la BD

class VentanaGestion:
    def __init__(self, master_window):
        
        # Configuración de estilo
        estilo =ttk.Style()
        estilo.configure('blue.TFrame', background='#0A0F1E')
        
        # 1. CREACIÓN DE LA VENTANA Toplevel
        self.ventana = tk.Toplevel(master_window)
        self.ventana.title("Ventana de Gestión")
        self.ventana.state('zoomed')
        self.ventana.grab_set() 
        self.ventana.transient(master_window) 
        
        # 2. CARGA Y AJUSTE DE LA IMAGEN DE FONDO
        try:
            image = Image.open(r"assets/fondo.png")
            self.original_image = image
            self.background_label = tk.Label(self.ventana)
            self.background_label.place(x=0, y=0, relwidth=1, relheight=1)
            # Vincula el redimensionamiento al evento <Configure> de la ventana
            self.ventana.bind("<Configure>", self.redimensionar_fondo)
        except Exception as e:
            print(f"Error al cargar la imagen de fondo: {e}")
            self.ventana.config(bg="grey")
            
        # 3. CREACIÓN DE COMPONENTES
        self.frame_principal = ttk.Frame(self.ventana, borderwidth=0, relief="solid", style='blue.TFrame')
        frame_ancho = 1100
        frame_alto = 700
        self.frame_principal.place(relx=0.5, rely=0.5, anchor='center', width=frame_ancho, height=frame_alto)
        
        boton_cerrar = ttk.Button(self.frame_principal, text="Cerrar", command=self.ventana.destroy)
        boton_cerrar.pack(pady=2)
        
        # Pestañas (Notebook)
        self.notebook=ttk.Notebook(self.frame_principal)
        self.notebook.pack(fill='both',expand='yes')
        self.pes0=ttk.Frame(self.notebook,style='blue.TFrame')
        self.pes1=ttk.Frame(self.notebook,style='blue.TFrame')
        
        self.notebook.add(self.pes0,text='Gestionar')
        self.notebook.add(self.pes1,text='ver horarios')
        
        # Frames principales
        frame_contenedor=ttk.Frame(self.pes0,style='blue.TFrame')
        frame_contenedor.pack(fill='x',pady=10)
        
        self.frame_izq=ttk.Frame(frame_contenedor, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_izq.pack(side='left',padx=10,anchor='n')
        ttk.Label(self.frame_izq,text="Gestion",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        
        self.frame_der=ttk.Frame(frame_contenedor, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_der.pack(side='left',padx=10,anchor='n')
        ttk.Label(self.frame_der,text="Vista previa",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        
        ttk.Label(self.frame_izq,text="Seleccione el periodo",background='#0A0F1E',foreground='#ffffff',font=("Roboto",10))
        self.combo_periodos=ttk.Combobox(self.frame_izq,width=30,font=("Roboto",9),state='readonly')
        self.combo_periodos['values']=("A (Septiembre-Octubre)","B (Febrero - Junio)")
        self.combo_periodos.pack(pady=2,padx=10)
        
        #ejecucion del filtro de materias
        self.combo_periodos.bind("<<ComboboxSelected>>",self.filtrar_materias_por_periodo )
        # Frame de profesores y materias
        frame_contenedor2=ttk.Frame(self.frame_izq,style='blue.TFrame')
        frame_contenedor2.pack(fill='x',pady=10)
        
        self.frame_izq_pf=ttk.Frame(frame_contenedor2, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_izq_pf.pack(side='left',padx=10,anchor='n')
        ttk.Label(self.frame_izq_pf,text="Profesor",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        
        # COMBO PROFESORES
        self.combo_profesores=ttk.Combobox(self.frame_izq_pf,width=30,font=("Roboto", 9), state='readonly') 
        self.combo_profesores.pack(pady=3,padx=10)
        # VINCULACIÓN: Actualiza la vista previa al seleccionar profesor
        self.combo_profesores.bind("<<ComboboxSelected>>", self.actualizar_vista_previa) 
        
        # Botón "Asignar Manualmente"
        boton_asignar = ttk.Button(self.frame_izq_pf, text="Asignar Manualmente", 
                                   command=self.asignar_profesor_materia)
        boton_asignar.pack(pady=2)
        
        
        self.frame_der_pf=ttk.Frame(frame_contenedor2, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_der_pf.pack(side='left',padx=10,anchor='n')
        ttk.Label(self.frame_der_pf,text="materia",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        
        # COMBO MATERIAS
        self.combo_materias=ttk.Combobox(self.frame_der_pf,width=30,font=("Roboto",9), state='readonly')
        self.combo_materias.pack(pady=3,padx=10)
        
        # VINCULACIÓN: Actualiza semestre y vista previa al seleccionar materia
        self.combo_materias.bind("<<ComboboxSelected>>", 
                                 lambda e: (self.mostrar_semestre_de_materia(e), self.actualizar_vista_previa(e)))
        
        # FRAME_ASIGNACION AUTOMATICA
        frame_contenedor3=ttk.Frame(self.frame_izq,style='blue.TFrame')
        frame_contenedor3.pack(fill='x',pady=10)
        
        self.frame_izq_gp=ttk.Frame(frame_contenedor3, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_izq_gp.pack(side='left',padx=10,anchor='n')
        ttk.Label(self.frame_izq_gp,text="grupo",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        
        # COMBO GRUPOS
        # ESTADO NORMAL para permitir la entrada manual de nuevos grupos
        self.combo_grupos=ttk.Combobox(self.frame_izq_gp,width=20,font=("Roboto", 9), state='normal') 
        self.combo_grupos.pack(pady=3,padx=10)
        
        boton_guardar2 = ttk.Button(self.frame_izq_gp, text="Empezar asignacion automatica")
        boton_guardar2.pack(pady=2)
        
        
        self.frame_der_gp=ttk.Frame(frame_contenedor3, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_der_gp.pack(side='left',padx=10,anchor='n')
        ttk.Label(self.frame_der_gp,text="semestre",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        # COMBO SEMESTRE
        self.combo_semestre=ttk.Combobox(self.frame_der_gp,width=30,font=("Roboto",10), state='readonly')
        self.combo_semestre.pack(pady=3,padx=10)
        
        # Vista Previa (Tabla)
        self.frame_tablas=ttk.Frame(self.frame_der, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_tablas.pack(side='left',padx=10,anchor='n')
        columnas=('Profesor','materia')
        self.tabla_profesores=ttk.Treeview(self.frame_tablas, columns=columnas, show='headings')
        self.tabla_profesores.column('Profesor',anchor='w',width=120)
        self.tabla_profesores.column('materia',anchor='w',width=120)
        
        self.tabla_profesores.heading('Profesor',text='Profesor')
        self.tabla_profesores.heading('materia',text='materia (Grupo)')
        
        scrollbar_vertical=ttk.Scrollbar(self.frame_tablas,orient='vertical',command=self.tabla_profesores.yview)
        self.tabla_profesores.configure(yscroll=scrollbar_vertical.set)
        scrollbar_vertical.pack(side='right',fill='y')
        
        scrollbar_horizontal=ttk.Scrollbar(self.frame_tablas,orient='horizontal',command=self.tabla_profesores.xview)
        self.tabla_profesores.configure(xscroll=scrollbar_horizontal.set)
        scrollbar_horizontal.pack(side='bottom',fill='x')
        self.tabla_profesores.pack()
        
        # Diccionarios para almacenar el mapeo de IDs y datos de la BD
        self.profesores_map = {} 
        self.materias_map = {} 
        self.grupos_map = {}
        self.semestres_map = {}
        self.grupos_por_semestre={
            "1":["S1A","S1B","S1C","S1D","S1E","S1F"],
            "2":["S2A","S2B","S2C","S2D","S2E","S2F"],
            "3":["S3A","S3B","S3C","S3D","S3E"],
            "4":["S4A","S4B","S4C","S4D","S4E"],
            "5":["S5A","S5B","S5C","S5D","S5E"],
            "6":["S6A","S6B","S6C","S6D"],
            "7":["S7A","S7B","S7C","S7D"],
            "8":["S8A","S8B","S8C"],
            "9":["S9A","S9B","S9C"]
        }
        
        # 4. Cargar datos iniciales y esperar cierre
        self.cargar_combos_bd() 
        self.ventana.wait_window() 
        
    # --- MÉTODOS DE LA CLASE ---
    def cargar_grupos_por_semestre(self,semestre_id):
        semestre_id=str(semestre_id)
        grupos_disponibles=self.grupos_por_semestre.get(semestre_id,[])
        self.combo_grupos['values']=grupos_disponibles
        if grupos_disponibles:
            self.combo_grupos.set(grupos_disponibles[0])
        else:
            self.combo_grupos.set("")
            self.combo_grupos.set("sin grupos cargados")
            
    
    def cargar_combos_bd(self):
        """Carga los datos de las tablas (profesores, materias, semestres, grupos) en los combos."""
        conexion = None
        cursor = None
        
        try:
            conexion = get_conexion()
            if conexion is None:
                messagebox.showerror("Error de Conexión", "No se pudo establecer conexión con la base de datos para cargar combos.")
                return

            cursor = conexion.cursor()
            
            # --- PROFESORES ---
            sql_profesores = "SELECT profesor_id, nombre FROM profesores ORDER BY nombre"
            cursor.execute(sql_profesores)
            profesores_data_raw = cursor.fetchall()
            self.profesores_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in profesores_data_raw}
            profesores_data = list(self.profesores_map.values())
            
            self.combo_profesores['values'] = profesores_data
            if profesores_data:
                self.combo_profesores.set(profesores_data[0])
                
            # --- SEMESTRES ---
            sql_semestres = "SELECT id_semestre, nombre FROM semestres ORDER BY id_semestre"
            cursor.execute(sql_semestres)
            semestres_data_raw = cursor.fetchall()
            
            self.semestres_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in semestres_data_raw}
            semestres_combo_data = list(self.semestres_map.values())
            
            self.lista_maestra_semestres=[]
            for row in semestres_data_raw:
                self.lista_maestra_semestres.append({
                    "texto": f"{row[0]}-{row[1]}",
                    "id": int (row[0])
                })
            self.combo_semestre['values']=semestres_combo_data
            if semestres_combo_data:
                self.combo_semestre.set(semestres_combo_data[0])

            # --- MATERIAS (Guardando ID de semestre en materias_map) ---
            sql_materias = "SELECT materia_id, nombre, semestre_id FROM materias ORDER BY semestre_id"
            cursor.execute(sql_materias)
            
            materias_combo_data = []
            self.materias_map = {}
            self.lista_maestra_materias=[]
            
            
            for row in cursor.fetchall():
                materia_id, nombre_materia, semestre_id = row
                combo_value = f"{materia_id} - {nombre_materia}"
                materias_combo_data.append(combo_value)
                
                self.materias_map[str(materia_id)] = semestre_id 
                
                self.lista_maestra_materias.append({
                    "texto":combo_value,
                    "semestre": int(semestre_id)
                })
                
            self.combo_materias['values'] = materias_combo_data
            if materias_combo_data:
                self.combo_materias.set(materias_combo_data[0])
                self.mostrar_semestre_de_materia() 
                
            # --- GRUPOS ---
            # Nota: Los grupos se cargan para que aparezcan en el desplegable
            #sql_grupos = "SELECT grupo_id, nombre FROM grupos ORDER BY nombre"
            #cursor.execute(sql_grupos)
            #grupos_data_raw = cursor.fetchall()
            
            # Almacenar en un mapa para referencia rápida y en la lista de valores del combo
            #self.grupos_map = {str(row[0]): f"{row[0]} - {row[1]}" for row in grupos_data_raw}
            #grupos_data = list(self.grupos_map.values())
            self.combo_grupos.set("cargando...")
            #self.combo_grupos['values'] = grupos_data
            #if grupos_data:
                #self.combo_grupos.set(grupos_data[0])
                
            
            # Cargar la tabla inicial
            self.actualizar_vista_previa()
            
        except mysql.connector.Error as err:
            messagebox.showerror("Error de BD", f"Error al cargar los combos: {err}")
            
        finally:
            if cursor is not None:
                cursor.close()
            if conexion is not None and conexion.is_connected():
                conexion.close()

    def filtrar_materias_por_periodo(self,event=None):
        """filtrar materias de acuerdo al periodo selecccionado"""
        periodo_seleccionado=self.combo_periodos.get()
        
        if not periodo_seleccionado:
            return
        semestres_validos=[]
        if "A (" in periodo_seleccionado:
            semestres_validos=[1,3,5,7,9]
        elif "B (" in periodo_seleccionado:
            semestres_validos=[2,4,6,8,10]
        
        materias_filtradas=[]
        if hasattr(self,'lista_maestra_materias'):
            for item in self.lista_maestra_materias:
                if item["semestre"] in semestres_validos:
                    materias_filtradas.append(item["texto"])
        self.combo_materias['values']=materias_filtradas
        
        semestres_filtrados=[]
        if hasattr(self,'lista_maestra_semestres'):
            for item in self.lista_maestra_semestres:
                if item["id"] in semestres_validos:
                    semestres_filtrados.append(item["texto"])
        self.combo_semestre['values']=semestres_filtrados
        
        
        self.combo_materias.set('')
        self.combo_semestre.set('')
        self.combo_grupos['values']=[]
        self.combo_grupos.set('')
        
        if semestres_filtrados:
            self.combo_semestre.set(semestres_filtrados[0])
        
        if materias_filtradas:
            self.combo_materias.set(materias_filtradas[0])
            self.mostrar_semestre_de_materia()
        else:
            self.combo_materias.set('sin materias para este periodo')
        
    def obtener_o_crear_grupo(self, grupo_input_str):

        """Busca el ID de un grupo existente o lo inserta como nuevo grupo si no lo encuentra.
        Si el grupo_input_str es simple (ej. "SA"), se usa ese valor como ID y Nombre.
        Retorna el grupo_id (VARCHAR) o None si falla.
        """
        grupo_input_str = grupo_input_str.strip()
        if not grupo_input_str:
            messagebox.showerror("Error de Grupo", "El campo Grupo no puede estar vacío.")
            return None
        
        conexion = None
        cursor = None
        
        try:
            conexion = get_conexion()
            if conexion is None:
                return None
            cursor = conexion.cursor()

            # 1. Intentar extraer ID si el formato es 'ID - Nombre' (grupo ya cargado)
            if ' - ' in grupo_input_str:
                grupo_id_check = grupo_input_str.split(' - ')[0]
                # Verificamos que este ID exista en la base de datos
                sql_check = "SELECT grupo_id FROM grupos WHERE grupo_id = %s"
                cursor.execute(sql_check, (grupo_id_check,))
                if cursor.fetchone():
                    return grupo_id_check # Grupo existente seleccionado del combo
            
            # 2. Usar la entrada simple como ID y Nombre
            grupo_simple = grupo_input_str.upper() # Usamos mayúsculas como convención para IDs simples
            
            # Buscar por ID (en caso de que el usuario haya escrito un ID existente)
            sql_check_id = "SELECT grupo_id FROM grupos WHERE grupo_id = %s"
            cursor.execute(sql_check_id, (grupo_simple,))
            if cursor.fetchone():
                return grupo_simple # Ya existe con ese ID/nombre simple, usar ese.

            # 3. Insertar como nuevo grupo (ID = Nombre = entrada simple)
            sql_insert = "INSERT INTO grupos (grupo_id, nombre) VALUES (%s, %s)"
            cursor.execute(sql_insert, (grupo_simple, grupo_simple))
            conexion.commit()
            
            # Recargar los combos para que el nuevo grupo esté disponible inmediatamente
            self.cargar_combos_bd() 
            messagebox.showinfo("Nuevo Grupo Creado", f"El grupo '{grupo_simple}' ha sido registrado y utilizado en la asignación.")
            
            return grupo_simple

        except mysql.connector.Error as err:
            conexion.rollback()
            messagebox.showerror("Error de BD", f"Error al gestionar el grupo: {err}")
            return None
        except Exception as e:
            messagebox.showerror("Error", f"Ocurrió un error inesperado al procesar el grupo: {e}")
            return None
        finally:
            if cursor is not None:
                cursor.close()
            if conexion is not None and conexion.is_connected():
                conexion.close()

    def mostrar_semestre_de_materia(self, event=None):
        """Detecta la materia seleccionada y actualiza el combobox de semestre automáticamente."""
        selected_materia_str = self.combo_materias.get()
        if not selected_materia_str:
            self.combo_semestre.set("")
            self.combo_grupos['values']=[]
            self.combo_grupos.set("")
            return
            
        try:
            materia_id = selected_materia_str.split(' - ')[0]
            semestre_id = self.materias_map.get(materia_id)
            
            if semestre_id is not None:
                semestre_display_value = self.semestres_map.get(str(semestre_id))
                
                if semestre_display_value:
                    self.combo_semestre.set(semestre_display_value)
                else:
                    self.combo_semestre.set("Error: Semestre desconocido")
                self.cargar_grupos_por_semestre(semestre_id)
            else:
                self.combo_semestre.set("No Asignado")
                self.combo_grupos['values']=[]
                self.combo_grupos.set("")
                
        except Exception as e:
            print(f"Error al procesar la selección de materia: {e}")
            self.combo_semestre.set("")
            self.combo_grupos['values']=[]
            self.combo_grupos.set("")

    def asignar_profesor_materia(self):
        """Guarda la asignación de Profesor, Materia y GRUPO en la tabla 'asignaciones'."""
        
        profesor_str = self.combo_profesores.get()
        materia_str = self.combo_materias.get()
        grupo_str = self.combo_grupos.get() 
        
        try:
            # Obtener solo los ID de Profesor y Materia
            profesor_id = profesor_str.split(' - ')[0]
            materia_id = materia_str.split(' - ')[0]
        except IndexError:
            messagebox.showerror("Error de Selección", "Debe seleccionar un Profesor y una Materia válidos.")
            return
        
        # Obtener o crear el ID del grupo
        grupo_id = self.obtener_o_crear_grupo(grupo_str)
        if grupo_id is None:
            # Si la función anterior falló o el campo estaba vacío, se detiene aquí.
            return 

        conexion = None
        cursor = None
        
        try:
            conexion = get_conexion()
            if conexion is None:
                messagebox.showerror("Error de Conexión", "No se pudo establecer conexión con la base de datos.")
                return

            cursor = conexion.cursor()
            
            # 1. Verificar si la asignación ya existe (usando Profesor, Materia, Y GRUPO)
            sql_check = "SELECT COUNT(*) FROM asignaciones WHERE profesor_id = %s AND materia_id = %s AND grupo_id = %s"
            cursor.execute(sql_check, (profesor_id, materia_id, grupo_id))
            if cursor.fetchone()[0] > 0:
                messagebox.showwarning("Asignación Existente", 
                                       f"Esta asignación (Profesor {profesor_id}, Materia {materia_id}, Grupo {grupo_id}) ya existe.")
                return
            
            # 2. Insertar la nueva asignación (incluyendo grupo_id)
            sql_insert = "INSERT INTO asignaciones (profesor_id, materia_id, grupo_id) VALUES (%s, %s, %s)"
            cursor.execute(sql_insert, (profesor_id, materia_id, grupo_id))
            conexion.commit()
            
            messagebox.showinfo("Éxito", 
                                 f"Asignación guardada: Profesor {profesor_id} a Materia {materia_id} para el Grupo {grupo_id}.")
            
            # 3. Actualizar la vista previa 
            self.actualizar_vista_previa()
            
        except mysql.connector.Error as err:
            if conexion and conexion.is_connected():
                   conexion.rollback()
            messagebox.showerror("Error de BD", 
                                 f"Error al intentar asignar: {err}\nVerifique si las claves foráneas existen.")
            
        finally:
            if cursor is not None:
                cursor.close()
            if conexion is not None and conexion.is_connected():
                conexion.close()

    
    def actualizar_vista_previa(self, event=None):
        """Consulta la BD para obtener las asignaciones y actualiza la tabla de vista previa."""
        
        profesor_str = self.combo_profesores.get()
        materia_str = self.combo_materias.get()
        grupo_str = self.combo_grupos.get() 
        
        try:
            profesor_id = profesor_str.split(' - ')[0] if profesor_str and ' - ' in profesor_str else None
            materia_id = materia_str.split(' - ')[0] if materia_str and ' - ' in materia_str else None
            
            # Si el grupo no está en formato 'ID - Nombre', se usa el valor directo como ID para filtrar.
            if grupo_str and ' - ' in grupo_str:
                 grupo_id = grupo_str.split(' - ')[0]
            elif grupo_str:
                 grupo_id = grupo_str.upper()
            else:
                 grupo_id = None
                 
        except:
            profesor_id = None
            materia_id = None
            grupo_id = None
        
        for item in self.tabla_profesores.get_children():
            self.tabla_profesores.delete(item)
        
        if not profesor_id and not materia_id and not grupo_id:
             return

        conexion = None
        cursor = None
        
        try:
            conexion = get_conexion()
            if conexion is None:
                return

            cursor = conexion.cursor()
            
            # Construir la consulta SQL (incluye JOIN con la tabla grupos)
            sql = """
                SELECT 
                    a.profesor_id, p.nombre AS nombre_profesor, 
                    a.materia_id, m.nombre AS nombre_materia,
                    a.grupo_id, g.nombre AS nombre_grupo
                FROM 
                    asignaciones a
                JOIN profesores p ON a.profesor_id = p.profesor_id
                JOIN materias m ON a.materia_id = m.materia_id
                JOIN grupos g ON a.grupo_id = g.grupo_id 
                WHERE 1=1 
            """
            params = []

            if profesor_id:
                sql += " AND a.profesor_id = %s"
                params.append(profesor_id)

            if materia_id:
                sql += " AND a.materia_id = %s"
                params.append(materia_id)
            
            if grupo_id: 
                sql += " AND a.grupo_id = %s"
                params.append(grupo_id)
                
            sql += " LIMIT 50" 
            
            cursor.execute(sql, params)
            resultados = cursor.fetchall()
            
            # Insertar resultados en la Treeview
            if resultados:
                for row in resultados:
                    # row[0]=prof_id, row[1]=prof_nombre, row[2]=materia_id, row[3]=materia_nombre, row[4]=grupo_id, row[5]=grupo_nombre
                    profesor_display = f"{row[0]} - {row[1]}"
                    # Muestra la materia y el grupo en la misma columna
                    materia_display = f"{row[2]} - {row[3]} ({row[5]})" 
                    self.tabla_profesores.insert('', 'end', values=(profesor_display, materia_display))
            else:
                self.tabla_profesores.insert('', 'end', values=("(No hay asignaciones para la selección)", ""))
                
        except mysql.connector.Error as err:
            self.tabla_profesores.insert('', 'end', values=(f"Error de BD: {err}", ""))
        except Exception as e:
            self.tabla_profesores.insert('', 'end', values=(f"Error general: {e}", ""))
            
        finally:
            if cursor is not None:
                cursor.close()
            if conexion is not None and conexion.is_connected():
                conexion.close()
    
    def redimensionar_fondo(self, event):
        """Redimensiona la imagen de fondo al tamaño de la ventana."""
        try:
            new_ancho = event.width
            new_alto = event.height
            
            if new_ancho > 0 and new_alto > 0 and hasattr(self, 'original_image'):
                resized_image = self.original_image.resize((new_ancho, new_alto), Image.LANCZOS)
                self.background_image = ImageTk.PhotoImage(resized_image)
                self.background_label.config(image=self.background_image)
        except Exception as e:
            print(f"Error al redimensionar fondo: {e}")