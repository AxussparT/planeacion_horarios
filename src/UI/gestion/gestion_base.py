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

def ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return os.path.join(base_path, relative_path)

def _migrar_bd():
    conn = None
    cursor = None
    try:
        conn = get_conexion()
        if conn is None:
            return
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(asignaciones)")
        columnas = {fila[1] for fila in cursor.fetchall()}
        if "dias" not in columnas:
            cursor.execute("ALTER TABLE asignaciones ADD COLUMN dias TEXT DEFAULT NULL")
            conn.commit()
    except sqlite3.Error as err:
        if conn:
            conn.rollback()
        print(f"Error migrando el esquema SQLite: {err}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def _backfill_dias():
    conn = None
    try:
        conn = get_conexion()
        if conn is None:
            return
        cur = conn.cursor(dictionary=True)

        cur.execute("SELECT asignacion_id, profesor_id, hora_inicio, hora_fin FROM asignaciones WHERE dias IS NULL AND hora_inicio IS NOT NULL AND hora_fin IS NOT NULL")
        pendientes = cur.fetchall()

        mapa_num_dia = {"0": "Lunes", "1": "Martes", "2": "Miércoles", "3": "Jueves", "4": "Viernes", "5": "Sábado"}

        for a in pendientes:
            cur.execute(
                "SELECT DISTINCT dia FROM profesor_disponibilidad WHERE profesor_id=%s AND hora_inicio=%s AND hora_fin=%s",
                (a['profesor_id'], a['hora_inicio'], a['hora_fin'])
            )
            dias_raw = [row['dia'] for row in cur.fetchall()]
            if dias_raw:
                dias_str = ", ".join(mapa_num_dia.get(str(d), str(d)) for d in sorted(dias_raw, key=lambda x: int(x) if str(x).isdigit() else 0))
                cur.execute("UPDATE asignaciones SET dias=%s WHERE asignacion_id=%s", (dias_str, a['asignacion_id']))
        conn.commit()
        if pendientes:
            print(f"[MIGRACIÓN] días asignados a {len(pendientes)} asignaciones existentes")
    except Exception as e:
        print(f"[MIGRACIÓN] Error backfill: {e}")
        conn.rollback() if conn else None
    finally:
        if conn and conn.is_connected():
            conn.close()

class GestionBaseMixin:
    def _cargar_grupos_desde_bd(self):
        grupos = {}
        try:
            with obtener_cursor() as ctx:
                if ctx is None:
                    return grupos
                cur, conn = ctx
                cur.execute("SELECT grupo_id, nivel FROM grupos ORDER BY nivel, grupo_id")
                filas = cur.fetchall()
                for row in filas:
                    gid = row[0]
                    nivel = self._normalizar_nivel_grupo(row[1])
                    if nivel not in grupos:
                        grupos[nivel] = []
                    grupos[nivel].append(gid)
        except Exception as e:
            print(f"Error cargando grupos desde BD: {e}")
        return grupos

    @staticmethod
    def _normalizar_nivel_grupo(nivel):
        if nivel is None:
            return "0"
        try:
            return str(int(float(nivel)))
        except (TypeError, ValueError, OverflowError):
            return str(nivel).strip()

    def _grupos_del_semestre(self, semestre_id):
        semestre_id = self._normalizar_nivel_grupo(semestre_id)
        for nivel, grupos in self.grupos_por_semestre.items():
            if self._normalizar_nivel_grupo(nivel) == semestre_id:
                return grupos
        return []

    def _confirmar_cierre(self):
        if self._en_operacion:
            messagebox.showwarning("Operación en curso", "Espera a que termine la operación actual antes de cerrar.")
            return
        if messagebox.askyesno("Confirmar cierre", "¿Estás seguro de cerrar la ventana de gestión?"):
            self.ventana.destroy()

    def _post_init(self):
        self._inicializar_fuentes()
        self.cargar_combos_bd()
        self.ventana.after(50, self._cargar_tensor_diferido)

    def _inicializar_fuentes(self):
        estilo = ttk.Style()
        estilo.configure('Treeview', rowheight=22)
        self._rescale_ui()

    def _cargar_tensor_diferido(self, forzar=False):
        if self._tensor_cargado and not forzar:
            return
        self._tensor_cargado = False
        def tarea():
            try:
                mem_grafico.inicializar_y_llenar_tensor("Salón")
                self.ventana.after(0, self._on_tensor_listo)
            except Exception as e:
                print(f"Error al cargar tensor: {e}")
        hilo = threading.Thread(target=tarea, daemon=True)
        hilo.start()

    def _on_tensor_listo(self):
        self._tensor_cargado = True
        if hasattr(self, 'combo_vista_horarios'):
            self.cambiar_modo_vista()

    def _rescale_ui(self):
        w = self.ventana.winfo_width()
        h = self.ventana.winfo_height()
        if w < 100 or h < 100:
            return
        escala = min(w / 1920, h / 1080)
        escala = max(0.5, min(escala, 2.0))
        if abs(escala - self._scale_factor) < 0.05:
            return
        self._scale_factor = escala
        if hasattr(self, '_fuente_titulo'):
            self._fuente_titulo.configure(size=max(12, int(18 * escala)))
        if hasattr(self, '_fuente_sub'):
            self._fuente_sub.configure(size=max(9, int(12 * escala)))
        if hasattr(self, '_fuente_label'):
            self._fuente_label.configure(size=max(8, int(10 * escala)))
        if hasattr(self, '_fuente_btn'):
            self._fuente_btn.configure(size=max(8, int(10 * escala)))
        estilo = ttk.Style()
        estilo.configure('Treeview', rowheight=max(18, int(22 * escala)))

    def redimensionar_fondo(self, event):
        try:
            if event.width > 0 and event.height > 0 and hasattr(self, 'original_image'):
                self._rescale_ui()
                if event.width != self._last_width or event.height != self._last_height:
                    self._last_width, self._last_height = event.width, event.height
                    resized = self.original_image.resize((event.width, event.height), Image.LANCZOS)
                    self.background_image = ImageTk.PhotoImage(resized)
                    self.background_label.config(image=self.background_image)
        except Exception as e: print(f"Error resize: {e}")
