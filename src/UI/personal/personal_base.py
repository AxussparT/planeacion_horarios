# -*- coding: utf-8 -*-
import os
import sys
import json
import sqlite3
import unicodedata
import datetime
import tkinter as tk
from tkinter import ttk, font, messagebox, filedialog, simpledialog
from PIL import Image, ImageTk

from src.conexion import get_conexion, obtener_cursor
from src.clases.materia import materia
from src.clases.profesor import profesor
from src.clases.salon import salon
from src.clases.grupo import grupo
from src.UI.icon_manager import IconManager

def ruta_recurso(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    return os.path.join(base_path, relative_path)

class PersonalBaseMixin:
    @staticmethod
    def _normalizar_tipo(tipo):
        if not tipo:
            return "NORMAL"
        import unicodedata
        t = ''.join(ch for ch in unicodedata.normalize('NFD', str(tipo)) if unicodedata.category(ch) != 'Mn').upper()
        if 'TEC' in t or 'COMPUT' in t:
            return "TECNOLOGICA"
        elif 'LAB' in t:
            return "LABORATORIO"
        elif 'AUD' in t:
            return "AUDITORIO"
        return "NORMAL"

    @classmethod
    def _ui_tipo_materia_salon(cls, tipo_db):
        norm = cls._normalizar_tipo(tipo_db)
        if norm == "TECNOLOGICA":
            return "Laboratorio de computación"
        elif norm == "LABORATORIO":
            return "Laboratorio"
        elif norm == "AUDITORIO":
            return "Auditorio"
        return "Normal"

    @classmethod
    def _db_tipo_materia_salon(cls, tipo_ui):
        return cls._normalizar_tipo(tipo_ui)

    def _crear_campo(self, parent, label, attr, row):
        ttk.Label(parent, text=label, style='fondo.TLabel').grid(row=row, column=0, sticky='w', pady=4)
        e = ttk.Entry(parent, width=34, font=self._fuente_label)
        e.grid(row=row, column=1, sticky='ew', padx=(12, 0), pady=4)
        setattr(self, attr, e)

    def _limitar_entrada(self, entry, max_length, solo_digitos=False):
        def validar(valor_propuesto, accion):
            if accion == "-1":
                return True
            if len(valor_propuesto) > max_length:
                return False
            return (
                not solo_digitos
                or not valor_propuesto
                or (valor_propuesto.isascii() and valor_propuesto.isdigit())
            )

        validar_cmd = (self.master.register(validar), "%P", "%d")
        entry.configure(validate="key", validatecommand=validar_cmd)

    def crear_seccion_tabla(self, titulo, var_busq, attr_tabla, cols, combo_semestre_var=None):
        ttk.Label(self.frame_derecho, text=titulo, font=self._fuente_sub, style='fondo.TLabel').pack(pady=(12, 4))
        if var_busq:
            f = ttk.Frame(self.frame_derecho, style='blue.TFrame')
            f.pack(fill='x', padx=5)
            ttk.Label(f, text="Buscar:", font=self._fuente_label, style='fondo.TLabel').pack(side='left', padx=(5, 2))
            e = ttk.Entry(f, textvariable=getattr(self, var_busq), width=25, font=self._fuente_label)
            e.pack(side='left', fill='x', expand=True, padx=(0, 5))
            if combo_semestre_var:
                ttk.Label(f, text="Semestre:", font=self._fuente_label, style='fondo.TLabel').pack(side='left', padx=(10, 2))
                combo = ttk.Combobox(f, textvariable=getattr(self, combo_semestre_var), width=8, state='readonly', font=self._fuente_label)
                combo['values'] = ("Todos", "1", "2", "3", "4", "5", "6", "7", "8", "9")
                combo.pack(side='left', padx=5)
        frame_t = ttk.Frame(self.frame_derecho)
        frame_t.pack(fill='both', expand=True, pady=(2, 8))
        t = ttk.Treeview(frame_t, columns=cols, show='headings', height=12)
        for c in cols:
            t.heading(c, text=c)
            t.column(c, width=110, anchor='center')
        t.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(frame_t, orient="vertical", command=t.yview)
        t.configure(yscroll=sb.set)
        sb.pack(side='right', fill='y')
        setattr(self, attr_tabla, t)

    def _refresh_all(self):
        self.master.update_idletasks()
        self.mostrar_datos_profesor()
        self.mostrar_datos_materias()
        self.mostrar_datos_salones()
        self.mostrar_datos_grupos()
        self.master.after(10, self._gestion_control.cargar_combos_bd)

    def _confirmar_cierre(self):
        resp = messagebox.askyesnocancel(
            "Cerrar aplicación",
            "¿Desea guardar la configuración en JSON antes de cerrar?"
        )
        if resp is None:
            return
        if resp:
            if hasattr(self, '_gestion_control') and self._gestion_control:
                ok = self._gestion_control._guardar_configuracion()
                if not ok:
                    return
        self.master.destroy()

    # =================== ESCALADO ===================

    def _rescale_ui(self):
        w = self.master.winfo_width()
        h = self.master.winfo_height()
        if w < 100 or h < 100:
            return
        escala = min(w / 1920, h / 1080)
        escala = max(0.5, min(escala, 2.0))
        if abs(escala - self._scale_factor) < 0.05:
            return
        self._scale_factor = escala
        tam_titulo = max(14, int(20 * escala))
        tam_sub = max(10, int(14 * escala))
        tam_label = max(9, int(12 * escala))
        tam_btn = max(10, int(14 * escala))
        tam_tree_h = max(8, int(10 * escala))
        tam_tree = max(8, int(10 * escala))
        self._fuente_titulo.configure(size=tam_titulo)
        self._fuente_sub.configure(size=tam_sub)
        self._fuente_label.configure(size=tam_label)
        self._fuente_btn.configure(size=tam_btn)
        self._fuente_tree_head.configure(size=tam_tree_h)
        self._fuente_tree.configure(size=tam_tree)
        estilo = ttk.Style()
        estilo.configure('Treeview', rowheight=max(20, int(25 * escala)))
        for t in [self.tabla_profesores, self.tabla_materias, self.tabla_salones]:
            if hasattr(t, 'column'):
                for c in t['columns']:
                    t.column(c, width=max(60, int(100 * escala)))
        self.tab_personal.columnconfigure(0, weight=0, minsize=max(500, int(720 * min(escala, 1.2))))

    def redimensionar_fondo(self, event):
        if event.widget is self.master:
            if event.width != self._last_width or event.height != self._last_height:
                self._last_width, self._last_height = event.width, event.height
                img = self.original_image.resize((event.width, event.height), Image.LANCZOS)
                self.bg_img = ImageTk.PhotoImage(img)
                self.background_label.config(image=self.bg_img)
                self._rescale_ui()
