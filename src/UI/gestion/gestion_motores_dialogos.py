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

class GestionMotoresDialogosMixin:
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
            text="Preasignación de Aulas y Horarios",
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
            text=" Solo grupos que no tienen aula aún", image=IconManager.get("bolt", 16), compound="left",
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
            text=" Todos los grupos registrados", image=IconManager.get("refresh", 16), compound="left",
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

    def _mostrar_dialogo_alertas_popup(self, alertas, cantidad):
        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Reporte de Conflictos en Asignación")
        dialogo.geometry("740x440")
        dialogo.configure(background='#0A0F1E')
        dialogo.transient(self.ventana)
        dialogo.grab_set()

        f_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=16, pady=14)

        ttk.Label(
            f_cont,
            text=f"Asignación finalizada: {cantidad} materias asignadas",
            background='#0A0F1E',
            foreground='#38BDF8',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 4))

        ttk.Label(
            f_cont,
            text=f"Se detectaron {len(alertas)} materias sin profesor asignable por cruce de horarios o falta de disponibilidad:",
            background='#0A0F1E',
            foreground='#FFA726',
            font=self._fuente_sub
        ).pack(anchor='w', pady=(0, 10))

        cols = ('Materia', 'Grupo', 'Profesor', 'Causa')
        tabla = ttk.Treeview(f_cont, columns=cols, show='headings', height=9)
        for c in cols:
            tabla.heading(c, text=c)
        tabla.column('Materia', width=180)
        tabla.column('Grupo', width=80)
        tabla.column('Profesor', width=200)
        tabla.column('Causa', width=240)

        for a in alertas:
            tabla.insert('', 'end', values=(
                a.get('materia', 'N/D'),
                a.get('grupo', 'N/D'),
                a.get('profesor', 'Sin profesor'),
                a.get('causa', 'Conflicto de horario')
            ))

        sb = ttk.Scrollbar(f_cont, orient='vertical', command=tabla.yview)
        tabla.configure(yscroll=sb.set)
        sb.pack(side='right', fill='y')
        tabla.pack(fill='both', expand=True, pady=(0, 10))

        ttk.Button(f_cont, text="Entendido / Cerrar", command=dialogo.destroy).pack(side='right', pady=4)

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

                es_mediacion = self._es_modalidad_en_linea(modalidad)

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

    def _abrir_dialogo_sabana_horarios(self):
        from src.generador_sabana import GeneradorSabana

        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Reportes e Impresión Oficial UAEMéx")
        dialogo.geometry("580x480")
        dialogo.resizable(False, False)
        dialogo.configure(background='#0A0F1E')
        dialogo.transient(self.ventana)
        dialogo.grab_set()

        f_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=20, pady=16)

        ttk.Label(
            f_cont,
            text="Centro de Reportes y Documentos Oficiales",
            background='#0A0F1E',
            foreground='#38BDF8',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 4))

        ttk.Label(
            f_cont,
            text="Genera sábanas matriciales, cédulas docentes y horarios oficiales:",
            background='#0A0F1E',
            foreground='#81C784',
            font=self._fuente_sub
        ).pack(anchor='w', pady=(0, 14))

        f_form = ttk.Frame(f_cont, style='blue.TFrame')
        f_form.pack(fill='x', pady=6)

        # Tipo de Reporte
        ttk.Label(f_form, text="Documento:", background='#0A0F1E', foreground='white', font=self._fuente_sub).grid(row=0, column=0, sticky='w', pady=6, padx=(0, 12))
        combo_tipo_rep = ttk.Combobox(
            f_form,
            values=[
                "1. Sábana Matricial Consolidada",
                "2. Cédula de Carga Horaria Docente (PDF)",
                "3. Horario de Alumnos por Grupo (PDF)",
                "4. Cédula de Ocupación por Aula / Laboratorio (PDF)"
            ],
            state='readonly',
            width=36,
            font=self._fuente_label
        )
        combo_tipo_rep.set("1. Sábana Matricial Consolidada")
        combo_tipo_rep.grid(row=0, column=1, sticky='w', pady=6)

        # Filtro Semestre
        ttk.Label(f_form, text="Semestre:", background='#0A0F1E', foreground='white', font=self._fuente_sub).grid(row=1, column=0, sticky='w', pady=6, padx=(0, 12))
        combo_sem = ttk.Combobox(f_form, values=["Todos", "1", "2", "3", "4", "5", "6", "7", "8", "9"], state='readonly', width=16, font=self._fuente_label)
        val_sem_actual = getattr(self, 'combo_filtro_semestre', None)
        sem_ini = val_sem_actual.get() if val_sem_actual and val_sem_actual.get() else "Todos"
        combo_sem.set(sem_ini)
        combo_sem.grid(row=1, column=1, sticky='w', pady=6)

        # Filtro Periodo
        ttk.Label(f_form, text="Período:", background='#0A0F1E', foreground='white', font=self._fuente_sub).grid(row=2, column=0, sticky='w', pady=6, padx=(0, 12))
        combo_per = ttk.Combobox(f_form, values=["Todos", "A", "B"], state='readonly', width=16, font=self._fuente_label)
        per_act = getattr(self, 'combo_periodos', None)
        combo_per.set(per_act.get() if per_act and per_act.get() in ("A", "B") else "Todos")
        combo_per.grid(row=2, column=1, sticky='w', pady=6)

        # Formato de exportación
        lbl_fmt = ttk.Label(f_form, text="Formato:", background='#0A0F1E', foreground='white', font=self._fuente_sub)
        lbl_fmt.grid(row=3, column=0, sticky='w', pady=6, padx=(0, 12))
        formato_var = tk.StringVar(value="excel")
        f_fmt = ttk.Frame(f_form, style='blue.TFrame')
        f_fmt.grid(row=3, column=1, sticky='w', pady=6)
        rb_excel = ttk.Radiobutton(f_fmt, text="Excel (.xlsx)", variable=formato_var, value="excel")
        rb_excel.pack(anchor='w', pady=2)
        rb_pdf = ttk.Radiobutton(f_fmt, text="PDF (.pdf) - Documento Oficial", variable=formato_var, value="pdf")
        rb_pdf.pack(anchor='w', pady=2)

        def _on_tipo_rep_cambio(event=None):
            rb_excel.configure(state='normal')
        combo_tipo_rep.bind("<<ComboboxSelected>>", _on_tipo_rep_cambio)

        lbl_estado = ttk.Label(f_cont, text="", background='#0A0F1E', foreground='#FFD700', font=self._fuente_label)
        lbl_estado.pack(anchor='w', pady=(8, 4))

        f_btns = ttk.Frame(f_cont, style='blue.TFrame')
        f_btns.pack(fill='x', side='bottom', pady=(10, 0))

        def _ejecutar_generacion():
            sem_sel = combo_sem.get()
            per_sel = combo_per.get()
            fmt_sel = formato_var.get()
            tipo_rep_sel = combo_tipo_rep.get()

            ext = ".xlsx" if fmt_sel == "excel" else ".pdf"
            def _get_filename_default():
                if "Docente" in tipo_rep_sel:
                    return f"Cedulas_Docentes_{per_sel}{ext}"
                elif "Grupo" in tipo_rep_sel:
                    return f"Horarios_Grupos_Semestre_{sem_sel}_{per_sel}{ext}"
                elif "Aula" in tipo_rep_sel:
                    return f"Cedulas_Ocupacion_Aulas_{per_sel}{ext}"
                else:
                    return f"Sabana_Horarios_Semestre_{sem_sel}_{per_sel}{ext}"

            nombre_sugerido = _get_filename_default()
            filetypes = [("Excel Workbook", "*.xlsx")] if fmt_sel == "excel" else [("PDF Document", "*.pdf")]

            ruta_destino = filedialog.asksaveasfilename(
                parent=dialogo,
                title="Guardar Documento Oficial SAGA",
                defaultextension=ext,
                initialfile=nombre_sugerido,
                filetypes=filetypes
            )
            if not ruta_destino:
                return

            lbl_estado.config(text="Generando documento oficial... por favor espera.")
            dialogo.update_idletasks()

            def tarea():
                try:
                    if fmt_sel == "excel":
                        if "Docente" in tipo_rep_sel:
                            res = GeneradorSabana.generar_excel_fichas_profesores(
                                ruta_destino,
                                filtro_periodo=per_sel if per_sel != "Todos" else None
                            )
                        elif "Grupo" in tipo_rep_sel:
                            res = GeneradorSabana.generar_excel_fichas_grupos(
                                ruta_destino,
                                filtro_semestre=sem_sel if sem_sel != "Todos" else None,
                                filtro_periodo=per_sel if per_sel != "Todos" else None
                            )
                        elif "Aula" in tipo_rep_sel:
                            res = GeneradorSabana.generar_excel_cedulas_aulas(
                                ruta_destino,
                                filtro_periodo=per_sel if per_sel != "Todos" else None
                            )
                        else:
                            res = GeneradorSabana.generar_excel_sabana(
                                ruta_destino,
                                filtro_semestre=sem_sel if sem_sel != "Todos" else None,
                                filtro_periodo=per_sel if per_sel != "Todos" else None
                            )
                    else:
                        if "Docente" in tipo_rep_sel:
                            res = GeneradorSabana.generar_pdf_fichas_profesores(
                                ruta_destino,
                                filtro_periodo=per_sel if per_sel != "Todos" else None
                            )
                        elif "Grupo" in tipo_rep_sel:
                            res = GeneradorSabana.generar_pdf_fichas_grupos(
                                ruta_destino,
                                filtro_semestre=sem_sel if sem_sel != "Todos" else None,
                                filtro_periodo=per_sel if per_sel != "Todos" else None
                            )
                        elif "Aula" in tipo_rep_sel:
                            res = GeneradorSabana.generar_pdf_cedulas_aulas(
                                ruta_destino,
                                filtro_periodo=per_sel if per_sel != "Todos" else None
                            )
                        else:
                            res = GeneradorSabana.generar_pdf_sabana(
                                ruta_destino,
                                filtro_semestre=sem_sel if sem_sel != "Todos" else None,
                                filtro_periodo=per_sel if per_sel != "Todos" else None
                            )

                    def procesar_resultado():
                        if res.get("exito"):
                            lbl_estado.config(text="")
                            if messagebox.askyesno(
                                "Documento Generado Exitosamente",
                                f"Archivo generado con éxito:\n{ruta_destino}\n\n¿Deseas abrir el archivo ahora?"
                            ):
                                try:
                                    os.startfile(ruta_destino)
                                except Exception:
                                    pass
                            dialogo.destroy()
                        else:
                            lbl_estado.config(text="")
                            messagebox.showerror("Error al Generar", res.get("mensaje", "Ocurrió un error."))

                    self.ventana.after(0, procesar_resultado)
                except Exception as ex:
                    def mostrar_err():
                        lbl_estado.config(text="")
                        messagebox.showerror("Error", f"Ocurrió una excepción al exportar: {ex}")
                    self.ventana.after(0, mostrar_err)

            threading.Thread(target=tarea, daemon=True).start()

        ttk.Button(
            f_btns,
            text=" Generar Documento",
            image=IconManager.get("table", 16),
            compound="left",
            command=_ejecutar_generacion
        ).pack(side='left', padx=4)

        ttk.Button(f_btns, text="Cancelar", command=dialogo.destroy).pack(side='right', padx=4)

