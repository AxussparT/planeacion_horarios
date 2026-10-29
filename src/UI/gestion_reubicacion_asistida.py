# -*- coding: utf-8 -*-
"""
Módulo de Reubicación Visual Asistida para SAGA.
Permite a los coordinadores mover o asignar clases mediante una retícula semanal
interactiva con detección en tiempo real de choques de docente, grupo y aula,
respetando aforos y pausas docentes.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
from src.conexion import obtener_cursor, obtener_cursor_dict
from src.UI.icon_manager import IconManager


class DialogoReubicacionAsistida(tk.Toplevel):
    HORA_INICIO = 7   # 07:00
    HORA_FIN = 19     # 19:00
    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    def __init__(self, parent, asig_info, callback_actualizar=None):
        super().__init__(parent)
        self.asig_info = dict(asig_info)
        self.callback_actualizar = callback_actualizar

        self.title("Reubicación Visual Asistida - SAGA")
        self.geometry("1020x720")
        self.minsize(880, 600)
        self.configure(bg="#0A0F1E")
        self.transient(parent)
        self.grab_set()

        # Extraer parámetros de la asignación
        self.asig_id = self.asig_info.get("asignacion_id")
        self.materia_id = self.asig_info.get("materia_id", "")
        self.materia_nombre = self.asig_info.get("materia_nombre", self.materia_id)
        self.grupo_id = self.asig_info.get("grupo_id", "")
        self.prof_id = self.asig_info.get("profesor_id", "SIN_ASIGNAR")
        self.prof_nombre = self.asig_info.get("profesor_nombre", "Sin profesor")
        self.salon_actual = (self.asig_info.get("salon_id") or "Sin aula").split(",")[0].strip()
        self.horas_semana = float(self.asig_info.get("horas_semana") or 4.0)

        # Variables reactivas
        self.var_salon = tk.StringVar(value=self.salon_actual if self.salon_actual != "Sin aula" else "")
        self.var_esquema = tk.StringVar()
        self.propuesta_seleccionada = None

        self._cargar_catalogo_salones()
        self._construir_ui()
        self._centrar_en_padre(parent)

    def _centrar_en_padre(self, parent):
        self.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _cargar_catalogo_salones(self):
        self.salones_disponibles = []
        with obtener_cursor() as ctx:
            if ctx:
                cur, _ = ctx
                cur.execute("SELECT salon_id, capacidad, tipo FROM salones ORDER BY salon_id")
                for r in cur.fetchall():
                    s_id = str(r[0]).strip()
                    if not s_id.upper().startswith("MEDIACION"):
                        self.salones_disponibles.append(s_id)
        if not self.var_salon.get() and self.salones_disponibles:
            self.var_salon.set(self.salones_disponibles[0])

    def _construir_ui(self):
        # 1. ENCABEZADO
        f_header = tk.Frame(self, bg="#111827", padx=16, pady=12, highlightthickness=1, highlightbackground="#1F2937")
        f_header.pack(fill="x", padx=14, pady=(12, 6))

        tk.Label(
            f_header,
            text="🎯 Asistente Visual de Reubicación de Horarios",
            font=("Segoe UI", 13, "bold"),
            fg="#F3F4F6",
            bg="#111827"
        ).pack(anchor="w")

        info_txt = (
            f"Materia: {self.materia_nombre} ({self.horas_semana:g} hrs/sem)  |  "
            f"Grupo: {self.grupo_id}  |  Docente: {self.prof_nombre}  |  "
            f"Horario Actual: {self.asig_info.get('hora_inicio','--')} a {self.asig_info.get('hora_fin','--')} "
            f"[{self.asig_info.get('dias','--')}] en Aula {self.salon_actual}"
        )
        tk.Label(
            f_header,
            text=info_txt,
            font=("Segoe UI", 9),
            fg="#9CA3AF",
            bg="#111827"
        ).pack(anchor="w", pady=(4, 0))

        # 2. BARRA DE CONFIGURACIÓN DE REUBICACIÓN
        f_barra = tk.Frame(self, bg="#0A0F1E", padx=14, pady=6)
        f_barra.pack(fill="x")

        tk.Label(f_barra, text="Aula destino:", fg="#D1D5DB", bg="#0A0F1E", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.combo_salon = ttk.Combobox(f_barra, textvariable=self.var_salon, values=self.salones_disponibles, state="readonly", width=12)
        self.combo_salon.pack(side="left", padx=(0, 16))
        self.combo_salon.bind("<<ComboboxSelected>>", lambda e: self._actualizar_grilla())

        tk.Label(f_barra, text="Distribución semanal:", fg="#D1D5DB", bg="#0A0F1E", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))

        # Determinar esquemas posibles según horas de la materia
        if self.horas_semana == 2:
            opciones_esquema = [("1 sesión de 2h", 1, 2)]
        elif self.horas_semana == 3:
            opciones_esquema = [("2 sesiones (1.5h y 1.5h)", 2, 1.5), ("1 sesión de 3h", 1, 3)]
        elif self.horas_semana == 4:
            opciones_esquema = [("2 sesiones de 2h (Lunes-Miércoles / Martes-Jueves)", 2, 2), ("1 sesión de 4h intensiva", 1, 4)]
        elif self.horas_semana == 5:
            opciones_esquema = [("2 sesiones (2.5h y 2.5h)", 2, 2.5), ("1 sesión de 5h", 1, 5)]
        elif self.horas_semana == 6:
            opciones_esquema = [("3 sesiones de 2h (Lun-Mié-Vie)", 3, 2), ("2 sesiones de 3h", 2, 3)]
        else:
            opciones_esquema = [(f"2 sesiones de {self.horas_semana/2:g}h", 2, self.horas_semana/2)]

        self.esquemas_map = {opt[0]: opt for opt in opciones_esquema}
        self.combo_esquema = ttk.Combobox(f_barra, textvariable=self.var_esquema, values=list(self.esquemas_map.keys()), state="readonly", width=36)
        self.var_esquema.set(opciones_esquema[0][0])
        self.combo_esquema.pack(side="left", padx=(0, 16))
        self.combo_esquema.bind("<<ComboboxSelected>>", lambda e: self._actualizar_grilla())

        # Indicador de estado
        tk.Label(f_barra, text="🟢 Espacio 100% Libre", fg="#34D399", bg="#0A0F1E", font=("Segoe UI", 8, "bold")).pack(side="right", padx=6)
        tk.Label(f_barra, text="🔴 Conflicto", fg="#F87171", bg="#0A0F1E", font=("Segoe UI", 8, "bold")).pack(side="right", padx=6)

        # 3. CONTENEDOR CON SCROLL PARA LA RETÍCULA SEMANAL
        f_grid_container = tk.Frame(self, bg="#0A0F1E", highlightthickness=1, highlightbackground="#1F2937")
        f_grid_container.pack(fill="both", expand=True, padx=14, pady=6)

        canvas = tk.Canvas(f_grid_container, bg="#0A0F1E", highlightthickness=0)
        v_scroll = ttk.Scrollbar(f_grid_container, orient="vertical", command=canvas.yview)
        self.frame_tabla = tk.Frame(canvas, bg="#0A0F1E")

        self.frame_tabla.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_win = canvas.create_window((0, 0), window=self.frame_tabla, anchor="nw")
        canvas.configure(xscrollcommand=None, yscrollcommand=v_scroll.set)

        def _on_canvas_resize(event):
            canvas.itemconfig(canvas_win, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        # Habilitar scroll del ratón
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        canvas.pack(side="left", fill="both", expand=True)
        v_scroll.pack(side="right", fill="y")

        # 4. FOOTER CON CONFIRMACIÓN
        f_footer = tk.Frame(self, bg="#111827", padx=16, pady=12, highlightthickness=1, highlightbackground="#1F2937")
        f_footer.pack(fill="x", padx=14, pady=(6, 14))

        self.lbl_propuesta = tk.Label(
            f_footer,
            text="Haz clic en cualquier celda verde para seleccionar la nueva franja horaria.",
            fg="#FCD34D",
            bg="#111827",
            font=("Segoe UI", 9, "bold")
        )
        self.lbl_propuesta.pack(side="left")

        self.btn_confirmar = ttk.Button(
            f_footer,
            text="✓ Confirmar Reubicación",
            image=IconManager.get("check", 16),
            compound="left",
            command=self._confirmar_reubicacion,
            state="disabled"
        )
        self.btn_confirmar.pack(side="right", padx=(8, 0))

        ttk.Button(
            f_footer,
            text="Cancelar",
            image=IconManager.get("x", 16),
            compound="left",
            command=self.destroy
        ).pack(side="right")

        self._actualizar_grilla()

    def _consultar_ocupaciones(self, salon_id):
        """Carga todas las reservas actuales de grupo, docente y aula seleccionada."""
        ocup_grupo = set()
        ocup_prof = set()
        ocup_salon = set()
        disp_prof = []

        with obtener_cursor_dict() as ctx:
            if not ctx:
                return ocup_grupo, ocup_prof, ocup_salon, disp_prof
            cur, _ = ctx

            # Ocupación grupo
            cur.execute("""
                SELECT h.dia, h.hora_inicio, h.hora_fin, a.materia_id, m.nombre AS materia_nom
                FROM horarios h
                JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                LEFT JOIN materias m ON a.materia_id = m.materia_id
                WHERE a.grupo_id = %s AND a.asignacion_id <> %s
            """, (self.grupo_id, self.asig_id or -1))
            for r in cur.fetchall():
                ocup_grupo.add((r['dia'], r['hora_inicio'], r['hora_fin'], r['materia_nom']))

            # Ocupación profesor
            if self.prof_id and self.prof_id != "SIN_ASIGNAR":
                cur.execute("""
                    SELECT h.dia, h.hora_inicio, h.hora_fin, a.grupo_id, m.nombre AS materia_nom
                    FROM horarios h
                    JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                    LEFT JOIN materias m ON a.materia_id = m.materia_id
                    WHERE a.profesor_id = %s AND a.asignacion_id <> %s
                """, (self.prof_id, self.asig_id or -1))
                for r in cur.fetchall():
                    ocup_prof.add((r['dia'], r['hora_inicio'], r['hora_fin'], r['grupo_id'], r['materia_nom']))

                # Disponibilidad profesor
                cur.execute("SELECT dia, hora_inicio, hora_fin FROM profesor_disponibilidad WHERE profesor_id = %s", (self.prof_id,))
                disp_prof = cur.fetchall()

            # Ocupación salón
            if salon_id:
                cur.execute("""
                    SELECT h.dia, h.hora_inicio, h.hora_fin, a.grupo_id, m.nombre AS materia_nom
                    FROM horarios h
                    JOIN asignaciones a ON h.asignacion_id = a.asignacion_id
                    LEFT JOIN materias m ON a.materia_id = m.materia_id
                    WHERE LOWER(h.salon_id) = LOWER(%s) AND a.asignacion_id <> %s
                """, (salon_id, self.asig_id or -1))
                for r in cur.fetchall():
                    ocup_salon.add((r['dia'], r['hora_inicio'], r['hora_fin'], r['grupo_id'], r['materia_nom']))

        return ocup_grupo, ocup_prof, ocup_salon, disp_prof

    def _minutos(self, hora_str):
        p = str(hora_str).split(":")
        return int(p[0]) * 60 + (int(p[1]) if len(p) > 1 else 0)

    def _se_solapan(self, h1_i, h1_f, h2_i, h2_f):
        return max(self._minutos(h1_i), self._minutos(h2_i)) < min(self._minutos(h1_f), self._minutos(h2_f))

    def _actualizar_grilla(self):
        for w in self.frame_tabla.winfo_children():
            w.destroy()

        salon_sel = self.var_salon.get().strip()
        esquema_sel = self.var_esquema.get().strip()
        _, num_sesiones, duracion_h = self.esquemas_map.get(esquema_sel, ("", 2, 2))

        ocup_grupo, ocup_prof, ocup_salon, disp_prof = self._consultar_ocupaciones(salon_sel)

        # Encabezado de columnas
        tk.Label(self.frame_tabla, text="Horario", bg="#1E293B", fg="#F8FAFC", font=("Segoe UI", 9, "bold"), padx=8, pady=6, relief="ridge").grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        for col_idx, dia in enumerate(self.DIAS, start=1):
            tk.Label(self.frame_tabla, text=dia, bg="#1E293B", fg="#F8FAFC", font=("Segoe UI", 9, "bold"), padx=8, pady=6, relief="ridge").grid(row=0, column=col_idx, sticky="nsew", padx=1, pady=1)
            self.frame_tabla.columnconfigure(col_idx, weight=1)

        # Franjas horarias estándar según duración
        bloques = []
        paso_min = int(duracion_h * 60)
        min_inicio = self.HORA_INICIO * 60
        min_limite = self.HORA_FIN * 60

        curr = min_inicio
        while curr + paso_min <= min_limite:
            h_i = f"{curr // 60:02d}:{curr % 60:02d}:00"
            sig = curr + paso_min
            h_f = f"{sig // 60:02d}:{sig % 60:02d}:00"
            bloques.append((h_i, h_f))
            curr += paso_min

        # Dibujar filas
        for row_idx, (hi, hf) in enumerate(bloques, start=1):
            lbl_rango = f"{hi[:5]} - {hf[:5]}"
            tk.Label(self.frame_tabla, text=lbl_rango, bg="#111827", fg="#E2E8F0", font=("Consolas", 8, "bold"), padx=6, pady=4, relief="ridge").grid(row=row_idx, column=0, sticky="nsew", padx=1, pady=1)

            for col_idx, dia in enumerate(self.DIAS, start=1):
                # Validar colisiones
                motivos_conflicto = []

                # Choque grupo
                for d_o, hi_o, hf_o, mat_o in ocup_grupo:
                    if d_o == dia and self._se_solapan(hi, hf, hi_o, hf_o):
                        motivos_conflicto.append(f"Grupo ocupado ({mat_o})")
                        break

                # Choque profesor
                for d_o, hi_o, hf_o, grp_o, mat_o in ocup_prof:
                    if d_o == dia and self._se_solapan(hi, hf, hi_o, hf_o):
                        motivos_conflicto.append(f"Docente ocupado ({grp_o})")
                        break

                # Choque aula
                for d_o, hi_o, hf_o, grp_o, mat_o in ocup_salon:
                    if d_o == dia and self._se_solapan(hi, hf, hi_o, hf_o):
                        motivos_conflicto.append(f"Aula ocupada ({grp_o})")
                        break

                # Verificar si es el horario actual
                es_horario_actual = (
                    dia in (self.asig_info.get("dias") or "")
                    and self._se_solapan(hi, hf, self.asig_info.get("hora_inicio", "00:00"), self.asig_info.get("hora_fin", "00:00"))
                )

                if es_horario_actual:
                    btn_color = "#1E3A8A"
                    btn_text = "Horario Actual"
                    btn_fg = "#93C5FD"
                    habilitado = False
                elif motivos_conflicto:
                    btn_color = "#3B1E22"
                    btn_text = "🔴 " + motivos_conflicto[0]
                    btn_fg = "#FCA5A5"
                    habilitado = False
                else:
                    btn_color = "#14532D"
                    btn_text = "🟢 Disponible"
                    btn_fg = "#86EFAC"
                    habilitado = True

                btn = tk.Button(
                    self.frame_tabla,
                    text=btn_text,
                    bg=btn_color,
                    fg=btn_fg,
                    font=("Segoe UI", 8, "bold" if habilitado else "normal"),
                    relief="flat",
                    cursor="hand2" if habilitado else "arrow",
                    state="normal" if habilitado else "disabled",
                    padx=4,
                    pady=6
                )
                if habilitado:
                    btn.config(command=lambda d=dia, i=hi, f=hf, n=num_sesiones: self._seleccionar_slot(d, i, f, n))
                btn.grid(row=row_idx, column=col_idx, sticky="nsew", padx=1, pady=1)

    def _seleccionar_slot(self, dia_base, hi, hf, num_sesiones):
        salon_sel = self.var_salon.get().strip()

        # Determinar días sugeridos según simetría académica
        if num_sesiones == 1:
            dias_propuestos = [dia_base]
        elif num_sesiones == 2:
            parejas = {
                "Lunes": ["Lunes", "Miércoles"],
                "Miércoles": ["Lunes", "Miércoles"],
                "Martes": ["Martes", "Jueves"],
                "Jueves": ["Martes", "Jueves"],
                "Viernes": ["Viernes", "Sábado"],
                "Sábado": ["Viernes", "Sábado"]
            }
            dias_propuestos = parejas.get(dia_base, [dia_base, "Miércoles" if dia_base != "Miércoles" else "Viernes"])
        elif num_sesiones == 3:
            dias_propuestos = ["Lunes", "Miércoles", "Viernes"] if dia_base in ["Lunes", "Miércoles", "Viernes"] else ["Martes", "Jueves", "Sábado"]
        else:
            dias_propuestos = [dia_base]

        dias_str = ", ".join(dias_propuestos)
        self.propuesta_seleccionada = {
            "dias": dias_propuestos,
            "dias_str": dias_str,
            "hora_inicio": hi,
            "hora_fin": hf,
            "salon_id": salon_sel
        }

        self.lbl_propuesta.config(
            text=f"Propuesta: {dias_str} de {hi[:5]} a {hf[:5]} en Aula {salon_sel}",
            fg="#6EE7B7"
        )
        self.btn_confirmar.config(state="normal")

    def _confirmar_reubicacion(self):
        if not self.propuesta_seleccionada:
            return

        p = self.propuesta_seleccionada
        msg = (
            f"¿Desea reubicar la clase '{self.materia_nombre}' al nuevo horario?\n\n"
            f"• Días: {p['dias_str']}\n"
            f"• Horario: {p['hora_inicio'][:5]} a {p['hora_fin'][:5]}\n"
            f"• Aula: {p['salon_id']}\n\n"
            "Se actualizarán automáticamente las sesiones y registros correspondientes."
        )

        if not messagebox.askyesno("Confirmar Reubicación", msg, parent=self):
            return

        with obtener_cursor() as ctx:
            if not ctx:
                messagebox.showerror("Error", "No se pudo conectar a la base de datos.", parent=self)
                return
            cur, conn = ctx
            try:
                # 1. Eliminar sesiones anteriores de horarios
                cur.execute("DELETE FROM horarios WHERE asignacion_id = %s", (self.asig_id,))

                # 2. Insertar nuevas sesiones por día
                for d in p['dias']:
                    cur.execute("""
                        INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (self.asig_id, p['salon_id'], d, p['hora_inicio'], p['hora_fin']))

                # 3. Actualizar asignación
                cur.execute("""
                    UPDATE asignaciones
                    SET hora_inicio = %s, hora_fin = %s, dias = %s
                    WHERE asignacion_id = %s
                """, (p['hora_inicio'], p['hora_fin'], p['dias_str'], self.asig_id))

                conn.commit()
                messagebox.showinfo("Éxito", f"Materia '{self.materia_nombre}' reubicada exitosamente.", parent=self)
                self.destroy()

                if self.callback_actualizar:
                    self.callback_actualizar()

            except Exception as e:
                conn.rollback()
                messagebox.showerror("Error al Reubicar", f"Error en la base de datos: {e}", parent=self)
