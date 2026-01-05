import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import mysql.connector
from src.conexion import get_conexion
from tkinter import messagebox
from src.UI.ventana_gestion import VentanaGestion


# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process                         
# .\.venv\Scripts\Activate      
#python -m src.UI.ventana_principal
#git add .
#git commit -m "alta de datos y visualizacion en tabla"
#git push


from src.clases.profesor import profesor 
# --para ejecutar usar python -m servicio_S.src.UI.ventana_principal
    
class VentanaPrincipal:
    
    def __init__(self, master):
        self.master = master
        self.master.title("PLASEM")
        self.master.state('zoomed')  # Maximiza la ventana al iniciar
        #nuevo
        self.cache_profesores=[]
        self.cache_materias=[]
        self.cache_salones=[]
        self._last_width=0
        self._last_height=0
        
        self.dias_seleccionados=""
        db_path = "data/PLASEM.db"
        
        # --- ESTILOS ---
        estilo =ttk.Style()
        estilo.theme_use('clam')
        estilo.configure('blue.TFrame', background='#0A0F1E')
        estilo.configure('Custom.TCheckbutton', font=('Roboto', 16), background='#0A0F1E', foreground='#ffffff')
        estilo.configure('Danger.TButton', font=('Roboto', 15), background='#6D583A', foreground='#000000', padding=10)
        estilo.configure('Treeview.Heading', background='#2f4a23', foreground='#ffffff')
        
        estilo.configure('fondo.TLabel', background='#0A0F1E', foreground='#ffffff')
        
        # --- Carga de la imagen de fondo ---
        try:
            image = Image.open(r"assets/fondo.png")
            self.original_image = image
            self.background_label = tk.Label(self.master)
            self.background_label.place(x=0, y=0, relwidth=1, relheight=1)
            self.master.bind("<Configure>", self.redimensionar_fondo)
        except Exception as e:
            print(f"Error al cargar la imagen de fondo: {e}")
            self.master.config(bg="grey")
        
        #--FRAMES PRINCIPAL
        self.frame_principal = ttk.Frame(self.master, borderwidth=0, relief="solid", style='blue.TFrame')
        frame_ancho = 1150
        frame_alto = 700
        self.frame_principal.place(relx=0.5, rely=0.5, anchor='center', width=frame_ancho, height=frame_alto)
        # Configurar pesos de columnas para que se dividan 50/50
        self.frame_principal.columnconfigure(0, weight=1) # Columna Izquierda
        self.frame_principal.columnconfigure(1, weight=1) # Columna Derecha
        self.frame_principal.rowconfigure(0, weight=1)

        # --- SECCIÓN IZQUIERDA ---
        self.canvas_izquierdo = tk.Canvas(self.frame_principal, highlightthickness=0, background='#0A0F1E')
        self.scrollbar_izquierdo = ttk.Scrollbar(self.frame_principal, orient="vertical", command=self.canvas_izquierdo.yview)
        self.frame_izquierdo_principal = ttk.Frame(self.canvas_izquierdo, style='blue.TFrame')
        
        #scroll actualizado
        #self.master.after(100,lambda: self.actualizar_scroll(self.canvas_izquierdo))
        self.frame_izquierdo_principal.bind(
            "<Configure>",
            lambda e: self.canvas_izquierdo.configure(
                scrollregion=self.canvas_izquierdo.bbox("all")
            )
        )
        
        self.canvas_izquierdo.create_window((0, 0), window=self.frame_izquierdo_principal, anchor="nw")
        self.canvas_izquierdo.configure(yscrollcommand=self.scrollbar_izquierdo.set)

        # Ubicación con grid (Fila 0, Columna 0)
        self.canvas_izquierdo.grid(row=0, column=0, sticky="nsew")
        self.scrollbar_izquierdo.grid(row=0, column=0, sticky="nse") # Pegada a la derecha del canvas izq
        
        boton_ventana2=ttk.Button(self.frame_izquierdo_principal,text="Abrir ventana materias",command=self.abrir_ventana_gestion,style='Danger.TButton')
        boton_ventana2.pack(pady=4,padx=5,anchor='n')

        e_profesores = ttk.Label(self.frame_izquierdo_principal, text="Profesores", 
                                 font=("Roboto", 20), style='fondo.TLabel')
        e_profesores.pack(pady=10, padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="No. Cuenta",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        self.entry_no_cuenta=ttk.Entry(self.frame_izquierdo_principal,width=20,font=("Roboto", 15)) # Atributo público
        self.entry_no_cuenta.pack(pady=3,padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="Nombre:",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)  
        self.entry_nombre=ttk.Entry(self.frame_izquierdo_principal,width=20,font=("Roboto", 15)) # Atributo público
        self.entry_nombre.pack(pady=3,padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="Apellidos:",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        self.entry_apellido=ttk.Entry(self.frame_izquierdo_principal,width=20,font=("Roboto", 15)) # Atributo público
        self.entry_apellido.pack(pady=3,padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="¿En línea?:",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        self.combo_linea=ttk.Combobox(self.frame_izquierdo_principal,width=20,font=("Roboto", 15)) # Atributo público
        self.combo_linea['values']=("Sí","No")
        self.combo_linea.pack(pady=3,padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="Horario:",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=3,padx=10)
        self.entry_horario_i=ttk.Entry(self.frame_izquierdo_principal,width=20,font=("Roboto", 15)) # Atributo público
        self.entry_horario_i.pack(pady=3,padx=10)
        self.entry_horario_f=ttk.Entry(self.frame_izquierdo_principal,width=20,font=("Roboto", 15)) # Atributo público
        self.entry_horario_f.pack(pady=3,padx=10)
        
        # Checkbuttons de días de semana
        frame_contenedor=ttk.Frame(self.frame_izquierdo_principal,style='blue.TFrame')
        frame_contenedor.pack(fill='x',pady=10)
        
        frame_dias=ttk.Frame(frame_contenedor, borderwidth=0, relief="solid", style='blue.TFrame')
        frame_dias.pack(side='left',padx=10,anchor='n')
        
        frame_confirmar=ttk.Frame(frame_contenedor, borderwidth=0, relief="solid", style='blue.TFrame')
        frame_confirmar.pack(side='left',padx=10,anchor='n')
                 # --- BOTÓN CORREGIDO ---
        # Ahora el command llama a self.evento_boton_profesores (el nuevo método de la clase)
        boton_confirmar=ttk.Button(frame_confirmar,text="Confirmar",command=self.evento_boton_profesores,style='Danger.TButton')
        boton_confirmar.pack(pady=5,padx=5,anchor='n')
        
        self.boton_modificar_profesores=ttk.Button(frame_confirmar,text="Modificar",command=self.modificar_profesor,style='Danger.TButton')
        self.boton_modificar_profesores.pack(pady=5,padx=5,anchor='n')
        
        #self.boton_eliminar_profesores=ttk.Button(frame_confirmar,text="Eliminar registro",command=self.eliminar_profesor,style='Danger.TButton')
        #self.boton_eliminar_profesores.pack(pady=5,padx=5,anchor='n')
        
        # Función local para los Checkbuttons (Esta sí funciona aquí porque no usa self)
        def seleccionar():
            seleccion = []
            if self.var_lunes.get(): seleccion.append("Lunes")
            if self.var_martes.get(): seleccion.append("Martes")
            if self.var_miercoles.get(): seleccion.append("Miércoles")
            if self.var_jueves.get(): seleccion.append("Jueves")
            if self.var_viernes.get(): seleccion.append("Viernes")
            if self.var_sabado.get(): seleccion.append("Sábado")
            
            self.dias_seleccionados=", ".join(seleccion)
            print("Días seleccionados:", ", ".join(seleccion))
            
        self.var_lunes = tk.IntVar()
        self.var_martes = tk.IntVar()
        self.var_miercoles = tk.IntVar()
        self.var_jueves = tk.IntVar()
        self.var_viernes = tk.IntVar()
        self.var_sabado = tk.IntVar()
        
        ttk.Checkbutton(frame_dias, text="Lunes", variable=self.var_lunes, command=seleccionar, style='Custom.TCheckbutton').pack(pady=5,padx=5,anchor='w')
        ttk.Checkbutton(frame_dias, text="Martes", variable=self.var_martes, command=seleccionar, style='Custom.TCheckbutton').pack(pady=5,padx=5,anchor='w')
        ttk.Checkbutton(frame_dias, text="Miércoles", variable=self.var_miercoles, command=seleccionar, style='Custom.TCheckbutton').pack(pady=5,padx=5,anchor='w')
        ttk.Checkbutton(frame_dias, text="Jueves", variable=self.var_jueves, command=seleccionar, style='Custom.TCheckbutton').pack(pady=5,padx=5,anchor='w')
        ttk.Checkbutton(frame_dias, text="Viernes", variable=self.var_viernes, command=seleccionar, style='Custom.TCheckbutton').pack(pady=5,padx=5, anchor='w')
        ttk.Checkbutton(frame_dias, text="Sábado", variable=self.var_sabado, command=seleccionar, style='Custom.TCheckbutton').pack(pady=5,padx=5, anchor='w')
        #--------------------------------------------------------------------------------------------------
        #SECCION DE MATERIAS
        e_profesores = ttk.Label(self.frame_izquierdo_principal, text="Materias", 
                                 font=("Roboto", 20), style='fondo.TLabel')
        e_profesores.pack(pady=10, padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="Clave",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=4,padx=10)
        self.entry_materia_clave=ttk.Entry(self.frame_izquierdo_principal,width=30,font=("Roboto", 15))
        self.entry_materia_clave.pack(pady=4,padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="Nombre",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=4,padx=10)
        self.entry_materia_nom=ttk.Entry(self.frame_izquierdo_principal,width=30,font=("Roboto", 15))
        self.entry_materia_nom.pack(pady=4,padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="Horas a la semana",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=4,padx=10)
        self.entry_materia_horas=ttk.Entry(self.frame_izquierdo_principal,width=20,font=("Roboto", 15))
        self.entry_materia_horas.pack(pady=4,padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="Semestre",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=4,padx=10)
        self.entry_materia_semestre=ttk.Entry(self.frame_izquierdo_principal,width=20,font=("Roboto", 15))
        self.entry_materia_semestre.pack(pady=4,padx=10)
        
        boton_confirmar2=ttk.Button(self.frame_izquierdo_principal,text="agregar",command=self.evento_materias,style='Danger.TButton')
        boton_confirmar2.pack(pady=4,padx=5,anchor='n')
        

        
        
        
        separador=ttk.Separator(self.frame_izquierdo_principal,orient='horizontal')
        separador.pack(fill='x',padx=10,pady=10)
        #---------------------------------------------------------------------------
        #seccion de aulas
        ttk.Label(self.frame_izquierdo_principal,text="Número de aula",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=5,padx=10)
        self.entry_num_aula=ttk.Entry(self.frame_izquierdo_principal,width=30,font=("Roboto", 15))
        self.entry_num_aula.pack(pady=2,padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="Capacidad",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=5,padx=10)
        self.entry_capacidad_aula=ttk.Entry(self.frame_izquierdo_principal,width=20,font=("Roboto", 15))
        self.entry_capacidad_aula.pack(pady=2,padx=10)
        
        ttk.Label(self.frame_izquierdo_principal,text="Tipo de aula",background='#0A0F1E',foreground='#ffffff', font=("Roboto", 10)).pack(pady=5,padx=10)
        self.combo_tipo=ttk.Combobox(self.frame_izquierdo_principal,width=20,font=("Roboto", 15)) # Atributo público
        self.combo_tipo['values']=("Normal","tecnológica","laboratorio")
        self.combo_tipo.pack(pady=2,padx=10)
        
        boton_confirmar3=ttk.Button(self.frame_izquierdo_principal,text="agregar",command=self.evento_Salones,style='Danger.TButton')
        boton_confirmar3.pack(pady=5,padx=5,anchor='n')
        #---------------------------------------------------------------------------
       # --- SECCIÓN DERECHA ---
        self.canvas_derecho = tk.Canvas(self.frame_principal, highlightthickness=0, background='#0A0F1E')
        # Aumentamos un poco el ancho del scrollbar para que sea más visible
        self.scrollbar_derecho = ttk.Scrollbar(self.frame_principal, orient="vertical", command=self.canvas_derecho.yview)
        self.frame_derecho_principal = ttk.Frame(self.canvas_derecho, style='blue.TFrame')

        # Vincular el scrollregion
        #scroll actualizado 
        self.frame_derecho_principal.bind(
            "<Configure>",
            lambda e: self.canvas_derecho.configure(
                scrollregion=self.canvas_derecho.bbox("all")
            )
        )


        # Insertar el frame en el canvas
        # IMPORTANTE: Definir el ancho del window para que coincida con el canvas
        canvas_window = self.canvas_derecho.create_window((0, 0), window=self.frame_derecho_principal, anchor="nw")

        # Sincronizar el ancho del Frame interno con el Canvas para que no se "corte" la tabla
        def al_redimensionar_canvas(event):
            self.canvas_derecho.itemconfig(canvas_window, width=event.width)

        self.canvas_derecho.bind('<Configure>', al_redimensionar_canvas)
        self.canvas_derecho.configure(yscrollcommand=self.scrollbar_derecho.set)

        # Ubicación con grid
        self.canvas_derecho.grid(row=0, column=1, sticky="nsew", padx=(10, 25)) # Agregamos 25px de margen a la derecha
        self.scrollbar_derecho.grid(row=0, column=1, sticky="nse") # La barra del canvas queda en el borde extremo

        # --- CONTENIDO (Label y Tabla profesores) ---
        e_profesores_dis = ttk.Label(self.frame_derecho_principal, text="Profesores almacenados", 
                                    font=("Roboto", 20), style='fondo.TLabel')
        e_profesores_dis.pack(pady=10, padx=10)
        
        #barra de busqueda
        self.sv_busqueda=tk.StringVar()
        self.sv_busqueda.trace_add("write",lambda *args: self.filtrar_tabla_profesores())
        frame_busqueda_prof=ttk.Frame(self.frame_derecho_principal,style='blue.TFrame')
        frame_busqueda_prof.pack(pady=5,padx=10,fill='x')
        e_profesores_disp = ttk.Label(frame_busqueda_prof, text="Cuenta / nombre", 
                                    font=("Roboto", 20), style='fondo.TLabel')
        e_profesores_disp.pack(pady=10, padx=10)
        
        self.entry_busqueda_prof=ttk.Entry(frame_busqueda_prof,textvariable=self.sv_busqueda,width=40)
        self.entry_busqueda_prof.pack(side='left',padx=5)
        

        self.frame_tablas = ttk.Frame(self.frame_derecho_principal, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_tablas.pack(pady=10, padx=10, fill='x', expand=True) # Hacemos que el frame de la tabla ocupe el ancho

        columnas = ('Cuenta', 'Profesor', 'Dias', 'Horario', '¿en linea?')
        self.tabla_profesores = ttk.Treeview(self.frame_tablas, columns=columnas, show='headings')

        # Ajustamos anchos un poco más pequeños o dinámicos para evitar el scroll horizontal excesivo
        for col in columnas:
            self.tabla_profesores.column(col, anchor='w', width=100)
            self.tabla_profesores.heading(col, text=col)

        # Scrollbar Vertical de la TABLA (Diferente a la del Canvas)
        scrollbar_tabla_v = ttk.Scrollbar(self.frame_tablas, orient='vertical', command=self.tabla_profesores.yview)
        self.tabla_profesores.configure(yscroll=scrollbar_tabla_v.set)
        scrollbar_tabla_v.pack(side='right', fill='y')

        # Scrollbar Horizontal de la TABLA
        scrollbar_tabla_h = ttk.Scrollbar(self.frame_tablas, orient='horizontal', command=self.tabla_profesores.xview)
        self.tabla_profesores.configure(xscroll=scrollbar_tabla_h.set)
        scrollbar_tabla_h.pack(side='bottom', fill='x')

        self.tabla_profesores.pack(fill='both', expand=True)
        
        #--------------tabla de materias 
        # --- CONTENIDO (Label y Tabla materias) ---
        e_materias_reg = ttk.Label(self.frame_derecho_principal, text="Materias almacenadas", 
                                    font=("Roboto", 20), style='fondo.TLabel')
        e_materias_reg.pack(pady=10, padx=10)
        
        #filtro de materias
        self.sv_busqueda2=tk.StringVar()
        self.sv_busqueda2.trace_add("write",lambda *args: self.filtrar_tabla_materias())
        frame_busqueda_mat=ttk.Frame(self.frame_derecho_principal,style='blue.TFrame')
        frame_busqueda_mat.pack(pady=5,padx=10,fill='x')
        e_materias_disp = ttk.Label(frame_busqueda_mat, text="Clave / nombre", 
                                    font=("Roboto", 20), style='fondo.TLabel')
        e_materias_disp.pack(pady=10, padx=10)
        
        self.entry_busqueda_mat=ttk.Entry(frame_busqueda_mat,textvariable=self.sv_busqueda2,width=40)
        self.entry_busqueda_mat.pack(side='left',padx=5)
        #----------------
        self.frame_tablas2 = ttk.Frame(self.frame_derecho_principal, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_tablas2.pack(pady=10, padx=10, fill='x', expand=True) # Hacemos que el frame de la tabla ocupe el ancho

        columnas_materias = ('Clave', 'nombre', 'horas a la semana', 'semestre')
        self.tabla_materias = ttk.Treeview(self.frame_tablas2, columns=columnas_materias, show='headings')

        # Ajustamos anchos un poco más pequeños o dinámicos para evitar el scroll horizontal excesivo
        for col in columnas_materias:
            self.tabla_materias.column(col, anchor='w', width=100)
            self.tabla_materias.heading(col, text=col)

        # Scrollbar Vertical de la TABLA (Diferente a la del Canvas)
        scrollbar_tabla_v = ttk.Scrollbar(self.frame_tablas2, orient='vertical', command=self.tabla_materias.yview)
        self.tabla_materias.configure(yscroll=scrollbar_tabla_v.set)
        scrollbar_tabla_v.pack(side='right', fill='y')

        # Scrollbar Horizontal de la TABLA
        scrollbar_tabla_h = ttk.Scrollbar(self.frame_tablas2, orient='horizontal', command=self.tabla_materias.xview)
        self.tabla_materias.configure(xscroll=scrollbar_tabla_h.set)
        scrollbar_tabla_h.pack(side='bottom', fill='x')

        self.tabla_materias.pack(fill='both', expand=True)
       
        #--------------tabla de salones registrados 
        # --- CONTENIDO (Label y Tabla salones) ---
        e_salones_reg = ttk.Label(self.frame_derecho_principal, text="Salones almacenados", 
                                    font=("Roboto", 20), style='fondo.TLabel')
        e_salones_reg.pack(pady=10, padx=10)

        self.frame_tablas3 = ttk.Frame(self.frame_derecho_principal, borderwidth=0, relief="solid", style='blue.TFrame')
        self.frame_tablas3.pack(pady=10, padx=10, fill='x', expand=True) # Hacemos que el frame de la tabla ocupe el ancho

        columnas_salones = ('Salon', 'Capacidad', 'Tipo')
        self.tabla_salones = ttk.Treeview(self.frame_tablas3, columns=columnas_salones, show='headings')

        # Ajustamos anchos un poco más pequeños o dinámicos para evitar el scroll horizontal excesivo
        for col in columnas_salones:
            self.tabla_salones.column(col, anchor='w', width=100)
            self.tabla_salones.heading(col, text=col)

        # Scrollbar Vertical de la TABLA (Diferente a la del Canvas)
        scrollbar_tabla_v = ttk.Scrollbar(self.frame_tablas3, orient='vertical', command=self.tabla_salones.yview)
        self.tabla_salones.configure(yscroll=scrollbar_tabla_v.set)
        scrollbar_tabla_v.pack(side='right', fill='y')

        # Scrollbar Horizontal de la TABLA
        scrollbar_tabla_h = ttk.Scrollbar(self.frame_tablas3, orient='horizontal', command=self.tabla_salones.xview)
        self.tabla_salones.configure(xscroll=scrollbar_tabla_h.set)
        scrollbar_tabla_h.pack(side='bottom', fill='x')

        self.tabla_salones.pack(fill='both', expand=True)
        
        #CAMBIAR Y OPTIMIZAR FILTRO
        
        
        
    # --- MÉTODOS DE LA CLASE ---
    
    def modificar_profesor(self):
        seleccionado = self.tabla_profesores.focus()
        if not seleccionado:
            messagebox.showwarning("Aviso", "Selecciona un profesor")
            return

        datos = self.tabla_profesores.item(seleccionado, "values")

        # -------- No. Cuenta --------
        self.entry_no_cuenta.delete(0, tk.END)
        self.entry_no_cuenta.insert(0, datos[0])

        # -------- Nombre (completo, sin dividir) --------
        self.entry_nombre.delete(0, tk.END)
        self.entry_nombre.insert(0, datos[1])

        # -------- Apellidos (no se separan desde BD) --------
        self.entry_apellido.delete(0, tk.END)

        # -------- Días --------
        #self.entry_dias.delete(0, tk.END)
        #self.entry_dias.insert(0, datos[2])

        # -------- Horario (inicio / fin) --------
        horario = datos[3]

        if "-" in horario:
            hora_inicio, hora_fin = horario.split("-", 1)
        else:
            hora_inicio = horario
            hora_fin = ""

        self.entry_horario_i.delete(0, tk.END)
        self.entry_horario_i.insert(0, hora_inicio)

        self.entry_horario_f.delete(0, tk.END)
        self.entry_horario_f.insert(0, hora_fin)

        # -------- ¿En línea? --------
        self.combo_linea.set("Sí" if str(datos[4]).upper() in ("1", "SI", "TRUE") else "No")



            
    def eliminar_profesor(self):
        seleccion = self.tabla_profesores.selection()

        if not seleccion:
            messagebox.showwarning("Aviso", "Selecciona un profesor")
            return

        profesor_id = self.tabla_profesores.item(seleccion)["values"][0]

        if not messagebox.askyesno("Confirmar", "¿Eliminar este registro?"):
            return

        conexion = get_conexion()
        cursor = conexion.cursor()

        try:
            cursor.execute(
                "DELETE FROM profesores WHERE profesor_id = %s",
                (profesor_id,)
            )
            conexion.commit()
        finally:
            cursor.close()
            conexion.close()

        self.mostrar_datos_profesor()


        
    def actualizar_scroll(self,canvas):
        canvas.configure(scrollregion=canvas.bbox("all"))
        
    
    def filtrar_tabla_profesores(self):
        """foiltrar la tabla por nombre o cuenta de los profesores"""
        termino=self.sv_busqueda.get().lower()
        
        filtrados=[
            p for p in self.cache_profesores
            if termino in p[0].lower() or termino in p[1].lower()
        ]
        self.actulizar_tabla_profesores(filtrados)
    
    
    def abrir_ventana_gestion(self):
        try:
            VentanaGestion(self.master)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la ventana de gestión: {e}")
            
    def mostrar_datos_profesor(self):
        self.cache_profesores.clear()
        conexion=get_conexion()
        cursor=conexion.cursor()
        
        cursor.execute("""
                       SELECT profesor_id,nombre, dias_disponibles,
                       CONCAT (disponible_inicio,'-',disponible_fin),
                       en_linea
                       FROM profesores
                       """)
        self.cache_profesores=cursor.fetchall()
        cursor.close()
        conexion.close()
        
        self.actulizar_tabla_profesores(self.cache_profesores)
    
    def actulizar_tabla_profesores(self,datos):
        self.tabla_profesores.delete(*self.tabla_profesores.get_children())
        
        for p in datos:
            self.tabla_profesores.insert(
                "","end",
                values=(
                    p[0],p[1],p[2],p[3],
                    "SI" if p[4] else "NO"
                )
            )

    def mostrar_datos_materias(self):
        self.cache_materias.clear()

        conexion = get_conexion()
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT materia_id, nombre, horas_semana, semestre_id
            FROM materias
        """)
        self.cache_materias = cursor.fetchall()
        cursor.close()
        conexion.close()

        self.actualizar_tabla_materias(self.cache_materias)
        
    def actualizar_tabla_materias(self, datos):
        self.tabla_materias.delete(*self.tabla_materias.get_children())

        for m in datos:
            self.tabla_materias.insert(
                "", "end",
                values=(m[0], m[1], m[2], m[3])
            )

    def filtrar_tabla_materias(self):
        termino = self.sv_busqueda2.get().lower()

        filtrados = [
            m for m in self.cache_materias
            if termino in str(m[0]).lower() or termino in m[1].lower()
        ]

        self.actualizar_tabla_materias(filtrados)

    def mostrar_datos_salones(self):
        self.cache_salones.clear()

        conexion = get_conexion()
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT salon_id, capacidad, tipo
            FROM salones
        """)
        self.cache_salones = cursor.fetchall()
        cursor.close()
        conexion.close()

        self.actualizar_tabla_salones(self.cache_salones)

    def actualizar_tabla_salones(self, datos):
        self.tabla_salones.delete(*self.tabla_salones.get_children())

        for s in datos:
            self.tabla_salones.insert(
                "", "end",
                values=(s[0], s[1], s[2])
            )

    
    def evento_Salones(self):
        print("Botón Salones presionado")
        aula=self.entry_num_aula.get()
        capacidad=self.entry_capacidad_aula.get()
        tipo=self.combo_tipo.get()
        print(f"aula: {aula}")
        print(f"capacidad: {capacidad}")
        print(f"tipo: {tipo}")
        try:
            from src.clases.salon import salon
            nuevo_salon = salon(
                numero_aula=aula,
                capacidad=capacidad,
                tipo=tipo
            )
            self.mostrar_datos_salones()  # Actualiza la tabla después de agregar un salón
        except NameError:
            print("ERROR: La clase 'salon' no está definida o no ha sido importada.")
    
        
    def evento_materias(self):
        print("Botón Materias presionado")
        clave=self.entry_materia_clave.get()
        nombre=self.entry_materia_nom.get()
        #grupo=self.entry_materia_gru.get()
        #profesor=self.combo_profesor.get()
        horas=self.entry_materia_horas.get()
        semestre=self.entry_materia_semestre.get()
        #salon=self.combo_salon.get()
        print(f"clave: {clave}")
        print(f"nombre: {nombre}")
        #print(f"grupo: {grupo}")
        #print(f"profesor: {profesor}")
        #print(f"horas a la semana: {horas}")
        print(f"semestre: {semestre}")
        #print(f"salon: {salon}")
        
        try: 
            from src.clases.materia import materia
            nueva_materia = materia(
                clave=clave,
                nombre=nombre,
                #grupo=grupo,
                #profesor=profesor,
                horas_semana=horas,
                semestre=semestre,
                #salon=salon
            )
            self.mostrar_datos_materias()
        except NameError:
            print("ERROR: La clase 'profesor' no está definida o no ha sido importada.")

        
    def evento_boton_profesores(self): 
        print("Botón Profesores presionado")
        # Accediendo a los widgets, que son públicoS
        cuenta=self.entry_no_cuenta.get()
        nombre=self.entry_nombre.get()
        apellido=self.entry_apellido.get()
        en_linea=self.combo_linea.get()
        horario_inicio=self.entry_horario_i.get()
        horario_fin= self.entry_horario_f.get()
        dias_seleccionados = self.dias_seleccionados
        nombre_completo= f"{nombre} {apellido}"
        # 2. Llamar al constructor de la clase 'profesor'
        try:
            nuevo_profesor = profesor(
                cuenta=cuenta,
                nombre_completo=nombre_completo,
                dias=dias_seleccionados, 
                hora_entrada=horario_inicio,
                hora_salida=horario_fin,
                linea=en_linea
            )
        
        except NameError:
            print("ERROR: La clase 'profesor' no está definida o no ha sido importada.")
        print(f"nombre: {nombre_completo}")
        print(f"apellido: {apellido}")
        print(f"en linea: {en_linea}")
        print(f"horario: de {horario_inicio} a {horario_fin}")
        self.mostrar_datos_profesor()  # Actualiza la tabla después de agregar un profesor'
        
    def redimensionar_fondo(self, event):
        # Asegura que solo responda al resize de la ventana principal
        if event.widget is not self.master:
            return
        # Evita redimensionar si el tamaño no cambió realmente
        if event.width == self._last_width and event.height == self._last_height:
            return
        self._last_width = event.width
        self._last_height = event.height
        if hasattr(self, "_resize_job"):
            self.master.after_cancel(self._resize_job)
        self._resize_job = self.master.after(
            150,
            lambda: self._aplicar_resize(event.width, event.height)
        )

    def _aplicar_resize(self,w,h):
        img=self.original_image.resize((w,h),Image.BILINEAR)
        self.background_image=ImageTk.PhotoImage(img)
        self.background_label.config(image=self.background_image)

if __name__ == "__main__":
    root = tk.Tk()
    app = VentanaPrincipal(root)
    app.mostrar_datos_profesor()  # Carga inicial de datos en la tabla
    app.mostrar_datos_materias()
    app.mostrar_datos_salones()  # Carga inicial de datos en la tabla de salones
    root.mainloop()