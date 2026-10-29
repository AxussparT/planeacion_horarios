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

class GestionRespaldosMixin:
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
        ttk.Button(f_btns, text=" Reacomodar Seleccionadas", image=IconManager.get("refresh", 16), compound="left", command=_on_confirmar).pack(side='right', padx=3)

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


    def _deshacer_ultimo_punto(self, event=None):
        """
        Revierte el sistema al último punto de respaldo creado (Auto-Revertir / Ctrl+Z).
        """
        from src.gestor_restauracion import GestorRestauracion
        puntos = GestorRestauracion.listar_puntos()
        if not puntos:
            messagebox.showinfo(
                "Sin Puntos de Respaldo",
                "Aún no existen puntos de respaldo registrados para revertir."
            )
            return

        ultimo = puntos[0]
        if not messagebox.askyesno(
            "Deshacer Último Cambio (Ctrl+Z)",
            f"¿Deseas revertir el sistema al estado anterior?\n\n"
            f"• Punto: {ultimo['nombre']}\n"
            f"• Fecha: {ultimo['fecha_creacion']}\n"
            f"• Asignaciones: {ultimo['total_asignaciones']} | Horarios: {ultimo['total_horarios']}\n\n"
            f"Se restaurará el estado completo previo a la última acción."
        ):
            return

        res = GestorRestauracion.restaurar_punto(ultimo['punto_id'])
        if res.get("exito"):
            messagebox.showinfo(
                "Restauración Completada",
                f"Se restauró exitosamente al punto:\n'{ultimo['nombre']}'.\n\n"
                f"• Asignaciones restauradas: {res.get('asignaciones_restauradas', 0)}\n"
                f"• Horarios restaurados: {res.get('horarios_restaurados', 0)}"
            )
            self.actualizar_vista_previa()
            self._cargar_materias_grupo_gestion()
            if hasattr(self, '_actualizar_resumen_metricas'):
                self._actualizar_resumen_metricas()
        else:
            messagebox.showerror(
                "Error al Restaurar",
                res.get("mensaje", "Ocurrió un error al restaurar el punto.")
            )

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

        ttk.Button(f_btns, text=" Eliminar Punto", image=IconManager.get("trash", 16), compound="left", command=_eliminar_seleccionado).pack(side='left', padx=4)
        ttk.Button(f_btns, text="Cerrar", command=dialogo.destroy).pack(side='right', padx=4)
        ttk.Button(f_btns, text="⏪ Restaurar Punto Seleccionado", command=_ejecutar_restauracion).pack(side='right', padx=4)
