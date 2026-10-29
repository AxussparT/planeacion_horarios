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

class GestionPeriodosCardMixin:
    def _crear_spinner_hora(self, parent, valor_inicial="07:00", actualizar_periodos=True):
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
            if actualizar_periodos and hasattr(self, '_actualizar_todas_periodos'):
                if self._debounce_after_id:
                    self.ventana.after_cancel(self._debounce_after_id)
                self._debounce_after_id = self.ventana.after(1000, self._actualizar_todas_periodos)

        btn_menos = ttk.Button(f, text="-", width=3, command=lambda: ajustar(-30))
        btn_menos.pack(side='left')

        entry = ttk.Entry(f, textvariable=var, width=8, font=self._fuente_label, justify='center')
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
        if h is None:
            return ""
        s = str(h).strip()
        if not s or s.lower() == "none":
            return ""
        parts = s.split(':')
        try:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        except (ValueError, IndexError):
            return s

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
