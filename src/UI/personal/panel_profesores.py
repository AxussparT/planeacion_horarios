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

class PanelProfesoresMixin:
    def agregar_periodo_ui(self, datos=None):
        idx = len(self.periodos_widgets) + 1
        marco = ttk.LabelFrame(self.frame_periodos, text=f"Periodo {idx}", style='blue.TFrame')
        marco.pack(fill='x', pady=4, padx=2)

        f_h = ttk.Frame(marco, style='blue.TFrame')
        f_h.pack(fill='x', pady=2)
        ttk.Label(f_h, text="Horario:", style='fondo.TLabel', font=self._fuente_label).pack(side='left', padx=2)
        entry_i = ttk.Entry(f_h, width=10, font=self._fuente_label)
        entry_i.pack(side='left', padx=2)
        ttk.Label(f_h, text="-", style='fondo.TLabel', font=self._fuente_label).pack(side='left', padx=2)
        entry_f = ttk.Entry(f_h, width=10, font=self._fuente_label)
        entry_f.pack(side='left', padx=2)

        f_dias = ttk.Frame(marco, style='blue.TFrame')
        f_dias.pack(fill='x', pady=2)

        vars_dias = {}
        for i, dia in enumerate(self.NOMBRES_DIAS):
            var = tk.IntVar()
            vars_dias[dia] = var
            fila = i // 3
            col = i % 3
            cb = ttk.Checkbutton(f_dias, text=dia, variable=var, style='Custom.TCheckbutton')
            cb.grid(row=fila, column=col, sticky='w', padx=5, pady=1)

        f_dias.grid_columnconfigure(0, weight=1)
        f_dias.grid_columnconfigure(1, weight=1)
        f_dias.grid_columnconfigure(2, weight=1)

        btn_quitar = ttk.Button(marco, text="Quitar", command=lambda m=marco: self.quitar_periodo_ui(m))
        btn_quitar.pack(pady=2)

        if datos:
            entry_i.insert(0, datos.get('hora_inicio', ''))
            entry_f.insert(0, datos.get('hora_fin', ''))
            for dia in datos.get('dias', []):
                if dia in vars_dias:
                    vars_dias[dia].set(1)

        widget_data = {
            'frame': marco,
            'entry_i': entry_i,
            'entry_f': entry_f,
            'vars': vars_dias,
            'btn_quitar': btn_quitar
        }
        self.periodos_widgets.append(widget_data)
        self._renumerar_periodos()
        return widget_data

    def quitar_periodo_ui(self, marco):
        for w in self.periodos_widgets:
            if w['frame'] == marco:
                self.periodos_widgets.remove(w)
                marco.destroy()
                break
        self._renumerar_periodos()

    def _renumerar_periodos(self):
        for i, w in enumerate(self.periodos_widgets, 1):
            w['frame'].config(text=f"Periodo {i}")

    def obtener_periodos_desde_ui(self):
        periodos = []
        for w in self.periodos_widgets:
            dias_seleccionados = [d for d, v in w['vars'].items() if v.get() == 1]
            if not dias_seleccionados:
                continue
            hora_i = w['entry_i'].get().strip()
            hora_f = w['entry_f'].get().strip()
            if not hora_i or not hora_f:
                continue
            periodos.append({
                'dias': ', '.join(dias_seleccionados),
                'hora_inicio': hora_i,
                'hora_fin': hora_f
            })
        return periodos

    def limpiar_periodos_ui(self):
        for w in list(self.periodos_widgets):
            w['frame'].destroy()
        self.periodos_widgets.clear()
        self.agregar_periodo_ui()

    def cargar_periodos_en_ui(self, periodos_data):
        self.limpiar_periodos_ui()
        if not periodos_data:
            return
        self.periodos_widgets.clear()
        for w in list(self.frame_periodos.winfo_children()):
            w.destroy()
        for pd in periodos_data:
            self.agregar_periodo_ui(pd)
        if not periodos_data:
            self.agregar_periodo_ui()

    def limpiar_campos_profesor(self):
        self.entry_no_cuenta.config(state='normal')
        self.entry_no_cuenta.delete(0, tk.END)
        self.entry_nombre_completo.delete(0, tk.END)
        self.entry_correo_institucional.delete(0, tk.END)
        if hasattr(self, 'var_acude_semana'):
            self.var_acude_semana.set('SI')
        self._profesor_id_seleccionado = None

    def cargar_profesor_seleccionado(self, event):
        item = self.tabla_profesores.focus()
        if not item:
            return
        v = self.tabla_profesores.item(item, "values")
        self.limpiar_campos_profesor()

        no_cuenta = v[0]
        nombre = v[1] if len(v) > 1 else ''
        correo = v[2] if len(v) > 2 else ''
        self.entry_no_cuenta.insert(0, no_cuenta)
        self.entry_nombre_completo.insert(0, nombre)
        self.entry_correo_institucional.insert(0, correo)

        self._profesor_id_seleccionado = None
        acude_val = 'SI'
        for d in self.cache_profesores:
            if d[1] == no_cuenta:
                self._profesor_id_seleccionado = d[0]
                if len(d) > 4 and d[4]:
                    acude_val = str(d[4]).upper()
                break
        if not self._profesor_id_seleccionado:
            self._profesor_id_seleccionado = no_cuenta
        if hasattr(self, 'var_acude_semana'):
            self.var_acude_semana.set(acude_val)

    def evento_boton_profesores(self):
        self.master.update_idletasks()
        no_cuenta = self.entry_no_cuenta.get().strip()
        full_n = self.entry_nombre_completo.get().strip().upper()
        correo = self.entry_correo_institucional.get().strip() or None

        if not no_cuenta.isascii() or not no_cuenta.isdigit() or len(no_cuenta) > 10:
            messagebox.showwarning("Aviso", "El número de cuenta debe contener de 1 a 10 dígitos.")
            return
        if not full_n or len(full_n) > 255:
            messagebox.showwarning("Aviso", "El nombre del profesor es obligatorio y no puede exceder 255 caracteres.")
            return
        if correo and len(correo) > 255:
            messagebox.showwarning("Aviso", "El correo institucional no puede exceder 255 caracteres.")
            return

        periodos = self.obtener_periodos_desde_ui()
        acude_semana = self.var_acude_semana.get() if hasattr(self, 'var_acude_semana') else 'SI'
        registro = profesor(no_cuenta, full_n, periodos, correo, acude_toda_semana=acude_semana)
        if not registro.exito:
            return
        self.limpiar_campos_profesor()
        self._refresh_all()

    def eliminar_profesor(self):
        pid = getattr(self, '_profesor_id_seleccionado', None)
        if not pid:
            pid = self.entry_no_cuenta.get().strip()
        if not pid:
            return
        if messagebox.askyesno("Confirmar Eliminación", f"¿Estás seguro de eliminar al profesor {pid}? Esto borrará también sus asignaciones y horarios."):
            from src.conexion import obtener_cursor
            exito = False
            with obtener_cursor() as ctx:
                if ctx is None:
                    return
                cur, conn = ctx
                try:
                    cur.execute("DELETE FROM profesor_disponibilidad WHERE profesor_id = %s", (pid,))
                    cur.execute("DELETE FROM horarios WHERE asignacion_id IN (SELECT asignacion_id FROM asignaciones WHERE profesor_id = %s)", (pid,))
                    cur.execute("DELETE FROM asignaciones WHERE profesor_id = %s", (pid,))
                    cur.execute("DELETE FROM profesores WHERE profesor_id = %s", (pid,))
                    exito = True
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error de Base de Datos", str(e))
            if exito:
                self.limpiar_campos_profesor()
                self._refresh_all()
                messagebox.showinfo("Éxito", "Profesor eliminado correctamente.")

    def mostrar_datos_profesor(self):
        self.cache_profesores.clear()
        conn = get_conexion()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT profesor_id, no_cuenta, nombre, correo_institucional, IFNULL(acude_toda_semana, 'SI') AS acude_toda_semana
                    FROM profesores
                    ORDER BY nombre
                """)
                self.cache_profesores = cur.fetchall()
            except sqlite3.Error as err:
                messagebox.showerror("Error de Base de Datos", f"No se pudieron cargar los profesores: {err}")
            finally:
                cur.close()
                conn.close()
        self.refrescar_tabla_prof(self.cache_profesores)

    def refrescar_tabla_prof(self, datos):
        children = self.tabla_profesores.get_children()
        if children:
            self.tabla_profesores.delete(*children)
        for d in datos:
            prof_id = d[0]
            no_cuenta = d[1] if len(d) > 1 and d[1] is not None else ''
            nombre = d[2] if len(d) > 2 else ''
            correo = d[3] if len(d) > 3 and d[3] is not None else ''
            self.tabla_profesores.insert("", "end", values=(no_cuenta, nombre, correo))

    def _programar_filtro_profesores(self):
        if self._after_busqueda_profesores_id is not None:
            self.master.after_cancel(self._after_busqueda_profesores_id)
        self._after_busqueda_profesores_id = self.master.after(
            200, self._filtrar_profesores_diferido
        )

    def _filtrar_profesores_diferido(self):
        self._after_busqueda_profesores_id = None
        self.filtrar_profesores()

    def filtrar_profesores(self):
        t = self.sv_busqueda.get().lower()
        f = [
            p for p in self.cache_profesores
            if any(t in str(valor or '').lower() for valor in p[:4])
        ]
        self.refrescar_tabla_prof(f)
