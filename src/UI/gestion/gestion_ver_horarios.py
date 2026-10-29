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
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages
import src.clases.memoria_Horario_Grafico as mem_grafico

class GestionVerHorariosMixin:
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

        ttk.Button(
            frame_controles,
            text=" Reportes Oficiales",
            image=IconManager.get("table", 16),
            compound="left",
            command=self._abrir_dialogo_sabana_horarios
        ).pack(side='right', padx=4)

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