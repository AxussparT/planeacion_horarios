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

class GestionConflictosMixin:
    def _validar_disponibilidad_profesor(self, prof_id, dias_lista, hora_i, hora_f):
        if not prof_id or prof_id == 'SIN_ASIGNAR':
            return False, ""
        disp_choque = False
        disp_detalle = ""
        with obtener_cursor() as ctx:
            if ctx:
                cur, conn = ctx
                cur.execute(
                    "SELECT dia, hora_inicio, hora_fin FROM profesor_disponibilidad WHERE profesor_id = %s",
                    (prof_id,)
                )
                disp_rows = cur.fetchall()
                if disp_rows:
                    ini_min = self._minutos_hora_previa(hora_i)
                    fin_min = self._minutos_hora_previa(hora_f)
                    dias_indices = [self._dia_a_indice_previa(d) for d in dias_lista if self._dia_a_indice_previa(d) is not None]

                    cubiertos = set()
                    for d_idx in dias_indices:
                        for row_dia, row_hi, row_hf in disp_rows:
                            r_d_idx = self._dia_a_indice_previa(row_dia)
                            r_ini = self._minutos_hora_previa(row_hi)
                            r_fin = self._minutos_hora_previa(row_hf)
                            if r_d_idx == d_idx and r_ini is not None and r_fin is not None:
                                if r_ini <= ini_min and fin_min <= r_fin:
                                    cubiertos.add(d_idx)
                                    break
                    if len(cubiertos) < len(dias_indices):
                        disp_choque = True
                        disp_detalle = f"El horario ({hora_i} - {hora_f} en {', '.join(dias_lista)}) excede o no coincide con los periodos de disponibilidad registrados del profesor."
        return disp_choque, disp_detalle

    def _detectar_choques_aula(self, salon_id, asignacion_id, dias, hora_i, hora_f):
        if not salon_id or salon_id in ("Sin aula", "") or str(salon_id).upper().startswith("MEDIACION"):
            return []
        inicio = self._minutos_hora_previa(hora_i)
        fin = self._minutos_hora_previa(hora_f)
        dias_propuestos = {
            indice for indice in (self._dia_a_indice_previa(dia) for dia in dias)
            if indice is not None
        }
        if inicio is None or fin is None or fin <= inicio or not dias_propuestos:
            return []

        choques = []
        with obtener_cursor_dict() as ctx:
            if ctx is None:
                return []
            cur, conn = ctx
            cur.execute("""
                SELECT h.dia, h.hora_inicio, h.hora_fin, a.grupo_id, IFNULL(m.nombre, a.materia_id) AS materia,
                       a.asignacion_id, a.profesor_id, IFNULL(p.nombre, 'Sin profesor') AS profesor_nombre
                FROM horarios h
                JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                LEFT JOIN profesores p ON a.profesor_id = p.profesor_id
                WHERE LOWER(h.salon_id) = LOWER(%s)
                  AND h.asignacion_id <> %s
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
            """, (salon_id, asignacion_id or -1))
            filas = cur.fetchall()
            for f in filas:
                indice_dia = self._dia_a_indice_previa(f['dia'])
                if indice_dia in dias_propuestos:
                    ini_ex = self._minutos_hora_previa(f['hora_inicio'])
                    fin_ex = self._minutos_hora_previa(f['hora_fin'])
                    if ini_ex is not None and fin_ex is not None:
                        if inicio < fin_ex and fin > ini_ex:
                            choques.append({
                                "dia": self.NOMBRES_DIAS[indice_dia] if indice_dia < len(self.NOMBRES_DIAS) else str(f['dia']),
                                "inicio": f['hora_inicio'],
                                "fin": f['hora_fin'],
                                "grupo_id": f['grupo_id'],
                                "materia": f['materia'],
                                "asignacion_id": f.get('asignacion_id'),
                                "profesor_id": f.get('profesor_id'),
                                "profesor_nombre": f.get('profesor_nombre')
                            })
        return choques

    def _detectar_compactacion_docente(self, prof_id, asig_id, materia_id, grupo_id, modalidad, aula_actual):
        """
        Detecta si el docente ya tiene otras clases asignadas y busca acomodar la nueva materia
        en los MISMOS días que sus clases existentes, en horario corrido (contiguo),
        para compactar su jornada a la menor cantidad de días posibles (ej. concentrar en 2 días).
        """
        if not prof_id or prof_id == 'SIN_ASIGNAR':
            return None

        # 1. Consultar asignaciones activas existentes del profesor
        with obtener_cursor_dict() as ctx:
            if not ctx:
                return None
            cur, conn = ctx
            cur.execute("""
                SELECT a.asignacion_id, a.materia_id, IFNULL(m.nombre, a.materia_id) as materia_nombre,
                       a.grupo_id, h.dia, h.hora_inicio, h.hora_fin, h.salon_id
                FROM asignaciones a
                JOIN materias m ON a.materia_id = m.materia_id
                JOIN horarios h ON a.asignacion_id = h.asignacion_id
                WHERE a.profesor_id = %s
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
                  AND a.asignacion_id != %s
                ORDER BY h.dia, h.hora_inicio
            """, (prof_id, asig_id or -1))
            clases_existentes = cur.fetchall()

        if not clases_existentes:
            return None

        # 2. Extraer los días en los que el profesor ya imparte clase
        dias_prof = {}
        for c in clases_existentes:
            d_norm = self._normalizar_dia(c['dia'])
            d_nombre = getattr(self, 'MAPA_DIAS', {}).get(d_norm, c['dia'])
            if d_nombre not in dias_prof:
                dias_prof[d_nombre] = []
            ini_m = self._minutos_hora_previa(c['hora_inicio'])
            fin_m = self._minutos_hora_previa(c['hora_fin'])
            if ini_m is not None and fin_m is not None:
                dias_prof[d_nombre].append({
                    "ini": ini_m,
                    "fin": fin_m,
                    "hi": self._hora_db_a_str(c['hora_inicio']),
                    "hf": self._hora_db_a_str(c['hora_fin']),
                    "materia": c['materia_nombre'],
                    "grupo": c['grupo_id'],
                    "aula": c['salon_id']
                })

        dias_unicos = list(dias_prof.keys())
        parejas_posibles = [
            ["Lunes", "Miércoles"],
            ["Martes", "Jueves"],
            ["Miércoles", "Viernes"],
            ["Viernes", "Sábado"],
            ["Lunes", "Viernes"]
        ]

        dias_objetivo = None
        for p in parejas_posibles:
            if any(d in dias_prof for d in p):
                dias_objetivo = p
                break
        if not dias_objetivo:
            dias_objetivo = dias_unicos[:2] if len(dias_unicos) >= 2 else dias_unicos

        min_hora = 24 * 60
        max_hora = 0
        horas_ocupadas_prof = []
        for d in dias_objetivo:
            for c in dias_prof.get(d, []):
                min_hora = min(min_hora, c['ini'])
                max_hora = max(max_hora, c['fin'])
                horas_ocupadas_prof.append((c['ini'], c['fin']))

        if not horas_ocupadas_prof:
            return None

        h_req = self._get_horas_materia(materia_id)
        if h_req and len(dias_objetivo) > 0:
            duracion_min = int((h_req / len(dias_objetivo)) * 60)
        else:
            duracion_min = 120

        franjas_candidatas = []
        # Prioridad 1: Corrida posterior a la última clase del profesor
        if max_hora + duracion_min <= 17 * 60:
            franjas_candidatas.append((max_hora, max_hora + duracion_min, True))

        # Prioridad 2: Corrida anterior a la primera clase del profesor
        if min_hora - duracion_min >= 7 * 60:
            franjas_candidatas.append((min_hora - duracion_min, min_hora, True))

# Solo evaluar franjas continuas (clases corridas contiguas)

        if not aula_actual or aula_actual in ("Sin aula", ""):
            return None
        aula_objetivo = aula_actual

        resumen_existentes = []
        for d in dias_objetivo:
            for c in dias_prof.get(d, []):
                resumen_existentes.append(f"• {d} {c['hi']}-{c['hf']}: {c['materia']} (Grupo {c['grupo']}) en Aula {c['aula']}")

        docentes_en_conflicto = set()

        # Datos de la asignación original para evaluar swap si hay materia sin profesor
        orig_hi = ""
        orig_hf = ""
        orig_dias_str = ""
        orig_dias = []
        asig_info_act = getattr(self, '_materias_grupo_cache', {}).get(str(asig_id), {})
        if asig_info_act:
            orig_hi = self._hora_db_a_str(asig_info_act.get('hora_inicio')) if asig_info_act.get('hora_inicio') else ""
            orig_hf = self._hora_db_a_str(asig_info_act.get('hora_fin')) if asig_info_act.get('hora_fin') else ""
            orig_dias_str = asig_info_act.get('dias') or ""
            orig_dias = [d.strip() for d in orig_dias_str.split(',') if d.strip()]

        for h_ini, h_fin, es_continua in franjas_candidatas:
            hi_str = f"{h_ini // 60:02d}:{h_ini % 60:02d}"
            hf_str = f"{h_fin // 60:02d}:{h_fin % 60:02d}"

            ch_prof = self._detectar_choques_profesor(
                prof_id, materia_id, grupo_id, modalidad, dias_objetivo, hi_str, hf_str, excluir_asignacion_id=asig_id
            )
            if ch_prof:
                continue

            disp_ch, _ = self._validar_disponibilidad_profesor(prof_id, dias_objetivo, hi_str, hf_str)
            if disp_ch:
                continue

            ch_grupo = self._detectar_choques_grupo(
                grupo_id, materia_id, dias_objetivo, hi_str, hf_str, excluir_asignacion_id=asig_id
            )
            if ch_grupo:
                continue

            # Revisar choques en el aula_objetivo (exclusivamente en aula_actual, sin cambiar de salón)
            ch_aula = self._detectar_choques_aula(aula_objetivo, asig_id, dias_objetivo, hi_str, hf_str)
            if not ch_aula:
                # El aula está completamente libre en este horario corrido
                return {
                    "encontrado": True,
                    "dias": dias_objetivo,
                    "dias_str": ", ".join(dias_objetivo),
                    "hora_i": hi_str,
                    "hora_f": hf_str,
                    "salon": aula_objetivo,
                    "es_continua": es_continua,
                    "clases_actuales": resumen_existentes,
                    "desplazamiento": None
                }
            else:
                # El aula está ocupada. Comprobar si los ocupantes tienen profesor asignado
                tiene_otro_prof = False
                ocupantes_sin_prof = []
                for c in ch_aula:
                    p_id = c.get('profesor_id')
                    p_nom = c.get('profesor_nombre', 'Sin profesor')
                    if p_id and str(p_id).strip() != 'SIN_ASIGNAR' and str(p_id).strip() != str(prof_id):
                        tiene_otro_prof = True
                        if p_nom and p_nom != 'Sin profesor':
                            docentes_en_conflicto.add(p_nom)
                    else:
                        ocupantes_sin_prof.append(c)

                if tiene_otro_prof:
                    # Ocupado por otro profesor con clase asignada: NO desplazar para no afectarlo
                    continue

                if ocupantes_sin_prof and orig_hi and orig_hf and orig_dias:
                    # Desplazar la materia sin profesor al horario vacante en el mismo salón
                    asig_disp = ocupantes_sin_prof[0]
                    ch_grp_disp = self._detectar_choques_grupo(
                        asig_disp['grupo_id'], asig_disp.get('materia', ''), orig_dias, orig_hi, orig_hf,
                        excluir_asignacion_id=asig_id
                    )
                    if not ch_grp_disp:
                        return {
                            "encontrado": True,
                            "dias": dias_objetivo,
                            "dias_str": ", ".join(dias_objetivo),
                            "hora_i": hi_str,
                            "hora_f": hf_str,
                            "salon": aula_objetivo,
                            "es_continua": es_continua,
                            "clases_actuales": resumen_existentes,
                            "desplazamiento": {
                                "asignacion_id": asig_disp.get('asignacion_id'),
                                "materia_nombre": asig_disp.get('materia', 'Materia sin profesor'),
                                "grupo_id": asig_disp['grupo_id'],
                                "nuevo_hora_i": orig_hi,
                                "nuevo_hora_f": orig_hf,
                                "nuevos_dias": orig_dias,
                                "nuevos_dias_str": orig_dias_str,
                                "salon": aula_objetivo
                            }
                        }

        # No fue posible el acomodo en el salón sin afectar a otros profesores
        txt_prof = f" (horario ocupado por: {', '.join(sorted(docentes_en_conflicto))})" if docentes_en_conflicto else ""
        return {
            "encontrado": False,
            "motivo": "sin_lugar_en_aula",
            "salon": aula_objetivo,
            "mensaje": f"No fue posible compactar la jornada en horario contiguo en el aula '{aula_objetivo}' sin afectar los horarios de otros profesores asignados{txt_prof}."
        }

    def _mostrar_dialogo_sugerencia_compactacion(self, asig_info, prof_nombre, compactacion):
        """
        Diálogo interactivo para sugerir la compactación de la carga del docente en la menor
        cantidad de días posible con clases corridas (contiguas).
        Retorna True si el usuario acepta, False si prefiere mantener el original, None si cancela.
        """
        resultado = [False]

        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Optimización de Jornada Docente")
        dialogo.transient(self.ventana)
        dialogo.grab_set()
        dialogo.configure(background='#0A0F1E')

        ancho_dlg = 760
        alto_dlg = 640

        try:
            self.ventana.update_idletasks()
            px = self.ventana.winfo_rootx() + (self.ventana.winfo_width() // 2) - (ancho_dlg // 2)
            py = self.ventana.winfo_rooty() + (self.ventana.winfo_height() // 2) - (alto_dlg // 2)
            if px < 20: px = 20
            if py < 20: py = 20
            dialogo.geometry(f"{ancho_dlg}x{alto_dlg}+{px}+{py}")
        except Exception:
            dialogo.geometry(f"{ancho_dlg}x{alto_dlg}")

        dialogo.minsize(680, 500)
        dialogo.resizable(True, True)

        # 1. PIE DE PÁGINA (Botones SIEMPRE visibles y anclados al fondo)
        f_btns = ttk.Frame(dialogo, style='blue.TFrame')
        f_btns.pack(side='bottom', fill='x', padx=20, pady=(10, 16))

        def _aceptar():
            resultado[0] = True
            dialogo.destroy()

        def _conservar():
            resultado[0] = False
            dialogo.destroy()

        def _cancelar():
            resultado[0] = None
            dialogo.destroy()

        btn_cancelar = ttk.Button(f_btns, text="Cancelar", command=_cancelar)
        btn_cancelar.pack(side='right', padx=6)

        btn_conservar = ttk.Button(f_btns, text="Mantener Horario Original", command=_conservar)
        btn_conservar.pack(side='right', padx=6)

        btn_compactar = ttk.Button(f_btns, text="⚡ Sí, Compactar Horario", command=_aceptar)
        btn_compactar.pack(side='right', padx=6)

        sep = ttk.Separator(dialogo, orient='horizontal')
        sep.pack(side='bottom', fill='x', padx=16, pady=(4, 0))

        # 2. ÁREA CENTRAL DESPLAZABLE (Canvas con Scrollbar para garantizar visualización total)
        f_scroll_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_scroll_cont.pack(side='top', fill='both', expand=True, padx=16, pady=(14, 4))

        canvas = tk.Canvas(f_scroll_cont, background='#0A0F1E', highlightthickness=0, bd=0)
        sb_v = ttk.Scrollbar(f_scroll_cont, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=sb_v.set)

        sb_v.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        f_cont = ttk.Frame(canvas, style='blue.TFrame')
        canvas_window = canvas.create_window((0, 0), window=f_cont, anchor='nw')

        def _on_canvas_configure(evt):
            canvas.itemconfig(canvas_window, width=evt.width)
        canvas.bind('<Configure>', _on_canvas_configure)

        def _on_frame_configure(evt):
            canvas.configure(scrollregion=canvas.bbox("all"))
        f_cont.bind('<Configure>', _on_frame_configure)

        def _on_mousewheel(evt):
            try:
                delta = -1 if evt.delta < 0 else 1
                canvas.yview_scroll(delta * -1, "units")
            except Exception:
                pass

        def _bind_mousewheel(evt=None):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_mousewheel(evt=None):
            try:
                canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass

        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)
        dialogo.bind("<Destroy>", _unbind_mousewheel)

        # 3. CONTENIDO DEL DIÁLOGO
        ttk.Label(
            f_cont,
            text="⚡ Sugerencia: Compactación Continua de Jornada",
            background='#0A0F1E',
            foreground='#FFD700',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 6))

        ttk.Label(
            f_cont,
            text=f"El profesor {prof_nombre} ya cuenta con clases asignadas. El motor detectó una oportunidad para concentrar su asistencia en 2 días con clases corridas (sin tiempos muertos):",
            background='#0A0F1E',
            foreground='#CFD8DC',
            font=self._fuente_label,
            wraplength=670,
            justify='left'
        ).pack(anchor='w', pady=(0, 10))

        # Bloque 1: Clases asignadas actualmente
        f_exist = ttk.LabelFrame(f_cont, text=" Clases ya asignadas a este profesor ", style='blue.TFrame')
        f_exist.pack(fill='x', pady=4)
        txt_exist = "\n".join(compactacion['clases_actuales'][:6])
        ttk.Label(
            f_exist,
            text=txt_exist,
            background='#0A0F1E',
            foreground='#90CAF9',
            font=self._fuente_label,
            justify='left'
        ).pack(anchor='w', padx=12, pady=8)

        # Bloque 2: Comparativa de Horarios
        f_prop = ttk.LabelFrame(f_cont, text=" Comparativa de Asignación ", style='blue.TFrame')
        f_prop.pack(fill='x', pady=6)

        h_act = f"{asig_info.get('hora_inicio')} a {asig_info.get('hora_fin')} [{asig_info.get('dias')}] en Aula {asig_info.get('salon_id')}"
        tipo_continua = " (Clase corrida contigua)" if compactacion.get('es_continua') else " (Mismos días)"
        h_sug = f"{compactacion['hora_i']} a {compactacion['hora_f']} [{compactacion['dias_str']}] en Aula {compactacion['salon']}{tipo_continua}"

        f_grid = ttk.Frame(f_prop, style='blue.TFrame')
        f_grid.pack(fill='x', padx=10, pady=8)

        ttk.Label(f_grid, text="Horario Preasignado:", background='#0A0F1E', foreground='#B0BEC5', font=self._fuente_sub).grid(row=0, column=0, sticky='w', pady=3)
        ttk.Label(f_grid, text=h_act, background='#0A0F1E', foreground='#FFAB91', font=self._fuente_label, wraplength=490, justify='left').grid(row=0, column=1, sticky='w', padx=10, pady=3)

        ttk.Label(f_grid, text="Propuesta Compactada:", background='#0A0F1E', foreground='#B0BEC5', font=self._fuente_sub).grid(row=1, column=0, sticky='w', pady=3)
        ttk.Label(f_grid, text=h_sug, background='#0A0F1E', foreground='#A5D6A7', font=self._fuente_btn, wraplength=490, justify='left').grid(row=1, column=1, sticky='w', padx=10, pady=3)

        # Bloque 3: Reacomodo en el mismo salón (si aplica)
        desp = compactacion.get('desplazamiento')
        if desp:
            f_desp = ttk.LabelFrame(f_cont, text=" Reacomodo Interno (Mismo Salón) ", style='blue.TFrame')
            f_desp.pack(fill='x', pady=6)
            txt_desp = (
                f"• Para habilitar este horario corrido, la materia '{desp['materia_nombre']}' (Grupo {desp['grupo_id']}),\n"
                f"  que no tiene profesor asignado, se reubicará al horario {desp['nuevo_hora_i']} a {desp['nuevo_hora_f']} [{desp['nuevos_dias_str']}]\n"
                f"  dentro del mismo salón {desp['salon']}."
            )
            ttk.Label(
                f_desp,
                text=txt_desp,
                background='#0A0F1E',
                foreground='#FFE082',
                font=self._fuente_sub,
                wraplength=670,
                justify='left'
            ).pack(anchor='w', padx=12, pady=6)

        # Bloque 4: Lista de verificación de ventajas
        ttk.Label(
            f_cont,
            text=f"✔ Concentra la asistencia del profesor en 2 días.\n✔ Clases corridas sin horas libres intermedias.\n✔ Aula conservada: {compactacion['salon']}.\n✔ Sin afectar a ningún otro profesor.",
            background='#0A0F1E',
            foreground='#81C784',
            font=self._fuente_label,
            justify='left'
        ).pack(anchor='w', pady=(6, 12))

        dialogo.wait_window()
        return resultado[0]

    def _mostrar_modal_resolucion_conflicto(self, asig_info, prof_id, prof_nombre, choques, motivo_disp=""):
        dialogo = tk.Toplevel(self.ventana)
        dialogo.title("Conflicto de Horario / Disponibilidad")
        dialogo.transient(self.ventana)
        dialogo.grab_set()
        dialogo.configure(background='#0A0F1E')
        dialogo.geometry("680x570")
        dialogo.minsize(620, 480)
        dialogo.resizable(True, True)

        # Botones siempre anclados abajo
        f_btns = ttk.Frame(dialogo, style='blue.TFrame')
        f_btns.pack(side='bottom', fill='x', padx=18, pady=(10, 14))

        opcion_var = tk.StringVar(value="imponer")

        def ejecutar_resolucion():
            eleccion = opcion_var.get()
            dialogo.destroy()

            if eleccion == "cancelar":
                messagebox.showinfo("Cancelado", "Asignación cancelada. No se realizaron cambios.")
                return

            elif eleccion == "imponer":
                self._aplicar_vinculacion_docente(asig_info['asignacion_id'], prof_id, estado='pendiente')

            elif eleccion == "intercambiar":
                self._ejecutar_intercambio_profesor(asig_info, prof_id, prof_nombre, choques)

            elif eleccion == "reubicar":
                self._ejecutar_reubicacion_automatica(asig_info, prof_id, prof_nombre)

        ttk.Button(f_btns, text="Cerrar", command=dialogo.destroy).pack(side='right', padx=4)
        ttk.Button(f_btns, text="Confirmar y Aplicar", command=ejecutar_resolucion).pack(side='right', padx=4)

        sep = ttk.Separator(dialogo, orient='horizontal')
        sep.pack(side='bottom', fill='x', padx=16, pady=(4, 0))

        f_cont = ttk.Frame(dialogo, style='blue.TFrame')
        f_cont.pack(fill='both', expand=True, padx=18, pady=(14, 4))

        ttk.Label(
            f_cont,
            text="⚠ CONFLICTO DETECTADO AL ASIGNAR PROFESOR",
            background='#0A0F1E',
            foreground='#FF6B6B',
            font=self._fuente_titulo
        ).pack(anchor='w', pady=(0, 6))

        materia_txt = f"{asig_info['materia_id']} - {asig_info['materia_nombre']}"
        horario_txt = f"{asig_info['hora_inicio']} - {asig_info['hora_fin']} [{asig_info['dias']}] en Aula {asig_info['salon_id']}"
        detalles_txt = f"• Materia a vincular: {materia_txt}\n• Horario preasignado: {horario_txt}\n• Profesor seleccionado: {prof_nombre}\n\n"

        if choques:
            detalles_txt += "Cruce con otra(s) clase(s) del profesor:\n"
            for ch in choques:
                detalles_txt += f"  - {ch['dia']} ({ch['inicio']} - {ch['fin']}): {ch['materia']} (Grupo: {ch['grupo']})\n"
        if motivo_disp:
            detalles_txt += f"\nDisponibilidad:\n  - {motivo_disp}\n"

        txt_widget = tk.Text(f_cont, height=7, font=("Consolas", 10), bg='#111827', fg='#E5E7EB', relief='flat', bd=2)
        txt_widget.insert('1.0', detalles_txt)
        txt_widget.config(state='disabled')
        txt_widget.pack(fill='x', pady=6)

        ttk.Label(
            f_cont,
            text="Selecciona una opción para resolver este conflicto:",
            background='#0A0F1E',
            foreground='#FFD700',
            font=self._fuente_sub
        ).pack(anchor='w', pady=(8, 4))

        rb1 = ttk.Radiobutton(
            f_cont,
            text="1. Intercambiar profesor (Intercambiar con el docente de la otra clase en conflicto)",
            variable=opcion_var,
            value="intercambiar"
        )
        rb1.pack(anchor='w', pady=3)

        rb2 = ttk.Radiobutton(
            f_cont,
            text="2. Cancelar asignación (No realizar cambios y mantener sin profesor)",
            variable=opcion_var,
            value="cancelar"
        )
        rb2.pack(anchor='w', pady=3)

        rb3 = ttk.Radiobutton(
            f_cont,
            text="3. Imponer como pendiente (Asignar al profesor conservando el horario y marcar 'pendiente')",
            variable=opcion_var,
            value="imponer"
        )
        rb3.pack(anchor='w', pady=3)

        rb4 = ttk.Radiobutton(
            f_cont,
            text="4. Reubicar automáticamente (Buscar un aula u horario alternativo sin conflicto)",
            variable=opcion_var,
            value="reubicar"
        )
        rb4.pack(anchor='w', pady=3)

    def _ejecutar_intercambio_profesor(self, asig_info, prof_id, prof_nombre, choques):
        """
        Intercambia profesores:
        Asigna el prof_id a la materia actual, y si la materia actual tenía otro profesor,
        se intercambia con la clase en conflicto.
        """
        asig_id_actual = asig_info['asignacion_id']
        prof_id_anterior = asig_info.get('profesor_id')

        asig_conflicto_id = None
        if choques:
            # Buscar el asignacion_id de la clase en conflicto
            with obtener_cursor() as ctx:
                if ctx:
                    cur, conn = ctx
                    ch = choques[0]
                    cur.execute("""
                        SELECT a.asignacion_id FROM asignaciones a
                        JOIN materias m ON a.materia_id = m.materia_id
                        WHERE a.profesor_id = %s AND a.grupo_id = %s AND m.nombre = %s
                        LIMIT 1
                    """, (prof_id, ch['grupo'], ch['materia']))
                    row = cur.fetchone()
                    if row:
                        asig_conflicto_id = row[0]

        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            try:
                # Asignar prof_id a la materia actual
                cur.execute("UPDATE asignaciones SET profesor_id = %s, estado = 'asignado' WHERE asignacion_id = %s",
                            (prof_id, asig_id_actual))

                if asig_conflicto_id:
                    # El profesor anterior toma la clase que tenía el profesor_id
                    nuevo_profe_para_conflicto = prof_id_anterior if (prof_id_anterior and prof_id_anterior != 'SIN_ASIGNAR') else 'SIN_ASIGNAR'
                    cur.execute("UPDATE asignaciones SET profesor_id = %s, estado = %s WHERE asignacion_id = %s",
                                (nuevo_profe_para_conflicto, 'asignado' if nuevo_profe_para_conflicto != 'SIN_ASIGNAR' else 'no asignado', asig_conflicto_id))

                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"Error realizando intercambio: {err}")
                return

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo("Intercambio Realizado", "Se ha realizado el intercambio de profesores exitosamente.")

    def _ejecutar_reubicacion_automatica(self, asig_info, prof_id, prof_nombre):
        """
        Busca otro bloque libre para esta materia y aula o profesor que no tenga choques.
        """
        asig_id = asig_info['asignacion_id']
        grupo_id = self._sv_grupo_gestion.get().strip()
        materia_id = asig_info['materia_id']
        salon_id = asig_info['salon_id'].split(',')[0].strip() if asig_info.get('salon_id') else 'Normal'

        dias_alternativos = [("Lunes", "Miércoles"), ("Martes", "Jueves"), ("Miércoles", "Viernes")]
        horas_alternativas = [
            ("07:00", "09:00"), ("09:00", "11:00"), ("11:00", "13:00"),
            ("13:00", "15:00"), ("15:00", "17:00")
        ]

        encontrado = None

        # Prioridad 1: Compactar en los mismos días del profesor con horario continuo
        comp = self._detectar_compactacion_docente(
            prof_id=prof_id,
            asig_id=asig_id,
            materia_id=materia_id,
            grupo_id=grupo_id,
            modalidad='Presencial',
            aula_actual=salon_id
        )
        if comp and comp.get("encontrado"):
            encontrado = (tuple(comp['dias']), comp['hora_i'], comp['hora_f'])
            if comp.get('salon'):
                salon_id = comp['salon']

        # Prioridad 2: Buscar en parejas estándar si no se pudo compactar
        if not encontrado:
            for pareja in dias_alternativos:
                dias_str = ", ".join(pareja)
                for hi, hf in horas_alternativas:
                    choques_g = self._detectar_choques_grupo(grupo_id, materia_id, list(pareja), hi, hf)
                    if choques_g:
                        continue
                    choques_p = self._detectar_choques_profesor(prof_id, materia_id, grupo_id, 'Presencial', list(pareja), hi, hf)
                    if choques_p:
                        continue
                    encontrado = (pareja, hi, hf)
                    break
                if encontrado:
                    break

        if not encontrado:
            # Si no encuentra espacio idéntico, asigna con estado pendiente
            self._aplicar_vinculacion_docente(asig_id, prof_id, estado='pendiente')
            messagebox.showwarning(
                "Reubicación Compleja",
                "No se encontró un bloque automático libre sin choques.\n"
                "La asignación se guardó como 'PENDIENTE' para que se ajuste manualmente."
            )
            return

        pareja, hi, hf = encontrado
        dias_str = ", ".join(pareja)

        with obtener_cursor() as ctx:
            if not ctx:
                return
            cur, conn = ctx
            try:
                # Actualizar asignación
                cur.execute("""
                    UPDATE asignaciones
                    SET profesor_id = %s, hora_inicio = %s, hora_fin = %s, dias = %s, estado = 'asignado'
                    WHERE asignacion_id = %s
                """, (prof_id, hi, hf, dias_str, asig_id))

                # Actualizar sesiones en horarios
                cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (asig_id,))
                for d in pareja:
                    cur.execute("""
                        INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (asig_id, salon_id if salon_id != "Sin aula" else "F10", d, f"{hi}:00", f"{hf}:00"))

                conn.commit()
            except sqlite3.Error as err:
                conn.rollback()
                messagebox.showerror("Error", f"Error al reubicar: {err}")
                return

        self._cargar_materias_grupo_gestion()
        self.actualizar_vista_previa()
        self._cargar_previa_horario_grupo()
        self._cargar_tensor_diferido(forzar=True)
        messagebox.showinfo(
            "Reubicación Exitosa",
            f"La materia fue reubicada automáticamente sin conflictos:\n\n"
            f"• Días: {dias_str}\n"
            f"• Horario: {hi} a {hf}\n"
            f"• Profesor: {prof_nombre}"
        )

    def _dia_a_indice_previa(self, dia):
        dia_normalizado = self._normalizar_dia(dia)
        if dia_normalizado.isdigit():
            indice = int(dia_normalizado)
            return indice if 0 <= indice < len(self.NOMBRES_DIAS) else None
        for indice, nombre in enumerate(self.NOMBRES_DIAS):
            if self._normalizar_dia(nombre) == dia_normalizado:
                return indice
        return None

    @staticmethod
    def _minutos_hora_previa(hora):
        if isinstance(hora, datetime.timedelta):
            segundos = int(hora.total_seconds())
            return (segundos // 3600) * 60 + (segundos % 3600) // 60
        if isinstance(hora, datetime.time):
            return hora.hour * 60 + hora.minute
        partes = str(hora).split(':')
        try:
            return int(partes[0]) * 60 + int(partes[1])
        except (ValueError, IndexError):
            return None

    def _detectar_choques_profesor(
        self, profesor_id, materia_id, grupo_id, modalidad, dias, hora_i, hora_f, excluir_asignacion_id=None
    ):
        inicio = self._minutos_hora_previa(hora_i)
        fin = self._minutos_hora_previa(hora_f)
        dias_propuestos = {
            indice for indice in (self._dia_a_indice_previa(dia) for dia in dias)
            if indice is not None
        }
        if inicio is None or fin is None or fin <= inicio or not dias_propuestos:
            return []

        choques = []
        with obtener_cursor_dict() as ctx:
            if ctx is None:
                raise RuntimeError("No hay conexión a la base de datos para validar el horario.")
            cur, conn = ctx
            if excluir_asignacion_id is not None:
                excluir_id = excluir_asignacion_id
            else:
                cur.execute(
                    """
                    SELECT asignacion_id
                    FROM asignaciones
                    WHERE profesor_id = %s
                      AND materia_id = %s
                      AND grupo_id = %s
                      AND modalidad = %s
                      AND (estado IS NULL OR estado != 'cancelada')
                    ORDER BY asignacion_id
                    LIMIT 1
                    """,
                    (profesor_id, materia_id, grupo_id, modalidad)
                )
                asignacion_existente = cur.fetchone()
                excluir_id = asignacion_existente['asignacion_id'] if asignacion_existente else None

            cur.execute(
                """
                SELECT a.asignacion_id, a.dias, a.hora_inicio AS asignacion_inicio,
                       a.hora_fin AS asignacion_fin, a.grupo_id,
                       m.nombre AS materia, h.dia AS horario_dia,
                       h.hora_inicio AS horario_inicio, h.hora_fin AS horario_fin
                FROM asignaciones a
                LEFT JOIN materias m ON m.materia_id = a.materia_id
                LEFT JOIN horarios h ON h.asignacion_id = a.asignacion_id
                WHERE a.profesor_id = %s
                  AND a.asignacion_id IS NOT ?
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
                """,
                (profesor_id, excluir_id)
            )
            for fila in cur.fetchall():
                if fila['horario_dia'] is not None:
                    horarios_existentes = [{
                        "dia": fila['horario_dia'],
                        "inicio": fila['horario_inicio'],
                        "fin": fila['horario_fin']
                    }]
                else:
                    horarios_existentes = [
                        {
                            "dia": dia.strip(),
                            "inicio": fila['asignacion_inicio'],
                            "fin": fila['asignacion_fin']
                        }
                        for dia in (fila.get('dias') or "").split(',')
                        if dia.strip()
                    ]

                for horario in horarios_existentes:
                    indice_dia = self._dia_a_indice_previa(horario['dia'])
                    inicio_existente = self._minutos_hora_previa(horario['inicio'])
                    fin_existente = self._minutos_hora_previa(horario['fin'])
                    if (
                        indice_dia in dias_propuestos
                        and inicio_existente is not None
                        and fin_existente is not None
                        and inicio < fin_existente
                        and fin > inicio_existente
                    ):
                        choques.append({
                            "dia": self.NOMBRES_DIAS[indice_dia],
                            "inicio": horario['inicio'],
                            "fin": horario['fin'],
                            "materia": fila.get('materia') or "Materia sin nombre",
                            "grupo": fila['grupo_id']
                        })
        return choques

    def _detectar_choques_grupo(self, grupo_id, materia_id, dias, hora_i, hora_f, excluir_asignacion_id=None):
        inicio = self._minutos_hora_previa(hora_i)
        fin = self._minutos_hora_previa(hora_f)
        dias_propuestos = {
            indice for indice in (self._dia_a_indice_previa(dia) for dia in dias)
            if indice is not None
        }
        if inicio is None or fin is None or fin <= inicio or not dias_propuestos:
            return []

        choques = []
        with obtener_cursor_dict() as ctx:
            if ctx is None:
                raise RuntimeError("No hay conexión a la base de datos para validar el horario.")
            cur, conn = ctx
            if excluir_asignacion_id is not None:
                cond_asig = "AND a.asignacion_id <> %s"
                param_asig = excluir_asignacion_id
            else:
                cond_asig = "AND a.materia_id <> %s"
                param_asig = materia_id
            cur.execute(
                f"""
                SELECT a.asignacion_id, a.dias, a.hora_inicio AS asignacion_inicio,
                       a.hora_fin AS asignacion_fin, m.nombre AS materia,
                       h.dia AS horario_dia, h.hora_inicio AS horario_inicio,
                       h.hora_fin AS horario_fin
                FROM asignaciones a
                LEFT JOIN materias m ON m.materia_id = a.materia_id
                LEFT JOIN horarios h ON h.asignacion_id = a.asignacion_id
                WHERE a.grupo_id = %s
                  {cond_asig}
                  AND (a.estado IS NULL OR a.estado != 'cancelada')
                """,
                (grupo_id, param_asig)
            )
            for fila in cur.fetchall():
                if fila['horario_dia'] is not None:
                    horarios_existentes = [{
                        "dia": fila['horario_dia'],
                        "inicio": fila['horario_inicio'],
                        "fin": fila['horario_fin']
                    }]
                else:
                    horarios_existentes = [
                        {
                            "dia": dia.strip(),
                            "inicio": fila['asignacion_inicio'],
                            "fin": fila['asignacion_fin']
                        }
                        for dia in (fila.get('dias') or "").split(',')
                        if dia.strip()
                    ]

                for horario in horarios_existentes:
                    indice_dia = self._dia_a_indice_previa(horario['dia'])
                    inicio_existente = self._minutos_hora_previa(horario['inicio'])
                    fin_existente = self._minutos_hora_previa(horario['fin'])
                    if (
                        indice_dia in dias_propuestos
                        and inicio_existente is not None
                        and fin_existente is not None
                        and inicio < fin_existente
                        and fin > inicio_existente
                    ):
                        choques.append({
                            "dia": self.NOMBRES_DIAS[indice_dia],
                            "inicio": horario['inicio'],
                            "fin": horario['fin'],
                            "materia": fila.get('materia') or "Materia sin nombre"
                        })
        return choques
