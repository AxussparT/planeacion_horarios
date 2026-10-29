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

class GestionAsignacionesMixin:
    def _on_cambio_grupo_gestion(self, event=None):
        self._materia_grupo_seleccionada_id = None
        self._cargar_materias_grupo_gestion()
        self._actualizar_estado_boton_vinculo()
        if hasattr(self, '_sv_filtro_grupo_vp'):
            g = self._sv_grupo_gestion.get().strip()
            if g:
                self._seleccionar_grupo_previa(g)

    def _cargar_materias_grupo_gestion(self):
        if not hasattr(self, 'tabla_materias_grupo'):
            return
        for item in self.tabla_materias_grupo.get_children():
            self.tabla_materias_grupo.delete(item)

        grupo_id = self._sv_grupo_gestion.get().strip()
        if not grupo_id:
            self._lbl_info_grupo_gestion.config(text="Selecciona un grupo para ver sus materias preasignadas.")
            return

        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            cur.execute("""
                SELECT 
                    a.asignacion_id,
                    a.materia_id,
                    IFNULL(m.nombre, a.materia_id) AS materia_nombre,
                    IFNULL(a.dias, '') AS dias,
                    a.hora_inicio,
                    a.hora_fin,
                    a.profesor_id,
                    IFNULL(p.nombre, 'Sin profesor') AS prof_nombre,
                    IFNULL(a.estado, 'no asignado') AS estado,
                    GROUP_CONCAT(DISTINCT h.salon_id) AS salones,
                    IFNULL(a.modalidad, 'Presencial') AS modalidad
                FROM asignaciones a
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                LEFT JOIN horarios h ON a.asignacion_id = h.asignacion_id
                WHERE a.grupo_id = %s AND (a.estado IS NULL OR a.estado != 'cancelada')
                GROUP BY a.asignacion_id
                ORDER BY a.materia_id
            """, (grupo_id,))
            filas = cur.fetchall()

        if not filas:
            # Si no hay registros en 'asignaciones', consultar si el grupo tiene materias en 'grupo_materias'
            filas_gm = []
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
                    filas_gm = cur.fetchall()

            if filas_gm:
                self._materias_grupo_cache = {}
                for fgm in filas_gm:
                    m_id, m_nom = fgm
                    item_id = f"gm_{m_id}"
                    self.tabla_materias_grupo.insert(
                        '', 'end', iid=item_id,
                        values=(f"{m_id} - {m_nom}", "Sin preasignar", "Presencial", "Pendiente", "Pendiente", "Sin profesor", "NO PREASIGNADO")
                    )
                self._lbl_info_grupo_gestion.config(
                    text=f"Grupo: {grupo_id} | {len(filas_gm)} materias sin preasignar. Presiona '⚡ Volver a preasignar' para asignar aula y horarios."
                )
                self._actualizar_estado_boton_vinculo()
                return

        self._materias_grupo_cache = {}
        total_asignadas = 0
        for f in filas:
            asig_id, m_id, m_nom, dias, hi, hf, prof_id, prof_nom, estado, salones, modalidad = f
            hi_str = self._hora_db_a_str(hi) if hi else ""
            hf_str = self._hora_db_a_str(hf) if hf else ""
            horario_str = f"{hi_str} - {hf_str}" if hi_str and hf_str else "Sin horario"
            aula_str = salones if salones else "Sin aula"
            p_display = "Sin profesor" if (not prof_id or prof_id == 'SIN_ASIGNAR') else prof_nom
            if p_display != "Sin profesor":
                total_asignadas += 1

            info_asig = {
                "asignacion_id": asig_id,
                "materia_id": m_id,
                "materia_nombre": m_nom,
                "dias": dias,
                "hora_inicio": hi_str,
                "hora_fin": hf_str,
                "profesor_id": prof_id,
                "profesor_nombre": p_display,
                "estado": estado,
                "salon_id": aula_str,
                "modalidad": modalidad
            }
            self._materias_grupo_cache[str(asig_id)] = info_asig

            self.tabla_materias_grupo.insert(
                '', 'end', iid=str(asig_id),
                values=(f"{m_id} - {m_nom}", aula_str, modalidad, dias, horario_str, p_display, estado.upper())
            )

        self._lbl_info_grupo_gestion.config(
            text=f"Grupo: {grupo_id} | Total Materias: {len(filas)} | Con Profesor: {total_asignadas} / {len(filas)}"
        )
        self._actualizar_estado_boton_vinculo()


    def _abrir_reubicacion_asistida(self):
        asig_id = self._materia_grupo_seleccionada_id
        if not asig_id:
            messagebox.showwarning(
                "Seleccionar Materia",
                "Por favor selecciona una materia de la tabla de materias preasignadas (izquierda) para reubicar su horario de manera asistida."
            )
            return

        asig_info = self._materias_grupo_cache.get(str(asig_id))
        if not asig_info:
            messagebox.showerror("Error", "No se encontró la información de la materia seleccionada.")
            return

        try:
            self._crear_punto_restauracion(f"Antes de Reubicación Asistida ({asig_info.get('materia_nombre')})")
        except Exception:
            pass

        from src.UI.gestion_reubicacion_asistida import DialogoReubicacionAsistida
        DialogoReubicacionAsistida(
            self.ventana,
            asig_info,
            callback_actualizar=self._on_reubicacion_asistida_completada
        )

    def _on_reubicacion_asistida_completada(self):
        self._cargar_materias_grupo_gestion()
        self._cargar_tensor_diferido(forzar=True)
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
    def _toggle_horario_manual(self):
        if getattr(self, '_horario_manual_visible', False):
            self._frame_horario_manual.pack_forget()
            self._horario_manual_visible = False
            self._btn_toggle_horario_manual.config(text="⚙ Horario y Días Manual ▼")
        else:
            self._frame_horario_manual.pack(fill='x', padx=6, pady=4, before=self._lbl_estado_vinculo)
            self._horario_manual_visible = True
            self._btn_toggle_horario_manual.config(text="⚙ Ocultar Horario Manual ▲")

    def _cargar_salones_para_manual(self):
        try:
            with obtener_cursor() as ctx:
                if ctx:
                    cur, conn = ctx
                    cur.execute("SELECT DISTINCT salon_id FROM salones WHERE salon_id NOT LIKE 'MEDIACION%' ORDER BY salon_id")
                    salones = [r[0] for r in cur.fetchall()]
                    if hasattr(self, 'combo_manual_aula'):
                        self.combo_manual_aula['values'] = salones
                        if salones and not self.combo_manual_aula.get():
                            self.combo_manual_aula.set(salones[0])
        except Exception as e:
            print(f"Error cargando salones manuales: {e}")

    def _on_select_materia_grupo_gestion(self, event=None):
        sel = self.tabla_materias_grupo.selection()
        if not sel:
            self._materia_grupo_seleccionada_id = None
        else:
            self._materia_grupo_seleccionada_id = sel[0]
            asig_info = self._materias_grupo_cache.get(str(sel[0]))
            if asig_info:
                if hasattr(self, 'combo_modalidad_vinculo'):
                    self.combo_modalidad_vinculo.set(asig_info.get('modalidad') or 'Presencial')
                if hasattr(self, 'combo_manual_hora_i') and asig_info.get('hora_inicio'):
                    self.combo_manual_hora_i.set(self._hora_db_a_str(asig_info['hora_inicio']))
                if hasattr(self, 'combo_manual_hora_f') and asig_info.get('hora_fin'):
                    self.combo_manual_hora_f.set(self._hora_db_a_str(asig_info['hora_fin']))
                if hasattr(self, 'combo_manual_aula') and asig_info.get('salon_id'):
                    aula = asig_info['salon_id'].split(',')[0].strip()
                    if aula and aula != "Sin aula":
                        self.combo_manual_aula.set(aula)
                if hasattr(self, '_vars_dias_manual'):
                    dias_act = [d.strip() for d in (asig_info.get('dias') or '').split(',') if d.strip()]
                    for d_nom, var in self._vars_dias_manual.items():
                        var.set(d_nom in dias_act)
        self._actualizar_estado_boton_vinculo()

    def _actualizar_estado_boton_vinculo(self):
        asig_id = self._materia_grupo_seleccionada_id
        prof_id = self._profesor_id_seleccionado

        asig_info = self._materias_grupo_cache.get(str(asig_id)) if asig_id else None

        if hasattr(self, '_btn_guardar_manual'):
            self._btn_guardar_manual.config(state='normal' if asig_info else 'disabled')

        if asig_info:
            p_actual = asig_info.get("profesor_nombre", "Sin profesor")
            tiene_prof = (asig_info.get("profesor_id") and asig_info.get("profesor_id") != 'SIN_ASIGNAR')
            if hasattr(self, '_btn_desvincular_profesor'):
                self._btn_desvincular_profesor.config(state='normal' if tiene_prof else 'disabled')

            if prof_id:
                prof_info = self.profesores_map.get(str(prof_id), {})
                p_nombre_sel = prof_info.get("nombre", prof_id)
                self._lbl_estado_vinculo.config(
                    text=f"Materia: {asig_info['materia_nombre']} | Horario: {asig_info['hora_inicio']}-{asig_info['hora_fin']} [{asig_info['dias']}] (Aula: {asig_info['salon_id']}) [{asig_info.get('modalidad', 'Presencial')}]\n"
                         f"Docente a vincular: {p_nombre_sel}",
                    foreground='#98FB98'
                )
                if hasattr(self, '_btn_vincular_profesor'):
                    self._btn_vincular_profesor.config(state='normal')
            else:
                self._lbl_estado_vinculo.config(
                    text=f"Materia seleccionada: {asig_info['materia_nombre']} ({p_actual}) [{asig_info.get('modalidad', 'Presencial')}]. Selecciona un profesor de la tabla derecha.",
                    foreground='#FFD700'
                )
                if hasattr(self, '_btn_vincular_profesor'):
                    self._btn_vincular_profesor.config(state='disabled')
        else:
            if hasattr(self, '_btn_vincular_profesor'):
                self._btn_vincular_profesor.config(state='disabled')
            if hasattr(self, '_btn_desvincular_profesor'):
                self._btn_desvincular_profesor.config(state='disabled')
            self._lbl_estado_vinculo.config(
                text="Selecciona una materia preasignada arriba y un profesor a la derecha para vincular.",
                foreground='#7E8B9B'
            )

    def _aplicar_horario_manual_seleccionada(self):
        asig_id = self._materia_grupo_seleccionada_id
        if not asig_id:
            messagebox.showwarning("Aviso", "Selecciona primero una materia de la tabla de materias preasignadas.")
            return

        asig_info = self._materias_grupo_cache.get(str(asig_id))
        if not asig_info:
            messagebox.showerror("Error", "No se encontró la información de la materia seleccionada.")
            return

        hora_i = self.combo_manual_hora_i.get().strip()
        hora_f = self.combo_manual_hora_f.get().strip()
        aula_sel = self.combo_manual_aula.get().strip()
        modalidad_sel = self.combo_modalidad_vinculo.get().strip() or "Presencial"
        dias_sel = [d for d, var in self._vars_dias_manual.items() if var.get()]

        # 1. Validar horas
        ini_min = self._minutos_hora_previa(hora_i)
        fin_min = self._minutos_hora_previa(hora_f)
        if ini_min is None or fin_min is None or fin_min <= ini_min:
            messagebox.showerror("Horario Inválido", "La hora de fin debe ser posterior a la hora de inicio.")
            return

        # 2. Validar días
        if not dias_sel:
            messagebox.showwarning("Días Requeridos", "Debes seleccionar al menos un día para el horario manual.")
            return

        # 3. Límite vespertino (17:00 hrs = 1020 min)
        if fin_min > 17 * 60:
            if not messagebox.askyesno(
                "Horario Vespertino",
                f"La hora de fin ({hora_f}) excede las 17:00 hrs.\n"
                f"La normativa institucional establece las 17:00 hrs como límite para las asignaciones.\n\n"
                f"¿Desea continuar de todos modos?"
            ):
                return

        # 4. Validar horas semanales de la materia
        duracion_sesion_horas = (fin_min - ini_min) / 60.0
        total_horas_manual = duracion_sesion_horas * len(dias_sel)
        horas_requeridas = self._get_horas_materia(asig_info['materia_id'])
        if horas_requeridas > 0 and abs(total_horas_manual - horas_requeridas) > 0.01:
            if not messagebox.askyesno(
                "Discrepancia de Horas Semanales",
                f"La materia '{asig_info['materia_nombre']}' requiere {int(horas_requeridas)} hrs/semana según plan de estudios.\n\n"
                f"La configuración manual suma {total_horas_manual:.1f} hrs/semana ({len(dias_sel)} días x {duracion_sesion_horas:.1f} hrs/día).\n\n"
                f"¿Desea aplicar este horario de todos modos?"
            ):
                return

        # 5. Choque de Grupo
        grupo_id = self._sv_grupo_gestion.get().strip()
        choques_grupo = self._detectar_choques_grupo(grupo_id, asig_info['materia_id'], dias_sel, hora_i, hora_f, excluir_asignacion_id=asig_id)
        if choques_grupo:
            detalles = "\n".join([f"• {c['dia']} {c['inicio']}-{c['fin']}: {c['materia']}" for c in choques_grupo])
            messagebox.showerror(
                "Conflicto de Horario del Grupo",
                f"El grupo '{grupo_id}' ya tiene materias asignadas en ese horario:\n\n{detalles}\n\nNo es posible sobreponer materias para el mismo grupo."
            )
            return

        # 6. Choque de Aula (si es presencial)
        if self._es_modalidad_en_linea(modalidad_sel):
            if not aula_sel or aula_sel == "Sin aula":
                aula_sel = "MEDIACION_TECNOLOGICA"
        else:
            if not aula_sel or aula_sel == "Sin aula":
                messagebox.showwarning("Aula requerida", "Para la modalidad presencial debes seleccionar un aula válida.")
                return
            choques_aula = self._detectar_choques_aula(aula_sel, asig_id, dias_sel, hora_i, hora_f)
            if choques_aula:
                detalles = "\n".join([f"• {c['dia']} {c['inicio']}-{c['fin']}: Grupo {c['grupo_id']} ({c['materia']})" for c in choques_aula])
                messagebox.showerror(
                    "Conflicto de Aula",
                    f"El aula '{aula_sel}' ya está ocupada en ese horario:\n\n{detalles}\n\nSeleccione otra aula u otro horario."
                )
                return

        # 7. Choque de Profesor (si ya tiene profesor asignado)
        prof_id = asig_info.get('profesor_id')
        if prof_id and prof_id != 'SIN_ASIGNAR':
            choques_profesor = []
            try:
                choques_profesor = self._detectar_choques_profesor(
                    prof_id, asig_info['materia_id'], grupo_id, modalidad_sel, dias_sel, hora_i, hora_f, excluir_asignacion_id=asig_id
                )
            except Exception as e:
                print(f"Error comprobando choques de profesor: {e}")
            disp_choque, disp_detalle = self._validar_disponibilidad_profesor(prof_id, dias_sel, hora_i, hora_f)

            if choques_profesor or disp_choque:
                self._mostrar_modal_resolucion_conflicto(
                    asig_info=asig_info,
                    prof_id=prof_id,
                    prof_nombre=asig_info.get('profesor_nombre', prof_id),
                    choques=choques_profesor,
                    motivo_disp=disp_detalle
                )
                return

        # 8. Persistir en la base de datos
        dias_str = ", ".join(dias_sel)
        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            try:
                cur.execute("""
                    UPDATE asignaciones
                    SET hora_inicio = %s, hora_fin = %s, dias = %s, modalidad = %s
                    WHERE asignacion_id = %s
                """, (hora_i, hora_f, dias_str, modalidad_sel, asig_id))

                cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (asig_id,))
                for d in dias_sel:
                    cur.execute("""
                        INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (asig_id, aula_sel, d, f"{hora_i}:00" if len(hora_i) == 5 else hora_i, f"{hora_f}:00" if len(hora_f) == 5 else hora_f))

                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error actualizando horario manual: {err}")
                return

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo("Éxito", f"Horario manual asignado correctamente a '{asig_info['materia_nombre']}':\n{dias_str} de {hora_i} a {hora_f} en {aula_sel} ({modalidad_sel}).")

    def _desvincular_docente_materia(self):
        asig_id = self._materia_grupo_seleccionada_id
        if not asig_id:
            return
        asig_info = self._materias_grupo_cache.get(str(asig_id))
        if not asig_info:
            return

        if not messagebox.askyesno(
            "Confirmar Desvinculación",
            f"¿Desea desvincular al docente de la materia '{asig_info['materia_nombre']}'?\n"
            f"La materia conservará su aula y horario preasignados y volverá al estado 'Sin profesor'."
        ):
            return

        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            try:
                cur.execute("""
                    UPDATE asignaciones
                    SET profesor_id = 'SIN_ASIGNAR', estado = 'no asignado'
                    WHERE asignacion_id = %s
                """, (asig_id,))
                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"No se pudo desvincular: {err}")
                return

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo("Éxito", "Docente desvinculado. La materia ahora se muestra como 'Sin profesor'.")

    def _ejecutar_vinculacion_docente(self):
        asig_id = self._materia_grupo_seleccionada_id
        prof_id = self._profesor_id_seleccionado

        if not asig_id or not prof_id:
            messagebox.showwarning("Aviso", "Selecciona una materia del grupo y un profesor para vincular.")
            return

        asig_info = self._materias_grupo_cache.get(str(asig_id))
        if not asig_info:
            messagebox.showerror("Error", "No se encontró la información de la materia preasignada.")
            return

        prof_info = self.profesores_map.get(str(prof_id), {})
        prof_nombre = prof_info.get("nombre", prof_id)
        materia_id = asig_info['materia_id']
        materia_nombre = asig_info['materia_nombre']
        grupo_id = self._sv_grupo_gestion.get().strip()

        modalidad = self.combo_modalidad_vinculo.get().strip() or "Presencial"

        if getattr(self, '_horario_manual_visible', False):
            # Usar valores del panel manual
            hora_i = self.combo_manual_hora_i.get().strip()
            hora_f = self.combo_manual_hora_f.get().strip()
            aula_sel = self.combo_manual_aula.get().strip()
            dias_lista = [d for d, var in self._vars_dias_manual.items() if var.get()]
            dias_str = ", ".join(dias_lista)

            # Validar horas
            ini_min = self._minutos_hora_previa(hora_i)
            fin_min = self._minutos_hora_previa(hora_f)
            if ini_min is None or fin_min is None or fin_min <= ini_min:
                messagebox.showerror("Horario Inválido", "La hora de fin debe ser posterior a la hora de inicio.")
                return
            if not dias_lista:
                messagebox.showwarning("Días Requeridos", "Debes seleccionar al menos un día para el horario manual.")
                return
            if fin_min > 17 * 60:
                if not messagebox.askyesno("Horario Vespertino", f"La hora de fin ({hora_f}) excede las 17:00 hrs.\n¿Desea continuar de todos modos?"):
                    return
            dur_h = (fin_min - ini_min) / 60.0
            tot_h = dur_h * len(dias_lista)
            h_req = self._get_horas_materia(materia_id)
            if h_req > 0 and abs(tot_h - h_req) > 0.01:
                if not messagebox.askyesno("Discrepancia de Horas", f"La materia requiere {int(h_req)} hrs/sem y la selección manual suma {tot_h:.1f} hrs/sem.\n¿Desea continuar de todos modos?"):
                    return
            # Choque grupo
            choques_grupo = self._detectar_choques_grupo(grupo_id, materia_id, dias_lista, hora_i, hora_f, excluir_asignacion_id=asig_id)
            if choques_grupo:
                det = "\n".join([f"• {c['dia']} {c['inicio']}-{c['fin']}: {c['materia']}" for c in choques_grupo])
                messagebox.showerror("Conflicto de Grupo", f"El grupo '{grupo_id}' ya tiene clases en ese horario:\n\n{det}")
                return
            # Choque aula
            if self._es_modalidad_en_linea(modalidad):
                if not aula_sel or aula_sel == "Sin aula":
                    aula_sel = "MEDIACION_TECNOLOGICA"
            else:
                if not aula_sel or aula_sel == "Sin aula":
                    messagebox.showwarning("Aula requerida", "Para la modalidad presencial debes seleccionar un aula válida.")
                    return
                choques_aula = self._detectar_choques_aula(aula_sel, asig_id, dias_lista, hora_i, hora_f)
                if choques_aula:
                    det = "\n".join([f"• {c['dia']} {c['inicio']}-{c['fin']}: Grupo {c['grupo_id']} ({c['materia']})" for c in choques_aula])
                    messagebox.showerror("Conflicto de Aula", f"El aula '{aula_sel}' ya está ocupada en ese horario:\n\n{det}")
                    return
        else:
            hora_i = asig_info['hora_inicio']
            hora_f = asig_info['hora_fin']
            dias_str = asig_info['dias']
            dias_lista = [d.strip() for d in dias_str.split(',') if d.strip()]
            aula_sel = "MEDIACION_TECNOLOGICA" if self._es_modalidad_en_linea(modalidad) else asig_info.get('salon_id', 'Sin aula')

            # --- Detección y Sugerencia de Compactación Continua Docente ---
            compactacion = self._detectar_compactacion_docente(
                prof_id=prof_id,
                asig_id=asig_id,
                materia_id=materia_id,
                grupo_id=grupo_id,
                modalidad=modalidad,
                aula_actual=aula_sel
            )
            if compactacion and compactacion.get("encontrado"):
                dias_asig_norm = [self._dia_a_indice_previa(d) for d in dias_lista]
                dias_comp_norm = [self._dia_a_indice_previa(d) for d in compactacion['dias']]
                mismo_horario = (
                    dias_asig_norm == dias_comp_norm and
                    compactacion['hora_i'] == self._hora_db_a_str(hora_i) and
                    compactacion['hora_f'] == self._hora_db_a_str(hora_f)
                )
                if not mismo_horario:
                    resp_comp = self._mostrar_dialogo_sugerencia_compactacion(
                        asig_info=asig_info,
                        prof_nombre=prof_nombre,
                        compactacion=compactacion
                    )
                    if resp_comp is None:
                        # Cancelar vinculación
                        return
                    elif resp_comp is True:
                        # Aplicar compactación sugerida directamente (en el mismo salón)
                        hora_i = compactacion['hora_i']
                        hora_f = compactacion['hora_f']
                        dias_lista = compactacion['dias']
                        dias_str = compactacion['dias_str']
                        aula_sel = compactacion['salon']

                        # Si hubo materia desplazada sin profesor, aplicar su reubicación en BD
                        desp = compactacion.get('desplazamiento')
                        if desp and desp.get('asignacion_id'):
                            try:
                                with obtener_cursor() as ctx_desp:
                                    if ctx_desp:
                                        cur_d, conn_d = ctx_desp
                                        cur_d.execute("""
                                            UPDATE asignaciones
                                            SET hora_inicio = %s, hora_fin = %s, dias = %s
                                            WHERE asignacion_id = %s
                                        """, (desp['nuevo_hora_i'], desp['nuevo_hora_f'], desp['nuevos_dias_str'], desp['asignacion_id']))
                                        cur_d.execute("DELETE FROM horarios WHERE asignacion_id = %s", (desp['asignacion_id'],))
                                        for d_dia in desp['nuevos_dias']:
                                            cur_d.execute("""
                                                INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                                                VALUES (%s, %s, %s, %s, %s)
                                            """, (desp['asignacion_id'], desp['salon'], d_dia, desp['nuevo_hora_i'], desp['nuevo_hora_f']))
                                        conn_d.commit()
                            except Exception as e_desp:
                                print(f"Error aplicando desplazamiento de materia sin profesor: {e_desp}")

                        self._aplicar_vinculacion_docente(
                            asig_id, prof_id, estado='asignado', modalidad=modalidad,
                            hora_i=hora_i, hora_f=hora_f, dias_str=dias_str, dias_lista=dias_lista,
                            aula_sel=aula_sel
                        )
                        return
            elif compactacion and not compactacion.get("encontrado") and compactacion.get("motivo") == "sin_lugar_en_aula":
                messagebox.showinfo(
                    "Aviso de Jornada Docente",
                    f"El profesor {prof_nombre} ya cuenta con clases asignadas.\n\n"
                    f"{compactacion['mensaje']}\n\n"
                    f"Se conservará el salón '{aula_sel}' y su horario preasignado ({self._hora_db_a_str(hora_i)} a {self._hora_db_a_str(hora_f)})."
                )

        # 1. Comprobar si el profesor ya tiene esa misma asignación
        if asig_info.get('profesor_id') == prof_id and asig_info.get('modalidad') == modalidad and not getattr(self, '_horario_manual_visible', False):
            messagebox.showinfo("Información", f"El profesor '{prof_nombre}' ya está asignado a esta materia con la misma configuración.")
            return

        # 2. Comprobar choques de horario del profesor
        choques_profesor = []
        try:
            choques_profesor = self._detectar_choques_profesor(
                prof_id, materia_id, grupo_id, modalidad, dias_lista, hora_i, hora_f, excluir_asignacion_id=asig_id
            )
        except Exception as err:
            print(f"Error comprobando choques del profesor: {err}")

        # 3. Comprobar disponibilidad registrada del profesor
        disp_choque, disp_detalle = self._validar_disponibilidad_profesor(prof_id, dias_lista, hora_i, hora_f)

        # Si hay choques con otra clase o con su disponibilidad, abrir modal de 4 opciones
        if choques_profesor or disp_choque:
            self._mostrar_modal_resolucion_conflicto(
                asig_info=asig_info,
                prof_id=prof_id,
                prof_nombre=prof_nombre,
                choques=choques_profesor,
                motivo_disp=disp_detalle
            )
            return

        # Sin conflicto: proceder con la asignación directa
        self._aplicar_vinculacion_docente(
            asig_id, prof_id, estado='asignado', modalidad=modalidad,
            hora_i=hora_i if getattr(self, '_horario_manual_visible', False) else None,
            hora_f=hora_f if getattr(self, '_horario_manual_visible', False) else None,
            dias_str=dias_str if getattr(self, '_horario_manual_visible', False) else None,
            dias_lista=dias_lista if getattr(self, '_horario_manual_visible', False) else None,
            aula_sel=aula_sel if getattr(self, '_horario_manual_visible', False) else None
        )

    def _aplicar_vinculacion_docente(self, asig_id, prof_id, estado='asignado', modalidad=None,
                                    hora_i=None, hora_f=None, dias_str=None, dias_lista=None, aula_sel=None):
        if modalidad is None and hasattr(self, 'combo_modalidad_vinculo'):
            modalidad = self.combo_modalidad_vinculo.get().strip() or 'Presencial'
        with obtener_cursor() as ctx:
            if not ctx:
                return False
            cur, conn = ctx
            try:
                if hora_i and hora_f and dias_str is not None:
                    cur.execute("""
                        UPDATE asignaciones
                        SET profesor_id = %s, estado = %s, modalidad = %s, hora_inicio = %s, hora_fin = %s, dias = %s
                        WHERE asignacion_id = %s
                    """, (prof_id, estado, modalidad, hora_i, hora_f, dias_str, asig_id))
                    if aula_sel and dias_lista:
                        cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (asig_id,))
                        for d in dias_lista:
                            cur.execute("""
                                INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (asig_id, aula_sel, d, f"{hora_i}:00" if len(hora_i) == 5 else hora_i, f"{hora_f}:00" if len(hora_f) == 5 else hora_f))
                else:
                    cur.execute("""
                        UPDATE asignaciones
                        SET profesor_id = %s, estado = %s, modalidad = %s
                        WHERE asignacion_id = %s
                    """, (prof_id, estado, modalidad, asig_id))
                    if self._es_modalidad_en_linea(modalidad):
                        cur.execute("UPDATE horarios SET salon_id = 'MEDIACION_TECNOLOGICA' WHERE asignacion_id = %s", (asig_id,))
                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error al vincular docente: {err}")
                return False

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo("Éxito", "Profesor vinculado correctamente a la materia preasignada.")
        return True

    def _cargar_profesor_desde_tabla(self, event):
        item = self.tabla_profesores.focus()
        if not item:
            return
        v = self.tabla_profesores.item(item, "values")
        if len(v) < 2:
            return
        no_cuenta, nombre = v[0], v[1]
        if hasattr(self, 'entry_no_cuenta'):
            self.entry_no_cuenta.config(state='normal')
            self.entry_no_cuenta.delete(0, tk.END)
            self.entry_no_cuenta.insert(0, no_cuenta)
            self.entry_no_cuenta.config(state='readonly')
        if hasattr(self, 'entry_nombre_prof'):
            self.entry_nombre_prof.config(state='normal')
            self.entry_nombre_prof.delete(0, tk.END)
            self.entry_nombre_prof.insert(0, nombre)
            self.entry_nombre_prof.config(state='readonly')

        if hasattr(self, 'entry_prof_vinculo'):
            self.entry_prof_vinculo.config(state='normal')
            self.entry_prof_vinculo.delete(0, tk.END)
            self.entry_prof_vinculo.insert(0, f"{no_cuenta} - {nombre}")
            self.entry_prof_vinculo.config(state='readonly')

        for pid, info in self.profesores_map.items():
            if info["no_cuenta"] == no_cuenta:
                self._profesor_id_seleccionado = pid
                break
        self._actualizar_horas_info()
        self._actualizar_estado_boton_vinculo()
        for item in self._periodos_frame.winfo_children():
            item.destroy()
        self._periodos_asignacion.clear()
        self._cargar_periodos_desde_bd()

    def _cambiar_filtro_semestre(self, event=None):
        self._actualizar_materias_en_periodos()
        if hasattr(self, 'combo_grupo_gestion'):
            grupos = self._grupos_filtrados_actual()
            self.combo_grupo_gestion['values'] = grupos
            if grupos:
                self.combo_grupo_gestion.set(grupos[0])
            else:
                self.combo_grupo_gestion.set('')
            self._on_cambio_grupo_gestion()

    def _on_filtro_semestre_vp(self, preservar_seleccion=False):
        sel = self._sv_filtro_semestre_vp.get()
        grupo_seleccionado = self._sv_filtro_grupo_vp.get()
        grupos = ["Todos"]
        if sel and sel != "Todos" and ' - ' in sel:
            try:
                sid = self._normalizar_nivel_grupo(sel.split(' - ')[0])
                grupos_sem = self._grupos_del_semestre(sid)
                if grupos_sem:
                    grupos.extend(grupos_sem)
            except (ValueError, IndexError):
                pass
        else:
            grupos.extend(
                grupo
                for semestre in sorted(
                    self.grupos_por_semestre,
                    key=lambda valor: (
                        not self._normalizar_nivel_grupo(valor).isdigit(),
                        int(self._normalizar_nivel_grupo(valor))
                        if self._normalizar_nivel_grupo(valor).isdigit()
                        else self._normalizar_nivel_grupo(valor)
                    )
                )
                for grupo in self.grupos_por_semestre[semestre]
                if grupo not in grupos
            )
        self.combo_filtro_grupo_vp['values'] = grupos
        if preservar_seleccion and grupo_seleccionado in grupos:
            self._sv_filtro_grupo_vp.set(grupo_seleccionado)
        else:
            self._sv_filtro_grupo_vp.set("Todos")
        self.actualizar_vista_previa()

    def _on_cambio_filtro_grupo_vp(self):
        self.actualizar_vista_previa()
        if hasattr(self, 'canvas_previa_horario'):
            self._cargar_previa_horario_grupo()

    def _actualizar_grupos_en_periodos(self):
        for periodo in self._periodos_asignacion:
            for combo_materia, combo_grupo in periodo.get("filas_asignacion", []):
                grupo_actual = combo_grupo.get().strip().upper()
                asignacion_cargada = getattr(combo_grupo, "_asignacion_cargada", None)
                materia_id = self._obtener_id_valido(combo_materia.get())
                preservar_grupo = asignacion_cargada == (materia_id, grupo_actual)
                self._actualizar_grupos_de_asignacion(
                    combo_materia,
                    combo_grupo,
                    preservar_grupo=preservar_grupo
                )

    def _materias_filtradas_actual(self):
        semestre_txt = self.combo_filtro_semestre.get()
        periodo_txt = self.combo_periodos.get()
        materias = self.lista_maestra_materias
        if periodo_txt:
            semestres_validos = [2, 4, 6, 8, 10] if periodo_txt == "A" else [1, 3, 5, 7, 9]
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
        for pd in self._periodos_asignacion:
            for cm, cg in pd.get("filas_asignacion", []):
                cm['values'] = filtradas
                if cm.get() and cm.get() not in filtradas:
                    cm.set('')
                materia_id = self._obtener_id_valido(cm.get())
                grupo_actual = cg.get().strip().upper()
                asignacion_cargada = getattr(cg, "_asignacion_cargada", None)
                preservar_grupo = asignacion_cargada == (materia_id, grupo_actual)
                self._actualizar_grupos_de_asignacion(
                    cm, cg, preservar_grupo=preservar_grupo
                )

    def _grupos_para_materia(self, materia_texto):
        materia_id = self._obtener_id_valido(materia_texto)
        if not materia_id:
            return self._grupos_filtrados_actual()
        nivel = self.materias_map.get(str(materia_id))
        if nivel is None:
            return self._grupos_filtrados_actual()
        return self.cargar_grupos_por_semestre(nivel, materia_id)

    def _actualizar_grupos_de_asignacion(self, combo_materia, combo_grupo, preservar_grupo=False):
        grupos = self._grupos_para_materia(combo_materia.get())
        grupo_actual = combo_grupo.get().strip().upper()
        if preservar_grupo and grupo_actual and grupo_actual not in grupos:
            grupos.append(grupo_actual)
        combo_grupo['values'] = grupos
        if grupo_actual and grupo_actual not in grupos:
            combo_grupo.set('')

    def _on_cambio_materia_asignacion(self, combo_materia, combo_grupo, label_restante):
        self._actualizar_horas_periodo(combo_materia, label_restante)
        combo_grupo.set('')
        self._actualizar_grupos_de_asignacion(combo_materia, combo_grupo)

    def _grupos_filtrados_actual(self):
        semestre_txt = self.combo_filtro_semestre.get()
        if semestre_txt and semestre_txt != "Todos" and ' - ' in semestre_txt:
            try:
                sid = self._normalizar_nivel_grupo(semestre_txt.split(' - ')[0])
                return self._grupos_del_semestre(sid)
            except (ValueError, IndexError):
                pass
        todos = []
        for sem in sorted(
            self.grupos_por_semestre,
            key=lambda nivel: (
                not self._normalizar_nivel_grupo(nivel).isdigit(),
                int(self._normalizar_nivel_grupo(nivel))
                if self._normalizar_nivel_grupo(nivel).isdigit()
                else self._normalizar_nivel_grupo(nivel)
            )
        ):
            for g in self.grupos_por_semestre[sem]:
                if g not in todos:
                    todos.append(g)
        return todos

    @staticmethod
    def _normalizar_dia(valor):
        s = unicodedata.normalize('NFKD', str(valor)).encode('ascii', 'ignore').decode('ascii').strip().lower()
        mapa = {"lunes": "0", "martes": "1", "miercoles": "2", "jueves": "3", "viernes": "4", "sabado": "5", "domingo": "6"}
        return mapa.get(s, str(valor).strip())

    @staticmethod
    def _es_modalidad_en_linea(mod):
        if not mod:
            return False
        import unicodedata
        s = unicodedata.normalize('NFKD', str(mod)).encode('ascii', 'ignore').decode('ascii').strip().lower()
        return "mediacion" in s or "linea" in s or "virtual" in s or "online" in s

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
                # Clean up corrupted dia values (non-numeric)
                cur.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id=%s AND dia NOT IN ('0','1','2','3','4','5','6')",
                            (self._profesor_id_seleccionado,))

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
                    if str(hi) == str(hf):
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
        except Exception as e:
            print(f"Error cargando disponibilidad: {e}")

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
        if hasattr(self, 'entry_no_cuenta'):
            self.entry_no_cuenta.config(state='normal')
            self.entry_no_cuenta.delete(0, tk.END)
            self.entry_no_cuenta.config(state='readonly')
        if hasattr(self, 'entry_nombre_prof'):
            self.entry_nombre_prof.config(state='normal')
            self.entry_nombre_prof.delete(0, tk.END)
            self.entry_nombre_prof.config(state='readonly')
        if hasattr(self, 'entry_prof_vinculo'):
            self.entry_prof_vinculo.config(state='normal')
            self.entry_prof_vinculo.delete(0, tk.END)
            self.entry_prof_vinculo.config(state='readonly')
        self._profesor_id_seleccionado = None
        self._label_horas.config(text="")
        self._actualizar_estado_boton_vinculo()
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
        for wd in list(self._periodos_asignacion):
            baseline_minutos += wd.get('db_minutos', 0)
            entry_i = wd.get('entry_i')
            entry_f = wd.get('entry_f')
            vars_dias = wd.get('vars_dias', {})
            if entry_i and entry_f:
                try:
                    hi_str = entry_i.get().strip()
                except Exception:
                    continue
                try:
                    hf_str = entry_f.get().strip()
                except Exception:
                    continue
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
        self._debounce_after_id = None
        if not self._profesor_id_seleccionado:
            return
        for wd in list(self._periodos_asignacion):
            for cm, cg in list(wd.get('filas_asignacion', [])):
                try:
                    cm.get()
                except Exception:
                    continue
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

    def _cambiar_filtro_periodo(self, event=None):
        periodo = self.combo_periodos.get()
        if not periodo: return
        self._periodo_seleccionado = periodo
        semestres_validos = [2, 4, 6, 8, 10] if periodo == "A" else [1, 3, 5, 7, 9]
        self._semestres_filtrados = semestres_validos
        lista_sem = [v for k, v in self.semestres_map.items() if int(k) in semestres_validos]
        if lista_sem:
            self.combo_filtro_semestre['values'] = lista_sem
            if self.combo_filtro_semestre.get() not in lista_sem:
                self.combo_filtro_semestre.set(lista_sem[0])
        if hasattr(self, 'combo_filtro_semestre_vp'):
            self.combo_filtro_semestre_vp['values'] = ["Todos"] + lista_sem
        self._cambiar_filtro_semestre()
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
                        conn.commit()
                        self.grupos_por_semestre = self._cargar_grupos_desde_bd()
                        self._actualizar_materias_en_periodos()
                    return grupo_id
                if nivel is None:
                    nivel = 0
                cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, %s)", (grupo_id, nivel))
                self.grupos_por_semestre = self._cargar_grupos_desde_bd()
                self._actualizar_materias_en_periodos()
                self.cargar_combos_bd() 
                messagebox.showinfo("Éxito", f"Grupo '{grupo_id}' creado.")
                return grupo_id
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error gestionando grupo: {err}")
                return None

    def _asignar_periodo(self, profesor_id, materia_id, grupo_id, periodo, hora_i, hora_f, modalidad="Presencial", dias_str=""):
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
                            "DELETE FROM horarios WHERE asignacion_id=%s",
                            (existente[0],)
                        )
                        cur.execute(
                            "UPDATE asignaciones SET periodo=%s, hora_inicio=%s, hora_fin=%s, dias=%s, estado='pendiente' WHERE asignacion_id=%s",
                            (periodo, hora_i, hora_f, dias_str, existente[0])
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
                                "DELETE FROM horarios WHERE asignacion_id=%s",
                                (old_asig_id,)
                            )
                            cur.execute(
                                "UPDATE asignaciones SET profesor_id=%s, hora_inicio=%s, hora_fin=%s, dias=%s, estado='pendiente' WHERE asignacion_id=%s",
                                (profesor_id, hora_i, hora_f, dias_str, old_asig_id)
                            )
                            conn.commit()
                            messagebox.showinfo("Sustituido", "Asignación transferida al nuevo profesor")
                            exito = True
                        else:
                            conn.rollback()
                            return False
                    else:
                        cur.execute(
                            "INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, estado, periodo, hora_inicio, hora_fin, dias, modalidad) VALUES (%s, %s, %s, 'pendiente', %s, %s, %s, %s, %s)",
                            (profesor_id, materia_id, grupo_id, periodo, hora_i, hora_f, dias_str, modalidad)
                        )
                        conn.commit()
                        messagebox.showinfo("Éxito", f"Asignación guardada para el periodo {periodo}")
                        exito = True
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error BD", f"Error al asignar: {err}")
                return False

        if exito:
            self.actualizar_vista_previa()
            return True
        return False

    def actualizar_vista_previa(self, event=None, mostrar_todo=False):
        if self._after_busqueda_asignaciones_id is not None:
            self.ventana.after_cancel(self._after_busqueda_asignaciones_id)
            self._after_busqueda_asignaciones_id = None

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
            children = tabla.get_children()
            if children:
                tabla.delete(*children)

        with obtener_cursor() as ctx:
            if ctx is None:
                return
            cur, conn = ctx
            try:
                sql = """
                    SELECT 
                        a.asignacion_id,
                        a.profesor_id,
                        CASE 
                            WHEN a.profesor_id IS NULL OR a.profesor_id = 'SIN_ASIGNAR' THEN 'Sin profesor asignado'
                            ELSE IFNULL(p.nombre, 'Sin profesor asignado')
                        END AS profesor_nombre,
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
                    if estado_filtro == "pendiente":
                        sql += " AND (a.estado = 'pendiente' OR a.estado = 'no asignado' OR a.profesor_id = 'SIN_ASIGNAR' OR a.profesor_id IS NULL)"
                    elif estado_filtro == "asignado":
                        sql += " AND a.estado = 'asignado' AND a.profesor_id != 'SIN_ASIGNAR' AND a.profesor_id IS NOT NULL"
                    else:
                        sql += " AND a.estado = %s"
                        params.append(estado_filtro)

                if texto_busqueda:
                    sql += """ AND (
                        p.nombre LIKE %s OR 
                        m.nombre LIKE %s OR 
                        a.grupo_id LIKE %s OR 
                        a.profesor_id LIKE %s OR 
                        a.materia_id LIKE %s OR
                        EXISTS (SELECT 1 FROM horarios h_sub WHERE h_sub.asignacion_id = a.asignacion_id AND (h_sub.salon_id LIKE %s OR h_sub.dia LIKE %s))
                    )"""
                    like = f"%{texto_busqueda}%"
                    params.extend([like, like, like, like, like, like, like])

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
                        prof_id_val = row[1]
                        prof_nom_val = row[2]
                        if not prof_id_val or prof_id_val == 'SIN_ASIGNAR':
                            p_str = "Sin profesor asignado"
                        else:
                            p_str = f"{prof_id_val} - {prof_nom_val}"
                        m_str = f"{row[3]} - {row[4]} ({row[5]})"
                        estado_str = str(row[7]).upper()
                        tabla.insert('', 'end', iid=str(asig_id), values=(p_str, m_str, estado_str))
                elif tabla:
                    tabla.insert('', 'end', iid="no_results", values=("(No hay resultados)", "", ""))

            except sqlite3.Error as err:
                if tabla:
                    tabla.insert('', 'end', iid="error_bd", values=(f"Error BD: {err}", "", ""))
