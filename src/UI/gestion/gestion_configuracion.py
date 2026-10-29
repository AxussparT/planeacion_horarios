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

class GestionConfiguracionMixin:
    def _guardar_configuracion(self, filepath=None):
        if not filepath:
            filepath = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json")],
                title="Guardar Configuración de Periodos y Asignaciones"
            )
            if not filepath:
                return False

        exito, total_asigs = self._escribir_config_en(filepath)
        if exito:
            messagebox.showinfo(
                "Configuración Guardada",
                f"Configuración guardada exitosamente en:\n{filepath}\n\n"
                f"Total de asignaciones respaldadas: {total_asigs}\n"
                f"Los datos activos en la base de datos se conservan intactos."
            )
            return True
        return False

    def _actualizar_configuracion(self):
        if not self._ultimo_config_path or not os.path.exists(self._ultimo_config_path):
            if not messagebox.askyesno("Sin archivo",
                    "No hay un archivo de configuración previo.\n¿Deseas elegir una ubicación para guardar?"):
                return
            self._guardar_configuracion()
            return
        exito, total_asigs = self._escribir_config_en(self._ultimo_config_path)
        if exito:
            messagebox.showinfo(
                "Configuración Actualizada",
                f"Configuración actualizada correctamente en:\n{self._ultimo_config_path}\n\n"
                f"Total de asignaciones respaldadas: {total_asigs}"
            )

    def _escribir_config_en(self, filepath):
        self._progress_config.pack(side='left', padx=5)
        self._progress_config["value"] = 0
        self.ventana.update_idletasks()
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return False, 0
                cur, conn = ctx

                # 1. Limpiar registros de disponibilidad inválidos
                cur.execute("DELETE FROM profesor_disponibilidad WHERE dia NOT IN ('0','1','2','3','4','5','6')")
                conn.commit()

                # 2. Catálogo de Materias
                cur.execute("SELECT materia_id, nombre, horas_semana, semestre_id, tipo FROM materias ORDER BY materia_id")
                materias_catalog = []
                for m_id, m_nombre, m_hs, m_sem, m_tipo in cur.fetchall():
                    materias_catalog.append({
                        "materia_id": m_id,
                        "nombre": m_nombre,
                        "horas_semana": str(m_hs) if m_hs else "4",
                        "semestre_id": m_sem,
                        "tipo": m_tipo or "Normal"
                    })

                # 3. Catálogo de Salones
                cur.execute("SELECT salon_id, capacidad, tipo FROM salones ORDER BY salon_id")
                salones_catalog = []
                for s_id, s_cap, s_tipo in cur.fetchall():
                    salones_catalog.append({
                        "salon_id": s_id,
                        "capacidad": s_cap,
                        "tipo": s_tipo or "Normal"
                    })

                # 4. Catálogo de Grupos
                cur.execute("SELECT grupo_id, nivel FROM grupos ORDER BY nivel, grupo_id")
                grupos_catalog = []
                for g_id, g_nivel in cur.fetchall():
                    grupos_catalog.append({
                        "grupo_id": g_id,
                        "nivel": g_nivel
                    })

                # 5. Grupo-Materias (vínculos curriculares)
                cur.execute("SELECT grupo_id, materia_id FROM grupo_materias ORDER BY grupo_id, materia_id")
                grupo_materias_catalog = []
                for g_id, m_id in cur.fetchall():
                    grupo_materias_catalog.append({
                        "grupo_id": g_id,
                        "materia_id": m_id
                    })

                # 6. Catálogo de Profesores
                cur.execute("""
                    SELECT profesor_id, no_cuenta, nombre, correo_institucional,
                           disponible_inicio, disponible_fin, dias_disponibles, en_linea
                    FROM profesores ORDER BY nombre
                """)
                profesores_catalog = []
                for row in cur.fetchall():
                    pid, ncta, nom, correo, di, df, dd, enl = row
                    profesores_catalog.append({
                        "profesor_id": pid,
                        "no_cuenta": ncta or "",
                        "nombre": nom,
                        "correo_institucional": correo or "",
                        "disponible_inicio": self._hora_db_a_str(di) if di else None,
                        "disponible_fin": self._hora_db_a_str(df) if df else None,
                        "dias_disponibles": dd or "",
                        "en_linea": enl or "NO"
                    })

                # 7. Disponibilidad de Profesores
                cur.execute("""
                    SELECT profesor_id, dia, hora_inicio, hora_fin, modalidad
                    FROM profesor_disponibilidad
                    WHERE dia != '6'
                    ORDER BY profesor_id, dia, hora_inicio
                """)
                disp_catalog = []
                for pid, dia, hi, hf, modal in cur.fetchall():
                    disp_catalog.append({
                        "profesor_id": pid,
                        "dia": dia,
                        "hora_inicio": self._hora_db_a_str(hi),
                        "hora_fin": self._hora_db_a_str(hf),
                        "modalidad": modal or "Presencial"
                    })

                # 8. Todas las Asignaciones activas con sus Horarios
                cur.execute("""
                    SELECT asignacion_id, profesor_id, materia_id, grupo_id,
                           periodo, hora_inicio, hora_fin, dias, modalidad, estado
                    FROM asignaciones
                    WHERE estado IS NULL OR estado != 'cancelada'
                    ORDER BY grupo_id, materia_id
                """)
                asig_rows = cur.fetchall()
                asignaciones_catalog = []
                total_asigs = len(asig_rows)

                for idx, row in enumerate(asig_rows):
                    asig_id, p_id, m_id, g_id, per, hi, hf, dias, modal, est = row
                    cur.execute("""
                        SELECT salon_id, dia, hora_inicio, hora_fin
                        FROM horarios
                        WHERE asignacion_id = %s
                        ORDER BY dia, hora_inicio
                    """, (asig_id,))
                    horarios_list = []
                    for s_id, h_dia, h_hi, h_hf in cur.fetchall():
                        horarios_list.append({
                            "salon_id": s_id,
                            "dia": h_dia,
                            "hora_inicio": self._hora_db_a_str(h_hi),
                            "hora_fin": self._hora_db_a_str(h_hf)
                        })

                    asignaciones_catalog.append({
                        "asignacion_id": asig_id,
                        "profesor_id": p_id if p_id else "SIN_ASIGNAR",
                        "materia_id": m_id,
                        "grupo_id": str(g_id),
                        "periodo": per or "A",
                        "hora_inicio": self._hora_db_a_str(hi),
                        "hora_fin": self._hora_db_a_str(hf),
                        "dias": dias or "",
                        "modalidad": modal or "Presencial",
                        "estado": est or "pendiente",
                        "horarios": horarios_list
                    })

                    if total_asigs > 0:
                        self._progress_config["value"] = ((idx + 1) / total_asigs) * 90
                        if idx % 10 == 0:
                            self.ventana.update_idletasks()

                # Profesores formato v1 para retrocompatibilidad
                profesores_v1 = []
                for p_info in profesores_catalog:
                    pid = p_info["profesor_id"]
                    p_disps = [d for d in disp_catalog if d["profesor_id"] == pid]
                    periods_map = {}
                    for d in p_disps:
                        clave = f"{d['hora_inicio']}-{d['hora_fin']}-{d['modalidad']}"
                        if clave not in periods_map:
                            periods_map[clave] = {
                                "hora_i": d["hora_inicio"],
                                "hora_f": d["hora_fin"],
                                "modalidad": d["modalidad"],
                                "dias": [],
                                "asignaciones": []
                            }
                        dia_num = self._normalizar_dia(d["dia"])
                        dia_nombre = self.MAPA_DIAS.get(dia_num, dia_num)
                        if dia_nombre not in periods_map[clave]["dias"]:
                            periods_map[clave]["dias"].append(dia_nombre)

                    p_asigs = [a for a in asignaciones_catalog if str(a["profesor_id"]) == str(pid)]
                    for a in p_asigs:
                        asig_sub = {
                            "materia_id": a["materia_id"],
                            "grupo_id": a["grupo_id"],
                            "periodo": a["periodo"],
                            "estado": a["estado"],
                            "hora_inicio": a["hora_inicio"],
                            "hora_fin": a["hora_fin"],
                            "dias": a["dias"],
                            "modalidad": a["modalidad"],
                            "horarios": a["horarios"]
                        }
                        clave_asig = f"{a['hora_inicio']}-{a['hora_fin']}-{a['modalidad']}"
                        if clave_asig in periods_map:
                            periods_map[clave_asig]["asignaciones"].append(asig_sub)
                        else:
                            dias_p = [d.strip() for d in a["dias"].split(",") if d.strip()]
                            periods_map[clave_asig] = {
                                "hora_i": a["hora_inicio"],
                                "hora_f": a["hora_fin"],
                                "modalidad": a["modalidad"],
                                "dias": dias_p,
                                "asignaciones": [asig_sub]
                            }

                    profesores_v1.append({
                        "profesor_id": pid,
                        "no_cuenta": p_info["no_cuenta"],
                        "nombre": p_info["nombre"],
                        "periodos": list(periods_map.values())
                    })

                config = {
                    "version": 2,
                    "materias": materias_catalog,
                    "salones": salones_catalog,
                    "grupos": grupos_catalog,
                    "grupo_materias": grupo_materias_catalog,
                    "profesores_catalogo": profesores_catalog,
                    "profesor_disponibilidad": disp_catalog,
                    "asignaciones": asignaciones_catalog,
                    "profesores": profesores_v1
                }

                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)

                self._ultimo_config_path = filepath
                self._progress_config["value"] = 100
                self.ventana.update_idletasks()
                return True, len(asignaciones_catalog)
        except Exception as e:
            messagebox.showerror("Error al guardar", f"No se pudo guardar la configuración:\n{e}")
            return False, 0
        finally:
            self._progress_config.pack_forget()

    def _sincronizar_profesor_desde_json(self, cur, prof):
        """Inserta o reutiliza un profesor en la BD al cargar una configuración."""
        prof_id_json = (prof.get("profesor_id") or "").strip()
        no_cuenta_json = (prof.get("no_cuenta") or "").strip()
        nombre_json = (prof.get("nombre") or "").strip()

        candidatos = []
        if no_cuenta_json:
            cur.execute("SELECT profesor_id, no_cuenta, nombre FROM profesores WHERE no_cuenta = %s", (no_cuenta_json,))
            for row in cur.fetchall():
                if row not in candidatos:
                    candidatos.append(row)
        if nombre_json:
            cur.execute("SELECT profesor_id, no_cuenta, nombre FROM profesores WHERE nombre = %s", (nombre_json,))
            for row in cur.fetchall():
                if row not in candidatos:
                    candidatos.append(row)

        if candidatos:
            detalle_bd = "\n".join(
                f"    {pid}  |  Cuenta: {nc or '(vacía)'}  |  Nombre: {nm}"
                for pid, nc, nm in candidatos
            )
            mismo = messagebox.askyesno(
                "Profesor existente",
                f"El profesor del archivo JSON:\n"
                f"    {prof_id_json or '(sin ID)'}  |  Cuenta: {no_cuenta_json or '(vacía)'}  |  Nombre: {nombre_json}\n\n"
                f"Coincide con el(los) registro(s) en la base de datos:\n{detalle_bd}\n\n"
                f"¿Son el MISMO profesor?\n\n"
                f"[Sí]  Conservar el registro de la BD y solo actualizar su disponibilidad.\n"
                f"[No]  Crear un nuevo registro para este profesor."
            )
            if mismo:
                return candidatos[0][0]

        nuevo_id = None
        if prof_id_json:
            cur.execute("SELECT 1 FROM profesores WHERE profesor_id = %s", (prof_id_json,))
            if not cur.fetchone():
                nuevo_id = prof_id_json
        if not nuevo_id:
            nuevo_id = _generar_profesor_id(cur)

        cur.execute(
            "INSERT INTO profesores (profesor_id, no_cuenta, nombre, disponible_inicio, disponible_fin, dias_disponibles, en_linea) "
            "VALUES (%s, %s, %s, '00:00:00', '00:00:00', '', 'NO')",
            (nuevo_id, no_cuenta_json or None, nombre_json)
        )
        return nuevo_id

    def _cargar_configuracion(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")],
            title="Cargar Configuración de Periodos y Asignaciones"
        )
        if not filepath:
            return

        if not messagebox.askyesno("Cargar Configuración",
                "Se restaurará la configuración completa desde el archivo seleccionado.\n\n"
                "• Se actualizarán los catálogos (materias, salones, grupos y profesores).\n"
                "• Se reemplazarán las asignaciones, disponibilidad y horarios actuales con los del archivo.\n\n"
                "¿Desea continuar?"):
            return

        self._progress_config.pack(side='left', padx=5)
        self._progress_config["value"] = 0
        self.ventana.update_idletasks()

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                config = json.load(f)

            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx

                # 1. Catálogo de Materias
                materias_catalog = config.get("materias", [])
                for mat in materias_catalog:
                    m_id = mat.get("materia_id")
                    if not m_id:
                        continue
                    m_nombre = mat.get("nombre", "")
                    m_hs = mat.get("horas_semana", "4")
                    m_sem = mat.get("semestre_id")
                    m_tipo = mat.get("tipo", "Normal")
                    cur.execute("SELECT 1 FROM materias WHERE materia_id = %s", (m_id,))
                    if cur.fetchone():
                        cur.execute(
                            "UPDATE materias SET nombre=%s, horas_semana=%s, semestre_id=%s, tipo=%s WHERE materia_id=%s",
                            (m_nombre, m_hs, m_sem, m_tipo, m_id)
                        )
                    else:
                        cur.execute(
                            "INSERT INTO materias (materia_id, nombre, horas_semana, semestre_id, tipo) VALUES (%s, %s, %s, %s, %s)",
                            (m_id, m_nombre, m_hs, m_sem, m_tipo)
                        )

                # 2. Catálogo de Salones
                salones_catalog = config.get("salones", [])
                for sal in salones_catalog:
                    s_id = sal.get("salon_id")
                    if not s_id:
                        continue
                    s_cap = sal.get("capacidad", 0)
                    s_tipo = sal.get("tipo", "Normal")
                    cur.execute("SELECT 1 FROM salones WHERE salon_id = %s", (s_id,))
                    if cur.fetchone():
                        cur.execute(
                            "UPDATE salones SET capacidad=%s, tipo=%s WHERE salon_id=%s",
                            (s_cap, s_tipo, s_id)
                        )
                    else:
                        cur.execute(
                            "INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, %s, %s)",
                            (s_id, s_cap, s_tipo)
                        )

                # 3. Catálogo de Grupos
                grupos_catalog = config.get("grupos", [])
                for grp in grupos_catalog:
                    g_id = grp.get("grupo_id")
                    if not g_id:
                        continue
                    g_niv = grp.get("nivel")
                    cur.execute("SELECT 1 FROM grupos WHERE grupo_id = %s", (g_id,))
                    if cur.fetchone():
                        if g_niv is not None:
                            cur.execute("UPDATE grupos SET nivel=%s WHERE grupo_id=%s", (g_niv, g_id))
                    else:
                        cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, %s)", (g_id, g_niv if g_niv is not None else 0))

                # 4. Grupo-Materias (vínculos curriculares)
                grupo_mat_catalog = config.get("grupo_materias", [])
                for gm in grupo_mat_catalog:
                    g_id = gm.get("grupo_id")
                    m_id = gm.get("materia_id")
                    if g_id and m_id:
                        cur.execute("SELECT 1 FROM grupos WHERE grupo_id = %s", (g_id,))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, 0)", (g_id,))
                        cur.execute("SELECT 1 FROM grupo_materias WHERE grupo_id = %s AND materia_id = %s", (g_id, m_id))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO grupo_materias (grupo_id, materia_id) VALUES (%s, %s)", (g_id, m_id))

                # 5. Profesores
                prof_id_map = {}
                profesores_cat = config.get("profesores_catalogo")
                if profesores_cat:
                    for p in profesores_cat:
                        p_id = (p.get("profesor_id") or "").strip()
                        ncta = (p.get("no_cuenta") or "").strip() or None
                        nom = (p.get("nombre") or "").strip()
                        correo = p.get("correo_institucional") or None
                        di = p.get("disponible_inicio")
                        df = p.get("disponible_fin")
                        dd = p.get("dias_disponibles")
                        enl = p.get("en_linea") or "NO"

                        if not nom and not p_id:
                            continue

                        cur.execute("SELECT profesor_id FROM profesores WHERE profesor_id = %s", (p_id,))
                        row = cur.fetchone()
                        if not row and ncta:
                            cur.execute("SELECT profesor_id FROM profesores WHERE no_cuenta = %s", (ncta,))
                            row = cur.fetchone()
                        if not row and nom:
                            cur.execute("SELECT profesor_id FROM profesores WHERE nombre = %s", (nom,))
                            row = cur.fetchone()

                        if row:
                            bd_pid = row[0]
                            prof_id_map[p_id] = bd_pid
                            cur.execute("""
                                UPDATE profesores
                                SET no_cuenta=COALESCE(%s, no_cuenta),
                                    nombre=%s,
                                    correo_institucional=COALESCE(%s, correo_institucional),
                                    disponible_inicio=COALESCE(%s, disponible_inicio),
                                    disponible_fin=COALESCE(%s, disponible_fin),
                                    dias_disponibles=COALESCE(%s, dias_disponibles),
                                    en_linea=%s
                                WHERE profesor_id = %s
                            """, (ncta, nom, correo, di, df, dd, enl, bd_pid))
                        else:
                            nuevo_pid = p_id if p_id else _generar_profesor_id(cur)
                            cur.execute("""
                                INSERT INTO profesores (profesor_id, no_cuenta, nombre, correo_institucional,
                                                       disponible_inicio, disponible_fin, dias_disponibles, en_linea)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (nuevo_pid, ncta, nom, correo, di, df, dd, enl))
                            prof_id_map[p_id] = nuevo_pid
                else:
                    for prof in config.get("profesores", []):
                        pid_orig = (prof.get("profesor_id") or "").strip()
                        pid_nuevo = self._sincronizar_profesor_desde_json(cur, prof)
                        if pid_orig:
                            prof_id_map[pid_orig] = pid_nuevo

                # 6. Limpiar tablas transaccionales antes de recargar disponibilidad, asignaciones y horarios
                cur.execute("TRUNCATE TABLE horarios")
                cur.execute("DELETE FROM asignaciones")
                cur.execute("DELETE FROM profesor_disponibilidad")

                # 7. Disponibilidad de Profesores
                disponibilidad_cat = config.get("profesor_disponibilidad")
                if disponibilidad_cat:
                    for d in disponibilidad_cat:
                        raw_pid = d.get("profesor_id")
                        real_pid = prof_id_map.get(raw_pid, raw_pid)
                        dia_num = self._normalizar_dia(d.get("dia", "0"))
                        hi = d.get("hora_inicio")
                        hf = d.get("hora_fin")
                        modal = d.get("modalidad", "Presencial")
                        if real_pid and hi and hf and dia_num in ('0','1','2','3','4','5'):
                            cur.execute(
                                "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin, modalidad) VALUES (%s, %s, %s, %s, %s)",
                                (real_pid, dia_num, hi, hf, modal)
                            )
                elif "profesores" in config:
                    for prof in config.get("profesores", []):
                        raw_pid = prof.get("profesor_id")
                        real_pid = prof_id_map.get(raw_pid, raw_pid)
                        if not real_pid:
                            continue
                        for per in prof.get("periodos", []):
                            hi = per.get("hora_i")
                            hf = per.get("hora_f")
                            modal = per.get("modalidad", "Presencial")
                            for dia_nom in per.get("dias", []):
                                dia_num = self._normalizar_dia(dia_nom)
                                if dia_num in ('0','1','2','3','4','5'):
                                    cur.execute(
                                        "INSERT INTO profesor_disponibilidad (profesor_id, dia, hora_inicio, hora_fin, modalidad) VALUES (%s, %s, %s, %s, %s)",
                                        (real_pid, dia_num, hi, hf, modal)
                                    )

                # 8. Asignaciones y Horarios
                asignaciones_cat = config.get("asignaciones")
                total_cargadas = 0

                if asignaciones_cat is not None:
                    # Formato v2
                    total_total = len(asignaciones_cat)
                    for idx, asig in enumerate(asignaciones_cat):
                        raw_pid = asig.get("profesor_id")
                        if raw_pid and raw_pid != 'SIN_ASIGNAR':
                            real_pid = prof_id_map.get(raw_pid, raw_pid)
                        else:
                            real_pid = 'SIN_ASIGNAR'

                        m_id = asig.get("materia_id")
                        g_id = asig.get("grupo_id")
                        per = asig.get("periodo", "A")
                        hi = asig.get("hora_inicio") or None
                        hf = asig.get("hora_fin") or None
                        dias = asig.get("dias") or ""
                        modal = asig.get("modalidad", "Presencial")
                        est = asig.get("estado", "pendiente")

                        if not m_id or not g_id:
                            continue

                        cur.execute("SELECT 1 FROM grupos WHERE grupo_id = %s", (g_id,))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, 0)", (g_id,))
                        cur.execute("SELECT 1 FROM grupo_materias WHERE grupo_id = %s AND materia_id = %s", (g_id, m_id))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO grupo_materias (grupo_id, materia_id) VALUES (%s, %s)", (g_id, m_id))

                        cur.execute("""
                            INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, periodo, hora_inicio, hora_fin, dias, modalidad, estado)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (real_pid, m_id, g_id, per, hi, hf, dias, modal, est))
                        nueva_asig_id = cur.lastrowid
                        total_cargadas += 1

                        for h in asig.get("horarios", []):
                            s_id = h.get("salon_id")
                            h_dia = h.get("dia")
                            h_hi = h.get("hora_inicio")
                            h_hf = h.get("hora_fin")
                            if s_id and h_dia and h_hi and h_hf:
                                cur.execute("SELECT 1 FROM salones WHERE salon_id = %s", (s_id,))
                                if not cur.fetchone():
                                    cur.execute("INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, 30, 'Normal')", (s_id,))
                                dia_num = self._normalizar_dia(h_dia)
                                dia_nombre = self.MAPA_DIAS.get(dia_num, h_dia)
                                cur.execute("""
                                    INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                                    VALUES (%s, %s, %s, %s, %s)
                                """, (nueva_asig_id, s_id, dia_nombre, h_hi, h_hf))

                        if total_total > 0:
                            self._progress_config["value"] = ((idx + 1) / total_total) * 100
                            if idx % 10 == 0:
                                self.ventana.update_idletasks()
                else:
                    # Formato v1 legacy
                    profesores_list = config.get("profesores", [])
                    total_total = len(profesores_list)
                    for idx, prof in enumerate(profesores_list):
                        raw_pid = prof.get("profesor_id")
                        real_pid = prof_id_map.get(raw_pid, raw_pid)
                        for periodo in prof.get("periodos", []):
                            hora_i = periodo.get("hora_i")
                            hora_f = periodo.get("hora_f")
                            modalidad = periodo.get("modalidad", "Presencial")
                            dias_list = periodo.get("dias", [])
                            dias_str = ", ".join(dias_list)

                            for asig in periodo.get("asignaciones", []):
                                mat_id = asig.get("materia_id")
                                grupo_texto = asig.get("grupo_id")
                                periodo_letra = asig.get("periodo", "A")
                                estado = asig.get("estado", "pendiente")
                                grupo_id = self._obtener_id_valido(grupo_texto, es_grupo=True)
                                if not grupo_id or not mat_id:
                                    continue

                                cur.execute("SELECT 1 FROM grupos WHERE grupo_id = %s", (grupo_id,))
                                if not cur.fetchone():
                                    cur.execute("INSERT INTO grupos (grupo_id, nivel) VALUES (%s, 0)", (grupo_id,))
                                cur.execute("SELECT 1 FROM grupo_materias WHERE grupo_id = %s AND materia_id = %s", (grupo_id, mat_id))
                                if not cur.fetchone():
                                    cur.execute("INSERT INTO grupo_materias (grupo_id, materia_id) VALUES (%s, %s)", (grupo_id, mat_id))

                                cur.execute("""
                                    INSERT INTO asignaciones (profesor_id, materia_id, grupo_id, estado, periodo, hora_inicio, hora_fin, dias, modalidad)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """, (real_pid, mat_id, grupo_id, estado, periodo_letra, hora_i, hora_f, dias_str, modalidad))
                                nueva_asig_id = cur.lastrowid
                                total_cargadas += 1

                                for h in asig.get("horarios", []):
                                    dia_num = self._normalizar_dia(h["dia"])
                                    dia_nombre = self.MAPA_DIAS.get(dia_num, "Lunes")
                                    salon_id = h["salon_id"]
                                    cur.execute("SELECT 1 FROM salones WHERE salon_id = %s", (salon_id,))
                                    if not cur.fetchone():
                                        cur.execute("INSERT INTO salones (salon_id, capacidad, tipo) VALUES (%s, 30, 'Normal')", (salon_id,))
                                    cur.execute("""
                                        INSERT INTO horarios (asignacion_id, salon_id, dia, hora_inicio, hora_fin)
                                        VALUES (%s, %s, %s, %s, %s)
                                    """, (nueva_asig_id, salon_id, dia_nombre, h["hora_inicio"], h["hora_fin"]))

                        if total_total > 0:
                            self._progress_config["value"] = ((idx + 1) / total_total) * 100
                            self.ventana.update_idletasks()

                conn.commit()

            # Refrescar toda la interfaz gráfica
            self.grupos_por_semestre = self._cargar_grupos_desde_bd()
            self.cargar_combos_bd()

            if hasattr(self, 'combo_filtro_semestre'):
                self.combo_filtro_semestre['values'] = ["Todos"] + list(self.semestres_map.values())
                self.combo_filtro_semestre.set("Todos")

            if hasattr(self, 'combo_filtro_semestre_vp'):
                self.combo_filtro_semestre_vp['values'] = ["Todos"] + list(self.semestres_map.values())
                self._sv_filtro_semestre_vp.set("Todos")
                self._on_filtro_semestre_vp()

            grupos = self._grupos_filtrados_actual()
            if hasattr(self, 'combo_grupo_gestion'):
                self.combo_grupo_gestion['values'] = grupos
                if grupos:
                    self.combo_grupo_gestion.set(grupos[0])
                    self._on_cambio_grupo_gestion()
                    self._seleccionar_grupo_previa(grupos[0])
                else:
                    self.combo_grupo_gestion.set('')
                    self._cargar_materias_grupo_gestion()

            if self._profesor_id_seleccionado:
                self._cargar_periodos_desde_bd()

            self.actualizar_vista_previa()
            self._cargar_previa_horario_grupo()
            self._ultimo_config_path = filepath
            messagebox.showinfo(
                "Configuración Cargada",
                f"Configuración cargada exitosamente desde:\n{filepath}\n\n"
                f"Total de asignaciones restauradas: {total_cargadas}"
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Error al cargar configuración", f"Ocurrió un error al cargar el archivo:\n{e}")
        finally:
            self._progress_config.pack_forget()
